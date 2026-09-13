"""Persist the latest non-sensitive provider snapshots for failure fallback."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .claude_usage import ClaudeSnapshot
from .codex_usage import UsageSnapshot, UsageWindow


DEFAULT_CACHE_PATH = Path("output/usage-cache.json")
DEFAULT_DISPLAY_STATE_PATH = Path("output/display-state.json")
DISPLAY_MODES = frozenset({"usage", "clock", "weather"})


@dataclass(frozen=True)
class CachedSnapshots:
    codex: UsageSnapshot | None = None
    claude: ClaudeSnapshot | None = None


def _window(value: Any) -> UsageWindow | None:
    if not isinstance(value, dict):
        return None
    try:
        return UsageWindow(
            used_percent=float(value["used_percent"]),
            remaining_percent=float(value["remaining_percent"]),
            window_seconds=(
                int(value["window_seconds"])
                if value.get("window_seconds") is not None
                else None
            ),
            reset_at=(
                int(value["reset_at"]) if value.get("reset_at") is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _codex(value: Any) -> UsageSnapshot | None:
    if not isinstance(value, dict):
        return None
    try:
        return UsageSnapshot(
            plan_type=str(value["plan_type"]),
            allowed=bool(value["allowed"]),
            primary=_window(value.get("primary")),
            secondary=_window(value.get("secondary")),
            fetched_at=int(value["fetched_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _claude(value: Any) -> ClaudeSnapshot | None:
    if not isinstance(value, dict):
        return None
    try:
        return ClaudeSnapshot(
            plan_type=str(value["plan_type"]),
            primary=_window(value.get("primary")),
            secondary=_window(value.get("secondary")),
            fetched_at=int(value["fetched_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_snapshots(path: Path = DEFAULT_CACHE_PATH) -> CachedSnapshots:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return CachedSnapshots()
    if not isinstance(value, dict):
        return CachedSnapshots()
    return CachedSnapshots(
        codex=_codex(value.get("codex")),
        claude=_claude(value.get("claude")),
    )


def save_snapshots(
    snapshots: CachedSnapshots, path: Path = DEFAULT_CACHE_PATH
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "codex": snapshots.codex.to_dict() if snapshots.codex else None,
        "claude": snapshots.claude.to_dict() if snapshots.claude else None,
    }
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, separators=(",", ":"))
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


def load_display_mode(path: Path = DEFAULT_DISPLAY_STATE_PATH) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return "usage"
    if isinstance(value, dict) and value.get("mode") in DISPLAY_MODES:
        return str(value["mode"])
    return "usage"


def save_display_mode(mode: str, path: Path = DEFAULT_DISPLAY_STATE_PATH) -> None:
    if mode not in DISPLAY_MODES:
        raise ValueError(f"unsupported display mode: {mode}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"mode": mode}, output, separators=(",", ":"))
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
