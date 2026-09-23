"""Content pass (prompt v10.7): place a slide's explanatory body in its declared layout.

A slide now carries a HEADLINE (slide_copy) and, when the story needs it, a BODY (slide_body: 1-3 short explanatory lines). The Creative
Director may place the body itself (a text region with content_ref "body"); when it does not, this module adds that region
deterministically, directly under the headline in the same column: exactly the space a short headline used to leave empty. If there is
no room below the headline, a media region directly underneath gives up a bounded strip (it stays large); as a last resort the headline
box shares its own height with the body. Nothing is dropped: the layout validator rejects any slide whose body has no text region.

Pure geometry on the plan's normalized coordinates - no model call, no pixels read."""
from __future__ import annotations

import math

from services.instagram_layout_validation import LOGO_ZONES, copy_parts

HEADLINE_REFS = ("copy", "copy_no_number", "copy_rest", "copy_lead")
BODY_TOKEN = "BODY"
# BODY type is 0.042 x canvas width (about 45px); an average Cyrillic glyph in the semibold face is ~0.52 of the font size wide
_BODY_FONT_FRAC = 0.042
_GLYPH_W = 0.52
_LINE_H = 1.32
_ASPECT = 1350 / 1080  # the carousel canvas is 4:5: a width fraction times _ASPECT is the same length as a height fraction
_GAP = 0.018
_MEDIA_MIN_H = 0.34
_GRAPHIC_MIN_H = 0.18


def body_height_needed(body: str, width: float, *, font_frac: float = _BODY_FONT_FRAC) -> float:
    """Normalized height a body of this length needs in a column this wide (a deliberate over-estimate of one line)."""
    chars_per_line = max(8, int(width / (font_frac * _GLYPH_W)))
    lines = math.ceil(len(body) / chars_per_line) + (1 if len(body) > chars_per_line else 0)
    return lines * font_frac * _LINE_H / _ASPECT


def _overlaps_x(a: dict, x0: float, x1: float) -> bool:
    return min(a["x"] + a["w"], x1) - max(a["x"], x0) > 0.02


def _contains(outer: dict, inner: dict) -> bool:
    return (outer["x"] <= inner["x"] + 1e-6 and outer["y"] <= inner["y"] + 1e-6
            and outer["x"] + outer["w"] >= inner["x"] + inner["w"] - 1e-6 and outer["y"] + outer["h"] >= inner["y"] + inner["h"] - 1e-6)


def attach_body_region(layout_plan: dict | None, slide_text: str) -> tuple[dict | None, str | None]:
    """Return (layout with a body region, how it was placed) - or the plan unchanged with None when there is no body or the plan
    already places it. `slide_text` is the composed headline + body string (see compose_slide_text)."""
    if not layout_plan or not copy_parts(slide_text)["body"]:
        return layout_plan, None
    regions = [dict(r) for r in layout_plan.get("regions") or []]
    if any(r.get("kind") == "text" and r.get("content_ref") == "body" for r in regions):
        return layout_plan, None
    headlines = [r for r in regions if r.get("kind") == "text" and r.get("content_ref") in HEADLINE_REFS]
    if not headlines:
        headlines = [r for r in regions if r.get("kind") == "text"]
    if not headlines:
        return layout_plan, None
    anchor = max(headlines, key=lambda r: (r["y"] + r["h"], r["w"]))
    body = copy_parts(slide_text)["body"]
    x0, x1 = anchor["x"], anchor["x"] + anchor["w"]
    top = anchor["y"] + anchor["h"] + _GAP
    host = next((r for r in regions if r.get("kind") == "media" and anchor.get("on_media") and _contains(r, anchor)), None)
    logo = LOGO_ZONES.get(layout_plan.get("logo_position") or "BOTTOM_RIGHT")
    floor = (logo[1] - _GAP) if (logo is not None and x1 > logo[0] and x0 < logo[2]) else 0.93
    below = [r for r in regions if r is not anchor and r is not host and r.get("kind") in ("media", "graphic", "text")
             and r["y"] >= anchor["y"] + anchor["h"] - 0.01 and _overlaps_x(r, x0, x1)]
    limit = min([r["y"] - _GAP for r in below] + [floor])
    need = body_height_needed(body, anchor["w"])
    base = {"kind": "text", "x": x0, "w": anchor["w"], "z": max(int(anchor.get("z") or 2), 2), "content_ref": "body", "scale_token": BODY_TOKEN,
            "align": anchor.get("align") or "left", "valign": "top", "max_lines": None, "tone": "primary", "on_media": bool(anchor.get("on_media")),
            "surface": None, "crop_mode": None, "focus_x": None, "focus_y": None, "frame": None, "accent_type": None, "graphic_type": None,
            "tilt_deg": None, "flow_steps": None}
    if limit - top >= need:
        regions.append({**base, "y": top, "h": min(limit - top, need * 1.35)})
        return {**layout_plan, "regions": regions}, "below_headline"
    blocker = min((r for r in below if r.get("kind") in ("media", "graphic")), key=lambda r: r["y"], default=None)
    if blocker is not None and not host and layout_plan.get("arrangement") != "collage":
        # the nearest image band or diagram under the headline gives up a bounded strip; everything else below it stays where it is
        shift = top + need + _GAP - blocker["y"]
        minimum = _MEDIA_MIN_H if blocker["kind"] == "media" else _GRAPHIC_MIN_H
        new_h = blocker["h"] - shift
        if blocker["kind"] == "graphic":
            others = [r["y"] - _GAP for r in regions if r is not blocker and r.get("kind") in ("media", "graphic", "text") and r["y"] > blocker["y"]]
            new_h = min(blocker["h"], min(others + [floor]) - (blocker["y"] + shift))
        if new_h >= minimum:
            blocker.update({"y": blocker["y"] + shift, "h": new_h})
            regions.append({**base, "y": top, "h": need})
            return {**layout_plan, "regions": regions}, f"{blocker['kind']}_moved_down"
    # last resort: the headline box shares its own height (the headline fit then picks a smaller size, never clips)
    total = anchor["h"] + max(0.0, limit - (anchor["y"] + anchor["h"]))
    body_h = min(max(need, 0.08), total * 0.55)
    anchor["h"] = max(0.05, total - body_h - _GAP)
    regions.append({**base, "y": anchor["y"] + anchor["h"] + _GAP, "h": body_h})
    return {**layout_plan, "regions": regions}, "headline_box_shared"
