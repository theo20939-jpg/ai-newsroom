"""Deterministic media-scale adapter for media-first declarative slides.

The founder reference puts the image edge to edge and the headline huge. The Creative Director often declares a
two-column magazine layout instead: a framed 0.3-0.5-wide inset image beside a narrow text column, which leaves most
of the canvas empty and forces the text fit to shrink the headline to body size. On a SOURCE/GENERATED slide whose
single media region covers less than MIN_MEDIA_AREA of the canvas, this re-lays the slide as an edge-to-edge bleed:
a vertical split (image band + wide headline band) or, for short copy beside the image, a full-height side panel.
The result is re-validated by the unchanged layout validator; a caller keeps the original plan when it cannot render.
Collage/stage arrangements, graphic compositions and on-media (immersive) text are never touched."""
from __future__ import annotations

from dataclasses import dataclass

from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion

MIN_MEDIA_AREA = 0.50
SHORT_COPY_CHARS = 34
ORIENTATIONS = ("side_right", "side_left", "text_top", "text_bottom", "mixed_bands")
SUBSTANTIVE_GRAPHICS = frozenset({"flow_diagram", "poll_cards", "ui_frame"})
DECORATIVE_GRAPHICS = frozenset({"badge", "scribble", "arrow_scribble", "circle_scribble", "box_scribble", "underline_scribble", "highlight", "burst"})
_HEADLINE_REFS = ("copy", "copy_lead", "copy_no_number")
_PROMOTE = {"HEADLINE_S", "HEADLINE_M", "HEADLINE_L"}


@dataclass(frozen=True)
class MediaScaleAdaptation:
    layout: InstagramSlideLayout
    requested: tuple[float, float, float, float]
    executed: tuple[float, float, float, float]
    orientation: str

    def notes(self) -> dict:
        return {
            "media_scale_adapted": True, "media_scale_orientation": self.orientation,
            "media_scale_requested": [round(v, 3) for v in self.requested],
            "media_scale_executed": [round(v, 3) for v in self.executed],
        }


def _clipped_area(r: LayoutRegion) -> float:
    w = max(0.0, min(1.0, r.x + r.w) - max(0.0, r.x))
    h = max(0.0, min(1.0, r.y + r.h) - max(0.0, r.y))
    return w * h


def _stack(texts: list[LayoutRegion], x: float, y: float, w: float, h: float) -> list[LayoutRegion]:
    """Stack the text regions top to bottom (original reading order) inside one band, heights proportional to the plan."""
    ordered = sorted(texts, key=lambda t: (round(t.y, 2), t.x))
    total = sum(t.h for t in ordered) or 1.0
    gap = 0.015 if len(ordered) > 1 else 0.0
    usable = h - gap * (len(ordered) - 1)
    out, cy = [], y
    for t in ordered:
        th = max(0.05, usable * t.h / total)
        token = "HEADLINE_XL" if t.content_ref in _HEADLINE_REFS and t.scale_token in _PROMOTE else t.scale_token
        out.append(t.model_copy(update={"x": x, "y": cy, "w": w, "h": th, "scale_token": token, "valign": "top", "on_media": False,
                                  "max_lines": None}))  # the band now bounds the block; a plan's line cap for its old narrow box would only shrink the type
        cy += th + gap
    return out


def adapt_media_scale(layout: InstagramSlideLayout, *, slide_copy: str, force: bool = False,
                      orientation: str | None = None) -> MediaScaleAdaptation | None:
    """`force`: the plan was rejected, or its headline rendered below the floor - rebuild the geometry regardless of the media's size.
    `orientation` (one of ORIENTATIONS) overrides the one derived from where the plan put its text."""
    if orientation is not None and orientation not in ORIENTATIONS:
        raise ValueError(f"unknown orientation {orientation!r}")
    collage = layout.arrangement == "collage"
    if layout.arrangement not in ("standard", "stage") and not (force and collage):
        return None
    medias = [r for r in layout.regions if r.kind == "media"]
    if not collage:
        # outside a collage, a second region showing the SAME asset is the same picture pasted twice (real TREND iteration-5
        # slide: one generated photo at 0.49x0.58 plus a tilted 0.25x0.22 copy of it), not a second visual - only the largest counts
        largest: dict[str | None, LayoutRegion] = {}
        for r in sorted(medias, key=_clipped_area, reverse=True):
            largest.setdefault(r.content_ref, r)
        medias = [r for r in medias if largest.get(r.content_ref) is r]
    texts = [r for r in layout.regions if r.kind == "text"]
    graphics = [r for r in layout.regions if r.kind == "graphic"]
    if force and collage:
        # a collage whose headline shrank below the floor (or that was rejected): its largest fragment becomes the one image,
        # the decorative marks go - a substantive graphic (ui_frame, flow_diagram, poll_cards) still keeps the plan as it is
        graphics = [g for g in graphics if g.graphic_type not in DECORATIVE_GRAPHICS]
        medias = sorted(medias, key=_clipped_area, reverse=True)[:1]
    substantive = [g for g in graphics if g.graphic_type in SUBSTANTIVE_GRAPHICS]
    # one image + one substantive graphic on a plain slide: both get a band. A collage is never flattened into this - its other
    # fragments would be lost - so a collage carrying a substantive graphic still keeps the plan the model wrote.
    one_image_one_graphic = not collage and len(medias) == 1 and len(graphics) == 1 and len(substantive) == 1
    mixed = bool(one_image_one_graphic and (force or _clipped_area(medias[0]) < MIN_MEDIA_AREA))
    if len(medias) != 1 or not texts or (graphics and not mixed) or (not force and any(t.on_media for t in texts)):
        return None
    media = medias[0]
    staged_on_ground = any(r.kind == "surface" and r.surface == "media_ground" for r in layout.regions)
    if not force and staged_on_ground and media.crop_mode in ("object_contain", "object_cover", "cutout", "cutout_contain"):
        return None  # a real hero object / cut-out on its own uniform ground merges with it - it reads large by design
    if media.crop_mode in ("cutout", "cutout_contain"):
        return None  # an alpha cut-out is never re-cropped as a rectangular photo
    if not force and _clipped_area(media) >= MIN_MEDIA_AREA:
        return None

    tx0, ty0 = min(t.x for t in texts), min(t.y for t in texts)
    tx1, ty1 = max(t.x + t.w for t in texts), max(t.y + t.h for t in texts)
    text_cx, text_cy = (tx0 + tx1) / 2, (ty0 + ty1) / 2
    media_cx, media_cy = media.x + media.w / 2, media.y + media.h / 2
    logo_right = layout.logo_position == "BOTTOM_RIGHT"

    if mixed:
        # a slide carrying BOTH a paid image and a substantive graphic: neither may be dropped, so both get a full-width band
        regions = [r for r in layout.regions if r.kind == "surface" and r.w >= 0.99 and r.h >= 0.99 and r.surface != "media_ground"]
        regions.append(media.model_copy(update={"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.44, "z": 1, "frame": "none", "tilt_deg": None, "crop_mode": "cover"}))
        rule_region = next((r for r in layout.regions if r.kind == "accent" and r.accent_type == "rule_h"), None)
        if rule_region is not None:
            regions.append(rule_region.model_copy(update={"x": 0.07, "y": 0.475, "w": 0.1, "h": 0.018, "z": 2, "on_media": None}))
        regions.extend(t.model_copy(update={"z": 2}) for t in _stack(texts, 0.07, 0.51, 0.86, 0.15))
        regions.append(substantive[0].model_copy(update={"x": 0.07, "y": 0.68, "w": 0.86, "h": 0.12, "z": 2, "tilt_deg": None}))
        adapted_mixed = layout.model_copy(update={"regions": regions, "media_dominance": "DOMINANT", "arrangement": "standard"})
        return MediaScaleAdaptation(adapted_mixed, (media.x, media.y, media.w, media.h), (0.0, 0.0, 1.0, 0.44), "mixed_bands")
    if orientation is None:
        if len(slide_copy.strip()) <= SHORT_COPY_CHARS and abs(media_cx - text_cx) >= 0.25:
            orientation = "side_right" if media_cx > text_cx else "side_left"
        else:
            orientation = "text_top" if text_cy <= media_cy else "text_bottom"
    if orientation.startswith("side"):
        right = orientation == "side_right"
        mbox = (0.44, 0.0, 0.56, 1.0) if right else (0.0, 0.0, 0.56, 1.0)
        col_x = 0.07 if right else 0.60
        band = (col_x, 0.16, 0.34, 0.60)
        rule_at = (col_x, 0.12)
    elif orientation == "text_top":
        mbox = (0.0, 0.45, 1.0, 0.55)
        band = (0.07, 0.15, 0.86, 0.27)
        rule_at = (0.07, 0.115)
    else:
        mbox = (0.0, 0.0, 1.0, 0.56)
        band = (0.07, 0.63, 0.75 if logo_right else 0.86, 0.29)
        rule_at = (0.07, 0.595)

    regions: list[LayoutRegion] = [r for r in layout.regions if r.kind == "surface" and r.w >= 0.99 and r.h >= 0.99 and r.surface != "media_ground"]
    new_media = media.model_copy(update={
        "x": mbox[0], "y": mbox[1], "w": mbox[2], "h": mbox[3], "z": 1, "frame": "none", "tilt_deg": None,
        "crop_mode": "cover",
    })
    regions.append(new_media)
    rule = next((r for r in layout.regions if r.kind == "accent" and r.accent_type == "rule_h"), None)
    if rule is not None:
        regions.append(rule.model_copy(update={"x": rule_at[0], "y": rule_at[1], "w": 0.1, "h": 0.018, "z": 2, "on_media": None}))
    regions.extend(t.model_copy(update={"z": 2}) for t in _stack(texts, *band))
    adapted = layout.model_copy(update={"regions": regions, "media_dominance": "DOMINANT", "arrangement": "standard"})
    return MediaScaleAdaptation(adapted, (media.x, media.y, media.w, media.h), mbox, orientation)
