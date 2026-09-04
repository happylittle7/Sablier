"""Render Codex usage for a 264x176 monochrome e-paper panel."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .claude_usage import ClaudeSnapshot
from .codex_usage import UsageSnapshot, UsageWindow


WIDTH = 264
HEIGHT = 176
FONT_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
OPENAI_LOGO = (
    "...........#####..............",
    ".........#########............",
    "........###.....######........",
    ".......###.......########.....",
    "......###......####...####....",
    ".....###.....####.......###...",
    "...#####...####..........###..",
    "..######..####.....#......##..",
    ".###..##..##.....#####....##..",
    ".##...##..##...###..####..##..",
    "##....##..##.####.....######..",
    "##....##..########.....#####..",
    "##....##..###....###.....###..",
    "##....##..##......####....###.",
    "##....##..##......##.##....##.",
    ".##...###.##......##..##....##",
    ".###....####......##..##....##",
    "..###.....###....###..##....##",
    "..#####.....########..##....##",
    "..######.....####.##..##....##",
    "..##..####..###...##..##...##.",
    "..##....#####.....##..##..###.",
    "..##......#.....####..######..",
    "..###..........####...#####...",
    "...###.......####.....###.....",
    "....####...####......###......",
    ".....########.......###.......",
    "........######.....###........",
    "............#########.........",
    "..............#####...........",
)
CLAUDE_LOGO = (
    ".....##.....#.........",
    ".....###....##........",
    ".....###....##...#....",
    "......###...##..###...",
    "..##...##..##..####...",
    "..###..###.##..###....",
    "...###..##.##.###.....",
    "....#############.....",
    ".....###########......",
    ".......###############",
    "#######.############..",
    "################......",
    "........##############",
    "......#########..#####",
    "....####.#######......",
    "...###..##.######.....",
    "..###..##.##.##.###...",
    "......##..##..##..##..",
    ".....###..##..###.....",
    ".....##...##...##.....",
    "..........##..........",
    "..........#...........",
)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)
    except OSError:
        return ImageFont.load_default()


def _draw_openai_logo(
    draw: ImageDraw.ImageDraw, x: int, y: int, *, size: int = 30
) -> None:
    """Draw the supplied OpenAI mark as a crisp 1-bit bitmap."""
    for target_y in range(size):
        source_y = target_y * 30 // size
        for target_x in range(size):
            source_x = target_x * 30 // size
            if OPENAI_LOGO[source_y][source_x] == "#":
                draw.point((x + target_x, y + target_y), fill=0)


def _draw_claude_logo(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw a monochrome Claude mark derived from the supplied brand artwork."""
    for row_y, row in enumerate(CLAUDE_LOGO):
        for row_x, pixel in enumerate(row):
            if pixel == "#":
                draw.point((x + row_x, y + row_y), fill=0)


def _window_label(window: UsageWindow, fallback: str) -> str:
    seconds = window.window_seconds
    if not seconds:
        return fallback
    if seconds % 604800 == 0:
        weeks = seconds // 604800
        return "WEEK" if weeks == 1 else f"{weeks}W"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}H"
    return fallback


def _reset_text(reset_at: int | None, now: int) -> str:
    if reset_at is None:
        return "reset --"
    remaining = max(0, reset_at - now)
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"reset {days}d {hours}h"
    if hours:
        return f"reset {hours}h {minutes:02d}m"
    return f"reset {minutes}m"


def _draw_window(
    draw: ImageDraw.ImageDraw,
    window: UsageWindow,
    *,
    fallback_label: str,
    y: int,
    now: int,
) -> None:
    label_font = _font(16, bold=True)
    percent_font = _font(20, bold=True)
    small_font = _font(12)
    label = _window_label(window, fallback_label)
    percent = int(round(window.remaining_percent))

    draw.text((7, y), label, font=label_font, fill=0)
    percent_text = f"{percent}%"
    box = draw.textbbox((0, 0), percent_text, font=percent_font)
    draw.text((257 - (box[2] - box[0]), y - 3), percent_text, font=percent_font, fill=0)

    bar_x, bar_y, bar_w, bar_h = 59, y + 3, 145, 15
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=4, outline=0, width=2
    )
    fill_w = round((bar_w - 4) * window.remaining_percent / 100)
    if fill_w > 0:
        draw.rectangle(
            (bar_x + 2, bar_y + 2, bar_x + 2 + fill_w, bar_y + bar_h - 2), fill=0
        )
    draw.text((59, y + 21), _reset_text(window.reset_at, now), font=small_font, fill=0)


def render_usage(snapshot: UsageSnapshot, now: int | None = None) -> Image.Image:
    timestamp = now or int(time.time())
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    _draw_openai_logo(draw, 6, 2)
    plan = snapshot.plan_type.upper()
    plan_box = draw.textbbox((0, 0), plan, font=_font(12, bold=True))
    plan_width = plan_box[2] - plan_box[0]
    draw.rounded_rectangle((253 - plan_width, 7, 259, 25), radius=4, outline=0)
    draw.text((256 - plan_width, 8), plan, font=_font(12, bold=True), fill=0)
    draw.line((5, 34, 258, 34), fill=0, width=2)

    windows = [
        (snapshot.primary, "SESSION", 44),
        (snapshot.secondary, "WEEK", 95),
    ]
    shown = 0
    for window, fallback, y in windows:
        if window is not None:
            _draw_window(draw, window, fallback_label=fallback, y=y, now=timestamp)
            shown += 1
    if shown == 0:
        draw.text((35, 73), "No limit data", font=_font(21, bold=True), fill=0)

    status = "AVAILABLE" if snapshot.allowed else "LIMIT REACHED"
    updated = datetime.fromtimestamp(snapshot.fetched_at).strftime("%H:%M")
    footer = f"{status}   updated {updated}"
    draw.line((5, 151, 258, 151), fill=0)
    draw.text((7, 157), footer, font=_font(12, bold=not snapshot.allowed), fill=0)
    return image


def _draw_compact_window(
    draw: ImageDraw.ImageDraw,
    window: UsageWindow | None,
    *,
    label: str,
    y: int,
    now: int,
) -> None:
    draw.text((7, y), label, font=_font(13, bold=True), fill=0)
    if window is None:
        draw.text((44, y), "No data", font=_font(12), fill=0)
        return
    percent = f"{int(round(window.remaining_percent))}%"
    percent_box = draw.textbbox((0, 0), percent, font=_font(16, bold=True))
    draw.text(
        (257 - (percent_box[2] - percent_box[0]), y - 2),
        percent,
        font=_font(16, bold=True),
        fill=0,
    )
    bar_x, bar_y, bar_w, bar_h = 42, y + 1, 157, 12
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=3, outline=0
    )
    fill_w = round((bar_w - 4) * window.remaining_percent / 100)
    if fill_w:
        draw.rectangle(
            (bar_x + 2, bar_y + 2, bar_x + 2 + fill_w, bar_y + bar_h - 2), fill=0
        )
    draw.text((43, y + 14), _reset_text(window.reset_at, now), font=_font(9), fill=0)


def _draw_plan_badge(draw: ImageDraw.ImageDraw, plan: str, y: int) -> None:
    text = plan.upper()
    badge_font = _font(10, bold=True)
    box = draw.textbbox((0, 0), text, font=badge_font)
    width = box[2] - box[0]
    draw.rounded_rectangle((252 - width, y, 259, y + 16), radius=3, outline=0)
    draw.text((255 - width, y + 1), text, font=badge_font, fill=0)


def render_dashboard(
    codex: UsageSnapshot,
    claude: ClaudeSnapshot,
    now: int | None = None,
) -> Image.Image:
    """Render Claude and Codex allowance together on the 2.7-inch panel."""
    timestamp = now or int(time.time())
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    _draw_claude_logo(draw, 6, 1)
    _draw_plan_badge(draw, claude.plan_type, 3)
    _draw_compact_window(draw, claude.primary, label="5H", y=24, now=timestamp)
    _draw_compact_window(draw, claude.secondary, label="WK", y=50, now=timestamp)
    draw.line((5, 78, 258, 78), fill=0, width=2)

    _draw_openai_logo(draw, 6, 82, size=21)
    _draw_plan_badge(draw, codex.plan_type, 84)
    _draw_compact_window(draw, codex.primary, label="5H", y=106, now=timestamp)
    _draw_compact_window(draw, codex.secondary, label="WK", y=132, now=timestamp)

    latest = max(codex.fetched_at, claude.fetched_at)
    footer = datetime.fromtimestamp(latest).strftime("Updated %H:%M  |  remaining")
    draw.line((5, 160, 258, 160), fill=0)
    draw.text((7, 163), footer, font=_font(9), fill=0)
    return image
