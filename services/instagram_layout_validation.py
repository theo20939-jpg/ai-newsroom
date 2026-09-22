"""Phase B.5: structural validation of a DECLARATIVE slide layout, run before any pixel is drawn.

Outcomes are deterministic and never silent:
  - small, safe corrections are APPLIED and recorded (`adapted` issues),
  - anything unsafe REJECTS the slide's layout (the caller falls back to the deterministic legacy /
    role renderer and records `layout_plan_rejected` with the reasons),
  - a media region whose subject no resolver listed is DROPPED (never filled with an unrelated image).

This module judges STRUCTURE only (bounds, sizes, collisions, copy coverage, safe zones). It does
not judge taste and contains no aesthetic scoring."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from schemas.instagram_creative import TEXT_CONTENT_REFS, InstagramSlideLayout, LayoutRegion

_CLAMP_TOLERANCE = 0.03
_SAFE_X = 0.04
_SAFE_TOP = 0.03
_SAFE_BOTTOM = 0.97
_MIN_TEXT_W, _MIN_TEXT_H = 0.16, 0.045
_MIN_MEDIA = 0.08
_MIN_SURFACE = 0.02
_MAX_TEXT_OVERLAP = 0.04
_MAX_MEDIA_OVERLAP = 0.02
_MAX_TEXT_ON_MEDIA = 0.02

# The logo is renderer-owned (bottom-right, fixed); this padded zone (normalized) is kept clear of text.
LOGO_ZONE = (0.83, 0.82, 0.94, 0.93)
LOGO_ZONES = {"BOTTOM_RIGHT": LOGO_ZONE, "BOTTOM_LEFT": (0.05, 0.82, 0.17, 0.93)}
_COLLAGE_BLEED = 0.10          # collage media fragments may run off the canvas edge by this much (cropped, never clamped)
_STAGE_BLEED = 0.40            # a staged hero object may bleed further off an edge (the object is cropped by the frame)
_COLLAGE_MAX_OVERLAP = 0.55    # controlled overlap: at most this share of the smaller fragment may be covered
_COLLAGE_MIN_HIERARCHY = 1.5   # the primary fragment is at least this many times the area of the secondary one
_COLLAGE_MIN_SPREAD = 2.5      # ... and this many times the smallest fragment (no equal-card grids)
PROGRESS_ZONE = (0.05, 0.04, 0.27, 0.10)

_KIND_RANK = {"surface": 0, "media": 1, "graphic": 2, "accent": 3, "text": 4}


@dataclass(frozen=True)
class LayoutIssue:
    code: str
    detail: str
    severity: str  # "adapted" | "rejected" | "note"
    region_index: int | None = None


@dataclass(frozen=True)
class ValidatedLayout:
    accepted: bool
    layout: InstagramSlideLayout | None
    issues: tuple[LayoutIssue, ...] = ()
    progress_hidden: bool = False
    unresolved_media: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rejection_codes(self) -> list[str]:
        return [i.code for i in self.issues if i.severity == "rejected"]


def _rect(r: LayoutRegion) -> tuple[float, float, float, float]:
    return r.x, r.y, r.x + r.w, r.y + r.h


def _inter_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _area(rect: tuple[float, float, float, float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


_CURRENCY = "$€£₽¥"


def _without_number(text: str, start: int, end: int) -> str:
    """The copy with the numeral taken out. A sentence the numeral carried alone ("От $149.") is left as a content-free fragment
    ("От") - that whole sentence goes, since the numeral itself is set in type beside it."""
    s0 = max((text.rfind(p, 0, start) for p in ".!?"), default=-1) + 1
    ends = [i for i in (text.find(p, end) for p in ".!?") if i >= 0]
    s1 = min(ends) + 1 if ends else len(text)
    residue = text[s0:start] + text[end:s1]
    if len(re.findall(r"\w+", residue)) <= 2 and (s0 > 0 or s1 < len(text)):
        rest = text[:s0] + text[s1:]
    else:
        rest = text[:start] + text[end:]
    rest = re.sub(r"\s+([.,:!?])", r"\1", re.sub(r"\s{2,}", " ", rest))
    return rest.strip(" :—-.,")


def copy_parts(slide_copy: str) -> dict[str, str]:
    """Deterministic derivations of the slide's OWN copy that a text region may reference."""
    text = slide_copy.strip()
    # the currency travels WITH its amount: "От $149." must never leave "От $." behind once the numeral is set in type
    number_match = re.search(rf"[{_CURRENCY}]?(?:\d[\d\s.,]*\d|\d)%?(?:\s?[{_CURRENCY}])?", text)
    number = number_match.group(0).strip() if number_match else ""
    step = re.match(r"^\s*(?:шаг|step)\s*\d{1,2}\s*[.:—\-]?\s*", text, re.IGNORECASE)
    if step:  # "Шаг 2. ..." -> the numeral is shown separately; drop the whole label, never leave "Шаг ."
        number = re.search(r"\d{1,2}", step.group(0)).group(0)
        no_number = text[step.end():].strip()
    elif number_match:
        no_number = _without_number(text, number_match.start(), number_match.end())
    else:
        no_number = text
    lead, rest = text, ""
    vs = re.search(r"\s+(?:vs\.?|VS|Vs)\s+", text)
    m = re.search(r"[:.!?—]\s+", text)
    if vs and len(text[:vs.start()].strip()) >= 2 and len(text[vs.end():].strip()) >= 2:
        lead, rest = text[:vs.start()].strip(), text[vs.end():].strip()
    elif m and len(text[:m.start() + 1].strip()) >= 3 and len(text[m.end():].strip()) >= 3:
        lead, rest = text[:m.start() + (1 if text[m.start()] != "—" else 0)].strip(), text[m.end():].strip()
    return {"copy": text, "number": number, "copy_no_number": no_number or text, "copy_lead": lead, "copy_rest": rest}


def validate_layout(
    layout: InstagramSlideLayout, *, slide_copy: str, resolvable_subjects: set[str],
) -> ValidatedLayout:
    issues: list[LayoutIssue] = []
    regions: list[LayoutRegion] = []
    unresolved: list[str] = []
    parts = copy_parts(slide_copy)
    collage = layout.arrangement == "collage"
    logo_zone = LOGO_ZONES[layout.logo_position]

    for idx, region in enumerate(layout.regions):
        x0, y0, x1, y1 = region.x, region.y, region.x + region.w, region.y + region.h
        if region.w <= 0 or region.h <= 0:
            issues.append(LayoutIssue("non_positive_size", f"{region.kind} {region.w}x{region.h}", "rejected", idx))
            continue
        overshoot = max(-x0, -y0, x1 - 1.0, y1 - 1.0)
        bleed = _COLLAGE_BLEED if collage else (_STAGE_BLEED if layout.arrangement == "stage" else 0.0)
        if bleed and region.kind == "media" and overshoot <= bleed:
            overshoot = 0.0  # deliberate edge bleed: the fragment/object is cropped by the canvas, not moved
        if region.tilt_deg and region.kind in ("text", "surface") and not collage:
            issues.append(LayoutIssue("tilt_only_in_collage", region.kind, "rejected", idx))
            continue
        if overshoot > _CLAMP_TOLERANCE:
            issues.append(LayoutIssue("out_of_bounds", f"{region.kind} overshoots the canvas by {overshoot:.2f}", "rejected", idx))
            continue
        if overshoot > 0:
            nx0, ny0, nx1, ny1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
            region = region.model_copy(update={"x": nx0, "y": ny0, "w": nx1 - nx0, "h": ny1 - ny0})
            issues.append(LayoutIssue("clamped_to_canvas", f"{region.kind} moved inside the canvas", "adapted", idx))

        k = region.kind
        if k == "text":
            if region.content_ref not in TEXT_CONTENT_REFS:
                issues.append(LayoutIssue("unknown_text_ref", str(region.content_ref), "rejected", idx))
                continue
            if region.scale_token is None:
                issues.append(LayoutIssue("text_without_scale_token", "", "rejected", idx))
                continue
            if region.w < _MIN_TEXT_W or region.h < _MIN_TEXT_H:
                issues.append(LayoutIssue("text_region_too_small", f"{region.w:.2f}x{region.h:.2f}", "rejected", idx))
                continue
            if region.x < _SAFE_X - 1e-9 or region.x + region.w > 1 - _SAFE_X + 1e-9 or region.y < _SAFE_TOP - 1e-9 or region.y + region.h > _SAFE_BOTTOM + 1e-9:
                # a small, deterministic pull inside the safe area; a big violation is rejected
                nx0, ny0 = max(_SAFE_X, region.x), max(_SAFE_TOP, region.y)
                nx1, ny1 = min(1 - _SAFE_X, region.x + region.w), min(_SAFE_BOTTOM, region.y + region.h)
                if (region.x + region.w - nx1) + (nx0 - region.x) > 0.12 or nx1 - nx0 < _MIN_TEXT_W or ny1 - ny0 < _MIN_TEXT_H:
                    issues.append(LayoutIssue("text_outside_safe_area", "", "rejected", idx))
                    continue
                region = region.model_copy(update={"x": nx0, "y": ny0, "w": nx1 - nx0, "h": ny1 - ny0})
                issues.append(LayoutIssue("text_pulled_into_safe_area", "", "adapted", idx))
            if region.content_ref in ("copy_rest", "copy_lead", "number") and not parts.get(region.content_ref):
                issues.append(LayoutIssue("text_ref_has_no_content", f"{region.content_ref} is empty for this copy", "adapted", idx))
                continue
        elif k == "media":
            if not region.content_ref:
                issues.append(LayoutIssue("media_without_subject", "", "rejected", idx))
                continue
            if region.w < _MIN_MEDIA or region.h < _MIN_MEDIA:
                issues.append(LayoutIssue("media_region_too_small", f"{region.w:.2f}x{region.h:.2f}", "rejected", idx))
                continue
            if region.content_ref not in resolvable_subjects:
                unresolved.append(region.content_ref)
                issues.append(LayoutIssue("media_subject_unresolved", region.content_ref, "adapted", idx))
                continue
        elif k == "surface":
            if region.surface is None or region.w < _MIN_SURFACE or region.h < _MIN_SURFACE:
                issues.append(LayoutIssue("surface_invalid", "", "rejected", idx))
                continue
            if region.surface == "media_ground":
                if not region.content_ref:
                    issues.append(LayoutIssue("media_ground_without_subject", "", "rejected", idx))
                    continue
                if region.content_ref not in resolvable_subjects:
                    unresolved.append(region.content_ref)
                    issues.append(LayoutIssue("media_subject_unresolved", region.content_ref, "adapted", idx))
                    continue
        elif k == "accent":
            if region.accent_type is None:
                issues.append(LayoutIssue("accent_without_type", "", "rejected", idx))
                continue
            if (region.accent_type == "rule_h" and (region.w < 0.05 or region.h > 0.05)) or (
                region.accent_type == "rule_v" and (region.h < 0.05 or region.w > 0.05)
            ) or (region.accent_type == "block" and (region.w < 0.02 or region.h < 0.02)):
                issues.append(LayoutIssue("accent_geometry_invalid", region.accent_type, "rejected", idx))
                continue
        elif k == "graphic":
            small_ok = region.graphic_type in ("badge", "scribble", "arrow_scribble", "circle_scribble", "highlight", "burst", "box_scribble", "underline_scribble")
            if region.graphic_type is None or region.w < (0.05 if small_ok else 0.15) or region.h < (0.05 if small_ok else 0.1):
                issues.append(LayoutIssue("graphic_invalid", "", "rejected", idx))
                continue
        regions.append(region)

    if any(i.severity == "rejected" for i in issues):
        return ValidatedLayout(False, None, tuple(issues), False, tuple(unresolved))

    texts = [r for r in regions if r.kind == "text"]
    medias = [r for r in regions if r.kind == "media"]

    # 1. logo zone is kept clear of text (deterministic width trim, otherwise reject)
    fixed: list[LayoutRegion] = []
    for r in regions:
        if r.kind == "text" and _inter_area(_rect(r), logo_zone) > 0:
            trimmed_right = logo_zone[0] - 0.01
            if layout.logo_position == "BOTTOM_RIGHT" and r.y < logo_zone[3] and r.y + r.h > logo_zone[1] and trimmed_right - r.x >= _MIN_TEXT_W:
                r = r.model_copy(update={"w": trimmed_right - r.x})
                issues.append(LayoutIssue("text_trimmed_clear_of_logo", "", "adapted", regions.index(r) if r in regions else None))
            if _inter_area(_rect(r), logo_zone) > 0:
                issues.append(LayoutIssue("text_collides_with_logo", "", "rejected"))
        fixed.append(r)
    regions = fixed
    texts = [r for r in regions if r.kind == "text"]

    # 2. collisions
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            ov = _inter_area(_rect(a), _rect(b))
            if ov > _MAX_TEXT_OVERLAP * min(_area(_rect(a)), _area(_rect(b))):
                issues.append(LayoutIssue("text_regions_collide", "", "rejected"))
    max_overlap = _COLLAGE_MAX_OVERLAP if collage else _MAX_MEDIA_OVERLAP
    for i, a in enumerate(medias):
        for b in medias[i + 1:]:
            if _inter_area(_rect(a), _rect(b)) > max_overlap * min(_area(_rect(a)), _area(_rect(b))):
                issues.append(LayoutIssue("media_regions_collide", "", "rejected"))
    if collage and len(medias) >= 3:
        areas = sorted((_area(_rect(m)) for m in medias), reverse=True)
        if areas[0] < _COLLAGE_MIN_HIERARCHY * areas[1] or areas[0] < _COLLAGE_MIN_SPREAD * areas[-1]:
            issues.append(LayoutIssue("collage_hierarchy_flat", "a collage needs one clearly primary fragment and uneven sizes, not equal cards", "rejected"))
    for t in texts:
        for m in medias:
            overlap = _inter_area(_rect(t), _rect(m))
            if overlap <= _MAX_TEXT_ON_MEDIA * _area(_rect(t)):
                continue
            # text may sit on a media region only when declared (`on_media`) and fully inside it; the renderer then
            # MEASURES contrast on the unaltered pixels and rejects the plan if unreadable - never an overlay
            if not (t.on_media and overlap >= 0.9 * _area(_rect(t))):
                issues.append(LayoutIssue("text_over_media", "text on media must be declared on_media and lie fully inside the media region", "rejected"))

    # 3. the slide's own copy must actually be presented, in full
    refs = {r.content_ref for r in texts}
    lead_rest_split = bool(parts["copy_rest"])
    if any(r.kind == "graphic" and r.graphic_type == "poll_cards" for r in regions):
        refs = refs | {"copy_rest"}  # poll option cards present the slide's own remainder copy
    covered = (
        "copy" in refs
        or ({"copy_lead", "copy_rest"} <= refs and lead_rest_split)
        or ("copy_lead" in refs and not lead_rest_split)
        or ({"number", "copy_no_number"} <= refs)
    )
    if not texts or not covered:
        issues.append(LayoutIssue("copy_not_fully_presented", f"text refs={sorted(str(r) for r in refs)}", "rejected"))

    if any(i.severity == "rejected" for i in issues):
        return ValidatedLayout(False, None, tuple(issues), False, tuple(unresolved))

    # 4. progress marker: hidden (never drawn over media/panels) when its corner is covered
    hidden = False
    for r in regions:
        if r.kind in ("media", "surface", "graphic") and _inter_area(_rect(r), PROGRESS_ZONE) > 0.2 * _area(PROGRESS_ZONE):
            hidden = True
    if hidden:
        issues.append(LayoutIssue("progress_marker_hidden", "corner covered by media/panel", "note"))

    if collage:  # explicit layer order: z first, so a label chip or sticker can sit above one fragment and below another
        ordered = sorted(enumerate(regions), key=lambda p: (p[1].z, _KIND_RANK[p[1].kind], p[0]))
    else:
        ordered = sorted(enumerate(regions), key=lambda p: (_KIND_RANK[p[1].kind], p[1].z, p[0]))
    final = layout.model_copy(update={"regions": [r for _, r in ordered]})
    return ValidatedLayout(True, final, tuple(issues), hidden, tuple(unresolved))
