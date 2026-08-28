"""Phase V2.10F/H - narrow, dependency-free rasterizer for the canonical NNJ wordmark ONLY. Not a
general SVG renderer. Works because `assets/brand/nnj_logo.svg` / `nnj_logo_red.svg` are confirmed
(direct inspection, re-verified by `_parse_path_polygons()`'s own strict token check below) to use
ONLY straight-line path commands (M/L/Z - no curves, no arcs). Parses each `<path d="...">` into
its exact vertex list and rasterizes with PIL's own polygon fill at supersampled resolution (then
downsamples for anti-aliasing) - the exact canonical path geometry, never approximated, never
hand-traced, never substituted with a font glyph. No new dependency: PIL is already installed;
`cairosvg`/`svglib` remain absent from this environment (confirmed live at import time by
services/brand_renderer.py's own docstring, and independently re-confirmed during Phase V2.10F)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

_REPO_ROOT = Path(__file__).resolve().parent.parent
NNJ_RED_SVG = _REPO_ROOT / "assets" / "brand" / "nnj_logo_red.svg"
NNJ_WHITE_SVG = _REPO_ROOT / "assets" / "brand" / "nnj_logo.svg"
NNJ_RED_FILL = (237, 28, 36, 255)  # #ED1C24 - read from the SVG's own fill attribute, not chosen here


def _parse_path_polygons(d: str) -> list[list[tuple[float, float]]]:
    """Splits one `d` attribute into its subpaths (each starting at 'M', ending at 'Z') and
    returns each as a list of (x, y) vertices. Raises on any command letter other than M/L/Z -
    a curve would be caught here, never silently mis-rendered."""
    tokens = re.findall(r'[MLZ]|-?\d+(?:\.\d+)?', d)
    polygons: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("M", "L"):
            x, y = float(tokens[i + 1]), float(tokens[i + 2])
            current.append((x, y))
            i += 3
        elif tok == "Z":
            if current:
                polygons.append(current)
            current = []
            i += 1
        else:
            raise ValueError(f"unexpected token in supposedly straight-line-only NNJ path: {tok!r}")
    if current:
        polygons.append(current)
    return polygons


@lru_cache(maxsize=8)
def _rasterize_full_res(svg_path: str, supersample: int = 4) -> Image.Image:
    content = Path(svg_path).read_text(encoding="utf-8")
    view_box = re.search(r'viewBox="([\d.\s-]+)"', content)
    assert view_box is not None
    _, _, vb_w, vb_h = (float(v) for v in view_box.group(1).split())
    fill_match = re.search(r'fill="(#[0-9A-Fa-f]{6})"', content)
    assert fill_match is not None
    fill_rgb = tuple(int(fill_match.group(1)[i:i + 2], 16) for i in (1, 3, 5))

    path_ds = re.findall(r'<path d="([^"]+)"', content)
    assert len(path_ds) > 0

    canvas = Image.new("RGBA", (round(vb_w * supersample), round(vb_h * supersample)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for d in path_ds:
        for poly in _parse_path_polygons(d):
            scaled = [(x * supersample, y * supersample) for x, y in poly]
            draw.polygon(scaled, fill=(*fill_rgb, 255))

    bbox = canvas.split()[-1].getbbox()
    assert bbox is not None, "rasterized canonical NNJ mark produced no visible content"
    return canvas.crop(bbox)


def rasterize_nnj_mark(*, target_width: int, red: bool = True) -> Image.Image:
    """Returns an RGBA image, `target_width` wide, of the exact canonical NNJ wordmark geometry -
    red (`nnj_logo_red.svg`) by default, matching the locked MASTER NEWS visual contract
    (Phase V2.10H §1: pure NNJ red #ED1C24, never a boxed badge). `target_width` must be positive;
    the source SVG is parsed once per process and cached (`_rasterize_full_res`)."""
    assert target_width > 0
    svg_path = NNJ_RED_SVG if red else NNJ_WHITE_SVG
    full_res = _rasterize_full_res(str(svg_path))
    scale = target_width / full_res.width
    return full_res.resize((target_width, max(1, round(full_res.height * scale))), Image.Resampling.LANCZOS)
