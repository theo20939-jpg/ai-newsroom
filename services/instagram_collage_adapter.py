"""Phase B.5.1.3: deterministic COLLAGE GEOMETRY ADAPTER.

The Creative Director chooses `internet_culture_collage` and a rough composition; it cannot be trusted to satisfy the accepted geometric inequalities
exactly (services/instagram_layout_validation.py: controlled overlap, one clearly primary fragment). When - and only when - the ONLY reasons the validator
rejects a collage are `media_regions_collide` and/or `collage_hierarchy_flat`, this module makes the smallest bounded, deterministic geometry change that
makes the plan pass the UNCHANGED validator, then re-validates it. Nothing here weakens a threshold; if no bounded change passes, the caller keeps its
fail-closed fallback.

Preserved: media content_ref / count / z-order / frame / tilt / crop mode, text, graphics, background, palette, logo position and family. Changed: only the
x, y, w, h of media fragments. No randomness: every search is a fixed ordered enumeration and the first minimal-cost passing candidate wins."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from schemas.instagram_creative import InstagramSlideLayout
from services.instagram_layout_validation import (
    _COLLAGE_MAX_OVERLAP,
    _COLLAGE_MIN_HIERARCHY,
    _COLLAGE_MIN_SPREAD,
    ValidatedLayout,
    _area,
    _inter_area,
    _rect,
    validate_layout,
)

ADAPTABLE_CODES = frozenset({"media_regions_collide", "collage_hierarchy_flat"})
MAX_DISPLACEMENT = 0.12   # largest allowed centre shift of any fragment (fraction of the canvas side)
MAX_SCALE_CHANGE = 0.20   # largest allowed linear resize of any fragment (0.20 = +/-20% of width and height)
_SCALE_STEPS = (0.0, 0.05, 0.10, 0.15, 0.20)
_RINGS = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12)
# eight compass directions, fixed order; the search re-sorts them by how well they point AWAY from the primary fragment
_DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


@dataclass(frozen=True)
class CollageAdaptation:
    layout: InstagramSlideLayout
    validated: ValidatedLayout
    reasons: tuple[str, ...]
    requested_media_regions: tuple[tuple[float, float, float, float], ...]
    executed_media_regions: tuple[tuple[float, float, float, float], ...]
    max_region_displacement: float
    max_scale_change: float
    primary_index: int
    details: dict = field(default_factory=dict)

    def notes(self) -> dict:
        return {
            "collage_geometry_adapted": True, "collage_adaptation_reasons": list(self.reasons),
            "requested_media_regions": [list(r) for r in self.requested_media_regions],
            "executed_media_regions": [list(r) for r in self.executed_media_regions],
            "max_region_displacement": self.max_region_displacement, "max_scale_change": self.max_scale_change,
            "collage_bounds": {"max_displacement": MAX_DISPLACEMENT, "max_scale_change": MAX_SCALE_CHANGE},
        }


def _geom(region) -> tuple[float, float, float, float]:
    return (round(region.x, 4), round(region.y, 4), round(region.w, 4), round(region.h, 4))


def _hierarchy_ok(areas: list[float]) -> bool:
    ordered = sorted(areas, reverse=True)
    if len(ordered) < 3:
        return True
    return ordered[0] >= _COLLAGE_MIN_HIERARCHY * ordered[1] and ordered[0] >= _COLLAGE_MIN_SPREAD * ordered[-1]


def _colliding_pairs(medias: list) -> list[tuple[int, int]]:
    pairs = []
    for i, a in enumerate(medias):
        for j in range(i + 1, len(medias)):
            b = medias[j]
            if _inter_area(_rect(a), _rect(b)) > _COLLAGE_MAX_OVERLAP * min(_area(_rect(a)), _area(_rect(b))):
                pairs.append((i, j))
    return pairs


def _any_overlap(medias: list) -> bool:
    return any(_inter_area(_rect(a), _rect(b)) > 0 for a, b in itertools.combinations(medias, 2))


def _resized(region, factor: float):
    if factor == 1.0:
        return region
    w, h = region.w * factor, region.h * factor
    cx, cy = region.x + region.w / 2, region.y + region.h / 2
    return region.model_copy(update={"x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h})


def adapt_collage(layout: InstagramSlideLayout, *, slide_copy: str, resolvable_subjects: set[str]) -> CollageAdaptation | None:
    """Return the adapted layout (already re-validated and accepted by the unchanged validator) or None - in which case the caller must keep its fail-closed fallback."""
    if layout.arrangement != "collage":
        return None
    base = validate_layout(layout, slide_copy=slide_copy, resolvable_subjects=resolvable_subjects)
    codes = set(base.rejection_codes)
    if base.accepted or not codes or not codes <= ADAPTABLE_CODES:
        return None  # an unrelated rejection is never "fixed" here
    regions = list(layout.regions)
    media_idx = [i for i, r in enumerate(regions) if r.kind == "media"]
    if len(media_idx) < 2:
        return None
    original = {i: regions[i] for i in media_idx}
    had_overlap = _any_overlap([original[i] for i in media_idx])
    # primary: largest planned area, then higher z, then original order
    primary = max(media_idx, key=lambda i: (_area(_rect(original[i])), original[i].z, -i))
    by_area = sorted(media_idx, key=lambda i: (-_area(_rect(original[i])), -original[i].z, i))
    others = [i for i in by_area if i != primary]

    def build(overrides: dict) -> InstagramSlideLayout:
        return layout.model_copy(update={"regions": [overrides.get(i, r) for i, r in enumerate(regions)]})

    def within_bounds(candidate: dict) -> bool:
        for i, r in candidate.items():
            o = original[i]
            if math.hypot((r.x + r.w / 2) - (o.x + o.w / 2), (r.y + r.h / 2) - (o.y + o.h / 2)) > MAX_DISPLACEMENT + 1e-9:
                return False
            if abs(r.w / o.w - 1) > MAX_SCALE_CHANGE + 1e-9 or abs(r.h / o.h - 1) > MAX_SCALE_CHANGE + 1e-9:
                return False
        return True

    current = dict(original)
    # 1. hierarchy: the smallest deterministic resize of the primary (up) and the second-largest / smallest fragment (down)
    if "collage_hierarchy_flat" in codes:
        second, smallest = others[0], others[-1]
        options = []
        for up, dn2, dn3 in itertools.product(_SCALE_STEPS, _SCALE_STEPS, _SCALE_STEPS):
            factors = {primary: 1 + up, second: 1 - dn2}
            if smallest != second:
                factors[smallest] = 1 - dn3
            elif dn3:
                continue
            options.append((round(up + dn2 + dn3, 4), up, dn2, dn3, factors))
        chosen = None
        for _, _, _, _, factors in sorted(options, key=lambda o: o[:4]):
            trial = {i: _resized(original[i], factors.get(i, 1.0)) for i in media_idx}
            if not within_bounds(trial):
                continue
            if any(r.x < -0.10 or r.y < -0.10 or r.x + r.w > 1.10 or r.y + r.h > 1.10 for r in trial.values()):
                continue  # would overshoot the collage bleed the validator allows
            if _hierarchy_ok([_area(_rect(r)) for r in trial.values()]):
                chosen = trial
                break
        if chosen is None:
            return None
        current = chosen

    # 2. collisions: keep the primary fixed, move the SMALLER fragment of each colliding pair by the smallest ordered offset
    guard = 0
    while guard < 6:
        guard += 1
        medias_now = [current[i] for i in media_idx]
        pairs = _colliding_pairs(medias_now)
        if not pairs:
            break
        a, b = pairs[0]
        ia, ib = media_idx[a], media_idx[b]
        mover = ib if (ia == primary or (ib != primary and _area(_rect(current[ib])) <= _area(_rect(current[ia])))) else ia
        anchor = ia if mover == ib else ib
        ax, ay = current[anchor].x + current[anchor].w / 2, current[anchor].y + current[anchor].h / 2
        mx, my = current[mover].x + current[mover].w / 2, current[mover].y + current[mover].h / 2
        away = (mx - ax, my - ay)
        norm = math.hypot(*away) or 1.0
        ordered_dirs = sorted(range(len(_DIRECTIONS)), key=lambda k: (-(away[0] * _DIRECTIONS[k][0] + away[1] * _DIRECTIONS[k][1]) / (norm * math.hypot(*_DIRECTIONS[k])), k))
        placed = False
        for ring in _RINGS:
            for k in ordered_dirs:
                dx, dy = _DIRECTIONS[k]
                scale = ring / math.hypot(dx, dy)
                moved = current[mover].model_copy(update={"x": current[mover].x + dx * scale, "y": current[mover].y + dy * scale})
                if moved.x < -0.10 or moved.y < -0.10 or moved.x + moved.w > 1.10 or moved.y + moved.h > 1.10:
                    continue
                trial = {**current, mover: moved}
                if not within_bounds({mover: moved}):
                    continue
                if any(media_idx.index(mover) in p for p in _colliding_pairs([trial[i] for i in media_idx])):
                    continue  # this offset still collides with something
                if had_overlap and not _any_overlap([trial[i] for i in media_idx]):
                    continue  # keep the layered relation the plan intended
                current = trial
                placed = True
                break
            if placed:
                break
        if not placed:
            return None

    adapted = build({i: r for i, r in current.items() if r is not original[i]})
    validated = validate_layout(adapted, slide_copy=slide_copy, resolvable_subjects=resolvable_subjects)
    if not validated.accepted or validated.layout is None:
        return None
    displacement = max(math.hypot((current[i].x + current[i].w / 2) - (original[i].x + original[i].w / 2),
                                  (current[i].y + current[i].h / 2) - (original[i].y + original[i].h / 2)) for i in media_idx)
    scale_change = max(max(abs(current[i].w / original[i].w - 1), abs(current[i].h / original[i].h - 1)) for i in media_idx)
    return CollageAdaptation(
        layout=adapted, validated=validated, reasons=tuple(sorted(codes)),
        requested_media_regions=tuple(_geom(original[i]) for i in media_idx),
        executed_media_regions=tuple(_geom(current[i]) for i in media_idx),
        max_region_displacement=round(displacement, 4), max_scale_change=round(scale_change, 4), primary_index=primary,
    )
