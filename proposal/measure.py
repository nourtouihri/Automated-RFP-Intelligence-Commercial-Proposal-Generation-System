"""Text measurement shared by the renderer (autofit) and the validator.

Uses the real font files, so a box that measures as fitting here renders as
fitting in LibreOffice and, with the same fonts installed, in PowerPoint.
"""

from __future__ import annotations

import glob
import os
import sys
from functools import lru_cache

from PIL import ImageFont

def font_dirs(platform: str = sys.platform, environ=os.environ) -> list[str]:
    if platform == "win32":
        dirs = [os.path.join(environ.get("WINDIR", r"C:\Windows"), "Fonts")]
        if environ.get("LOCALAPPDATA"):
            dirs.append(os.path.join(environ["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts"))
        return dirs
    return ["/usr/share/fonts"]


FONT_DIRS = font_dirs()


class FontNotFound(RuntimeError):
    pass


@lru_cache(maxsize=None)
def font_file(name: str | None, bold: bool) -> str | None:
    """The run's own font when installed, else Inter, else DejaVu Sans or Arial."""
    weight = "Bold" if bold else "Regular"
    names = [n.replace(" ", "") for n in (name, "Inter") if n]
    patterns = [f"{n}-{weight}.[ot]tf" for n in names]
    patterns += [f"DejaVuSans{'-Bold' if bold else ''}.ttf", "arialbd.ttf" if bold else "arial.ttf"]
    for pattern in patterns:
        for d in FONT_DIRS:
            hits = glob.glob(os.path.join(glob.escape(d), "**", pattern), recursive=True)
            if hits:
                return sorted(hits)[0]
    return None


def font_gaps(names: tuple[str, ...]) -> list[str]:
    """Each named font (regular and bold) that is not installed, with the file text is
    measured with instead. Raises FontNotFound when there is no usable font at all."""
    gaps = []
    for name in names:
        for bold in (False, True):
            path = font_file(name, bold)
            if path is None:
                raise FontNotFound(f"no font file for {name!r} or its fallbacks in {FONT_DIRS}")
            used = os.path.basename(path)
            if not used.lower().startswith(name.replace(" ", "").lower()):
                gaps.append(f"{name} {'Bold' if bold else 'Regular'} (measured with {used})")
    return gaps


@lru_cache(maxsize=None)
def _font(name: str | None, bold: bool, size_px: int):
    path = font_file(name, bold)
    if path is None:
        # Measuring nothing would make autofit and every overflow check pass.
        raise FontNotFound(f"no font file for {name!r} or its fallbacks in {FONT_DIRS}")
    return ImageFont.truetype(path, max(1, size_px))


def line_count(text: str, name: str | None, bold: bool, size_px: float, width_px: float) -> int:
    font = _font(name, bold, round(size_px))
    lines = 0
    for para in text.split("\n"):
        line, n = "", 1
        for word in para.split():
            trial = f"{line} {word}".strip()
            if font.getlength(trial) <= width_px:
                line = trial
            else:
                n += 1
                line = word
        lines += n
    return lines


def line_pitch(name: str | None, bold: bool, size_px: float, line_spacing: float = 1.0) -> float:
    """Proportional spacing (what python-pptx writes) multiplies the font's own
    line height, ascent + descent: 1.21 em for Inter, 1.22 for Montserrat. It
    is not a multiple of the font size."""
    font = _font(name, bold, round(size_px))
    ascent, descent = font.getmetrics()
    return (ascent + descent) * line_spacing


def wrapped_height(text: str, name: str | None, bold: bool, size_px: float, width_px: float,
                   line_spacing: float = 1.2) -> float:
    return (line_count(text, name, bold, size_px, width_px)
            * line_pitch(name, bold, size_px, line_spacing))


def fits(text, name, bold, size_px, w, h, line_spacing=1.2, tolerance=1.02) -> bool:
    return wrapped_height(text, name, bold, size_px, w, line_spacing) <= h * tolerance


def fit_text(text: str, name: str | None, bold: bool, size_px: float, w: float, h: float,
             line_spacing: float = 1.2, min_scale: float = 0.8,
             truncate: bool = False) -> tuple[str, float]:
    """Shrink the font down to min_scale; if still too tall and truncation is
    allowed, cut whole words and end with an ellipsis. Returns (text, size)."""
    size = size_px
    while not fits(text, name, bold, size, w, h, line_spacing) and size > size_px * min_scale:
        size -= 1
    if fits(text, name, bold, size, w, h, line_spacing) or not truncate:
        return text, size
    words = text.split()
    while len(words) > 1 and not fits(" ".join(words) + "…", name, bold, size, w, h, line_spacing):
        words.pop()
    if len(words) == 1:  # one unbroken word, a URL or a very long name: cut characters
        word = words[0]
        while len(word) > 1 and not fits(word + "…", name, bold, size, w, h, line_spacing):
            word = word[:-1]
        words = [word]
    return " ".join(words).rstrip(",;:·-") + "…", size
