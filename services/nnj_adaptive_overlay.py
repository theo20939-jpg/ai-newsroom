"""Phase V2.7 §9-12 (extended by Phase V2.8 §3-5) - the Adaptive NNJ Overlay Director.

V2.7 replaced Candidate C's fixed lower-right rectangle with a small, fixed-size placement table
(LOWER_RIGHT/LOWER_LEFT/UPPER_RIGHT/UPPER_LEFT/LOGO_ONLY/NO_OVERLAY) - a real improvement, but
still binary at each placement: the full-size pulse signature either fit or it didn't, with no
step in between before falling all the way to the minimal logo mark. Real review of the V2.7
robot-vacuum proof showed exactly that gap: a large, legitimate hero-photography subject rejected
all four full-size placements and landed on LOGO_ONLY, losing the NNJ pulse signature entirely
even though a SMALLER real pulse signature would have fit cleanly.

Phase V2.8 §3 fix: a deterministic SCALE LADDER. For each placement (still the same four trusted
corners, still derived from the same two trusted primitives - the real Candidate C pulse/line/logo
composite and the canonical logo alone), try the full-size signature first, then progressively
smaller uniform scales, before moving to the next placement. LOGO_ONLY remains the true emergency
fallback - reachable only when every (placement, scale) pair collides - and NO_OVERLAY only when
even the minimal logo mark cannot be placed safely.

Every transform applied to the trusted Candidate C pixels is uniform-scale and/or axis flip only -
never a non-uniform stretch, never a re-render from measured geometry, never a new asset. Gemini
still never draws any NNJ element (unchanged, non-negotiable).

Phase V2.9 §2-3: `apply_adaptive_nnj_branding()` is the one production compositing entry point -
`worker/content_cycle.py` calls it directly for both ORIGINAL_SOURCE and successfully-recomposed
NEWS images, never duplicating the placement/scale/collision logic inline.

Phase V2.10A (docs/phase_v2_10_visual_acceptance_report.md - the real Stage-A canary that exposed
this): the real, unattended production call passes no `subject_bbox` at all (no automatic
semantic subject-region detector exists anywhere in this codebase - confirmed by a direct forensic
sweep of `EditorialImageCandidate`, `image_intelligence.py`, and `media_vision_review_capability.py`
- the only per-image signals that exist are whole-image boolean flags like `possible_logo`, never a
bounding box). Treating the ENTIRE canvas as the subject in that case (this module's original V2.9
behavior) was honest but useless - it deterministically forced NO_OVERLAY on every real automatic
NEWS image, proven directly by the V2.10 canary's own robot-vacuum result. `subject_bbox=None` now
instead falls back to a small, deterministic, real-pixel-content occupancy signal
(`_zone_pixel_risk_score()`): for each candidate zone, in the SAME `photo_for_occupancy` pixels the
caller is about to composite onto, measure real edge density (`ImageFilter.FIND_EDGES` mean) - a
zone showing a real watermark, logo, or fine detail scores high (unsafe); an out-of-focus
background, open floor, wall, or sky scores low (safe). This is deterministic pixel analysis, not
semantic vision, and it costs zero provider calls. When a caller DOES supply a trustworthy semantic
`subject_bbox` (human review, or a future real per-image signal), that bbox is used exactly as
before - this is strictly additive, never a behavior change for any existing bbox-supplying caller."""
from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageFilter, ImageStat

from services.nnj_candidate_c_contract import CANDIDATE_C_OVERLAY_PNG_PATH

BoundingBox = tuple[int, int, int, int]

_CANVAS_WIDTH = 1280
_CANVAS_HEIGHT = 720
_MARGIN_PX = 32  # matches Candidate C's own established _RIGHT_MARGIN (scripts/nnj_v2_4f_...)

# Phase V2.8 §3: measured directly against the real, locked Candidate C asset before choosing this
# ladder (its own real alpha content bbox is 422x59px at scale 1.00, on a 1280x720 canvas) - the
# recommended starting ladder produces a legible signature at every step (down to 232x32px at
# 0.55, still clearly a real pulse+logo mark, not a smudge), so it was kept unchanged rather than
# adjusted; no measurement argued for a different set of steps.
SCALE_LADDER: tuple[float, ...] = (1.00, 0.85, 0.70, 0.55)

# Phase V2.8 §4: the clearance buffer scales proportionally with the overlay's own scale (a
# smaller signature earns a proportionally smaller safety margin - both are real, measured pixel
# distances, never a semantic judgment), but never below this documented floor, so even the
# smallest rung on the ladder keeps a real, meaningful gap from the factual subject.
_BASE_CLEARANCE_PX = 20  # at scale 1.00 - matches Candidate C's own original clearance
_MIN_CLEARANCE_PX = 12  # documented floor - never goes below this regardless of scale

# LOGO_ONLY's own fixed size - not on the scale ladder (Stage 5: LOGO_ONLY is one fixed emergency
# mark, not itself a multi-scale candidate - keeping it singular keeps the fallback predictable).
_LOGO_ONLY_WIDTH_PX = 40
_LOGO_ONLY_CLEARANCE_PX = 20

# Phase V2.9 §3: the disclosed, safe default `apply_adaptive_nnj_branding()` uses whenever the
# caller has no trustworthy per-image subject bbox (today: every unattended/automatic production
# call - no automatic subject-region detector exists anywhere in this codebase). Assuming the
# entire canvas could be real content is the single safest possible assumption - it can only ever
# cause the algorithm to under-brand (degrade toward NO_OVERLAY), never to cover real, unknown-
# location factual content. A human-reviewed bbox for one specific image (a Stage-A canary) should
# always be passed explicitly instead, to unlock the full scale ladder.
FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX: BoundingBox = (0, 0, _CANVAS_WIDTH, _CANVAS_HEIGHT)

# Phase V2.10A - calibrated directly against three real, already-on-disk source photos (never a
# guessed number): the real robot-vacuum photo's own "9TO5Google" watermark corner measured
# edge_mean=15.24, a bright floor-reflection corner (no real branding, just a specular highlight)
# measured 14.64, a blurred-couch corner measured 10.49 - all real risk. The real iPhone/Honor
# photos' own preferred lower-right corners (the same corners a human reviewer independently
# picked in the V2.8 local proofs) measured 3.49 and 5.66 - real safe. 8.0 sits in the real,
# measured gap between the safe cluster (<=5.75) and the risky cluster (>=10.49) - not a round
# number chosen for convenience.
_PIXEL_RISK_EDGE_THRESHOLD = 8.0


class OverlayPlacement(str, Enum):
    """Six pre-approved compositions, all derived from the same two trusted primitives (the real
    Candidate C pulse/line/logo composite, and the canonical logo alone) - never casually invented
    layouts. `HORIZONTAL_CENTER` was deliberately NOT added: it is not derivable as a pure
    flip/scale of the existing trusted asset, and building it would mean designing new geometry
    rather than reusing approved geometry."""

    LOWER_RIGHT = "lower_right"  # Candidate C itself, unmodified at scale 1.00
    LOWER_LEFT = "lower_left"  # horizontal flip of Candidate C
    UPPER_RIGHT = "upper_right"  # vertical flip of Candidate C
    UPPER_LEFT = "upper_left"  # horizontal + vertical flip of Candidate C
    LOGO_ONLY = "logo_only"  # canonical logo alone, no pulse/line - the true degraded fallback
    NO_OVERLAY = "no_overlay"  # no branding element placed at all


# Phase V2.8 §3's own documented priority algorithm: PLACEMENT is the primary axis, SCALE is
# secondary WITHIN each placement (largest-fitting scale wins) - "a preferred placement at a
# slightly smaller scale may be better than moving a full-size signature into an awkward corner"
# (the phase's own explicit instruction). Concretely: try LOWER_RIGHT at every scale in
# SCALE_LADDER (largest first) before ever trying LOWER_LEFT at all - never the reverse (never
# exhausting all four corners at scale 1.00 before considering any corner at a smaller scale).
# This keeps the signature's usual visual position stable and predictable across most real photos,
# only shrinking it (not relocating it) when the preferred corner is merely a tight fit.
_PLACEMENT_PRIORITY: tuple[OverlayPlacement, ...] = (
    OverlayPlacement.LOWER_RIGHT,
    OverlayPlacement.LOWER_LEFT,
    OverlayPlacement.UPPER_RIGHT,
    OverlayPlacement.UPPER_LEFT,
)


@dataclass(frozen=True)
class OverlayZone:
    """This is a deterministic geometric collision guard, not semantic vision - `x_start..y_end`
    is always the real, measured alpha-content bounding box of the actual rendered overlay layer,
    never a guessed or invented rectangle."""

    x_start: int
    y_start: int
    x_end: int
    y_end: int
    clearance: int

    @property
    def clearance_x_start(self) -> int:
        return max(0, self.x_start - self.clearance)

    @property
    def clearance_y_start(self) -> int:
        return max(0, self.y_start - self.clearance)

    @property
    def clearance_x_end(self) -> int:
        return min(_CANVAS_WIDTH, self.x_end + self.clearance)

    @property
    def clearance_y_end(self) -> int:
        return min(_CANVAS_HEIGHT, self.y_end + self.clearance)


@dataclass(frozen=True)
class CandidateAttempt:
    """One (placement, scale) pair that was tried and rejected - Phase V2.8 §5's own required
    manifest disclosure (`placements_tested`/`rejection_reason`)."""

    placement: OverlayPlacement
    scale: float | None  # None for LOGO_ONLY (not on the scale ladder)
    zone: OverlayZone
    rejection_reason: str
    # Phase V2.10A - populated only on the pixel-occupancy path (subject_bbox=None); None on the
    # bbox-collision path, where a numeric risk score was never computed.
    pixel_risk_score: float | None = None


@dataclass(frozen=True)
class OverlayPlacementDecision:
    placement: OverlayPlacement
    scale: float | None  # None for LOGO_ONLY/NO_OVERLAY
    zone: OverlayZone | None  # None only for NO_OVERLAY
    image: Image.Image | None  # RGBA canvas-sized overlay layer; None only for NO_OVERLAY
    # Phase V2.10A: when `used_pixel_occupancy` is True, this is NOT a real detected region - it
    # stays FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX as a nominal reference value only (kept for the
    # field's pre-existing type/telemetry shape); the real per-candidate evidence is each
    # attempt's own `pixel_risk_score`, not this field, whenever that flag is True.
    collision_checked_against: BoundingBox
    attempts: tuple[CandidateAttempt, ...]  # every (placement, scale) tried, in priority order
    used_pixel_occupancy: bool = False

    @property
    def overlay_mode(self) -> str:
        """Phase V2.8 §5's required manifest field: `full_signature | logo_only | no_overlay`."""
        if self.placement is OverlayPlacement.NO_OVERLAY:
            return "no_overlay"
        if self.placement is OverlayPlacement.LOGO_ONLY:
            return "logo_only"
        return "full_signature"

    @property
    def rejected_placements(self) -> tuple[OverlayPlacement, ...]:
        """Backward-compatible view over `attempts` - the distinct placements tried and rejected,
        in first-seen order (collapsing the per-scale attempts within one placement)."""
        seen: list[OverlayPlacement] = []
        for attempt in self.attempts:
            if attempt.placement not in seen:
                seen.append(attempt.placement)
        return tuple(seen)


def _rects_intersect(a: BoundingBox, b: BoundingBox) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def _zone_collides(subject_bbox: BoundingBox, zone: OverlayZone) -> bool:
    clearance_zone = (zone.clearance_x_start, zone.clearance_y_start, zone.clearance_x_end, zone.clearance_y_end)
    return _rects_intersect(subject_bbox, clearance_zone)


def _load_candidate_c_layer() -> Image.Image:
    """A fresh RGBA load every call - no module-level caching, so callers always get the real
    persisted Candidate C pixels, never a stale in-process copy."""
    return Image.open(CANDIDATE_C_OVERLAY_PNG_PATH).convert("RGBA")


def _zone_from_alpha(image: Image.Image, *, clearance: int) -> OverlayZone:
    bbox = image.split()[-1].getbbox()
    assert bbox is not None
    return OverlayZone(x_start=bbox[0], y_start=bbox[1], x_end=bbox[2], y_end=bbox[3], clearance=clearance)


def _clearance_for_scale(scale: float) -> int:
    return max(_MIN_CLEARANCE_PX, round(_BASE_CLEARANCE_PX * scale))


def _flip_for_placement(image: Image.Image, placement: OverlayPlacement) -> Image.Image:
    if placement is OverlayPlacement.LOWER_RIGHT:
        return image
    if placement is OverlayPlacement.LOWER_LEFT:
        return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if placement is OverlayPlacement.UPPER_RIGHT:
        return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if placement is OverlayPlacement.UPPER_LEFT:
        return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    raise ValueError(f"unhandled full-signature placement: {placement}")  # pragma: no cover - exhaustive


def build_overlay_layer(placement: OverlayPlacement, *, scale: float = 1.0) -> tuple[Image.Image, OverlayZone] | None:
    """Returns the real, canvas-sized (1280x720) RGBA overlay layer and its measured zone for one
    (placement, scale) pair - `None` for NO_OVERLAY. `scale` is applied as a UNIFORM resize
    (identical factor on both axes - never a non-uniform stretch) to the trusted Candidate C
    pixels, cropped to their own real alpha content first so scaling never wastes precision on
    fully-transparent canvas margin. `scale` is ignored for LOGO_ONLY (Stage 5: one fixed emergency
    mark, not itself on the ladder)."""
    if placement is OverlayPlacement.NO_OVERLAY:
        return None
    if placement is OverlayPlacement.LOGO_ONLY:
        from services.brand_renderer import load_brand_mark

        canvas = Image.new("RGBA", (_CANVAS_WIDTH, _CANVAS_HEIGHT), (0, 0, 0, 0))
        logo = load_brand_mark()
        logo_scale = _LOGO_ONLY_WIDTH_PX / logo.width
        logo_resized = logo.resize((_LOGO_ONLY_WIDTH_PX, round(logo.height * logo_scale)), Image.Resampling.LANCZOS)
        x = _CANVAS_WIDTH - logo_resized.width - _MARGIN_PX
        y = _CANVAS_HEIGHT - logo_resized.height - _MARGIN_PX
        canvas.alpha_composite(logo_resized, (x, y))
        return canvas, _zone_from_alpha(canvas, clearance=_LOGO_ONLY_CLEARANCE_PX)

    base = _load_candidate_c_layer()
    content_bbox = base.split()[-1].getbbox()
    assert content_bbox is not None
    content = base.crop(content_bbox)  # real pixels only - no wasted transparent margin

    if scale != 1.0:
        new_w = max(1, round(content.width * scale))
        new_h = max(1, round(content.height * scale))
        content = content.resize((new_w, new_h), Image.Resampling.LANCZOS)  # uniform - same factor both axes

    flipped = _flip_for_placement(content, placement)

    canvas = Image.new("RGBA", (_CANVAS_WIDTH, _CANVAS_HEIGHT), (0, 0, 0, 0))
    if placement is OverlayPlacement.LOWER_RIGHT:
        x, y = _CANVAS_WIDTH - flipped.width - _MARGIN_PX, _CANVAS_HEIGHT - flipped.height - _MARGIN_PX
    elif placement is OverlayPlacement.LOWER_LEFT:
        x, y = _MARGIN_PX, _CANVAS_HEIGHT - flipped.height - _MARGIN_PX
    elif placement is OverlayPlacement.UPPER_RIGHT:
        x, y = _CANVAS_WIDTH - flipped.width - _MARGIN_PX, _MARGIN_PX
    elif placement is OverlayPlacement.UPPER_LEFT:
        x, y = _MARGIN_PX, _MARGIN_PX
    else:  # pragma: no cover - exhaustive over the four full-signature placements
        raise ValueError(f"unhandled placement: {placement}")
    canvas.alpha_composite(flipped, (x, y))
    return canvas, _zone_from_alpha(canvas, clearance=_clearance_for_scale(scale))


def _zone_pixel_risk_score(photo_for_occupancy: Image.Image, zone: OverlayZone) -> float:
    """Phase V2.10A - deterministic pixel-content occupancy signal, used ONLY when the caller has
    no trustworthy semantic `subject_bbox`. Crops the zone's own clearance-expanded region out of
    the REAL photo pixels the overlay is about to be composited onto (never a separate/re-fetched
    image), converts to grayscale, and measures edge density via `ImageFilter.FIND_EDGES`'s own
    mean intensity - real watermarks, logos, and fine text/UI detail produce strong local edges;
    an out-of-focus background, open floor, wall, or sky does not. This is pixel analysis of the
    literal candidate region, not an attempt to semantically understand the whole photograph - see
    `_PIXEL_RISK_EDGE_THRESHOLD`'s own calibration comment for the real measured numbers this
    threshold is grounded in."""
    box = (zone.clearance_x_start, zone.clearance_y_start, zone.clearance_x_end, zone.clearance_y_end)
    cropped = photo_for_occupancy.convert("L").crop(box)
    if cropped.width == 0 or cropped.height == 0:
        return float("inf")  # degenerate crop - never trust an empty region as safe
    edges = cropped.filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).mean[0]


def _zone_is_blocked(
    zone: OverlayZone, *, subject_bbox: BoundingBox | None, photo_for_occupancy: Image.Image | None,
) -> tuple[bool, str, float | None]:
    """Phase V2.10A - the one place that decides "does this candidate zone collide", dispatching
    between the two available signals. A trustworthy `subject_bbox` (human review, or a future
    real semantic signal) always wins when supplied - the pixel-occupancy path only ever runs when
    the caller has no such bbox at all, never as a second-guessing override of one that exists."""
    if subject_bbox is not None:
        return _zone_collides(subject_bbox, zone), "collides_with_subject_bbox_plus_clearance", None
    if photo_for_occupancy is not None:
        score = _zone_pixel_risk_score(photo_for_occupancy, zone)
        blocked = score >= _PIXEL_RISK_EDGE_THRESHOLD
        reason = f"pixel_occupancy_risk_score_{score:.2f}_over_threshold_{_PIXEL_RISK_EDGE_THRESHOLD}" if blocked else ""
        return blocked, reason, score
    # Neither a semantic bbox nor real photo pixels were supplied - the only remaining honest
    # assumption is the original V2.9 full-frame-conservative one (see that constant's own
    # docstring); this path is not reachable from apply_adaptive_nnj_branding() itself, which
    # always has the real fitted photo, but is kept for any other direct caller of this function.
    return _zone_collides(FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX, zone), "collides_with_subject_bbox_plus_clearance", None


def select_overlay_placement(
    subject_bbox: BoundingBox | None, *, photo_for_occupancy: Image.Image | None = None,
) -> OverlayPlacementDecision:
    """The deterministic selection algorithm (Phase V2.8 §3-5, extended by Phase V2.10A §2-3): for
    each placement in `_PLACEMENT_PRIORITY` (lower_right -> lower_left -> upper_right ->
    upper_left), try every scale in `SCALE_LADDER` (largest first); return the first (placement,
    scale) whose measured zone (plus its scale-proportional clearance) is not "blocked" per
    `_zone_is_blocked()`. Falls back to LOGO_ONLY only when every full-signature candidate was
    blocked, then NO_OVERLAY only when even the logo mark is blocked.

    `subject_bbox`, when supplied (human visual review or another already-existing deterministic
    semantic signal), is used exactly as before - a deterministic geometric collision guard, no
    detection of its own. When `subject_bbox is None`, `photo_for_occupancy` (if supplied) drives
    a deterministic real-pixel-content occupancy check instead (Phase V2.10A) - this is the actual
    unattended production path today, since no semantic subject-bbox signal exists anywhere in
    this codebase."""
    used_pixel_occupancy = subject_bbox is None and photo_for_occupancy is not None
    attempts: list[CandidateAttempt] = []
    for placement in _PLACEMENT_PRIORITY:
        for scale in SCALE_LADDER:
            built = build_overlay_layer(placement, scale=scale)
            assert built is not None
            image, zone = built
            blocked, reason, score = _zone_is_blocked(
                zone, subject_bbox=subject_bbox, photo_for_occupancy=photo_for_occupancy,
            )
            if not blocked:
                return OverlayPlacementDecision(
                    placement=placement, scale=scale, zone=zone, image=image,
                    collision_checked_against=subject_bbox if subject_bbox is not None else FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX,
                    attempts=tuple(attempts), used_pixel_occupancy=used_pixel_occupancy,
                )
            attempts.append(CandidateAttempt(
                placement=placement, scale=scale, zone=zone, rejection_reason=reason, pixel_risk_score=score,
            ))

    logo_built = build_overlay_layer(OverlayPlacement.LOGO_ONLY)
    assert logo_built is not None
    logo_image, logo_zone = logo_built
    logo_blocked, logo_reason, logo_score = _zone_is_blocked(
        logo_zone, subject_bbox=subject_bbox, photo_for_occupancy=photo_for_occupancy,
    )
    if not logo_blocked:
        return OverlayPlacementDecision(
            placement=OverlayPlacement.LOGO_ONLY, scale=None, zone=logo_zone, image=logo_image,
            collision_checked_against=subject_bbox if subject_bbox is not None else FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX,
            attempts=tuple(attempts), used_pixel_occupancy=used_pixel_occupancy,
        )
    attempts.append(CandidateAttempt(
        placement=OverlayPlacement.LOGO_ONLY, scale=None, zone=logo_zone,
        rejection_reason=logo_reason, pixel_risk_score=logo_score,
    ))

    return OverlayPlacementDecision(
        placement=OverlayPlacement.NO_OVERLAY, scale=None, zone=None, image=None,
        collision_checked_against=subject_bbox if subject_bbox is not None else FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX,
        attempts=tuple(attempts), used_pixel_occupancy=used_pixel_occupancy,
    )


def _fit_photo_to_canvas(photo: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / photo.width, target_h / photo.height)
    scaled = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.Resampling.LANCZOS)
    x0 = (scaled.width - target_w) // 2
    y0 = (scaled.height - target_h) // 2
    return scaled.crop((x0, y0, x0 + target_w, y0 + target_h))


def apply_adaptive_nnj_branding(
    source_image_bytes: bytes, *, subject_bbox: BoundingBox | None = None,
) -> tuple[bytes, OverlayPlacementDecision]:
    """Phase V2.9 §2 - the ONE production compositing entry point. Fits `source_image_bytes` to
    the locked 1280x720 canvas, calls `select_overlay_placement()` (never duplicated inline),
    composites the selected overlay (if any), and returns `(jpeg_bytes, decision)` - the caller
    logs `decision`'s own fields directly (never raw image bytes). Works identically for an
    ORIGINAL_SOURCE image or a successfully-recomposed one - the caller decides which bytes to
    pass in; this function has no opinion about where they came from.

    `subject_bbox=None` (every current production caller, unchanged) now drives the Phase V2.10A
    deterministic pixel-occupancy signal - `photo_fit` (the exact same pixels about to be
    composited onto, fitted to the real canvas) is passed to `select_overlay_placement()` as
    `photo_for_occupancy`, never a full-frame placeholder. See `select_overlay_placement()`'s own
    docstring for the real, measured calibration this replaces the old all-NO_OVERLAY default
    with."""
    photo = Image.open(io.BytesIO(source_image_bytes)).convert("RGBA")
    photo_fit = _fit_photo_to_canvas(photo, (_CANVAS_WIDTH, _CANVAS_HEIGHT))

    decision = select_overlay_placement(
        subject_bbox, photo_for_occupancy=photo_fit if subject_bbox is None else None,
    )

    branded = photo_fit.copy()
    if decision.image is not None:
        branded.alpha_composite(decision.image)
    buf = io.BytesIO()
    branded.convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue(), decision
