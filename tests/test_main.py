from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import main
from sablier.claude_usage import ClaudeSnapshot
from sablier.codex_usage import UsageError, UsageSnapshot
from sablier.state import CachedSnapshots


class UpdateTests(unittest.TestCase):
    def test_failed_provider_uses_cache_and_sets_its_warning(self) -> None:
        cached_codex = UsageSnapshot("plus", True, None, None, 1000)
        fresh_claude = ClaudeSnapshot("pro", None, None, 2000)
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                preview=Path(directory) / "preview.png",
                json=False,
                daemon=False,
                interval=300,
            )
            with (
                patch.object(
                    main,
                    "load_snapshots",
                    return_value=CachedSnapshots(codex=cached_codex),
                ),
                patch.object(main, "fetch_usage", side_effect=UsageError("offline")),
                patch.object(main, "fetch_claude_usage", return_value=fresh_claude),
                patch.object(main, "save_snapshots"),
                patch.object(
                    main,
                    "render_dashboard",
                    return_value=Image.new("1", (264, 176), 255),
                ) as render,
            ):
                self.assertEqual(main.update(args), 0)

        render.assert_called_once_with(
            cached_codex,
            fresh_claude,
            codex_warning=True,
            claude_warning=False,
        )


if __name__ == "__main__":
    unittest.main()
