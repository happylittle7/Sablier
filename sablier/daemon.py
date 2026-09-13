"""Long-running display-mode scheduler and Waveshare key listener."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable


KEY1_GPIO = 5
KEY2_GPIO = 6
KEY3_GPIO = 13
KEY4_GPIO = 19
BUTTON_GPIOS = {
    "KEY1": KEY1_GPIO,
    "KEY2": KEY2_GPIO,
    "KEY3": KEY3_GPIO,
    "KEY4": KEY4_GPIO,
}
BUTTON_MODES = {"KEY1": "usage", "KEY2": "clock", "KEY3": "weather"}
DEBOUNCE_SECONDS = 0.1
POLL_SECONDS = 0.05
DEFAULT_INTERVAL_SECONDS = 5 * 60
WEATHER_INTERVAL_SECONDS = 15 * 60
MAX_PARTIAL_REFRESHES = {"usage": 5, "clock": 15, "weather": 3}


def refresh_mode_for(
    reason: str, partial_refreshes: int, display_mode: str = "usage"
) -> str:
    """Choose a ghosting-safe mode for the next refresh."""
    limit = MAX_PARTIAL_REFRESHES.get(display_mode, 0)
    if reason == "scheduled" and partial_refreshes < limit:
        return "partial"
    return "full"


def seconds_until_next_minute(now: float | None = None) -> float:
    timestamp = time.time() if now is None else now
    remainder = timestamp % 60
    return 60.0 if remainder == 0 else 60.0 - remainder


def _wait_for_trigger(
    buttons: dict[str, object], stopping: threading.Event, timeout: float
) -> str | None:
    """Poll for one debounced key press or the next scheduled refresh."""
    deadline = time.monotonic() + timeout
    while not stopping.is_set():
        for name, button in buttons.items():
            if button.is_pressed:  # type: ignore[attr-defined]
                if stopping.wait(DEBOUNCE_SECONDS):
                    return None
                if not button.is_pressed:  # type: ignore[attr-defined]
                    continue
                logging.info("%s pressed", name)
                while button.is_pressed:  # type: ignore[attr-defined]
                    if stopping.wait(POLL_SECONDS):
                        return None
                return name

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "scheduled"
        stopping.wait(min(POLL_SECONDS, remaining))
    return None


def run_daemon(
    refresh: Callable[[str, str, bool], int],
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    initial_mode: str = "usage",
    on_mode_change: Callable[[str], None] | None = None,
) -> int:
    """Schedule the active display mode and respond to all four HAT keys."""
    try:
        from gpiozero import Button
    except ImportError:
        logging.error("gpiozero is required to monitor the HAT keys")
        return 1

    stopping = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logging.info("Received signal %d; stopping daemon", signum)
        stopping.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    buttons = {
        name: Button(gpio, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
        for name, gpio in BUTTON_GPIOS.items()
    }
    logging.info(
        "Sablier daemon started; usage interval %.0fs, mode %s",
        interval,
        initial_mode,
    )

    active_mode = (
        initial_mode if initial_mode in ("usage", "clock", "weather") else "usage"
    )
    reason = "startup"
    partial_refreshes = 0
    try:
        while not stopping.is_set():
            refresh_mode = refresh_mode_for(reason, partial_refreshes, active_mode)
            logging.info(
                "Starting %s refresh (%s display, %s refresh)",
                reason,
                active_mode,
                refresh_mode,
            )
            try:
                exit_code = refresh(active_mode, refresh_mode, reason == "KEY4")
            except Exception:
                logging.exception("Unexpected refresh failure")
            else:
                if exit_code:
                    logging.warning("Refresh exited with status %d", exit_code)
                elif refresh_mode == "partial":
                    partial_refreshes += 1
                else:
                    partial_refreshes = 0

            if stopping.is_set():
                break
            wait_seconds = (
                seconds_until_next_minute()
                if active_mode == "clock"
                else WEATHER_INTERVAL_SECONDS
                if active_mode == "weather"
                else interval
            )
            deadline = time.monotonic() + wait_seconds
            while not stopping.is_set():
                trigger = _wait_for_trigger(
                    buttons, stopping, max(0.0, deadline - time.monotonic())
                )
                if trigger is None:
                    break
                target_mode = BUTTON_MODES.get(trigger)
                if target_mode is not None:
                    if target_mode == active_mode:
                        logging.info("Already in %s mode; use KEY4 to refresh", active_mode)
                        continue
                    active_mode = target_mode
                    partial_refreshes = 0
                    if on_mode_change is not None:
                        try:
                            on_mode_change(active_mode)
                        except OSError as exc:
                            logging.warning("Could not persist display mode: %s", exc)
                    reason = trigger
                    break
                reason = trigger if trigger == "KEY4" else "scheduled"
                break
            if trigger is None:
                break
        return 0
    finally:
        for button in buttons.values():
            button.close()  # type: ignore[attr-defined]
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
        logging.info("Sablier daemon stopped")
