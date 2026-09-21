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
        "surface": "dark" if str(layout.get("background")) in ("ink", "graphite") else "light",
    }


def layout_signature(layout: dict[str, Any]) -> str:
    c = layout_characteristics(layout)
    return "|".join(f"{k}={c[k]}" for k in ("headline_zone", "media_zone", "media_dominance", "density", "asymmetry", "visual_weight", "region_count", "surface"))


def _rects(layout: dict[str, Any]) -> list[tuple[str, float, float, float, float]]:
    return [
        (r["kind"], float(r["x"]), float(r["y"]), float(r["x"]) + float(r["w"]), float(r["y"]) + float(r["h"]))
        for r in (layout.get("regions") or []) if isinstance(r, dict) and r.get("kind") in ("text", "media", "graphic")
    ]


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    inter = max(0.0, w) * max(0.0, h)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def geometry_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """0.0 = the same normalized geometry, 1.0 = nothing in common. Compares content regions (text / media / graphic)
    of the same kind by best overlap; unmatched regions count as fully different. Used only to PROVE that two
    plans of one visual family are not the same layout nudged - never as a quality score."""
    ra, rb = _rects(a), _rects(b)
    if not ra and not rb:
        return 0.0
    used: set[int] = set()
    total = 0.0
    for kind, *box in ra:
        best, best_j = 0.0, None
        for j, (k2, *box2) in enumerate(rb):
            if j in used or k2 != kind:
                continue
            score = _iou(tuple(box), tuple(box2))
            if score > best:
                best, best_j = score, j
        if best_j is not None:
            used.add(best_j)
        total += best
    return 1.0 - total / max(len(ra), len(rb))


def structure_profile(layout: dict[str, Any]) -> dict[str, str]:
    """Coarse visual STRUCTURE of a plan (surface, palette, what carries the weight, which devices appear)."""
    regions = [r for r in (layout.get("regions") or []) if isinstance(r, dict)]
    devices = sorted({str(r.get("graphic_type")) for r in regions if r.get("kind") == "graphic"})
    medias = [r for r in regions if r.get("kind") == "media"]
    return {
        "surface": "dark" if str(layout.get("background")) in ("ink", "graphite") else "light",
        "palette": str(layout.get("palette") or "brand"),
        "visual_weight": str(layout.get("visual_weight")),
        "media_count": str(min(len(medias), 3)),
        "devices": ",".join(devices) or "none",
        "numeral": "yes" if any(r.get("content_ref") == "number" for r in regions) else "no",
        "tilted_media": "yes" if any(r.get("tilt_deg") for r in medias) else "no",
        "media_coverage": _coverage(medias),
        "text_on_media": "yes" if any(r.get("on_media") for r in regions if r.get("kind") == "text") else "no",
        "media_ground": "yes" if any(r.get("kind") == "surface" and r.get("surface") == "media_ground" for r in regions) else "no",
        "edge_bleed": "yes" if any(float(r["x"]) < -0.001 or float(r["y"]) < -0.001 or float(r["x"]) + float(r["w"]) > 1.001 or float(r["y"]) + float(r["h"]) > 1.001
                                   for r in medias) else "no",
    }


def _coverage(medias: list[dict[str, Any]]) -> str:
    area = sum(float(r["w"]) * float(r["h"]) for r in medias)
    return "none" if not medias else "low" if area < 0.25 else "mid" if area < 0.6 else "high"
