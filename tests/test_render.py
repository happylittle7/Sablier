from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from PIL import ImageChops

from sablier.claude_usage import ClaudeSnapshot
from sablier.codex_usage import UsageSnapshot, UsageWindow
from sablier.render import (
    CLAUDE_LOGO,
    OPENAI_LOGO,
    _future_rain_summary,
    _reset_text,
    render_clock,
    render_dashboard,
    render_usage,
    render_weather,
)
from sablier.weather import WeatherPeriod, WeatherSnapshot


class RenderTests(unittest.TestCase):
    def test_provider_logos_share_native_22_pixel_canvas(self) -> None:
        for logo in (CLAUDE_LOGO, OPENAI_LOGO):
            self.assertEqual(len(logo), 22)
            self.assertTrue(all(len(row) == 22 for row in logo))

    def test_full_allowance_without_reset_is_available_now(self) -> None:
        self.assertEqual(_reset_text(None, 1000, 100), "Available now")
        self.assertEqual(_reset_text(None, 1000, 80), "Reset in --")

    def test_renders_panel_dimensions(self) -> None:
        snapshot = UsageSnapshot(
            plan_type="plus",
            allowed=True,
            primary=UsageWindow(25, 75, 18000, 4600),
            secondary=UsageWindow(60, 40, 604800, 91000),
            fetched_at=1000,
        )
        image = render_usage(snapshot, now=1000)
        self.assertEqual(image.size, (264, 176))
        self.assertEqual(image.mode, "1")

    def test_clock_changes_on_the_next_minute(self) -> None:
        first = render_clock(datetime(2026, 9, 5, 13, 4))
        second = render_clock(datetime(2026, 9, 5, 13, 5))
        self.assertEqual(first.size, (264, 176))
        self.assertEqual(first.mode, "1")
        self.assertIsNotNone(ImageChops.difference(first, second).getbbox())

    def test_renders_weather_forecast(self) -> None:
        current = datetime(2026, 9, 14, 9, 20).astimezone()
        start = int(current.replace(minute=0, second=0).timestamp())
        weather = WeatherSnapshot(
            28,
            2,
            True,
            31,
            25,
            60,
            int(current.timestamp()),
            apparent_temperature=30,
            humidity=74,
            forecast_periods=(
                WeatherPeriod(start, start + 10800, 28, 2, 20),
                WeatherPeriod(start + 10800, start + 21600, 27, 61, 60),
                WeatherPeriod(start + 21600, start + 32400, 25, 95, 80),
            ),
        )
        image = render_weather(current, weather)
        self.assertEqual(image.size, (264, 176))
        self.assertEqual(image.mode, "1")

    def test_rain_summary_uses_24_for_midnight(self) -> None:
        current = datetime(2026, 9, 14, 18, 0).astimezone()
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = int((start + timedelta(hours=21)).timestamp())
        periods = (
            WeatherPeriod(
                period_start,
                int((start + timedelta(days=1)).timestamp()),
                25,
                61,
                60,
            ),
        )
        peak, summary = _future_rain_summary(list(periods), current)
        self.assertEqual(peak, 60)
        self.assertEqual(summary, "RAIN LIKELY 21-24")

    def test_renders_combined_dashboard(self) -> None:
        codex = UsageSnapshot(
            plan_type="plus",
            allowed=True,
            primary=UsageWindow(12, 88, 18000, 4600),
            secondary=UsageWindow(17, 83, 604800, 91000),
            fetched_at=1000,
        )
        claude = ClaudeSnapshot(
            plan_type="pro",
            primary=UsageWindow(8, 92, 18000, 5000),
            secondary=UsageWindow(14, 86, 604800, 92000),
            fetched_at=1001,
        )
        image = render_dashboard(codex, claude, now=1000)
        self.assertEqual(image.size, (264, 176))
        self.assertEqual(image.mode, "1")

        warned = render_dashboard(codex, claude, now=1000, claude_warning=True)
        difference = ImageChops.difference(image, warned)
        self.assertIsNotNone(difference.getbbox())


if __name__ == "__main__":
    unittest.main()
