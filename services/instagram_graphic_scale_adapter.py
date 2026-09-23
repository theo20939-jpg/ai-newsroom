"""Deterministic scale adapter for GRAPHIC slides (a flow or a poll is the slide's only visual).

The founder reference's interface slides are a large headline over stacked, full-width cards that fill most of the frame. The
Creative Director tends to declare the graphic as a 0.84 x 0.28 strip under a small headline, leaving most of the canvas empty -
the same "the meaningful visual is too small" defect the media-scale adapter fixes for images, but for a graphic the right
composition is different: the graphic stays drawn by its own renderer, it just gets the canvas. A slide whose only visual is one
substantive graphic covering less than MIN_GRAPHIC_AREA of the canvas is re-laid as: accent rule, headline band, then the graphic
filling the rest of the frame above the logo. The result is re-validated by the unchanged layout validator; callers keep the
original plan when it cannot render. Slides with media, collages and decorative-only graphics are never touched."""
from __future__ import annotations

from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion

MIN_GRAPHIC_AREA = 0.35
SUBSTANTIVE = ("flow_diagram", "poll_cards")
_PROMOTE = {"HEADLINE_S", "HEADLINE_M", "HEADLINE_L"}
_HEADLINE_REFS = ("copy", "copy_lead", "copy_no_number")
_TEXT_BAND = (0.07, 0.15, 0.86, 0.20)
_GRAPHIC_BOX = (0.07, 0.39, 0.86, 0.41)  # ends at 0.80: clear of both logo corners (y >= 0.82)
# with an explanatory body the text band needs room for headline + body; the graphic keeps a large box below it
_TEXT_BAND_WITH_BODY = (0.07, 0.14, 0.86, 0.30)
_GRAPHIC_BOX_WITH_BODY = (0.07, 0.47, 0.86, 0.33)


def adapt_graphic_scale(layout: InstagramSlideLayout, *, body: str = "") -> tuple[InstagramSlideLayout, dict] | None:
    if layout.arrangement != "standard" or any(r.kind == "media" for r in layout.regions):
        return None
    graphics = [r for r in layout.regions if r.kind == "graphic"]
    substantive = [g for g in graphics if g.graphic_type in SUBSTANTIVE]
    texts = [r for r in layout.regions if r.kind == "text"]
    if len(substantive) != 1 or len(graphics) != 1 or not texts:
        return None
    graphic = substantive[0]
    if graphic.w * graphic.h >= MIN_GRAPHIC_AREA:
        return None

    regions: list[LayoutRegion] = [r for r in layout.regions if r.kind == "surface" and r.w >= 0.99 and r.h >= 0.99]
    rule = next((r for r in layout.regions if r.kind == "accent" and r.accent_type == "rule_h"), None)
    if rule is not None:
        regions.append(rule.model_copy(update={"x": 0.07, "y": 0.115, "w": 0.1, "h": 0.018, "z": 2}))
    ordered = sorted(texts, key=lambda t: (round(t.y, 2), t.x))
    x, y, w, h = _TEXT_BAND_WITH_BODY if body else _TEXT_BAND
    if body:
        # an explanatory body gets only the height it needs; the headline keeps the rest (the same split the media rebuild uses)
        from services.instagram_media_scale_adapter import _stack

        regions.extend(t.model_copy(update={"z": 2}) for t in _stack(ordered, x, y, w, h, body=body))
    else:
        total = sum(t.h for t in ordered) or 1.0
        gap = 0.015 if len(ordered) > 1 else 0.0
        cy = y
        for t in ordered:
            th = max(0.05, (h - gap * (len(ordered) - 1)) * t.h / total)
            token = "HEADLINE_XL" if t.content_ref in _HEADLINE_REFS and t.scale_token in _PROMOTE else t.scale_token
            regions.append(t.model_copy(update={"x": x, "y": cy, "w": w, "h": th, "z": 2, "scale_token": token, "valign": "top",
                                                "on_media": False, "max_lines": None}))
            cy += th + gap
    gx, gy, gw, gh = _GRAPHIC_BOX_WITH_BODY if body else _GRAPHIC_BOX
    regions.append(graphic.model_copy(update={"x": gx, "y": gy, "w": gw, "h": gh, "z": 1, "tilt_deg": None}))
    notes = {"graphic_scale_adapted": True, "graphic_scale_requested": [round(graphic.x, 3), round(graphic.y, 3), round(graphic.w, 3), round(graphic.h, 3)],
             "graphic_scale_executed": [gx, gy, gw, gh]}
    return layout.model_copy(update={"regions": regions, "visual_weight": "GRAPHIC"}), notes
