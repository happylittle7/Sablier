from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sablier.claude_usage import (
    OAUTH_HEADERS,
    REFRESH_URL,
    ClaudeAuthStore,
    ClaudeUsageError,
    fetch_claude_usage,
    parse_claude_usage,
)


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

    def test_expired_login_refresh_uses_claude_code_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".credentials.json"
            path.write_text(
                json.dumps(
                    {
                        "claudeAiOauth": {
                            "accessToken": "old-access",
                            "refreshToken": "old-refresh",
                            "expiresAt": int((time.time() - 60) * 1000),
                            "scopes": ["user:profile"],
                            "subscriptionType": "pro",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "sablier.claude_usage._request_json",
                return_value={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            ) as request:
                access, plan = ClaudeAuthStore(path).access()

            self.assertEqual((access, plan), ("new-access", "pro"))
            self.assertEqual(request.call_args.args, (REFRESH_URL,))
            self.assertEqual(request.call_args.kwargs["headers"], OAUTH_HEADERS)
            saved = json.loads(path.read_text(encoding="utf-8"))["claudeAiOauth"]
            self.assertEqual(saved["refreshToken"], "new-refresh")

    def test_active_cooldown_skips_auth_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cooldown = Path(directory) / "cooldown"
            cooldown.write_text(str(time.time() + 600), encoding="utf-8")
            with patch("sablier.claude_usage.ClaudeAuthStore.access") as access:
                with self.assertRaisesRegex(ClaudeUsageError, "cooling down"):
                    fetch_claude_usage(cooldown_path=cooldown)
            access.assert_not_called()


if __name__ == "__main__":
    unittest.main()
