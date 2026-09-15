#!/usr/bin/env python3
"""Generate deterministic, non-sensitive screenshots for the README."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sablier.claude_usage import ClaudeSnapshot  # noqa: E402
from sablier.codex_usage import UsageSnapshot, UsageWindow  # noqa: E402
from sablier.render import render_clock, render_dashboard, render_weather  # noqa: E402
from sablier.weather import WeatherPeriod, WeatherSnapshot  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
OUTPUT_DIRECTORY = ROOT / "docs" / "images"


def _window(
    remaining: float, seconds: int, reset_at: datetime
) -> UsageWindow:
    return UsageWindow(
        used_percent=100 - remaining,
        remaining_percent=remaining,
        window_seconds=seconds,
        reset_at=int(reset_at.timestamp()),
    )


def main() -> None:
    # render_dashboard formats its footer in the process timezone.
    os.environ["TZ"] = "Asia/Taipei"
    if hasattr(time, "tzset"):
        time.tzset()

    now = datetime(2026, 9, 6, 9, 41, tzinfo=TAIPEI)
    timestamp = int(now.timestamp())
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    claude = ClaudeSnapshot(
        plan_type="pro",
        primary=_window(72, 5 * 60 * 60, now + timedelta(hours=3, minutes=19)),
        secondary=_window(46, 7 * 24 * 60 * 60, now + timedelta(days=4, hours=8)),
        fetched_at=timestamp,
    )
    codex = UsageSnapshot(
        plan_type="plus",
        allowed=True,
        primary=_window(88, 5 * 60 * 60, now + timedelta(hours=4, minutes=6)),
        secondary=_window(64, 7 * 24 * 60 * 60, now + timedelta(days=5, hours=2)),
        fetched_at=timestamp,
    )
    weather = WeatherSnapshot(
        temperature=28,
        weather_code=2,
        is_day=True,
        high=31,
        low=25,
        rain_probability=60,
        fetched_at=timestamp,
        source="cwa",
        rain_period_start=int(now.replace(minute=0).timestamp()),
        rain_period_end=int((now.replace(minute=0) + timedelta(hours=3)).timestamp()),
        apparent_temperature=30,
        humidity=74,
        forecast_periods=tuple(
            WeatherPeriod(
                int((day_start + timedelta(hours=index * 3)).timestamp()),
                int((day_start + timedelta(hours=(index + 1) * 3)).timestamp()),
                temperature,
                code,
                rain,
            )
            for index, (temperature, code, rain) in enumerate(
                (
                    (25, 0, 10),
                    (25, 0, 10),
                    (26, 1, 20),
                    (28, 2, 30),
                    (31, 2, 60),
                    (29, 61, 80),
                    (27, 61, 50),
                    (26, 2, 30),
                )
            )
        ),
    )

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    render_dashboard(codex, claude, now=timestamp).save(
        OUTPUT_DIRECTORY / "usage.png"
    )
    render_clock(now=now, weather=weather).save(OUTPUT_DIRECTORY / "clock.png")
    render_weather(now=now, weather=weather).save(OUTPUT_DIRECTORY / "weather.png")


if __name__ == "__main__":
    main()
