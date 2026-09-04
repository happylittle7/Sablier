"""Fetch Codex subscription usage using the local Codex CLI login."""

from __future__ import annotations

import base64
import fcntl
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
REFRESH_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_WINDOW_SECONDS = 5 * 60


class UsageError(RuntimeError):
    """A safe, user-facing usage retrieval error."""


class AuthenticationError(UsageError):
    """The Codex login is missing or no longer valid."""


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float
    remaining_percent: float
    window_seconds: int | None
    reset_at: int | None


@dataclass(frozen=True)
class UsageSnapshot:
    plan_type: str
    allowed: bool
    primary: UsageWindow | None
    secondary: UsageWindow | None
    fetched_at: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT claims without treating them as verified identity data."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(decoded)
        return value if isinstance(value, dict) else {}
    except (IndexError, ValueError, UnicodeError, json.JSONDecodeError):
        return {}


def _token_expires_soon(token: str, now: int | None = None) -> bool:
    exp = _decode_jwt_payload(token).get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return exp <= (now or int(time.time())) + REFRESH_WINDOW_SECONDS


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
        if exc.code == 401:
            raise AuthenticationError("Codex login was rejected; sign in again") from exc
        if exc.code == 429:
            retry = exc.headers.get("Retry-After")
            suffix = f"; retry after {retry}s" if retry else ""
            raise UsageError(f"Codex usage is rate limited{suffix}") from exc
        raise UsageError(f"Codex service returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UsageError("Could not reach the Codex usage service") from exc
    except json.JSONDecodeError as exc:
        raise UsageError("Codex service returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise UsageError("Codex service returned an unexpected response")
    return result


class CodexAuthStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".codex" / "auth.json"
        self.lock_path = self.path.with_name(f"{self.path.name}.sablier.lock")

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AuthenticationError("Codex is not signed in on this device") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthenticationError("Could not read the Codex login") from exc
        tokens = data.get("tokens")
        if data.get("auth_mode") != "chatgpt" or not isinstance(tokens, dict):
            raise AuthenticationError("Codex must be signed in with ChatGPT")
        if not tokens.get("access_token") or not tokens.get("account_id"):
            raise AuthenticationError("Codex login is incomplete; sign in again")
        return data

    def access(self, *, force_refresh: bool = False) -> tuple[str, str]:
        data = self.read()
        token = data["tokens"]["access_token"]
        if force_refresh or _token_expires_soon(token):
            data = self._refresh_locked(force=force_refresh)
        tokens = data["tokens"]
        return tokens["access_token"], tokens["account_id"]

    def _refresh_locked(self, *, force: bool) -> dict[str, Any]:
        self.lock_path.touch(mode=0o600, exist_ok=True)
        with self.lock_path.open("r+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            data = self.read()
            tokens = data["tokens"]
            if not force and not _token_expires_soon(tokens["access_token"]):
                return data
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                raise AuthenticationError("Codex refresh token is missing; sign in again")
            refreshed = _request_json(
                REFRESH_URL,
                method="POST",
                body={
                    "client_id": CODEX_CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            for key in ("id_token", "access_token", "refresh_token"):
                value = refreshed.get(key)
                if isinstance(value, str) and value:
                    tokens[key] = value
            if not tokens.get("access_token"):
                raise AuthenticationError("Token refresh returned no access token")
            data["last_refresh"] = datetime.now(timezone.utc).isoformat()
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
                json.dump(data, temp_file, indent=2)
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _parse_window(value: Any, fetched_at: int) -> UsageWindow | None:
    if not isinstance(value, dict):
        return None
    used = _number(value.get("used_percent"))
    if used is None:
        return None
    used = max(0.0, min(100.0, used))
    seconds = _number(value.get("limit_window_seconds"))
    reset_at = _number(value.get("reset_at"))
    reset_after = _number(value.get("reset_after_seconds"))
    if reset_at is None and reset_after is not None:
        reset_at = fetched_at + reset_after
    if reset_at is not None and reset_at > 10_000_000_000:
        reset_at /= 1000
    return UsageWindow(
        used_percent=used,
        remaining_percent=100.0 - used,
        window_seconds=int(seconds) if seconds is not None else None,
        reset_at=int(reset_at) if reset_at is not None else None,
    )


def parse_usage(payload: dict[str, Any], fetched_at: int | None = None) -> UsageSnapshot:
    now = fetched_at or int(time.time())
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise UsageError("Codex response has no rate-limit data")
    return UsageSnapshot(
        plan_type=str(payload.get("plan_type") or "unknown"),
        allowed=bool(rate_limit.get("allowed", not rate_limit.get("limit_reached", False))),
        primary=_parse_window(rate_limit.get("primary_window"), now),
        secondary=_parse_window(rate_limit.get("secondary_window"), now),
        fetched_at=now,
    )


def fetch_usage(auth_path: Path | None = None) -> UsageSnapshot:
    store = CodexAuthStore(auth_path)
    access_token, account_id = store.access()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "ChatGPT-Account-Id": account_id,
        "User-Agent": "sablier-epaper/0.1",
    }
    try:
        payload = _request_json(USAGE_URL, headers=headers)
    except AuthenticationError:
        access_token, account_id = store.access(force_refresh=True)
        headers["Authorization"] = f"Bearer {access_token}"
        headers["ChatGPT-Account-Id"] = account_id
        payload = _request_json(USAGE_URL, headers=headers)
    return parse_usage(payload)
