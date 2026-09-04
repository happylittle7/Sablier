#!/usr/bin/env python3
"""Fetch Codex allowance and update the e-paper display."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path

from sablier.claude_usage import ClaudeUsageError, fetch_claude_usage
from sablier.codex_usage import UsageError, fetch_usage
from sablier.epaper import EPD2in7V2, EpaperError
from sablier.render import render_dashboard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview",
        type=Path,
        help="save a PNG preview without touching the e-paper display",
    )
    parser.add_argument(
        "--json", action="store_true", help="print normalized non-sensitive usage JSON"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            codex_future = executor.submit(fetch_usage)
            claude_future = executor.submit(fetch_claude_usage)
            codex = codex_future.result()
            claude = claude_future.result()
        if args.json:
            print(
                json.dumps(
                    {"codex": codex.to_dict(), "claude": claude.to_dict()}, indent=2
                )
            )
        image = render_dashboard(codex, claude)
        if args.preview:
            output_path = args.preview
        else:
            output_path = Path("output/latest.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        logging.info("Saved rendered dashboard to %s", output_path)
        if not args.preview:
            logging.info("Refreshing e-paper display")
            with EPD2in7V2() as epd:
                epd.display(image)
            logging.info("Display updated")
        return 0
    except (UsageError, ClaudeUsageError, EpaperError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
