"""Generate a simple typographic cover (1600x2560, Kindle's recommended size)."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 2560

_FONT_CANDIDATES = {
    "bold": ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
             "C:/Windows/Fonts/georgiab.ttf"],
    "regular": ["/System/Library/Fonts/Supplemental/Georgia.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                "C:/Windows/Fonts/georgia.ttf"],
    "italic": ["/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
               "C:/Windows/Fonts/georgiai.ttf"],
}


def _font(kind: str, size: int):
    for p in _FONT_CANDIDATES[kind]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


MARGIN = 160            # inside the decorative frame


def _wrap(draw, text, font, max_w):
    """Greedy word wrap by measured pixel width (not character count)."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit(draw, text, kind, size, max_lines, max_w=W - 2 * MARGIN, min_size=40):
    """Largest font (<= size) at which text fits in max_lines lines of max_w pixels."""
    while True:
        font = _font(kind, size)
        lines = _wrap(draw, text, font, max_w)
        if size <= min_size or (len(lines) <= max_lines
                                and all(draw.textlength(l, font=font) <= max_w for l in lines)):
            return font, lines
        size -= 6


def _centered(draw, y, text, font, fill, max_lines=3, kind="regular"):
    font, lines = _fit(draw, text, kind, font.size, max_lines)
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((W - w) / 2, y), line, font=font, fill=fill)
        y += int(font.size * 1.25)
    return y


def make_cover(author: str, title: str, subtitle: str = "", footer: str = "",
               bg: str = "#7a1712", fg: str = "#f4ecd8", accent: str = "#e0b84f",
               portrait: bytes | None = None) -> bytes:
    img = Image.new("RGB", (W, H), _hex(bg))
    d = ImageDraw.Draw(img)
    fgc, acc = _hex(fg), _hex(accent)

    d.rectangle([60, 60, W - 60, H - 60], outline=acc, width=6)
    y = 260
    y = _centered(d, y, author.upper(), _font("regular", 92), acc, max_lines=2)
    y += 50
    d.line([(W / 2 - 220, y), (W / 2 + 220, y)], fill=acc, width=5)
    y += 90

    if portrait:
        try:
            p = Image.open(io.BytesIO(portrait)).convert("L").convert("RGB")
            scale = min(820 / p.width, 900 / p.height)
            p = p.resize((int(p.width * scale), int(p.height * scale)), Image.LANCZOS)
            img.paste(p, (int((W - p.width) / 2), y))
            d.rectangle([(W - p.width) / 2 - 4, y - 4, (W + p.width) / 2 + 3, y + p.height + 3],
                        outline=acc, width=4)
            y += p.height + 110
        except Exception:
            y += 200
    else:
        y += 300

    y = _centered(d, y, title, _font("bold", 128), fgc, max_lines=4, kind="bold")
    if subtitle:
        y += 40
        y = _centered(d, y, subtitle, _font("italic", 64), fgc, max_lines=3, kind="italic")
    if footer:
        _centered(d, H - 260, footer, _font("regular", 48), acc, max_lines=2)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
