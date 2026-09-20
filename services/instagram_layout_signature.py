"""Phase B.5: a small, normalized, coordinate-free characterization of a declarative slide layout.

Used by (a) the anti-template diagnostic, (b) render evidence (a stable variant name), and (c)
cross-post fatigue, which must NOT store raw floating-point coordinates. Pure and deterministic;
takes a plain dict (a persisted `layout` payload or `InstagramSlideLayout.model_dump()`)."""
from __future__ import annotations

from typing import Any

_TOKEN_RANK = {"DISPLAY": 6, "HEADLINE_L": 5, "HEADLINE_M": 4, "HEADLINE_S": 3, "BODY": 2, "CAPTION": 1}


def _zone(cx: float, cy: float) -> str:
    v = "top" if cy < 0.36 else "bottom" if cy > 0.64 else "middle"
    h = "left" if cx < 0.4 else "right" if cx > 0.6 else "center"
    return f"{v}-{h}"


def _center(region: dict[str, Any]) -> tuple[float, float]:
    return region["x"] + region["w"] / 2.0, region["y"] + region["h"] / 2.0


def layout_characteristics(layout: dict[str, Any]) -> dict[str, str]:
    regions = [r for r in (layout.get("regions") or []) if isinstance(r, dict)]
    texts = [r for r in regions if r.get("kind") == "text"]
    medias = [r for r in regions if r.get("kind") == "media"]

    headline_zone = "none"
    if texts:
        lead = max(texts, key=lambda r: (_TOKEN_RANK.get(str(r.get("scale_token")), 0), r["w"] * r["h"]))
        headline_zone = _zone(*_center(lead))
    media_zone = "none"
    if len(medias) == 1:
        media_zone = _zone(*_center(medias[0]))
    elif len(medias) > 1:
        media_zone = "multi"

    weighted = [(r["w"] * r["h"], *_center(r)) for r in regions if r.get("kind") in ("text", "media", "graphic")]
    total = sum(a for a, _, _ in weighted) or 1.0
    dx = sum(a * cx for a, cx, _ in weighted) / total - 0.5 if weighted else 0.0
    dy = sum(a * cy for a, _, cy in weighted) / total - 0.5 if weighted else 0.0
    asymmetry = "asymmetric" if (abs(dx) + abs(dy)) > 0.12 else "centered"

    n = len(regions)
    return {
        "headline_zone": headline_zone,
        "media_zone": media_zone,
        "media_dominance": str(layout.get("media_dominance") or "NONE"),
        "density": str(layout.get("density") or "MEDIUM"),
        "asymmetry": asymmetry,
        "visual_weight": str(layout.get("visual_weight") or "TEXT"),
        "region_count": "1-2" if n <= 2 else "3-4" if n <= 4 else "5+",
    }


def layout_signature(layout: dict[str, Any]) -> str:
    c = layout_characteristics(layout)
    return "|".join(f"{k}={c[k]}" for k in ("headline_zone", "media_zone", "media_dominance", "density", "asymmetry", "visual_weight", "region_count"))
