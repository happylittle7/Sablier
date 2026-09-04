#!/usr/bin/env python3
"""Render a minimal hardware test on a Waveshare 2.7-inch e-Paper HAT V2."""

from __future__ import annotations

import logging
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from sablier.epaper import EPD2in7V2


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
        )
    except OSError:
        return ImageFont.load_default()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        logging.info("Initializing 2.7-inch e-Paper HAT V2")
        image = Image.new("1", (264, 176), 255)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((3, 3, 260, 172), radius=10, outline=0, width=3)
        draw.text((18, 20), "SABLIER", font=font(34), fill=0)
        draw.line((18, 68, 246, 68), fill=0, width=2)
        draw.text((18, 82), "e-Paper OK", font=font(28), fill=0)
        draw.text((18, 132), time.strftime("%Y-%m-%d  %H:%M"), font=font(17), fill=0)

        logging.info("Refreshing display")
        with EPD2in7V2() as epd:
            epd.display(image)
        logging.info("Hardware test completed")
        return 0
    except Exception:
        logging.exception("Hardware test failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
