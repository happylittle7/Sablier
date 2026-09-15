"""Render Codex usage for a 264x176 monochrome e-paper panel."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .claude_usage import ClaudeSnapshot
from .codex_usage import UsageSnapshot, UsageWindow
from .weather import WeatherPeriod, WeatherSnapshot, weather_kind, weather_label


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


def _draw_cloud_with_halo(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Separate a foreground cloud from a sun or moon behind it."""
    draw.ellipse((x + 1, y + 7, x + 15, y + 21), fill=255)
    draw.ellipse((x + 6, y + 2, x + 22, y + 21), fill=255)
    draw.ellipse((x + 13, y + 6, x + 27, y + 21), fill=255)
    draw.rectangle((x + 5, y + 9, x + 23, y + 21), fill=255)
    _draw_cloud(draw, x, y)


def _draw_moon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.ellipse((x + 5, y + 3, x + 21, y + 21), fill=0)
    draw.ellipse((x + 11, y, x + 24, y + 16), fill=255)


def _draw_weather_icon(
    draw: ImageDraw.ImageDraw, weather: WeatherSnapshot, x: int, y: int
) -> None:
    _draw_weather_symbol(draw, weather.weather_code, weather.is_day, x, y)


def _draw_weather_symbol(
    draw: ImageDraw.ImageDraw, code: int, is_day: bool, x: int, y: int
) -> None:
    kind = weather_kind(code, is_day)
    if kind == "clear":
        _draw_sun(draw, x, y)
        return
    if kind == "night":
        _draw_moon(draw, x, y)
        return
    if kind == "partly_cloudy":
        if is_day:
            _draw_sun(draw, x - 2, y - 3)
        else:
            _draw_moon(draw, x - 2, y - 3)
        _draw_cloud_with_halo(draw, x + 3, y + 5)
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


def _tracked_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    tracking: int = 1,
) -> None:
    """Draw tiny labels with explicit spacing for clearer e-paper pixels."""
    x, y = position
    for character in text:
        draw.text((x, y), character, font=font, fill=0)
        x += round(draw.textlength(character, font=font)) + tracking


def _draw_arrow_icon(
    draw: ImageDraw.ImageDraw, x: int, y: int, *, up: bool
) -> None:
    """Draw a crisp filled temperature trend arrow."""
    if up:
        draw.polygon(
            (
                (x + 5, y),
                (x + 10, y + 6),
                (x + 7, y + 6),
                (x + 7, y + 13),
                (x + 3, y + 13),
                (x + 3, y + 6),
                (x, y + 6),
            ),
            fill=0,
        )
    else:
        draw.polygon(
            (
                (x + 3, y),
                (x + 7, y),
                (x + 7, y + 7),
                (x + 10, y + 7),
                (x + 5, y + 13),
                (x, y + 7),
                (x + 3, y + 7),
            ),
            fill=0,
        )


def _draw_rain_icon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw an umbrella that reads clearly as rain at e-paper resolution."""
    draw.text((x, y - 3), "☂", font=_font(18, bold=True), fill=0)


def _draw_thermometer_icon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rounded_rectangle((x + 3, y, x + 8, y + 10), radius=2, outline=0)
    draw.line((x + 5, y + 4, x + 5, y + 11), fill=0, width=2)
    draw.ellipse((x + 1, y + 8, x + 10, y + 17), fill=0)


def _draw_humidity_icon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.polygon(
        (
            (x + 6, y),
            (x + 1, y + 8),
            (x + 1, y + 11),
            (x + 3, y + 15),
            (x + 6, y + 17),
            (x + 9, y + 15),
            (x + 11, y + 11),
            (x + 11, y + 8),
        ),
        fill=0,
    )


def _draw_umbrella_icon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw a legible outline umbrella without relying on a font glyph."""
    draw.arc((x, y, x + 14, y + 10), 180, 360, fill=0, width=2)
    draw.line(
        (
            x,
            y + 5,
            x + 3,
            y + 4,
            x + 5,
            y + 5,
            x + 8,
            y + 4,
            x + 10,
            y + 5,
            x + 14,
            y + 5,
        ),
        fill=0,
        width=1,
    )
    draw.line((x + 7, y + 5, x + 7, y + 12), fill=0, width=2)
    draw.arc((x + 7, y + 9, x + 12, y + 14), 0, 100, fill=0, width=2)


def _draw_clock_metric(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: int,
    value: str,
    caption: str,
    icon: str,
) -> None:
    value_font = _font(16, bold=True)
    caption_font = _font(11)
    value_width = draw.textlength(value, font=value_font)
    icon_width = 16 if icon == "rain" else 10
    gap = 4
    left = round(center_x - (icon_width + gap + value_width) / 2)
    if icon == "high":
        _draw_arrow_icon(draw, left, 135, up=True)
    elif icon == "low":
        _draw_arrow_icon(draw, left, 135, up=False)
    else:
        _draw_rain_icon(draw, left, 134)
    draw.text((left + icon_width + gap, 131), value, font=value_font, fill=0)
    _column_text(draw, center_x, 156, caption, caption_font)


def _rain_period_label(
    weather: WeatherSnapshot | None, current: datetime
) -> str:
    if (
        weather is None
        or weather.rain_period_start is None
        or weather.rain_period_end is None
    ):
        return "TODAY" if weather is not None else "RAIN"
    timezone = current.tzinfo
    start = datetime.fromtimestamp(weather.rain_period_start, timezone)
    end = datetime.fromtimestamp(weather.rain_period_end, timezone)
    return f"{start:%H}–{end:%H}"


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

    draw.text((8, 3), "WENSHAN", font=_mono_bold_font(11), fill=0)
    date_text = f"{current.strftime('%a').upper()}  {current.strftime('%b %d').upper()}"
    draw.text((8, 17), date_text, font=_font(10, bold=True), fill=0)
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
    captions = ("HIGH", "LOW", _rain_period_label(weather, current))
    for center, value, caption, icon in zip(
        (45, 132, 219), values, captions, ("high", "low", "rain")
    ):
        _draw_clock_metric(
            draw,
            center_x=center,
            value=value,
            caption=caption,
            icon=icon,
        )
    draw.line((88, 133, 88, 170), fill=0)
    draw.line((176, 133, 176, 170), fill=0)
    return image


def _today_weather_periods(
    weather: WeatherSnapshot, current: datetime
) -> list[WeatherPeriod]:
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return sorted(
        (
            period
            for period in weather.forecast_periods
            if period.start < day_end.timestamp()
            and period.end > day_start.timestamp()
        ),
        key=lambda period: period.start,
    )


def _future_rain_summary(
    periods: list[WeatherPeriod], current: datetime
) -> tuple[int | None, str]:
    now = current.timestamp()
    future = [period for period in periods if period.end > now]
    if not future:
        return None, "NO MORE FORECAST TODAY"

    peak = max(period.rain_probability for period in future)
    threshold = 50 if peak >= 50 else 30 if peak >= 30 else None
    if threshold is None:
        return peak, "LOW RAIN RISK TODAY"

    candidates = [period for period in future if period.rain_probability >= threshold]
    first = candidates[0]
    last = first
    for period in candidates[1:]:
        if period.start != last.end:
            break
        last = period

    start = datetime.fromtimestamp(first.start, current.tzinfo)
    end = datetime.fromtimestamp(last.end, current.tzinfo)
    likelihood = "LIKELY" if threshold == 50 else "POSSIBLE"
    end_hour = (
        "24" if end.date() > current.date() and end.hour == 0 else f"{end:%H}"
    )
    if first.start <= now:
        period_label = f"NOW-{end_hour}"
    else:
        period_label = f"{start:%H}-{end_hour}"
    return peak, f"RAIN {likelihood} {period_label}"


def _compact_rain_summary(summary: str) -> str:
    if summary.startswith("RAIN "):
        return summary.removeprefix("RAIN ")
    if summary == "LOW RAIN RISK TODAY":
        return "LOW RISK"
    if summary == "NO MORE FORECAST TODAY":
        return "NO FORECAST"
    return summary


def _forecast_periods(
    weather: WeatherSnapshot, current: datetime, *, count: int = 4
) -> list[WeatherPeriod]:
    now = current.timestamp()
    return sorted(
        (period for period in weather.forecast_periods if period.end > now),
        key=lambda period: period.start,
    )[:count]


def _forecast_label(period: WeatherPeriod, current: datetime) -> str:
    if period.start <= current.timestamp() < period.end:
        return "NOW"
    start = datetime.fromtimestamp(period.start, current.tzinfo)
    end = datetime.fromtimestamp(period.end, current.tzinfo)
    end_hour = "24" if end.date() > start.date() and end.hour == 0 else f"{end:%H}"
    return f"{start:%H}-{end_hour}"


def _draw_forecast_slot(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: int,
    period: WeatherPeriod | None,
    current: datetime,
) -> None:
    if period is None:
        _column_text(draw, center_x, 67, "--", _mono_bold_font(9))
        _column_text(draw, center_x, 105, "--°C", _font(12, bold=True))
        return

    _column_text(
        draw,
        center_x,
        67,
        _forecast_label(period, current),
        _mono_bold_font(9),
    )
    midpoint = datetime.fromtimestamp(
        period.start + (period.end - period.start) / 2, current.tzinfo
    )
    _draw_weather_symbol(
        draw,
        period.weather_code,
        6 <= midpoint.hour < 18,
        center_x - 14,
        78,
    )
    _column_text(
        draw,
        center_x,
        105,
        f"{round(period.temperature):.0f}°C",
        _font(12, bold=True),
    )


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    dash: int = 3,
    gap: int = 3,
    width: int = 1,
) -> None:
    x1, y1 = start
    x2, y2 = end
    if x1 == x2:
        direction = 1 if y2 >= y1 else -1
        position = y1
        while (position - y2) * direction <= 0:
            finish = position + direction * (dash - 1)
            finish = min(finish, y2) if direction > 0 else max(finish, y2)
            draw.line((x1, position, x2, finish), fill=0, width=width)
            position += direction * (dash + gap)
        return

    direction = 1 if x2 >= x1 else -1
    position = x1
    while (position - x2) * direction <= 0:
        finish = position + direction * (dash - 1)
        finish = min(finish, x2) if direction > 0 else max(finish, x2)
        draw.line((position, y1, finish, y2), fill=0, width=width)
        position += direction * (dash + gap)


def _draw_rain_chart(
    draw: ImageDraw.ImageDraw,
    periods: list[WeatherPeriod],
    current: datetime,
) -> None:
    plot_left, plot_right = 27, 257
    plot_top, plot_bottom = 143, 161
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    day_start_ts = day_start.timestamp()
    day_seconds = (day_end - day_start).total_seconds()

    def x_for(timestamp: float) -> int:
        ratio = (timestamp - day_start_ts) / day_seconds
        return round(plot_left + max(0, min(1, ratio)) * (plot_right - plot_left))

    def y_for(probability: int) -> int:
        ratio = max(0, min(100, probability)) / 100
        return round(plot_bottom - ratio * (plot_bottom - plot_top))

    grid_font = _mono_font(7)
    middle_y = y_for(50)
    draw.text((5, middle_y - 4), "50", font=grid_font, fill=0)
    _dashed_line(draw, (plot_left, middle_y), (plot_right, middle_y), dash=2, gap=3)
    draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill=0)

    axis_font = _mono_bold_font(8)
    for hour in (0, 6, 12, 18, 24):
        timestamp = day_start_ts + hour * 3600
        x = x_for(timestamp)
        label = f"{hour:02d}"
        box = draw.textbbox((0, 0), label, font=axis_font)
        width = box[2] - box[0]
        draw.text(
            (max(2, min(WIDTH - width - 2, x - width // 2)), 165),
            label,
            font=axis_font,
            fill=0,
        )

    now_ts = current.timestamp()
    if day_start_ts <= now_ts < day_end.timestamp():
        now_x = x_for(now_ts)
        _dashed_line(draw, (now_x, plot_top), (now_x, plot_bottom), dash=2, gap=2)
        draw.polygon(
            ((now_x - 2, plot_top - 3), (now_x + 2, plot_top - 3), (now_x, plot_top)),
            fill=0,
        )

    previous: WeatherPeriod | None = None
    for period in periods:
        start = max(period.start, day_start_ts)
        end = min(period.end, day_end.timestamp())
        if start >= end:
            continue
        x1, x2 = x_for(start), x_for(end)
        y = y_for(period.rain_probability)
        if previous is not None and previous.end == period.start:
            boundary = x_for(period.start)
            previous_y = y_for(previous.rain_probability)
            if period.start < now_ts:
                _dashed_line(draw, (boundary, previous_y), (boundary, y), dash=2, gap=2)
            else:
                draw.line((boundary, previous_y, boundary, y), fill=0, width=2)

        if end <= now_ts:
            _dashed_line(draw, (x1, y), (x2, y), dash=3, gap=2)
        elif start < now_ts < end:
            now_x = x_for(now_ts)
            _dashed_line(draw, (x1, y), (now_x, y), dash=3, gap=2)
            draw.line((now_x, y, x2, y), fill=0, width=2)
        else:
            draw.line((x1, y, x2, y), fill=0, width=2)
        previous = period


def render_weather(
    now: datetime | None = None,
    weather: WeatherSnapshot | None = None,
    *,
    weather_warning: bool = False,
) -> Image.Image:
    """Render current conditions, four forecast slots, and a rain sparkline."""
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    draw.text((7, 3), "WENSHAN", font=_mono_bold_font(11), fill=0)
    date_text = f"{current.strftime('%a').upper()}  {current.strftime('%b %d').upper()}"
    date_font = _font(10, bold=True)
    date_width = draw.textlength(date_text, font=date_font)
    draw.text((257 - date_width, 3), date_text, font=date_font, fill=0)
    if weather_warning:
        _draw_warning_icon(draw, 58, 1)

    if weather is not None:
        _draw_weather_icon(draw, weather, 7, 24)
        draw.text(
            (42, 18),
            f"{round(weather.temperature):.0f}°C",
            font=_font(27, bold=True),
            fill=0,
        )
        _tracked_text(
            draw,
            (43, 46),
            weather_label(weather.weather_code, weather.is_day),
            _mono_font(9),
        )
    else:
        draw.text((42, 18), "--°C", font=_font(27, bold=True), fill=0)
        draw.text((43, 47), "UNAVAILABLE", font=_mono_font(8), fill=0)

    draw.line((138, 21, 138, 59), fill=0)
    metric_font = _font(12, bold=True)
    high = f"{round(weather.high):.0f}°C" if weather else "--°C"
    low = f"{round(weather.low):.0f}°C" if weather else "--°C"
    apparent = (
        f"{round(weather.apparent_temperature):.0f}°C"
        if weather and weather.apparent_temperature is not None
        else "--°C"
    )
    humidity = (
        f"{weather.humidity}%"
        if weather and weather.humidity is not None
        else "--%"
    )
    _draw_arrow_icon(draw, 147, 22, up=True)
    draw.text((160, 20), high, font=metric_font, fill=0)
    _draw_arrow_icon(draw, 205, 22, up=False)
    draw.text((218, 20), low, font=metric_font, fill=0)
    _draw_thermometer_icon(draw, 147, 41)
    draw.text((160, 40), apparent, font=metric_font, fill=0)
    _draw_humidity_icon(draw, 205, 40)
    draw.text((218, 40), humidity, font=metric_font, fill=0)

    draw.line((7, 62, 257, 62), fill=0)
    slots = _forecast_periods(weather, current) if weather else []
    for index, center_x in enumerate((33, 99, 165, 231)):
        period = slots[index] if index < len(slots) else None
        _draw_forecast_slot(
            draw,
            center_x=center_x,
            period=period,
            current=current,
        )
    draw.line((7, 122, 257, 122), fill=0)

    periods = _today_weather_periods(weather, current) if weather else []
    peak, summary = _future_rain_summary(periods, current)
    peak_value = f"{peak} %" if peak is not None else "-- %"
    _draw_umbrella_icon(draw, 7, 126)
    draw.text((26, 124), f"PEAK {peak_value}", font=_mono_bold_font(9), fill=0)
    compact_summary = _compact_rain_summary(summary)
    summary_font = _mono_bold_font(8)
    summary_width = draw.textlength(compact_summary, font=summary_font)
    draw.text((257 - summary_width, 125), compact_summary, font=summary_font, fill=0)

    _draw_rain_chart(draw, periods, current)
    return image
