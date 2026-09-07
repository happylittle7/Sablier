from __future__ import annotations

import json
import tempfile
import time
import unittest
import urllib.error
from email.message import Message
from io import BytesIO
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch

from sablier.claude_usage import (
    REFRESH_TIMEOUT_SECONDS,
    REFRESH_URL,
    REFRESH_USER_AGENT,
    ClaudeAuthStore,
    ClaudeAuthenticationError,
    ClaudeRefreshRejectedError,
    ClaudeUsageError,
    _request_json,
    _request_json_curl,
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

    def test_expired_login_refresh_matches_claude_code_request(self) -> None:
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
                "sablier.claude_usage._request_json_curl",
                return_value={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 7200,
                    "scope": "user:profile user:inference",
                },
            ) as request:
                access, plan = ClaudeAuthStore(path).access()

            self.assertEqual((access, plan), ("new-access", "pro"))
            self.assertEqual(request.call_args.args, (REFRESH_URL,))
            self.assertNotIn("headers", request.call_args.kwargs)
            self.assertEqual(
                request.call_args.kwargs["timeout"], REFRESH_TIMEOUT_SECONDS
            )
            self.assertEqual(
                request.call_args.kwargs["diagnostic_path"],
                Path("output/claude-refresh-diagnostic.json"),
            )
            saved = json.loads(path.read_text(encoding="utf-8"))["claudeAiOauth"]
            self.assertEqual(saved["refreshToken"], "new-refresh")
            self.assertEqual(saved["scopes"], ["user:profile", "user:inference"])
            self.assertIn("refreshTokenExpiresAt", saved)

    def test_refresh_adopts_credentials_rotated_by_another_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".credentials.json"
            original = {
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": int((time.time() - 60) * 1000),
                    "scopes": ["user:profile"],
                    "subscriptionType": "pro",
                }
            }
            path.write_text(json.dumps(original), encoding="utf-8")

            def rotate_during_request(*_args: object, **_kwargs: object) -> dict:
                sibling = {
                    "claudeAiOauth": {
                        **original["claudeAiOauth"],
                        "accessToken": "sibling-access",
                        "refreshToken": "sibling-refresh",
                        "expiresAt": int((time.time() + 3600) * 1000),
                    }
                }
                path.write_text(json.dumps(sibling), encoding="utf-8")
                return {
                    "access_token": "our-access",
                    "refresh_token": "our-refresh",
                    "expires_in": 3600,
                }

            with patch(
                "sablier.claude_usage._request_json_curl",
                side_effect=rotate_during_request,
            ):
                access, _plan = ClaudeAuthStore(path).access()

            self.assertEqual(access, "sibling-access")
            saved = json.loads(path.read_text(encoding="utf-8"))["claudeAiOauth"]
            self.assertEqual(saved["refreshToken"], "sibling-refresh")

    def test_failed_refresh_adopts_newer_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".credentials.json"
            original = {
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": int((time.time() - 60) * 1000),
                    "scopes": ["user:profile"],
                    "subscriptionType": "pro",
                }
            }
            path.write_text(json.dumps(original), encoding="utf-8")

            def fail_after_sibling_refresh(*_args: object, **_kwargs: object) -> dict:
                sibling = {
                    "claudeAiOauth": {
                        **original["claudeAiOauth"],
                        "accessToken": "sibling-access",
                        "refreshToken": "sibling-refresh",
                        "expiresAt": int((time.time() + 3600) * 1000),
                    }
                }
                path.write_text(json.dumps(sibling), encoding="utf-8")
                raise ClaudeUsageError("request failed")

            with patch(
                "sablier.claude_usage._request_json_curl",
                side_effect=fail_after_sibling_refresh,
            ):
                access, _plan = ClaudeAuthStore(path).access()

            self.assertEqual(access, "sibling-access")

    def test_active_cooldown_skips_auth_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cooldown = Path(directory) / "cooldown"
            cooldown.write_text(str(time.time() + 600), encoding="utf-8")
            with patch("sablier.claude_usage.ClaudeAuthStore.access") as access:
                with self.assertRaisesRegex(ClaudeUsageError, "cooling down"):
                    fetch_claude_usage(cooldown_path=cooldown)
            access.assert_not_called()

    def test_rejected_refresh_is_not_retried_for_same_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / ".credentials.json"
            failure = root / "auth-failure.json"
            auth.write_text(
                json.dumps(
                    {
                        "claudeAiOauth": {
                            "accessToken": "expired-access",
                            "refreshToken": "rejected-refresh",
                            "expiresAt": int((time.time() - 60) * 1000),
                            "scopes": ["user:profile"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            failure.write_text(
                json.dumps(
                    {
                        "credentialFingerprint": ClaudeAuthStore(auth).fingerprint(),
                        "failedAt": int(time.time()),
                    }
                ),
                encoding="utf-8",
            )

            with patch("sablier.claude_usage._request_json") as request:
                with self.assertRaisesRegex(ClaudeUsageError, "auth login"):
                    fetch_claude_usage(
                        auth_path=auth,
                        cooldown_path=root / "cooldown",
                        auth_failure_path=failure,
                    )
            request.assert_not_called()

    def test_new_login_bypasses_previous_auth_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / ".credentials.json"
            failure = root / "auth-failure.json"
            auth.write_text(
                json.dumps(
                    {
                        "claudeAiOauth": {
                            "accessToken": "old-access",
                            "refreshToken": "old-refresh",
                            "expiresAt": int((time.time() + 3600) * 1000),
                            "scopes": ["user:profile"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            failure.write_text(
                json.dumps(
                    {
                        "credentialFingerprint": ClaudeAuthStore(auth).fingerprint(),
                        "failedAt": int(time.time()),
                    }
                ),
                encoding="utf-8",
            )
            credentials = json.loads(auth.read_text(encoding="utf-8"))
            credentials["claudeAiOauth"]["accessToken"] = "new-access"
            credentials["claudeAiOauth"]["refreshToken"] = "new-refresh"
            auth.write_text(json.dumps(credentials), encoding="utf-8")

            with patch(
                "sablier.claude_usage._request_json",
                return_value={
                    "five_hour": {"utilization": 10},
                    "seven_day": {"utilization": 20},
                },
            ) as request:
                snapshot = fetch_claude_usage(
                    auth_path=auth,
                    cooldown_path=root / "cooldown",
                    auth_failure_path=failure,
                )

            self.assertEqual(snapshot.primary.remaining_percent, 90)
            request.assert_called_once()
            self.assertFalse(failure.exists())

    def test_refresh_invalid_grant_writes_safe_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            diagnostic = Path(directory) / "diagnostic.json"
            headers = Message()
            headers["request-id"] = "req_test_123"
            headers["server"] = "cloudflare"
            response = BytesIO(
                json.dumps(
                    {
                        "error": "invalid_grant",
                        "error_description": "refresh_token=secret-value was rejected",
                    }
                ).encode("utf-8")
            )
            error = urllib.error.HTTPError(
                REFRESH_URL, 400, "Bad Request", headers, response
            )
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(ClaudeRefreshRejectedError):
                    _request_json(
                        REFRESH_URL,
                        method="POST",
                        body={"refresh_token": "never-written"},
                        diagnostic_path=diagnostic,
                    )

            saved = json.loads(diagnostic.read_text(encoding="utf-8"))
            self.assertEqual(saved["httpStatus"], 400)
            self.assertEqual(saved["oauthError"], "invalid_grant")
            self.assertEqual(saved["requestId"], "req_test_123")
            self.assertEqual(saved["server"], "cloudflare")
            self.assertNotIn("secret-value", saved["description"])
            self.assertNotIn("never-written", diagnostic.read_text(encoding="utf-8"))

    def test_unknown_refresh_400_is_not_treated_as_invalid_grant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            diagnostic = Path(directory) / "diagnostic.json"
            response = BytesIO(b'{"error":"invalid_request"}')
            error = urllib.error.HTTPError(
                REFRESH_URL, 400, "Bad Request", Message(), response
            )
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(ClaudeAuthenticationError) as raised:
                    _request_json(
                        REFRESH_URL,
                        method="POST",
                        body={"refresh_token": "never-written"},
                        diagnostic_path=diagnostic,
                    )

            self.assertNotIsInstance(raised.exception, ClaudeRefreshRejectedError)
            self.assertIn("error=invalid_request", str(raised.exception))

    def test_curl_refresh_keeps_token_out_of_process_arguments(self) -> None:
        def fake_run(command: list[str], **kwargs: object) -> CompletedProcess:
            Path(command[command.index("--output") + 1]).write_text(
                '{"access_token":"new-access"}', encoding="utf-8"
            )
            Path(command[command.index("--dump-header") + 1]).write_text(
                "HTTP/2 200\r\ncontent-type: application/json\r\n\r\n",
                encoding="iso-8859-1",
            )
            self.assertNotIn("secret-refresh-token", " ".join(command))
            self.assertIn(f"User-Agent: {REFRESH_USER_AGENT}", command)
            self.assertIn("Accept: application/json, text/plain, */*", command)
            self.assertIn(b"secret-refresh-token", kwargs["input"])
            return CompletedProcess(command, 0, stdout=b"200", stderr=b"")

        with patch("sablier.claude_usage.subprocess.run", side_effect=fake_run):
            result = _request_json_curl(
                REFRESH_URL,
                body={"refresh_token": "secret-refresh-token"},
                timeout=30,
            )
        self.assertEqual(result["access_token"], "new-access")


if __name__ == "__main__":
    unittest.main()
