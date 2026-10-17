"""Draw parsed LaTeX segments to a PNG using matplotlib (no pyplot, no global state). Worker process only."""
from __future__ import annotations

import io
import math
import re
from typing import Callable

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from matplotlib.transforms import IdentityTransform

from math_engine.errors import InputError

from .parse import MathSegment, MatrixSegment

MAX_WIDTH_PX = 3000
MAX_HEIGHT_PX = 2000
FONTSET = "stix"


def _friendly(exc: Exception) -> str:
    """Boil matplotlib's multi-line parser error down to one readable clause."""
    m = re.search(r"Parse\w*Exception: (.*)", str(exc))
    detail = re.sub(r"\s*\(at char.*$", "", m.group(1)).strip() if m else "invalid or unsupported LaTeX"
    return (f"Could not render that LaTeX: {detail[:150]}. "
            "The built-in renderer supports a large subset of LaTeX math (no custom macros or packages).")


class _Measurer:
    """Measures mathtext strings in pixels."""

    def __init__(self, fontsize: float, dpi: int) -> None:
        self.renderer = FigureCanvasAgg(Figure(dpi=dpi)).get_renderer()
        self.prop = FontProperties(size=fontsize)

    def __call__(self, tex: str) -> tuple[float, float, float]:
        """Returns (width, ascent above baseline, descent below baseline)."""
        if not tex.strip():
            return 0.0, 0.0, 0.0
        try:
            w, h, d = self.renderer.get_text_width_height_descent(f"${tex}$", self.prop, ismath=True)
        except ValueError as exc:
            raise InputError(_friendly(exc)) from None
        return w, h - d, d


class _Item:
    def __init__(self, w: float, ascent: float, descent: float, draw: Callable) -> None:
        self.w, self.ascent, self.descent, self.draw, self.x = w, ascent, descent, draw, 0.0


def render_png(segments: list, *, fontsize: float = 20.0, dpi: int = 200) -> bytes:
    with matplotlib.rc_context({"mathtext.fontset": FONTSET}):
        fs_px = fontsize * dpi / 72
        measure = _Measurer(fontsize, dpi)
        lw = max(1.0, fontsize * 0.065)
        items = [_math_item(s.text, measure, fontsize) if isinstance(s, MathSegment)
                 else _matrix_item(s, measure, fontsize, fs_px, lw) for s in segments]

        pad, gap = 0.4 * fs_px, 0.3 * fs_px
        x = pad
        for item in items:
            item.x = x
            x += item.w + gap
        width = math.ceil(x - gap + pad)
        above = max(0.0, max(i.ascent for i in items)) + pad
        below = max(0.0, max(i.descent for i in items)) + pad
        height = math.ceil(above + below)
        if width > MAX_WIDTH_PX or height > MAX_HEIGHT_PX:
            raise InputError("That expression would produce an image that is too large. Try a shorter one.")

        fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="white")
        FigureCanvasAgg(fig)
        baseline = below
        for item in items:
            item.draw(fig, item.x, baseline)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
        return buf.getvalue()


def _text(fig, x: float, y: float, tex: str, fontsize: float) -> None:
    fig.text(x, y, f"${tex}$", fontsize=fontsize, color="black", ha="left", va="baseline",
             transform=IdentityTransform())


def _math_item(tex: str, measure: _Measurer, fontsize: float) -> _Item:
    w, a, d = measure(tex)
    return _Item(w, a, d, lambda fig, x, base: _text(fig, x, base, tex, fontsize))


def _matrix_item(seg: MatrixSegment, measure: _Measurer, fontsize: float, fs_px: float, lw: float) -> _Item:
    cells = [[measure(c) for c in row] for row in seg.rows]
    nrows, ncols = len(cells), len(cells[0])
    col_w = [max(cells[i][j][0] for i in range(nrows)) for j in range(ncols)]
    row_a = [max(0.7 * fs_px, max(c[1] for c in row)) for row in cells]   # minimum height keeps empty rows open
    row_d = [max(0.2 * fs_px, max(c[2] for c in row)) for row in cells]
    col_gap, row_gap = 0.9 * fs_px, 0.35 * fs_px
    inner_w = sum(col_w) + col_gap * (ncols - 1)
    inner_h = sum(row_a) + sum(row_d) + row_gap * (nrows - 1)
    bw = 0.0 if seg.style == "none" else 0.55 * fs_px       # width reserved for each bracket
    overhang = 0.15 * fs_px if bw else 0.0
    axis = 0.25 * fs_px                                    # the matrix is centred on the maths axis
    total_w = inner_w + 2 * bw

    def draw(fig, x0: float, base: float) -> None:
        top = base + axis + inner_h / 2
        cursor = top
        for i in range(nrows):
            row_base = cursor - row_a[i]
            for j in range(ncols):
                if seg.rows[i][j]:
                    cx = x0 + bw + sum(col_w[:j]) + j * col_gap + (col_w[j] - cells[i][j][0]) / 2
                    _text(fig, cx, row_base, seg.rows[i][j], fontsize)
            cursor -= row_a[i] + row_d[i] + row_gap
        if bw:
            _brackets(fig, seg.style, x0, total_w, bw, top + overhang, top - inner_h - overhang, lw)

    return _Item(total_w, axis + inner_h / 2 + overhang, inner_h / 2 + overhang - axis, draw)


def _brackets(fig, style: str, x0: float, total_w: float, bw: float, top: float, bottom: float, lw: float) -> None:
    height = top - bottom
    tip, outer, mid = x0 + 0.75 * bw, x0 + 0.2 * bw, x0 + 0.5 * bw

    def mirror(x: float) -> float:   # reflect a point on the left bracket onto the right one
        return x0 + total_w - (x - x0)

    for side in ("left", "right"):
        fx = (lambda x: x) if side == "left" else mirror
        if style == "paren":
            verts = [(fx(tip), top), (fx(outer), top - 0.2 * height), (fx(outer), bottom + 0.2 * height), (fx(tip), bottom)]
            codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]
        elif style == "bracket":
            verts = [(fx(tip), top), (fx(outer), top), (fx(outer), bottom), (fx(tip), bottom)]
            codes = [Path.MOVETO, Path.LINETO, Path.LINETO, Path.LINETO]
        else:  # bar
            verts = [(fx(mid), top), (fx(mid), bottom)]
            codes = [Path.MOVETO, Path.LINETO]
        fig.add_artist(PathPatch(Path(verts, codes), fill=False, edgecolor="black", linewidth=lw,
                                 transform=IdentityTransform()))
