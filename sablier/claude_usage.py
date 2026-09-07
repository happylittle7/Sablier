"""Fetch Claude subscription usage using the local Claude Code login."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from .codex_usage import UsageWindow


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
REFRESH_WINDOW_MS = 5 * 60 * 1000
REFRESH_TIMEOUT_SECONDS = 30
REFRESH_USER_AGENT = "axios/1.15.2"
DEFAULT_COOLDOWN_SECONDS = 30 * 60
DEFAULT_COOLDOWN_PATH = Path("output/claude-cooldown")
DEFAULT_AUTH_FAILURE_PATH = Path("output/claude-auth-failure.json")
DEFAULT_REFRESH_DIAGNOSTIC_PATH = Path("output/claude-refresh-diagnostic.json")
MAX_ERROR_BODY_BYTES = 8192


class ClaudeUsageError(RuntimeError):
    """A safe, user-facing Claude usage retrieval error."""


class ClaudeAuthenticationError(ClaudeUsageError):
    """The Claude Code login is missing or no longer valid."""


class ClaudeRefreshRejectedError(ClaudeAuthenticationError):
    """The refresh token was permanently rejected and requires a new login."""


class ClaudeRateLimitError(ClaudeUsageError):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class ClaudeSnapshot:
    plan_type: str
    primary: UsageWindow | None
    secondary: UsageWindow | None
    fetched_at: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_error_text(value: Any, limit: int = 240) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.split())
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", text)
    text = re.sub(r"(?i)(access|refresh)[_-]?token[=: ]+\S+", r"\1_token=<redacted>", text)
    return text[:limit]


def _read_http_error(
    exc: urllib.error.HTTPError, *, transport: str = "python-urllib"
) -> tuple[dict[str, Any], str]:
    raw = exc.read(MAX_ERROR_BODY_BYTES).decode("utf-8", "replace")
    details: dict[str, Any] = {
        "occurredAt": int(time.time()),
        "httpStatus": exc.code,
        "transport": transport,
    }
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        description = payload.get("error_description")
        if isinstance(error, dict):
            details["oauthError"] = _safe_error_text(
                error.get("type") or error.get("code")
            )
            description = description or error.get("message")
        else:
            details["oauthError"] = _safe_error_text(error)
        safe_description = _safe_error_text(description)
        if safe_description:
            details["description"] = safe_description
        payload_request_id = _safe_error_text(
            payload.get("request_id") or payload.get("requestId"), limit=120
        )
        if payload_request_id:
            details["requestId"] = payload_request_id
    headers = exc.headers or {}
    request_id = _safe_error_text(
        headers.get("request-id") or headers.get("x-request-id"), limit=120
    )
    if request_id:
        details["requestId"] = request_id
    server = _safe_error_text(headers.get("server"), limit=80)
    if server:
        details["server"] = server
    cf_ray = _safe_error_text(headers.get("cf-ray"), limit=120)
    if cf_ray:
        details["cloudflareRay"] = cf_ray
    retry_after = _safe_error_text(headers.get("retry-after"), limit=40)
    if retry_after:
        details["retryAfter"] = retry_after
    return {key: value for key, value in details.items() if value is not None}, raw


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _http_error_summary(details: dict[str, Any]) -> str:
    parts = [f"HTTP {details['httpStatus']}"]
    if details.get("oauthError"):
        parts.append(f"error={details['oauthError']}")
    if details.get("requestId"):
        parts.append(f"request_id={details['requestId']}")
    return ", ".join(parts)


def _raise_http_error(
    url: str,
    exc: urllib.error.HTTPError,
    *,
    diagnostic_path: Path | None,
    transport: str,
) -> None:
    is_refresh = url == REFRESH_URL
    details, error_body = _read_http_error(exc, transport=transport)
    if is_refresh and diagnostic_path is not None:
        _write_json_atomic(diagnostic_path, details)
    summary = _http_error_summary(details)
    if exc.code in (400, 401):
        if is_refresh:
            if details.get("oauthError") in {
                "invalid_grant",
                "invalid_refresh_token",
            }:
                raise ClaudeRefreshRejectedError(
                    f"Claude refresh token was rejected ({summary}); "
                    "run 'claude auth login' again"
                ) from exc
            raise ClaudeAuthenticationError(
                f"Claude token refresh failed ({summary})"
            ) from exc
        raise ClaudeAuthenticationError(
            "Claude login was rejected; run 'claude auth login' again"
        ) from exc
    if exc.code == 403:
        if is_refresh:
            if "error code: 1010" in error_body:
                raise ClaudeUsageError(
                    f"Claude token refresh was blocked by edge security ({summary})"
                ) from exc
            raise ClaudeAuthenticationError(
                f"Claude token refresh was forbidden ({summary})"
            ) from exc
        raise ClaudeAuthenticationError(
            "Claude login lacks the user:profile scope; sign in again"
        ) from exc
    if exc.code == 429:
        retry = (exc.headers or {}).get("Retry-After")
        try:
            retry_seconds = max(1, int(retry)) if retry else DEFAULT_COOLDOWN_SECONDS
        except ValueError:
            retry_seconds = DEFAULT_COOLDOWN_SECONDS
        suffix = f"; retry after {retry_seconds}s"
        operation = "token refresh" if is_refresh else "usage"
        raise ClaudeRateLimitError(
            f"Claude {operation} is rate limited{suffix}", retry_seconds
        ) from exc
    raise ClaudeUsageError(f"Claude service returned {summary}") from exc


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 15,
    diagnostic_path: Path | None = None,
) -> dict[str, Any]:
    data = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        _raise_http_error(
            url,
            exc,
            diagnostic_path=diagnostic_path,
            transport="python-urllib",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ClaudeUsageError("Could not reach the Claude usage service") from exc
    except json.JSONDecodeError as exc:
        raise ClaudeUsageError("Claude service returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ClaudeUsageError("Claude service returned an unexpected response")
    return result


def _parse_curl_headers(raw: str) -> dict[str, str]:
    blocks = re.split(r"\r?\n\r?\n", raw.strip())
    for block in reversed(blocks):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("HTTP/"):
            continue
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if separator:
                headers[name.strip()] = value.strip()
        return headers
    return {}


def _request_json_curl(
    url: str,
    *,
    body: dict[str, Any],
    timeout: float,
    diagnostic_path: Path | None = None,
) -> dict[str, Any]:
    body_fd, body_name = tempfile.mkstemp(prefix="sablier-claude-body-")
    header_fd, header_name = tempfile.mkstemp(prefix="sablier-claude-headers-")
    os.close(body_fd)
    os.close(header_fd)
    try:
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--request",
            "POST",
            "--url",
            url,
            "--header",
            "Accept: application/json, text/plain, */*",
            "--header",
            "Content-Type: application/json",
            "--header",
            f"User-Agent: {REFRESH_USER_AGENT}",
            "--header",
            "Accept-Encoding: gzip, compress, deflate, br",
            "--compressed",
            "--data-binary",
            "@-",
            "--max-time",
            str(timeout),
            "--output",
            body_name,
            "--dump-header",
            header_name,
            "--write-out",
            "%{http_code}",
        ]
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(body).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout + 5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise ClaudeUsageError("Could not run curl for Claude token refresh") from exc
        if completed.returncode != 0:
            description = _safe_error_text(
                completed.stderr.decode("utf-8", "replace")
            )
            details: dict[str, Any] = {
                "occurredAt": int(time.time()),
                "transport": "curl",
                "curlExitCode": completed.returncode,
            }
            if description:
                details["description"] = description
            if diagnostic_path is not None:
                _write_json_atomic(diagnostic_path, details)
            raise ClaudeUsageError(
                f"Claude token refresh transport failed (curl exit {completed.returncode})"
            )
        try:
            status = int(completed.stdout.decode("ascii").strip())
        except ValueError as exc:
            raise ClaudeUsageError("curl returned no Claude HTTP status") from exc
        response_body = Path(body_name).read_bytes()
        response_headers = _parse_curl_headers(
            Path(header_name).read_text(encoding="iso-8859-1")
        )
        if not 200 <= status < 300:
            error = urllib.error.HTTPError(
                url,
                status,
                f"HTTP {status}",
                response_headers,
                BytesIO(response_body),
            )
            _raise_http_error(
                url,
                error,
                diagnostic_path=diagnostic_path,
                transport="curl",
            )
        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ClaudeUsageError("Claude token refresh returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ClaudeUsageError("Claude token refresh returned an unexpected response")
        return result
    finally:
        for name in (body_name, header_name):
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass


class ClaudeAuthStore:
    def __init__(
        self,
        path: Path | None = None,
        refresh_diagnostic_path: Path = DEFAULT_REFRESH_DIAGNOSTIC_PATH,
    ) -> None:
        default_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        self.path = path or default_dir / ".credentials.json"
        self.lock_path = self.path.with_name(f"{self.path.name}.sablier.lock")
        self.refresh_diagnostic_path = refresh_diagnostic_path

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ClaudeAuthenticationError("Claude Code is not signed in") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ClaudeAuthenticationError("Could not read the Claude Code login") from exc
        oauth = data.get("claudeAiOauth")
        if not isinstance(oauth, dict) or not oauth.get("accessToken"):
            raise ClaudeAuthenticationError("Claude Code login is incomplete")
        scopes = oauth.get("scopes")
        if isinstance(scopes, list) and scopes and "user:profile" not in scopes:
            raise ClaudeAuthenticationError("Claude login lacks the user:profile scope")
        return data

    def fingerprint(self) -> str:
        oauth = self.read()["claudeAiOauth"]
        material = f"{oauth.get('accessToken', '')}\0{oauth.get('refreshToken', '')}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _expires_soon(oauth: dict[str, Any]) -> bool:
        expires_at = oauth.get("expiresAt")
        return isinstance(expires_at, (int, float)) and (
            expires_at <= time.time() * 1000 + REFRESH_WINDOW_MS
        )

    def access(self, *, force_refresh: bool = False) -> tuple[str, str]:
        data = self.read()
        if force_refresh or self._expires_soon(data["claudeAiOauth"]):
            data = self._refresh_locked(force=force_refresh)
        oauth = data["claudeAiOauth"]
        return oauth["accessToken"], str(oauth.get("subscriptionType") or "unknown")

    def _refresh_locked(self, *, force: bool) -> dict[str, Any]:
        self.lock_path.touch(mode=0o600, exist_ok=True)
        with self.lock_path.open("r+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            data = self.read()
            oauth = data["claudeAiOauth"]
            if not force and not self._expires_soon(oauth):
                return data
            refresh_token = oauth.get("refreshToken")
            if not refresh_token:
                raise ClaudeAuthenticationError("Claude refresh token is missing")
            posted_access_token = oauth["accessToken"]
            try:
                refreshed = _request_json_curl(
                    REFRESH_URL,
                    body={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": CLIENT_ID,
                        "scope": SCOPES,
                    },
                    timeout=REFRESH_TIMEOUT_SECONDS,
                    diagnostic_path=self.refresh_diagnostic_path,
                )
            except ClaudeUsageError:
                # Claude Code may have rotated the credential while our request
                # was in flight. Adopt its result rather than reporting the
                # stale request failure or overwriting the newer token pair.
                latest = self.read()
                if latest["claudeAiOauth"]["accessToken"] != posted_access_token:
                    return latest
                raise
            access_token = refreshed.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ClaudeAuthenticationError("Claude token refresh returned no access token")

            # Match Claude Code's compare-and-swap save: only persist our
            # response if the refresh token on disk is still the one posted.
            latest = self.read()
            latest_oauth = latest["claudeAiOauth"]
            if latest_oauth.get("refreshToken") != refresh_token:
                if latest_oauth["accessToken"] != posted_access_token:
                    return latest
                raise ClaudeAuthenticationError(
                    "Claude credentials changed during token refresh"
                )
            oauth = latest_oauth
            oauth["accessToken"] = access_token
            rotated = refreshed.get("refresh_token")
            if isinstance(rotated, str) and rotated:
                oauth["refreshToken"] = rotated
            refreshed_scopes = refreshed.get("scope")
            if isinstance(refreshed_scopes, str) and refreshed_scopes.strip():
                oauth["scopes"] = refreshed_scopes.split()
            expires_in = refreshed.get("expires_in")
            refreshed_at = time.time()
            if isinstance(expires_in, (int, float)):
                oauth["expiresAt"] = int(refreshed_at * 1000 + expires_in * 1000)
            refresh_expires_in = refreshed.get("refresh_token_expires_in")
            if isinstance(refresh_expires_in, (int, float)):
                oauth["refreshTokenExpiresAt"] = int(
                    refreshed_at * 1000 + refresh_expires_in * 1000
                )
            response_client_id = refreshed.get("client_id")
            if isinstance(response_client_id, str) and response_client_id:
                oauth["clientId"] = response_client_id
            self._write_atomic(latest)
            try:
                self.refresh_diagnostic_path.unlink(missing_ok=True)
            except OSError:
                pass
            return latest

    def _write_atomic(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", text=True
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(data, temp_file, separators=(",", ":"))
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, self.path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise


def _parse_reset(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _parse_window(value: Any, window_seconds: int) -> UsageWindow | None:
    if not isinstance(value, dict):
        return None
    utilization = value.get("utilization")
    if isinstance(utilization, bool) or not isinstance(utilization, (int, float)):
        return None
    used = max(0.0, min(100.0, float(utilization)))
    return UsageWindow(
        used_percent=used,
        remaining_percent=100.0 - used,
        window_seconds=window_seconds,
        reset_at=_parse_reset(value.get("resets_at")),
    )


def parse_claude_usage(
    payload: dict[str, Any], *, plan_type: str, fetched_at: int | None = None
) -> ClaudeSnapshot:
    now = fetched_at or int(time.time())
    primary = _parse_window(payload.get("five_hour"), 5 * 3600)
    secondary = _parse_window(payload.get("seven_day"), 7 * 86400)
    if primary is None and secondary is None:
        raise ClaudeUsageError("Claude response has no usage-window data")
    return ClaudeSnapshot(
        plan_type=plan_type,
        primary=primary,
        secondary=secondary,
        fetched_at=now,
    )


def _cooldown_remaining(path: Path) -> float:
    try:
        retry_at = float(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return 0
    return max(0.0, retry_at - time.time())


def _start_cooldown(path: Path, seconds: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(f"{time.time() + seconds:.0f}\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _auth_failure_matches(path: Path, fingerprint: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return data.get("credentialFingerprint") == fingerprint


def _record_auth_failure(path: Path, fingerprint: str) -> None:
    _write_json_atomic(
        path,
        {
            "credentialFingerprint": fingerprint,
            "failedAt": int(time.time()),
        },
    )


def fetch_claude_usage(
    auth_path: Path | None = None,
    cooldown_path: Path = DEFAULT_COOLDOWN_PATH,
    auth_failure_path: Path = DEFAULT_AUTH_FAILURE_PATH,
    refresh_diagnostic_path: Path = DEFAULT_REFRESH_DIAGNOSTIC_PATH,
) -> ClaudeSnapshot:
    remaining = _cooldown_remaining(cooldown_path)
    if remaining > 0:
        raise ClaudeUsageError(
            f"Claude requests cooling down; retry in {math.ceil(remaining / 60)}m"
        )
    store = ClaudeAuthStore(auth_path, refresh_diagnostic_path)
    fingerprint = store.fingerprint()
    if _auth_failure_matches(auth_failure_path, fingerprint):
        raise ClaudeAuthenticationError(
            "Claude refresh token was rejected; run 'claude auth login' again"
        )
    try:
        access_token, plan_type = store.access()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "sablier-epaper/0.1",
        }
        try:
            payload = _request_json(USAGE_URL, headers=headers, timeout=10)
        except ClaudeAuthenticationError:
            access_token, plan_type = store.access(force_refresh=True)
            headers["Authorization"] = f"Bearer {access_token}"
            payload = _request_json(USAGE_URL, headers=headers, timeout=10)
    except ClaudeRefreshRejectedError:
        _record_auth_failure(auth_failure_path, fingerprint)
        raise
    except ClaudeRateLimitError as exc:
        _start_cooldown(cooldown_path, exc.retry_after)
        raise
    try:
        cooldown_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        auth_failure_path.unlink(missing_ok=True)
    except OSError:
        pass
    return parse_claude_usage(payload, plan_type=plan_type)
