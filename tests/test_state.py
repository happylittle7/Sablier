from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sablier.claude_usage import ClaudeSnapshot
from sablier.codex_usage import UsageSnapshot, UsageWindow
from sablier.state import CachedSnapshots, load_snapshots, save_snapshots


class StateTests(unittest.TestCase):
    def test_round_trips_provider_snapshots(self) -> None:
        snapshots = CachedSnapshots(
            codex=UsageSnapshot(
                "plus", True, UsageWindow(10, 90, 18000, 2000), None, 1000
            ),
            claude=ClaudeSnapshot(
                "pro", None, UsageWindow(20, 80, 604800, 3000), 1001
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage-cache.json"
            save_snapshots(snapshots, path)
            self.assertEqual(load_snapshots(path), snapshots)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_cache_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage-cache.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_snapshots(path), CachedSnapshots())


if __name__ == "__main__":
    unittest.main()
