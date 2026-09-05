"""Render Codex usage for a 264x176 monochrome e-paper panel."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .claude_usage import ClaudeSnapshot
from .codex_usage import UsageSnapshot, UsageWindow
from .weather import WeatherSnapshot, weather_kind, weather_label


WIDTH = 264
HEIGHT = 176
FONT_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_MONO = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
FONT_MONO_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
FONT_RESET_MONO = Path("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf")
OPENAI_LOGO = (
    "........####..........",
    "......##########......",
    ".....###....######....",
    "....###....###..###...",
    "..####..####......##..",
    ".#####.###....#....##.",
    ".##.##.##..######..##.",
    "##..##.##.###...#####.",
    "##..##.######....####.",
    "##..##.##....###..###.",
    "##..##.##....####..##.",
    ".##.#####....##.##..##",
    ".###..###....##.##..##",
    ".####....######.##..##",
    ".#####...###.##.##..##",
    ".##..######..##.##.##.",
    ".##....#....###.#####.",
    "..##......####..####..",
    "...###..###....###....",
    "....######....###.....",
    "......##########......",
    "..........####........",
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
WARNING_ICON = (
    ".......##.......",
    ".......##.......",
    "......####......",
    "......####......",
    ".....######.....",
    "....###..###....",
    "....###..###....",
    "...####..####...",
    "...####..####...",
    "..#####..#####..",
    "..############..",
    ".##############.",
    ".######..######.",
    "################",
    ".##############.",
)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)
    except OSError:
        return ImageFont.load_default()


def _mono_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_MONO), size)
    except OSError:
        return _font(size)


def _mono_bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_MONO_BOLD), size)
    except OSError:
        return _font(size, bold=True)


def _reset_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_RESET_MONO), size)
    except OSError:
        return _mono_font(size)


def _draw_bitmap(
    draw: ImageDraw.ImageDraw, bitmap: tuple[str, ...], x: int, y: int
) -> None:
    for row_y, row in enumerate(bitmap):
        for row_x, pixel in enumerate(row):
            if pixel == "#":
                draw.point((x + row_x, y + row_y), fill=0)


def _draw_openai_logo(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw the OpenAI mark from its native 22x22 monochrome bitmap."""
    _draw_bitmap(draw, OPENAI_LOGO, x, y)


def _draw_claude_logo(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw the Claude mark from its native 22x22 monochrome bitmap."""
    _draw_bitmap(draw, CLAUDE_LOGO, x, y)


def _draw_warning_icon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw the supplied filled warning mark as a monochrome bitmap."""
    for row_y, row in enumerate(WARNING_ICON):
        for row_x, pixel in enumerate(row):
            if pixel == "#":
                draw.point((x + row_x, y + row_y), fill=0)


def _draw_sun(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.ellipse((x + 8, y + 8, x + 18, y + 18), outline=0, width=2)
    rays = (
        (13, 2, 13, 6),
        (13, 20, 13, 24),
        (2, 13, 6, 13),
        (20, 13, 24, 13),
        (5, 5, 8, 8),
        (18, 18, 21, 21),
        (18, 8, 21, 5),
        (5, 21, 8, 18),
    )
    for x1, y1, x2, y2 in rays:
        draw.line((x + x1, y + y1, x + x2, y + y2), fill=0, width=2)


def _draw_cloud(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.ellipse((x + 3, y + 9, x + 13, y + 19), fill=0)
    draw.ellipse((x + 8, y + 4, x + 20, y + 19), fill=0)
    draw.ellipse((x + 15, y + 8, x + 25, y + 19), fill=0)
    draw.rectangle((x + 7, y + 11, x + 21, y + 19), fill=0)


def _draw_weather_icon(
    draw: ImageDraw.ImageDraw, weather: WeatherSnapshot, x: int, y: int
) -> None:
    kind = weather_kind(weather.weather_code, weather.is_day)
    if kind == "clear":
        _draw_sun(draw, x, y)
        return
    if kind == "night":
        draw.ellipse((x + 5, y + 3, x + 21, y + 21), fill=0)
        draw.ellipse((x + 11, y, x + 24, y + 16), fill=255)
        return
    if kind == "partly_cloudy":
        _draw_sun(draw, x - 2, y - 3)
        _draw_cloud(draw, x + 3, y + 5)
        return
    if kind == "fog":
        _draw_cloud(draw, x, y - 4)
        for offset in (17, 21, 25):
            draw.line((x + 3, y + offset, x + 24, y + offset), fill=0, width=2)
        return

    _draw_cloud(draw, x, y - 3)
    if kind == "rain":
        for offset in (6, 13, 20):
            draw.line(
                (x + offset, y + 19, x + offset - 2, y + 25), fill=0, width=2
            )
    elif kind == "snow":
        for offset in (7, 15, 23):
            draw.line((x + offset - 2, y + 22, x + offset + 2, y + 22), fill=0)
            draw.line((x + offset, y + 20, x + offset, y + 24), fill=0)
    elif kind == "thunder":
        draw.polygon(
            (
                (x + 14, y + 17),
                (x + 9, y + 25),
                (x + 14, y + 24),
                (x + 11, y + 30),
                (x + 21, y + 20),
                (x + 16, y + 21),
            ),
            fill=0,
        )


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


def _reset_text(
    reset_at: int | None, now: int, remaining_percent: float | None = None
) -> str:
    if reset_at is None:
        if remaining_percent is not None and remaining_percent >= 99.5:
            return "Available now"
        return "Reset in --"
    remaining = max(0, reset_at - now)
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"Reset in {days}d {hours}h"
    if hours:
        return f"Reset in {hours}h {minutes:02d}m"
    return f"Reset in {minutes}m"


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
    draw.text(
        (59, y + 21),
        _reset_text(window.reset_at, now, window.remaining_percent),
        font=small_font,
        fill=0,
    )


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


def _draw_column_window(
    draw: ImageDraw.ImageDraw,
    window: UsageWindow | None,
    *,
    label: str,
    x: int,
    y: int,
    now: int,
) -> None:
    left = x + 7
    right = x + 124
    draw.text((left, y), label, font=_font(12, bold=True), fill=0)
    if window is None:
        draw.text((left, y + 21), "No data", font=_font(11), fill=0)
        return
    percent = f"{int(round(window.remaining_percent))}%"
    percent_box = draw.textbbox((0, 0), percent, font=_font(16, bold=True))
    draw.text(
        (right - (percent_box[2] - percent_box[0]), y - 2),
        percent,
        font=_font(16, bold=True),
        fill=0,
    )
    bar_x, bar_y, bar_w, bar_h = left, y + 20, 117, 12
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=3, outline=0
    )
    fill_w = round((bar_w - 4) * window.remaining_percent / 100)
    if fill_w:
        draw.rectangle(
            (bar_x + 2, bar_y + 2, bar_x + 2 + fill_w, bar_y + bar_h - 2), fill=0
        )
    draw.text(
        (left, y + 35),
        _reset_text(window.reset_at, now, window.remaining_percent),
        font=_reset_font(11),
        fill=0,
    )


def _draw_plan_label(
    draw: ImageDraw.ImageDraw, plan: str, y: int, *, right: int = 259
) -> None:
    text = plan.upper()
    label_font = _mono_font(10)
    box = draw.textbbox((0, 0), text, font=label_font)
    width = box[2] - box[0]
    draw.text((right - width + 1, y), text, font=label_font, fill=0)


def render_dashboard(
    codex: UsageSnapshot,
    claude: ClaudeSnapshot,
    now: int | None = None,
    *,
    codex_warning: bool = False,
    claude_warning: bool = False,
) -> Image.Image:
    """Render Claude and Codex allowance together on the 2.7-inch panel."""
    timestamp = now or int(time.time())
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    _draw_claude_logo(draw, 8, 2)
    if claude_warning:
        _draw_warning_icon(draw, 32, 5)
    _draw_plan_label(draw, claude.plan_type, 5, right=126)
    _draw_column_window(
        draw, claude.primary, label="SESSION", x=0, y=36, now=timestamp
    )
    _draw_column_window(
        draw, claude.secondary, label="WEEKLY", x=0, y=94, now=timestamp
    )

    _draw_openai_logo(draw, 139, 2)
    if codex_warning:
        _draw_warning_icon(draw, 164, 5)
    _draw_plan_label(draw, codex.plan_type, 5, right=258)
    _draw_column_window(
        draw, codex.primary, label="SESSION", x=132, y=36, now=timestamp
    )
    _draw_column_window(
        draw, codex.secondary, label="WEEKLY", x=132, y=94, now=timestamp
    )

    draw.line((132, 2, 132, 155), fill=0)

    latest = max(codex.fetched_at, claude.fetched_at)
    footer = (
        datetime.fromtimestamp(latest).strftime("UPDATED %H:%M")
        if latest > 0
        else "UPDATED --:--"
    )
    footer_font = _mono_font(10)
    footer_box = draw.textbbox((0, 0), footer, font=footer_font)
    footer_width = footer_box[2] - footer_box[0]
    draw.line((5, 157, 258, 157), fill=0)
    draw.text(((WIDTH - footer_width) // 2, 164), footer, font=footer_font, fill=0)
    return image


def _centered_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    draw.text(((WIDTH - width) // 2, y), text, font=font, fill=0)


def _column_text(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    draw.text((center_x - width // 2, y), text, font=font, fill=0)


def render_clock(
    now: datetime | None = None,
    weather: WeatherSnapshot | None = None,
    *,
    weather_warning: bool = False,
) -> Image.Image:
    """Render a quiet minute-resolution clock for the e-paper display."""
    current = now or datetime.now().astimezone()
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    draw.text((8, 3), "BANQIAO", font=_mono_bold_font(11), fill=0)
    date_text = f"{current.strftime('%a').upper()} · {current.strftime('%b %d').upper()}"
    draw.text((8, 17), date_text, font=_mono_font(9), fill=0)
    if weather is not None:
        _draw_weather_icon(draw, weather, 187, 1)
        draw.text(
            (218, 4),
            f"{round(weather.temperature):.0f}°C",
            font=_font(17, bold=True),
            fill=0,
        )
    else:
        draw.text((218, 4), "--°C", font=_font(17, bold=True), fill=0)
    if weather_warning:
        _draw_warning_icon(draw, 166, 5)

    hour, minute = current.strftime("%H:%M").split(":")
    digit_font = _font(66, bold=True)
    colon_font = _font(48, bold=True)
    gap = 4
    hour_width = draw.textlength(hour, font=digit_font)
    colon_width = draw.textlength(":", font=colon_font)
    minute_width = draw.textlength(minute, font=digit_font)
    time_width = hour_width + gap + colon_width + gap + minute_width
    x = (WIDTH - time_width) / 2
    draw.text((x, 36), hour, font=digit_font, fill=0)
    x += hour_width + gap
    draw.text((x, 42), ":", font=colon_font, fill=0)
    x += colon_width + gap
    draw.text((x, 36), minute, font=digit_font, fill=0)

    condition = (
        weather_label(weather.weather_code, weather.is_day)
        if weather is not None
        else "WEATHER UNAVAILABLE"
    )
    _centered_text(draw, 108, condition, _mono_font(10))
    draw.line((8, 128, 255, 128), fill=0)
    if weather is not None:
        values = (
            f"{round(weather.high):.0f}°C",
            f"{round(weather.low):.0f}°C",
            f"{weather.rain_probability}%",
        )
    else:
        values = ("--°C", "--°C", "--%")
    centers = (45, 132, 219)
    for center, label, value in zip(centers, ("HIGH", "LOW", "RAIN"), values):
        _column_text(draw, center, 134, label, _mono_font(8))
        _column_text(draw, center, 146, value, _mono_bold_font(15))
    draw.line((88, 135, 88, 168), fill=0)
    draw.line((176, 135, 176, 168), fill=0)
    return image
