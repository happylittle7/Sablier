from __future__ import annotations

import unittest

from sablier.claude_usage import ClaudeUsageError, parse_claude_usage


class ParseClaudeUsageTests(unittest.TestCase):
    def test_parses_five_hour_and_weekly_windows(self) -> None:
        snapshot = parse_claude_usage(
            {
                "five_hour": {
                    "utilization": 8,
                    "resets_at": "2026-09-04T12:09:59+00:00",
                },
                "seven_day": {
                    "utilization": 14,
                    "resets_at": "2026-09-07T16:59:59+00:00",
                },
            },
            plan_type="pro",
            fetched_at=1000,
        )
        self.assertEqual(snapshot.plan_type, "pro")
        self.assertEqual(snapshot.primary.remaining_percent, 92)
        self.assertEqual(snapshot.primary.window_seconds, 18000)
        self.assertEqual(snapshot.secondary.remaining_percent, 86)
        self.assertEqual(snapshot.secondary.window_seconds, 604800)

    def test_rejects_missing_windows(self) -> None:
        with self.assertRaises(ClaudeUsageError):
            parse_claude_usage({}, plan_type="pro")


if __name__ == "__main__":
    unittest.main()
