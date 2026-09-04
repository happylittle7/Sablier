from __future__ import annotations

import unittest

from sablier.daemon import (
    DEBOUNCE_SECONDS,
    DEFAULT_INTERVAL_SECONDS,
    KEY4_GPIO,
    POLL_SECONDS,
)


class DaemonConfigurationTests(unittest.TestCase):
    def test_refreshes_every_five_minutes(self) -> None:
        self.assertEqual(DEFAULT_INTERVAL_SECONDS, 300)

    def test_key4_uses_bcm_gpio_19_with_debounce(self) -> None:
        self.assertEqual(KEY4_GPIO, 19)
        self.assertEqual(DEBOUNCE_SECONDS, 0.1)
        self.assertEqual(POLL_SECONDS, 0.05)


if __name__ == "__main__":
    unittest.main()
