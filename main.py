#!/usr/bin/env python3
"""Fetch Claude and Codex allowances and update the e-paper display."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import json
import logging
from pathlib import Path
from typing import Iterator

from PIL import Image, UnidentifiedImageError

from sablier.claude_usage import ClaudeSnapshot, ClaudeUsageError, fetch_claude_usage
from sablier.codex_usage import UsageError, UsageSnapshot, fetch_usage
from sablier.daemon import DEFAULT_INTERVAL_SECONDS, run_daemon
from sablier.epaper import EPD2in7V2, EpaperError
from sablier.render import render_clock, render_dashboard, render_weather
from sablier.state import (
    CachedSnapshots,
    load_display_mode,
    load_snapshots,
    save_display_mode,
    save_snapshots,
)
from sablier.weather import get_weather


REFRESH_LOCK = Path("output/refresh.lock")
DISPLAYED_FRAME = Path("output/displayed.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview",
        type=Path,
        help="save a PNG preview without touching the e-paper display",
    )
    parser.add_argument(
        "--json", action="store_true", help="print normalized non-sensitive usage JSON"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="run the display mode and button controller continuously",
    )
    parser.add_argument(
        "--mode",
        choices=("usage", "clock", "weather"),
        help="display one mode (daemon default: last selected mode)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


@contextmanager
def refresh_lock() -> Iterator[bool]:
    """Prevent the timer and hardware button from refreshing concurrently."""
    REFRESH_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with REFRESH_LOCK.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_displayed_frame() -> Image.Image | None:
    try:
        with Image.open(DISPLAYED_FRAME) as image:
            frame = image.convert("1")
            frame.load()
    except (FileNotFoundError, OSError, UnidentifiedImageError):
        return None
    if frame.size != (264, 176):
        return None
    return frame


def _save_displayed_frame(image: Image.Image) -> None:
    DISPLAYED_FRAME.parent.mkdir(parents=True, exist_ok=True)
    temporary = DISPLAYED_FRAME.with_suffix(".tmp.png")
    image.save(temporary)
    temporary.replace(DISPLAYED_FRAME)


def _present_image(
    args: argparse.Namespace, image: Image.Image, refresh_mode: str
) -> None:
    output_path = args.preview or Path("output/latest.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    logging.info("Saved rendered screen to %s", output_path)
    if args.preview:
        return

    base_image = _load_displayed_frame() if refresh_mode == "partial" else None
    actual_mode = "partial" if base_image is not None else "full"
    if refresh_mode == "partial" and base_image is None:
        logging.warning("No valid displayed frame; falling back to full refresh")
    logging.info("Refreshing e-paper display (%s mode)", actual_mode)
    with EPD2in7V2() as epd:
        if base_image is not None:
            epd.display_partial(image, base_image)
        else:
            epd.display(image)
    _save_displayed_frame(image)
    logging.info("Display updated")


def update(args: argparse.Namespace, refresh_mode: str = "full") -> int:
    try:
        cached = load_snapshots()
        with ThreadPoolExecutor(max_workers=2) as executor:
            codex_future = executor.submit(fetch_usage)
            claude_future = executor.submit(fetch_claude_usage)
            try:
                codex = codex_future.result()
                codex_warning = False
            except Exception as exc:
                logging.error("Codex update failed: %s", exc)
                codex = cached.codex or UsageSnapshot("unknown", False, None, None, 0)
                codex_warning = True
            try:
                claude = claude_future.result()
                claude_warning = False
            except Exception as exc:
                logging.error("Claude update failed: %s", exc)
                claude = cached.claude or ClaudeSnapshot("unknown", None, None, 0)
                claude_warning = True

        try:
            save_snapshots(CachedSnapshots(codex=codex, claude=claude))
        except OSError as exc:
            logging.warning("Could not save usage cache: %s", exc)
        if args.json:
            print(
                json.dumps(
                    {
                        "codex": codex.to_dict(),
                        "claude": claude.to_dict(),
                        "warnings": {
                            "codex": codex_warning,
                            "claude": claude_warning,
                        },
                    },
                    indent=2,
                )
            )
        image = render_dashboard(
            codex,
            claude,
            codex_warning=codex_warning,
            claude_warning=claude_warning,
        )
        _present_image(args, image, refresh_mode)
        return 0
    except (UsageError, ClaudeUsageError, EpaperError) as exc:
        logging.error("%s", exc)
        return 1


def update_clock(
    args: argparse.Namespace,
    refresh_mode: str = "full",
    *,
    force_data: bool = False,
) -> int:
    try:
        weather, weather_warning = get_weather(force=force_data)
        if weather_warning:
            logging.warning("Weather refresh failed; using cached data when available")
        _present_image(
            args,
            render_clock(weather=weather, weather_warning=weather_warning),
            refresh_mode,
        )
        return 0
    except EpaperError as exc:
        logging.error("%s", exc)
        return 1


def update_weather(
    args: argparse.Namespace,
    refresh_mode: str = "full",
    *,
    force_data: bool = False,
) -> int:
    try:
        weather, weather_warning = get_weather(
            force=force_data, require_forecast=True
        )
        if weather_warning:
            logging.warning("Weather refresh failed; using cached data when available")
        _present_image(
            args,
            render_weather(weather=weather, weather_warning=weather_warning),
            refresh_mode,
        )
        return 0
    except EpaperError as exc:
        logging.error("%s", exc)
        return 1


def refresh_once(
    args: argparse.Namespace,
    display_mode: str = "usage",
    refresh_mode: str = "full",
    force_data: bool = False,
) -> int:
    with refresh_lock() as acquired:
        if not acquired:
            logging.info("Another refresh is already running; skipping")
            return 0
        if display_mode == "clock":
            return update_clock(args, refresh_mode, force_data=force_data)
        if display_mode == "weather":
            return update_weather(args, refresh_mode, force_data=force_data)
        return update(args, refresh_mode)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    selected_mode = args.mode or (load_display_mode() if args.daemon else "usage")
    if args.json and selected_mode != "usage":
        logging.error("--json is only available in usage mode")
        return 2
    if args.daemon:
        if args.preview or args.json:
            logging.error("--daemon cannot be combined with --preview or --json")
            return 2
        if args.interval <= 0:
            logging.error("--interval must be greater than zero")
            return 2
        return run_daemon(
            lambda display, refresh, force: refresh_once(
                args, display, refresh, force_data=force
            ),
            interval=args.interval,
            initial_mode=selected_mode,
            on_mode_change=save_display_mode,
        )
    return refresh_once(args, selected_mode)


if __name__ == "__main__":
    raise SystemExit(main())
