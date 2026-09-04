"""Long-running refresh scheduler and Waveshare KEY4 listener."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable


KEY4_GPIO = 19
DEBOUNCE_SECONDS = 0.1
POLL_SECONDS = 0.05
DEFAULT_INTERVAL_SECONDS = 5 * 60


def _wait_for_trigger(button: object, stopping: threading.Event, interval: float) -> str | None:
    """Poll for one debounced KEY4 press or the next scheduled refresh."""
    deadline = time.monotonic() + interval
    while not stopping.is_set():
        if button.is_pressed:  # type: ignore[attr-defined]
            if stopping.wait(DEBOUNCE_SECONDS):
                return None
            if not button.is_pressed:  # type: ignore[attr-defined]
                continue
            logging.info("KEY4 pressed; requesting refresh")
            while button.is_pressed:  # type: ignore[attr-defined]
                if stopping.wait(POLL_SECONDS):
                    return None
            return "KEY4"

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "scheduled"
        stopping.wait(min(POLL_SECONDS, remaining))
    return None


def run_daemon(
    refresh: Callable[[], int],
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> int:
    """Refresh at startup, after each interval, and on every KEY4 press."""
    try:
        from gpiozero import Button
    except ImportError:
        logging.error("gpiozero is required to monitor KEY4")
        return 1

    stopping = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logging.info("Received signal %d; stopping daemon", signum)
        stopping.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    button = Button(KEY4_GPIO, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    logging.info(
        "Sablier daemon started; interval %.0fs, KEY4 on BCM GPIO %d",
        interval,
        KEY4_GPIO,
    )

    reason = "startup"
    try:
        while not stopping.is_set():
            logging.info("Starting %s refresh", reason)
            try:
                exit_code = refresh()
            except Exception:
                logging.exception("Unexpected refresh failure")
            else:
                if exit_code:
                    logging.warning("Refresh exited with status %d", exit_code)

            if stopping.is_set():
                break
            trigger = _wait_for_trigger(button, stopping, interval)
            if trigger is None:
                break
            reason = trigger
        return 0
    finally:
        button.close()
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
        logging.info("Sablier daemon stopped")
