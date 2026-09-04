#!/usr/bin/env python3
"""Refresh the Sablier display when KEY4 on the Waveshare HAT is pressed."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys
from typing import Callable


KEY4_GPIO = 19
DEBOUNCE_SECONDS = 0.1
PROJECT_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_DIR / "main.py"


def refresh_once(
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> int:
    """Run one refresh and return its process exit code."""
    result = runner(
        [sys.executable, str(MAIN_SCRIPT)],
        cwd=PROJECT_DIR,
        check=False,
    )
    return result.returncode


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        from gpiozero import Button
    except ImportError:
        logging.error("gpiozero is required to monitor KEY4")
        return 1

    button = Button(KEY4_GPIO, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    logging.info("Watching KEY4 on BCM GPIO %d", KEY4_GPIO)
    try:
        while True:
            button.wait_for_press()
            logging.info("KEY4 pressed; refreshing display")
            exit_code = refresh_once()
            if exit_code:
                logging.warning("Display refresh exited with status %d", exit_code)
            button.wait_for_release()
    except KeyboardInterrupt:
        logging.info("Button watcher stopped")
        return 0
    finally:
        button.close()


if __name__ == "__main__":
    raise SystemExit(main())
