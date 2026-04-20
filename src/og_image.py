"""
Per-briefing Open Graph card generator.

Renders the 1200x630 PNG that Bluesky / X / LinkedIn / iMessage / Slack
display when a briefing URL is shared. One unique card per briefing,
with the headline, category, and date burned into the image so the
preview tile stops being the same generic "Caracas Research" tile for
every link.

Design = Concept 3 ("Modern Sans"), the one we ship:

  +--------------------------------------------------------+
  | navy  |                       (red 6px rule)           |
  |       |                                                |
  | CARA- |  DAILY BRIEFING · MAR 13, 2026                 |
  | CAS   |                                                |
  | RES'H |  [ MINING ]                                    |
  |       |                                                |
  |       |  Headline goes here, in big                    |
  |       |  modern Inter Display Bold,                    |
  | BCV   |  three or four lines max                       |
  | 481   |                                                |
  | Bs/$  |                       caracasresearch.com      |
  +--------------------------------------------------------+

Pure-Python (Pillow) — same dependency we already have for the static
homepage OG. No headless browser, no native deps to manage on Render.

Usage:
    from src.og_image import render_briefing_card
    png_bytes = render_briefing_card(
        title=post.title,
        category=post.primary_sector,
        published_date=post.published_date,
        bcv_usd=481.22,                # optional — adds the stat block
    )
    # write to BlogPost.og_image_bytes; serve via /og/briefing/<slug>.png
"""

from __future__ import annotations

import io
import logging
import textwrap
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger(__name__)


# ── Layout constants ──────────────────────────────────────────────────
WIDTH, HEIGHT = 1200, 630
LEFT_PANEL_W = 450
RIGHT_PANEL_X = LEFT_PANEL_W

# ── Brand palette (matches caracasresearch.com) ───────────────────────
NAVY = (0, 31, 68)            # left panel + headline ink
NAVY_DEEP = (0, 19, 44)       # top of vertical gradient
RED = (204, 0, 0)             # accent — chip, rule, "RESEARCH" wordmark
WHITE = (255, 255, 255)
INK = (15, 23, 42)            # near-black for headline
GRAY_500 = (100, 116, 139)    # eyebrow + footer
GRAY_200 = (226, 232, 240)    # subtle dividers
NAVY_MUTED = (160, 180, 210)  # left-panel secondary text


# ── Font loading ──────────────────────────────────────────────────────
_FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_BUNDLED_FONTS = {
    "inter_bold": _FONT_DIR / "Inter-Bold.ttf",
    "inter_semibold": _FONT_DIR / "Inter-SemiBold.ttf",
    "inter_regular": _FONT_DIR / "Inter-Regular.ttf",
    "inter_display_bold": _FONT_DIR / "InterDisplay-Bold.ttf",
}

# System fallbacks — we only hit these if the bundled ttf isn't
# present (e.g. someone deleted static/fonts/ or a slimmed-down deploy).
_SYSTEM_FALLBACKS = {
    "bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "regular": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}


@lru_cache(maxsize=64)
def _font(weight: str, size: int) -> ImageFont.ImageFont:
    """weight ∈ {inter_bold, inter_semibold, inter_regular, inter_display_bold}"""
    bundled = _BUNDLED_FONTS.get(weight)
    if bundled and bundled.exists():
        return ImageFont.truetype(str(bundled), size=size)
    system_chain = _SYSTEM_FALLBACKS["bold"] if "bold" in weight else _SYSTEM_FALLBACKS["regular"]
    for path in system_chain:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


# ── Drawing helpers ───────────────────────────────────────────────────

def _vertical_gradient(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    """Cheap top→bottom gradient by row-fill (avoids a per-pixel loop)."""
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    """Return (width, height) of `text` using the given font."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Greedy word-wrap so each line fits inside `max_width` pixels."""
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _measure(draw, candidate, font)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_headline(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
    initial_size: int,
    min_size: int,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    """Auto-shrink the font until the headline fits in `max_lines` lines.

    Returns (font, wrapped_lines, font_size_used). If even at min_size the
    headline still overflows, the last line gets truncated with an
    ellipsis — we always return exactly <= max_lines lines.
    """
    size = initial_size
    while size >= min_size:
        font = _font("inter_display_bold", size)
        lines = _wrap_to_width(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines, size
        size -= 4

    # Last resort: take the first max_lines-1 wrapped lines + truncated tail.
    font = _font("inter_display_bold", min_size)
    lines = _wrap_to_width(draw, text, font, max_width)
    head = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1:])
    while tail and _measure(draw, tail + "…", font)[0] > max_width:
        tail = tail.rsplit(" ", 1)[0] if " " in tail else tail[:-1]
    head.append((tail + "…") if tail else "…")
    return font, head, min_size


def _rounded_chip(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    x: int,
    y: int,
    pad_x: int = 18,
    pad_y: int = 9,
    radius: int = 6,
    fill: tuple = RED,
    text_color: tuple = WHITE,
    font: Optional[ImageFont.ImageFont] = None,
) -> tuple[int, int]:
    """Draw a small filled chip (red category pill) and return its (w, h)."""
    if font is None:
        font = _font("inter_bold", 22)
    tw, th = _measure(draw, text, font)
    w = tw + pad_x * 2
    h = th + pad_y * 2
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=radius, fill=fill)
    draw.text((x + pad_x, y + pad_y - 2), text, font=font, fill=text_color)
    return w, h


# ── Display formatting ────────────────────────────────────────────────

def _format_category(category: Optional[str]) -> str:
    if not category:
        return "BRIEFING"
    cleaned = category.replace("_", " ").replace("-", " ").strip()
    # Map common internal slugs to nicer display names.
    aliases = {
        "OFAC": "SANCTIONS",
        "OFAC SANCTIONS": "SANCTIONS",
        "ASAMBLEA": "POLITICS",
        "ASAMBLEA NACIONAL": "POLITICS",
        "GACETA": "REGULATION",
        "GACETA OFICIAL": "REGULATION",
        "BCV": "FX & RATES",
        "BCV RATES": "FX & RATES",
    }
    upper = cleaned.upper()
    return aliases.get(upper, upper)[:24]


def _format_date(d: date | datetime | None) -> str:
    if d is None:
        d = date.today()
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%b %d, %Y").upper().replace(" 0", " ")


# ── Public API ────────────────────────────────────────────────────────

def render_briefing_card(
    *,
    title: str,
    category: Optional[str] = None,
    published_date: date | datetime | None = None,
    bcv_usd: Optional[float] = None,
) -> bytes:
    """Render a per-briefing OG card and return PNG bytes.

    Designed to be called once at blog-creation time and the bytes
    persisted on `BlogPost.og_image_bytes` for the lifetime of the post.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)

    # ── LEFT NAVY PANEL ───────────────────────────────────────────────
    left_panel = _vertical_gradient(LEFT_PANEL_W, HEIGHT, NAVY_DEEP, NAVY)
    img.paste(left_panel, (0, 0))

    draw = ImageDraw.Draw(img)

    # Thin red accent at the very top of the left panel.
    draw.rectangle([(0, 0), (LEFT_PANEL_W, 8)], fill=RED)

    # Wordmark
    wm_x = 60
    wm_y = 90
    wm_font = _font("inter_bold", 44)
    draw.text((wm_x, wm_y), "CARACAS", font=wm_font, fill=WHITE)
    _, wm_h = _measure(draw, "CARACAS", wm_font)
    draw.text((wm_x, wm_y + wm_h + 2), "RESEARCH", font=wm_font, fill=RED)

    # Tagline under the wordmark
    tag_font = _font("inter_regular", 18)
    draw.text(
        (wm_x, wm_y + (wm_h + 2) * 2 + 14),
        "Venezuela investment intelligence",
        font=tag_font,
        fill=NAVY_MUTED,
    )

    # Optional BCV stat block at bottom-left
    if bcv_usd is not None:
        try:
            rate_value = float(bcv_usd)
        except (TypeError, ValueError):
            rate_value = None
        if rate_value:
            label_font = _font("inter_semibold", 16)
            value_font = _font("inter_bold", 40)
            unit_font = _font("inter_regular", 18)

            draw.line(
                [(wm_x, HEIGHT - 170), (LEFT_PANEL_W - 60, HEIGHT - 170)],
                fill=(255, 255, 255, 50),
                width=1,
            )
            draw.text(
                (wm_x, HEIGHT - 150),
                "BCV OFFICIAL",
                font=label_font,
                fill=NAVY_MUTED,
            )
            draw.text(
                (wm_x, HEIGHT - 122),
                f"{rate_value:,.2f}",
                font=value_font,
                fill=WHITE,
            )
            draw.text(
                (wm_x, HEIGHT - 64),
                "Bs.D / USD",
                font=unit_font,
                fill=NAVY_MUTED,
            )

    # ── RIGHT WHITE PANEL ─────────────────────────────────────────────
    # Red rule across the top of the white area.
    draw.rectangle([(RIGHT_PANEL_X, 0), (WIDTH, 6)], fill=RED)

    inner_x = RIGHT_PANEL_X + 60
    inner_right = WIDTH - 60
    inner_w = inner_right - inner_x

    # Eyebrow: "DAILY BRIEFING · <DATE>"
    eyebrow_font = _font("inter_bold", 18)
    eyebrow_text = f"DAILY BRIEFING  ·  {_format_date(published_date)}"
    draw.text((inner_x, 70), eyebrow_text, font=eyebrow_font, fill=GRAY_500)

    # Category chip (red pill)
    chip_text = _format_category(category)
    chip_font = _font("inter_bold", 20)
    _rounded_chip(
        draw,
        text=chip_text,
        x=inner_x,
        y=110,
        font=chip_font,
        fill=RED,
        text_color=WHITE,
        radius=4,
    )

    # Headline — auto-fit so it never spills past 4 lines
    headline = (title or "").strip()
    headline_font, lines, _ = _fit_headline(
        draw,
        headline,
        max_width=inner_w,
        max_lines=4,
        initial_size=64,
        min_size=40,
    )
    line_height = headline_font.size + 12
    headline_top = 200
    for i, line in enumerate(lines):
        draw.text(
            (inner_x, headline_top + i * line_height),
            line,
            font=headline_font,
            fill=INK,
        )

    # Footer rule + URL
    footer_y = HEIGHT - 70
    draw.line(
        [(inner_x, footer_y - 18), (inner_right, footer_y - 18)],
        fill=GRAY_200,
        width=1,
    )
    footer_font = _font("inter_semibold", 22)
    url_text = "caracasresearch.com"
    url_w, _ = _measure(draw, url_text, footer_font)
    draw.text(
        (inner_right - url_w, footer_y),
        url_text,
        font=footer_font,
        fill=NAVY,
    )
    # Left side of footer: small "Independent · Twice-daily" tag
    note_font = _font("inter_regular", 18)
    draw.text(
        (inner_x, footer_y + 2),
        "Independent · Twice-daily research",
        font=note_font,
        fill=GRAY_500,
    )

    # ── encode ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_default_card() -> bytes:
    """Render the generic homepage / share-fallback card.

    Same Concept-3 chrome, but with a marquee headline rather than a
    per-briefing one. Suitable for shares of `/`, `/briefing`, etc.
    """
    return render_briefing_card(
        title="Venezuelan investment intelligence — daily research for international capital",
        category="DAILY BRIEFING",
        published_date=date.today(),
        bcv_usd=None,
    )


# ── Live data lookup ──────────────────────────────────────────────────

def latest_bcv_usd() -> Optional[float]:
    """Best-effort fetch of the most recent BCV official USD rate from
    the DB. Returns None if the table is empty or any error trips —
    callers should treat this as optional decoration."""
    try:
        from src.models import (  # local import to avoid cycle on module load
            ExternalArticleEntry,
            SessionLocal,
            SourceType,
            init_db,
        )
        init_db()
        db = SessionLocal()
        try:
            row = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.source == SourceType.BCC_RATES)
                .order_by(ExternalArticleEntry.published_date.desc())
                .first()
            )
            if not row or not row.extra_metadata:
                return None
            usd = row.extra_metadata.get("usd")
            return float(usd) if usd is not None else None
        finally:
            db.close()
    except Exception as exc:
        logger.warning("og_image: latest_bcv_usd failed: %s", exc)
        return None
