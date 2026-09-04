from __future__ import annotations

import unittest

from sablier.codex_usage import UsageError, parse_usage


class ParseUsageTests(unittest.TestCase):
    def test_parses_windows_and_fallback_reset(self) -> None:
        snapshot = parse_usage(
            {
                "plan_type": "plus",
                "rate_limit": {
                    "allowed": True,
                    "primary_window": {
                        "used_percent": 22.4,
                        "limit_window_seconds": 18000,
                        "reset_after_seconds": 600,
                    },
                    "secondary_window": {
                        "used_percent": 70,
                        "limit_window_seconds": 604800,
                        "reset_at": 2000,
                    },
                },
            },
            fetched_at=1000,
        )
        self.assertEqual(snapshot.plan_type, "plus")
        self.assertAlmostEqual(snapshot.primary.remaining_percent, 77.6)
        self.assertEqual(snapshot.primary.reset_at, 1600)
        self.assertEqual(snapshot.secondary.remaining_percent, 30)

    def test_clamps_percentages(self) -> None:
        snapshot = parse_usage(
            {
                "rate_limit": {
                    "primary_window": {"used_percent": 120},
                    "secondary_window": {"used_percent": -5},
                }
            },
            fetched_at=1000,
        )
        self.assertEqual(snapshot.primary.remaining_percent, 0)
        self.assertEqual(snapshot.secondary.remaining_percent, 100)

    def test_rejects_missing_rate_limit(self) -> None:
        with self.assertRaises(UsageError):
            parse_usage({})


if __name__ == "__main__":
    unittest.main()
