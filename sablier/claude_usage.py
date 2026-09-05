"""Fetch Claude subscription usage using the local Claude Code login."""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .codex_usage import UsageWindow


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
OAUTH_HEADERS = {
    "Content-Type": "application/json",
    "anthropic-beta": "oauth-2025-04-20",
    # Python urllib's default client fingerprint is rejected by the token
    # endpoint's edge security (Cloudflare error 1010).
    "User-Agent": "claude-code/2.1.260",
}
REFRESH_WINDOW_MS = 5 * 60 * 1000
DEFAULT_COOLDOWN_SECONDS = 30 * 60
DEFAULT_COOLDOWN_PATH = Path("output/claude-cooldown")


class ClaudeUsageError(RuntimeError):
    """A safe, user-facing Claude usage retrieval error."""


class ClaudeAuthenticationError(ClaudeUsageError):
    """The Claude Code login is missing or no longer valid."""


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


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 15,
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
        is_refresh = url == REFRESH_URL
        if exc.code in (400, 401):
            if is_refresh:
                raise ClaudeAuthenticationError(
                    "Claude refresh token was rejected; run 'claude auth login' again"
                ) from exc
            raise ClaudeAuthenticationError(
                "Claude login was rejected; run 'claude auth login' again"
            ) from exc
        if exc.code == 403:
            if is_refresh:
                error_body = exc.read().decode("utf-8", "replace")
                if "error code: 1010" in error_body:
                    raise ClaudeUsageError(
                        "Claude token refresh was blocked by edge security"
                    ) from exc
                raise ClaudeAuthenticationError(
                    "Claude refresh token was rejected; run 'claude auth login' again"
                ) from exc
            raise ClaudeAuthenticationError(
                "Claude login lacks the user:profile scope; sign in again"
            ) from exc
        if exc.code == 429:
            retry = exc.headers.get("Retry-After")
            try:
                retry_seconds = max(1, int(retry)) if retry else DEFAULT_COOLDOWN_SECONDS
            except ValueError:
                retry_seconds = DEFAULT_COOLDOWN_SECONDS
            suffix = f"; retry after {retry_seconds}s"
            operation = "token refresh" if is_refresh else "usage"
            raise ClaudeRateLimitError(
                f"Claude {operation} is rate limited{suffix}", retry_seconds
            ) from exc
        raise ClaudeUsageError(f"Claude service returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ClaudeUsageError("Could not reach the Claude usage service") from exc
    except json.JSONDecodeError as exc:
        raise ClaudeUsageError("Claude service returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ClaudeUsageError("Claude service returned an unexpected response")
    return result


class ClaudeAuthStore:
    def __init__(self, path: Path | None = None) -> None:
        default_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        self.path = path or default_dir / ".credentials.json"
        self.lock_path = self.path.with_name(f"{self.path.name}.sablier.lock")

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
            refreshed = _request_json(
                REFRESH_URL,
                method="POST",
                headers=OAUTH_HEADERS,
                body={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "scope": SCOPES,
                },
            )
            access_token = refreshed.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ClaudeAuthenticationError("Claude token refresh returned no access token")
            oauth["accessToken"] = access_token
            rotated = refreshed.get("refresh_token")
            if isinstance(rotated, str) and rotated:
                oauth["refreshToken"] = rotated
            expires_in = refreshed.get("expires_in")
            if isinstance(expires_in, (int, float)):
                oauth["expiresAt"] = int(time.time() * 1000 + expires_in * 1000)
            self._write_atomic(data)
            return data

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


def fetch_claude_usage(
    auth_path: Path | None = None,
    cooldown_path: Path = DEFAULT_COOLDOWN_PATH,
) -> ClaudeSnapshot:
    remaining = _cooldown_remaining(cooldown_path)
    if remaining > 0:
        raise ClaudeUsageError(
            f"Claude requests cooling down; retry in {math.ceil(remaining / 60)}m"
        )
    store = ClaudeAuthStore(auth_path)
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
    except ClaudeRateLimitError as exc:
        _start_cooldown(cooldown_path, exc.retry_after)
        raise
    try:
        cooldown_path.unlink(missing_ok=True)
    except OSError:
        pass
    return parse_claude_usage(payload, plan_type=plan_type)
