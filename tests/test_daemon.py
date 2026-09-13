from __future__ import annotations

import unittest

from sablier.daemon import (
    BUTTON_GPIOS,
    DEBOUNCE_SECONDS,
    DEFAULT_INTERVAL_SECONDS,
    KEY4_GPIO,
    MAX_PARTIAL_REFRESHES,
    POLL_SECONDS,
    WEATHER_INTERVAL_SECONDS,
    refresh_mode_for,
    seconds_until_next_minute,
)


class DaemonConfigurationTests(unittest.TestCase):
    def test_refreshes_every_five_minutes(self) -> None:
        self.assertEqual(DEFAULT_INTERVAL_SECONDS, 300)

    def test_key4_uses_bcm_gpio_19_with_debounce(self) -> None:
        self.assertEqual(KEY4_GPIO, 19)
        self.assertEqual(DEBOUNCE_SECONDS, 0.1)
        self.assertEqual(POLL_SECONDS, 0.05)

    def test_all_mode_keys_use_the_hat_gpio_mapping(self) -> None:
        self.assertEqual(
            BUTTON_GPIOS,
            {"KEY1": 5, "KEY2": 6, "KEY3": 13, "KEY4": 19},
        )
        self.assertEqual(WEATHER_INTERVAL_SECONDS, 900)

    def test_startup_and_key4_force_full_refresh(self) -> None:
        self.assertEqual(refresh_mode_for("startup", 0), "full")
        self.assertEqual(refresh_mode_for("KEY4", 2), "full")

    def test_five_scheduled_partial_refreshes_then_full(self) -> None:
        limit = MAX_PARTIAL_REFRESHES["usage"]
        for count in range(limit):
            self.assertEqual(refresh_mode_for("scheduled", count), "partial")
        self.assertEqual(refresh_mode_for("scheduled", limit), "full")

    def test_clock_uses_fifteen_partial_refreshes_then_full(self) -> None:
        limit = MAX_PARTIAL_REFRESHES["clock"]
        self.assertEqual(limit, 15)
        self.assertEqual(refresh_mode_for("scheduled", limit - 1, "clock"), "partial")
        self.assertEqual(refresh_mode_for("scheduled", limit, "clock"), "full")

    def test_weather_refreshes_fully_once_an_hour(self) -> None:
        limit = MAX_PARTIAL_REFRESHES["weather"]
        self.assertEqual(limit, 3)
        self.assertEqual(refresh_mode_for("scheduled", limit - 1, "weather"), "partial")
        self.assertEqual(refresh_mode_for("scheduled", limit, "weather"), "full")

    def test_clock_wait_aligns_to_the_next_minute(self) -> None:
        self.assertEqual(seconds_until_next_minute(120), 60)
        self.assertEqual(seconds_until_next_minute(125.5), 54.5)


if __name__ == "__main__":
    unittest.main()
