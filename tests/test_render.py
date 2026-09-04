from __future__ import annotations

import unittest

from sablier.claude_usage import ClaudeSnapshot
from sablier.codex_usage import UsageSnapshot, UsageWindow
from sablier.render import render_dashboard, render_usage


class RenderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
