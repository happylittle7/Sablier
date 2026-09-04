from __future__ import annotations

import unittest

from sablier.daemon import (
    DEBOUNCE_SECONDS,
    DEFAULT_INTERVAL_SECONDS,
    KEY4_GPIO,
    MAX_PARTIAL_REFRESHES,
    POLL_SECONDS,
    refresh_mode_for,
)


class DaemonConfigurationTests(unittest.TestCase):
    def test_refreshes_every_five_minutes(self) -> None:
        self.assertEqual(DEFAULT_INTERVAL_SECONDS, 300)

    def test_key4_uses_bcm_gpio_19_with_debounce(self) -> None:
        self.assertEqual(KEY4_GPIO, 19)
        self.assertEqual(DEBOUNCE_SECONDS, 0.1)
        self.assertEqual(POLL_SECONDS, 0.05)

    def test_startup_and_key4_force_full_refresh(self) -> None:
        self.assertEqual(refresh_mode_for("startup", 0), "full")
        self.assertEqual(refresh_mode_for("KEY4", 2), "full")

    def test_five_scheduled_partial_refreshes_then_full(self) -> None:
        for count in range(MAX_PARTIAL_REFRESHES):
            self.assertEqual(refresh_mode_for("scheduled", count), "partial")
        self.assertEqual(
            refresh_mode_for("scheduled", MAX_PARTIAL_REFRESHES), "full"
        )


if __name__ == "__main__":
    unittest.main()
