"""Phase V2.10H - the locked MASTER NEWS visual contract (Phase V2.10E-G design recovery ->
user-approved production selection: MASTER_BALANCED lower signature + MEDIUM upper mark) wired as
a real, automatic, deterministic placement system. Supersedes Candidate C
(services/nnj_adaptive_overlay.py) as the normal NEWS branding path - that module and its locked
asset remain untouched, kept as historical/fallback evidence, never called from this module.

Two independent components (Phase V2.10H §3):
  - UPPER MARK: a small standalone canonical NNJ mark (no line/pulse attached).
  - LOWER SIGNATURE: a thin edge line + pulse + a second canonical NNJ mark at its terminus.
Each is placed (or omitted) independently - they do not need to share a corner, and either can
degrade to absent while the other still renders (Phase V2.10H §6).

SAFE-ZONE ESTIMATOR (Phase V2.10H §7-8): no semantic subject/face/watermark-region detector
exists anywhere in this codebase (confirmed by the Phase V2.10D/V2.10A forensic sweep - the only
real per-image signals are whole-image boolean flags like `possible_logo`, never a bounding box).
This module does NOT invent one and does NOT call an AI model to locate the overlay. It scores
each candidate corner region directly against the REAL photo pixels using two deterministic
signals: edge density (`ImageFilter.FIND_EDGES` mean - real detail/text/logos produce strong local
edges; a quiet background does not) and local contrast (`ImageStat.Stat` stddev - a secondary,
reported-but-not-gating signal, since a busy-but-harmless bright/dark gradient can carry high
stddev without carrying real content, as V2.10A's own calibration already established). A
genuinely available `subject_bbox` (human review, or a future real per-image signal) is honored as
an additional geometric exclusion on top of the pixel score, never overridden by it.

BRAND VISIBILITY (Phase V2.10H §9): a candidate region that scores "quiet" by edge density can
still be a poor place for red branding if the local background color is itself a similar red/dark
tone the mark would nearly vanish into. A second, independent check - Euclidean RGB distance from
the candidate region's own mean color to the locked NNJ red (#ED1C24) - must also clear a minimum
threshold; a region that is spatially "safe" but insufficiently visible is still rejected.

PATCH-BASED WORST-CASE SCORING (Phase V2.10I - real forensic finding, not a hypothetical fix): a
real Honor-image failure was found where the LOWER SIGNATURE's own accepted region measured a
*whole-region average* edge_density of 6.45 (under the 8.0 gate) despite containing real,
factually-important disclaimer text - because the accepted box is large relative to the thin text
strip inside it, averaging over the whole box diluted the text's own much stronger local signal
(measured in isolation: edge_density 32.67 for the text alone) down below the gate. Root cause:
whole-region averaging can hide small, concentrated risk inside an otherwise-quiet larger area.
Fix: every candidate region is now divided into a `_PATCH_GRID` grid of sub-patches, and the GATE
uses the WORST (maximum) patch's edge_density and high-threshold gradient occupancy - not the
whole-region mean. Verified against the real Honor case (worst patch: edge_density 11.65, now
correctly rejected) and against three known-safe real regions (iPhone/portrait: worst-patch
edge_density 3-4, still correctly accepted) before being adopted - not tuned to make Honor alone
pass, and it also correctly rejects a previously-borderline busy-decorative (non-factual) swirl
background on a different real image, which is the intended, disclosed, conservative trade-off
(Phase V2.10I §5: "expected that more images become UPPER_MARK_ONLY... do not weaken gates merely
to maximize branded-image percentage").

DETAIL RISK (Phase V2.10I §4): a second, complementary per-patch signal - the percentage of a
patch's pixels whose edge response exceeds a high threshold (50/255). Real text measured 18-29% at
this threshold across multiple real sub-regions measured during the Honor forensic; every
genuinely quiet real region measured 0%, and the one busy-but-legitimate texture case measured
under 7%. Named `detail_risk_pct` in telemetry - deliberately not `text_detected`, since no OCR or
semantic text detection exists here; this is coarse pixel statistics only, evidence of
concentrated fine structure, not a semantic claim about what that structure is.

EXISTING METADATA REUSE (Phase V2.10I §7): `worker/content_cycle.py` already computes
`recomposition_source_risk` (via `assess_recomposition_source_risk()`, itself reading the real,
already-persisted `EditorialImageCandidate.warnings` field) before ever reaching this module's own
call site. That signal is whole-image, not spatial - it cannot say *where* the risk is, only that
the image as a whole carries a real flagged risk (a logo/banner/watermark/lower-third/branded-
screenshot warning already computed elsewhere in this codebase). Rather than pretending it
supplies coordinates, `apply_master_news_branding(..., disable_lower_signature=...)` uses it as a
coarse, whole-image veto on the LOWER SIGNATURE specifically (the larger, harder-to-earn
component) while leaving the UPPER MARK's own independent, spatial evaluation completely
unaffected - exactly the "degrade conservatively, do not pretend location knowledge" mapping this
phase's own instructions describe."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageFilter, ImageStat

from services.nnj_master_news_mark import NNJ_RED_FILL, rasterize_nnj_mark

BoundingBox = tuple[int, int, int, int]

_CANVAS_W, _CANVAS_H = 1280, 720

# --- Locked MASTER_BALANCED lower-signature geometry (Phase V2.10G user selection, Phase V2.10H
# §1 lock; Phase V2.17 rescale; Phase V2.25 rescale) - expressed as fractions of the 1280x720
# reference canvas so it scales proportionally to any real output canvas size (Phase V2.10H §1's
# own explicit requirement) - every source photo is fit to this exact reference canvas
# (`_fit_photo_to_canvas()`) before compositing, so a fraction-based constant already scales
# correctly across every supported source resolution without further change.
#
# Phase V2.17: real production Telegram rendering (mobile + desktop) showed the original
# MASTER_BALANCED footprint (~24.0% lower-signature width, 32px upper mark) was too subtle once
# Telegram's own client-side photo scaling shrank it further - the SAME approved visual language,
# scaled up by a uniform ~1.335x factor for every lower-signature component (so proportions among
# pulse/line/terminal-mark/total-width stay byte-identical to the original design), landing the
# lower-signature total width at ~32.0% of canvas width.
#
# Phase V2.25: still too small on a real Telegram mobile feed once V2.17 shipped - the user's own
# explicit target scaled every lower-signature component up again by a further uniform ~1.375x
# from the V2.17 numbers (so proportions among pulse/line/terminal-mark/total-width remain
# byte-identical to the original V2.10G design, exactly like the V2.17 rescale before it), landing
# the lower-signature total width at ~44.0% of canvas width. Line thickness is again bumped beyond
# the uniform factor (4px -> 6px, 1.5x) for the same downscaling-legibility reason V2.17 gave for
# its own above-proportional line bump. The upper mark is scaled 1.375x (48px -> 66px). Unlike
# V2.17, `_SAFE_INSET_FRAC` is ALSO increased this time (20px -> 24px) - the user's own explicit
# V2.25 instruction, not a re-derivation of V2.10H §2's calibration; a materially larger overlay
# footprint benefits from a proportionally larger clearance from the frame edge.
#
# IMPORTANT (Phase V2.25 Part D): `select_master_news_branding()` below computes the exact
# geometry it scores for safety (`lower_component_w/h`, `upper_mark_w`) directly from these SAME
# module-level fraction constants - there is no separate, duplicated "safety footprint" constant
# anywhere in this module. Changing these values therefore changes the real rendered size AND the
# safety-scored footprint together, atomically - there is no V2.17-era 32%-scale assumption left
# behind anywhere else to update.
_LOWER_TOTAL_WIDTH_FRAC = 563 / _CANVAS_W       # ~44.0% of canvas width (was 410/1280, ~32.0%)
_LOWER_PULSE_W_FRAC = 66 / _CANVAS_W             # was 48/1280
_LOWER_PULSE_H_FRAC = 62 / _CANVAS_H             # was 45/720
_LOWER_LINE_THICKNESS_FRAC = 6 / _CANVAS_H       # was 4/720 - above-proportional, see comment above
_LOWER_MARK_W_FRAC = 70 / _CANVAS_W              # was 51/1280

# --- Locked MEDIUM upper-mark geometry (Phase V2.25: further 1.375x rescale, see comment above) ---
_UPPER_MARK_W_FRAC = 66 / _CANVAS_W              # was 48/1280

# Safe edge inset (Phase V2.10H §2 original calibration; Phase V2.25 explicit enlargement to match
# the materially larger overlay footprint - see comment above).
_SAFE_INSET_FRAC = 24 / _CANVAS_W                # was 20/1280

_GAP_FRAC = 18 / _CANVAS_W  # clearance between the terminal NNJ mark and the pulse (was 13/1280,
# scaled by the same ~1.375x factor as the other lower-signature components, Phase V2.25)

# Pixel-occupancy safe-zone threshold (Phase V2.10A's own real-photo calibration, reused here
# rather than re-derived from scratch: real safe corners on real photos measured edge_mean<=5.83;
# real risky corners - a genuine watermark, a bright reflection streak - measured edge_mean>=10.49).
_EDGE_DENSITY_SAFE_THRESHOLD = 8.0

# Visibility threshold: minimum Euclidean RGB distance from a candidate region's own mean color to
# the locked NNJ red, calibrated against real photo regions (a red-on-warm-brown-wood region
# measured ~55-70; a red-on-neutral-gray/dark region measured >120) - 70 sits above the observed
# low-visibility cluster.
_VISIBILITY_MIN_DISTANCE = 70.0

# Score-region padding: MASTER_BALANCED's own component footprints are small (the upper mark is
# only ~32x13px), too few pixels for a stable edge-density statistic on their own - a real,
# empirically-found issue (a genuinely quiet corner on the real robot-vacuum photo measured
# edge_density=51.8 at the bare 32x13 mark footprint vs 4.8 once padded to a representative
# neighborhood, matching Phase V2.10A's own successful calibration at a comparable box size).
# Padding the SCORING box only (never the box used for subject_bbox collision, which stays the
# real render footprint) restores a statistically meaningful sample without changing what is
# actually drawn.
_SCORE_PAD_PX_FRAC = 50 / _CANVAS_W

# Patch-based worst-case scoring grid (Phase V2.10I - see module docstring's own "PATCH-BASED
# WORST-CASE SCORING" section for the real Honor forensic finding this fixes). 4x2 chosen as the
# smallest grid that gave clean separation on the real evidence measured during that forensic
# pass (Honor's own worst patch: edge_density 11.65 / detail_risk 6.67%; two known-safe real
# regions: 3-4 / 0%) - not swept/tuned beyond that one real comparison.
_DETAIL_RISK_PATCH_GRID = (4, 2)
# High-threshold gradient value (0-255 scale) used for the detail_risk_pct signal.
_DETAIL_RISK_EDGE_VALUE_THRESHOLD = 50
# Maximum allowed detail_risk_pct in the worst patch. Real text measured 18-29% at this threshold
# across several real sub-regions during the Honor forensic; the busiest legitimate (non-factual)
# texture found in the real proof set measured under 7%; every genuinely quiet real region
# measured 0%. 15% sits above the observed safe cluster with real margin, well below the observed
# risky cluster.
_DETAIL_RISK_MAX_PCT = 15.0

# Phase V2.25 Part B: the explicit, exhaustive final-NEWS-image diagnostic vocabulary. Every real
# NEWS send must record exactly one of these - `worker/content_cycle.py` is the only place that
# assigns them (this module has no knowledge of Telegram delivery), but the vocabulary itself is
# declared here, next to the branding decision it classifies, so both the single-photo path and
# the media-group path (services/image_preview_notifier.py::build_rich_media_plan() output) use
# the exact same four literal strings rather than each inventing their own ad hoc log field.
NEWS_BRANDING_BRANDED = "BRANDED"
NEWS_BRANDING_NO_OVERLAY_SAFETY = "NO_OVERLAY_SAFETY"
NEWS_BRANDING_ORIGINAL_SOURCE_FAILURE = "ORIGINAL_SOURCE_BRANDING_FAILURE"
# A real fourth state, distinct from the three the Phase V2.25 spec named: no candidate bytes were
# ever available to hand to select_master_news_branding() at all (a cached Telegram file_id with
# no independently-readable original, or no photo resolved for this draft in the first place) - it
# would be inaccurate to call this either a safety rejection (safety never ran) or a branding
# failure (branding was never attempted), so it gets its own explicit name rather than being
# force-fit into one of the other three and silently misreported.
NEWS_BRANDING_NO_SOURCE_BYTES = "NO_OVERLAY_NO_SOURCE_BYTES"


class ComponentPlacement(str, Enum):
    LOWER_RIGHT = "lower_right"
    LOWER_LEFT = "lower_left"
    UPPER_RIGHT = "upper_right"
    UPPER_LEFT = "upper_left"
    OMITTED = "omitted"


@dataclass(frozen=True)
class RegionScore:
    placement: ComponentPlacement
    box: BoundingBox
    edge_density: float             # worst-patch value (Phase V2.10I) - see module docstring
    contrast_stddev: float
    visibility_distance: float
    detail_risk_pct: float          # worst-patch high-threshold gradient occupancy (Phase V2.10I)
    safe_by_edge_density: bool
    safe_by_visibility: bool
    safe_by_detail_risk: bool
    collides_with_subject_bbox: bool
    accepted: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class ComponentDecision:
    placement: ComponentPlacement  # OMITTED if nothing safe was found
    image: Image.Image | None      # canvas-sized RGBA layer; None iff placement is OMITTED
    attempts: tuple[RegionScore, ...]
    # Phase V2.10I §7: set when this component was force-disabled by a whole-image, non-spatial
    # risk signal (assess_recomposition_source_risk()'s own already-computed warning) BEFORE any
    # region was even scored - `attempts` stays empty in that case, since no candidate was
    # evaluated at all, not because every candidate failed.
    disabled_reason: str | None = None


@dataclass(frozen=True)
class MasterNewsBrandingDecision:
    upper_mark: ComponentDecision
    lower_signature: ComponentDecision
    canvas_size: tuple[int, int]
    # VISUAL-SINGLE-BRAND-MARK-1 §6: True when `apply_master_news_branding()` detected the input
    # bytes already carry this module's own finalization marker (see `_FINALIZED_MARKER_PREFIX`
    # below) and returned them completely unchanged - no new compositing occurred, `upper_mark`/
    # `lower_signature` above are both placeholder OMITTED decisions with no real evaluation.
    # `already_finalized_had_overlay` preserves whether that PRIOR run actually placed a mark
    # (read back from the marker itself, never re-derived from pixels) so a caller's
    # BRANDED-vs-NO_OVERLAY_SAFETY accounting stays correct across repeated finalization instead
    # of blindly assuming a mark is present.
    already_finalized: bool = False
    already_finalized_had_overlay: bool = False

    @property
    def degradation_mode(self) -> str:
        if self.already_finalized:
            return "already_finalized" if self.already_finalized_had_overlay else "no_overlay"
        has_upper = self.upper_mark.placement is not ComponentPlacement.OMITTED
        has_lower = self.lower_signature.placement is not ComponentPlacement.OMITTED
        # VISUAL-SINGLE-BRAND-MARK-1 §6: upper_mark and lower_signature are now mutually
        # exclusive by construction (select_master_news_branding() never evaluates the upper mark
        # once the lower signature has already been placed) - "upper_and_lower" is therefore
        # structurally unreachable, kept only so a legacy log/telemetry reader never crashes on an
        # unrecognized value it may still hold in historical records.
        if has_upper and has_lower:
            return "upper_and_lower"  # pragma: no cover - structurally unreachable, see above
        if has_lower:
            return "lower_signature_only"
        if has_upper:
            return "upper_mark_only"
        return "no_overlay"

    @property
    def news_branding_status(self) -> str:
        """Phase V2.25 Part B: the explicit BRANDED / NO_OVERLAY_SAFETY classification for a
        successful `apply_master_news_branding()` call (i.e. one that did not raise) - the caller
        is responsible for the two exception/no-bytes states this decision object cannot itself
        represent (`NEWS_BRANDING_ORIGINAL_SOURCE_FAILURE` / `NEWS_BRANDING_NO_SOURCE_BYTES`),
        since this object is only ever constructed when branding actually ran to completion.
        Correctly reflects `already_finalized_had_overlay` on a repeated finalization too -
        `degradation_mode` above already folds that flag in, never blindly reporting BRANDED."""
        return NEWS_BRANDING_NO_OVERLAY_SAFETY if self.degradation_mode == "no_overlay" else NEWS_BRANDING_BRANDED


def _region_box(canvas_size: tuple[int, int], component_w: int, component_h: int, placement: ComponentPlacement, inset: int) -> BoundingBox:
    w, h = canvas_size
    if placement is ComponentPlacement.LOWER_RIGHT:
        return (w - inset - component_w, h - inset - component_h, w - inset, h - inset)
    if placement is ComponentPlacement.LOWER_LEFT:
        return (inset, h - inset - component_h, inset + component_w, h - inset)
    if placement is ComponentPlacement.UPPER_RIGHT:
        return (w - inset - component_w, inset, w - inset, inset + component_h)
    if placement is ComponentPlacement.UPPER_LEFT:
        return (inset, inset, inset + component_w, inset + component_h)
    raise ValueError(f"no region box for {placement}")  # pragma: no cover - exhaustive


def _rects_intersect(a: BoundingBox, b: BoundingBox) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def _score_region(photo: Image.Image, box: BoundingBox, *, subject_bbox: BoundingBox | None) -> tuple[float, float, float, float]:
    """Returns (worst_patch_edge_density, contrast_stddev, visibility_distance, worst_patch_
    detail_risk_pct) for `box` measured directly on the real `photo` pixels. `box` is divided
    into `_DETAIL_RISK_PATCH_GRID` sub-patches and the WORST (maximum) patch drives both the edge-
    density and detail-risk values - never the whole-region average - per this module's own
    docstring ("PATCH-BASED WORST-CASE SCORING"), which explains the real Honor-image dilution
    failure this replaces a simpler whole-region average with. `contrast_stddev` remains a
    whole-region statistic (reported only, never gating - unchanged from Phase V2.10H)."""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(photo.width, x1), min(photo.height, y1)
    if x1 <= x0 or y1 <= y0:
        return float("inf"), float("inf"), 0.0, 100.0
    crop_gray = photo.convert("L").crop((x0, y0, x1, y1))
    edges = crop_gray.filter(ImageFilter.FIND_EDGES)
    contrast = ImageStat.Stat(crop_gray).stddev[0]
    crop_rgb = photo.convert("RGB").crop((x0, y0, x1, y1))
    mean_rgb = ImageStat.Stat(crop_rgb).mean
    visibility_distance = math.dist(mean_rgb[:3], NNJ_RED_FILL[:3])

    w, h = edges.size
    cols, rows = _DETAIL_RISK_PATCH_GRID
    patch_w, patch_h = max(1, w // cols), max(1, h // rows)
    worst_edge_density = 0.0
    worst_detail_risk = 0.0
    for r in range(rows):
        for c in range(cols):
            pbox = (c * patch_w, r * patch_h, min(w, (c + 1) * patch_w), min(h, (r + 1) * patch_h))
            if pbox[2] <= pbox[0] or pbox[3] <= pbox[1]:
                continue
            patch = edges.crop(pbox)
            values = list(patch.getdata())
            n = len(values)
            if n == 0:
                continue
            patch_mean = sum(values) / n
            patch_detail_risk = 100 * sum(1 for v in values if v > _DETAIL_RISK_EDGE_VALUE_THRESHOLD) / n
            worst_edge_density = max(worst_edge_density, patch_mean)
            worst_detail_risk = max(worst_detail_risk, patch_detail_risk)
    return worst_edge_density, contrast, visibility_distance, worst_detail_risk


def _evaluate_placements(
    photo: Image.Image, *, component_size: tuple[int, int], candidates: tuple[ComponentPlacement, ...],
    inset: int, subject_bbox: BoundingBox | None,
) -> tuple[ComponentPlacement, BoundingBox | None, tuple[RegionScore, ...]]:
    attempts: list[RegionScore] = []
    pad = max(1, round(_SCORE_PAD_PX_FRAC * photo.width))
    for placement in candidates:
        box = _region_box((photo.width, photo.height), component_size[0], component_size[1], placement, inset)
        score_box = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
        edge_density, contrast, visibility, detail_risk = _score_region(photo, score_box, subject_bbox=subject_bbox)
        collides = subject_bbox is not None and _rects_intersect(subject_bbox, box)
        safe_edge = edge_density < _EDGE_DENSITY_SAFE_THRESHOLD
        safe_visible = visibility >= _VISIBILITY_MIN_DISTANCE
        safe_detail = detail_risk < _DETAIL_RISK_MAX_PCT
        accepted = safe_edge and safe_visible and safe_detail and not collides
        reason = None
        if not accepted:
            reasons = []
            if collides:
                reasons.append("collides_with_subject_bbox")
            if not safe_edge:
                reasons.append(f"edge_density_{edge_density:.2f}_over_threshold_{_EDGE_DENSITY_SAFE_THRESHOLD}")
            if not safe_detail:
                reasons.append(f"detail_risk_pct_{detail_risk:.2f}_over_threshold_{_DETAIL_RISK_MAX_PCT}")
            if not safe_visible:
                reasons.append(f"visibility_distance_{visibility:.1f}_under_threshold_{_VISIBILITY_MIN_DISTANCE}")
            reason = ";".join(reasons)
        attempts.append(RegionScore(
            placement=placement, box=box, edge_density=edge_density, contrast_stddev=contrast,
            visibility_distance=visibility, detail_risk_pct=detail_risk, safe_by_edge_density=safe_edge,
            safe_by_visibility=safe_visible, safe_by_detail_risk=safe_detail,
            collides_with_subject_bbox=collides, accepted=accepted, rejection_reason=reason,
        ))
        if accepted:
            return placement, box, tuple(attempts)
    return ComponentPlacement.OMITTED, None, tuple(attempts)


def _build_upper_mark_image(canvas_size: tuple[int, int], placement: ComponentPlacement, inset: int) -> Image.Image:
    w, h = canvas_size
    mark_w = max(1, round(_UPPER_MARK_W_FRAC * w))
    mark = rasterize_nnj_mark(target_width=mark_w, red=True)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    x = inset if placement is ComponentPlacement.UPPER_LEFT else w - inset - mark.width
    canvas.alpha_composite(mark, (x, inset))
    return canvas


def _build_corner_mark_image(canvas_size: tuple[int, int], placement: ComponentPlacement, inset: int) -> Image.Image:
    """FOUNDER-VISUAL-POLISH-2 §2: the RESTRAINED NEWS treatment - ONE small canonical NNJ mark in
    a safe corner, nothing else (no connecting line, no pulse). The board's "лёгкий фирменный
    водяной знак" for NEWS. Generalises `_build_upper_mark_image()` to all four corners so the
    adaptive scorer can pick whichever is least busy; the mark is identical (`rasterize_nnj_mark()`),
    never mirrored."""
    w, h = canvas_size
    mark_w = max(1, round(_UPPER_MARK_W_FRAC * w))
    mark = rasterize_nnj_mark(target_width=mark_w, red=True)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    x = inset if placement in (ComponentPlacement.UPPER_LEFT, ComponentPlacement.LOWER_LEFT) else w - inset - mark.width
    y = inset if placement in (ComponentPlacement.UPPER_LEFT, ComponentPlacement.UPPER_RIGHT) else h - inset - mark.height
    canvas.alpha_composite(mark, (x, y))
    return canvas


def _draw_pulse(draw, x0: int, y_mid: int, width: int, height: int, color, line_w: int) -> None:
    top, bottom = y_mid - height // 2, y_mid + height // 2
    pts = [
        (x0, y_mid), (x0 + round(width * 0.28), y_mid), (x0 + round(width * 0.42), top),
        (x0 + round(width * 0.56), bottom), (x0 + round(width * 0.72), y_mid), (x0 + width, y_mid),
    ]
    draw.line(pts, fill=color, width=line_w, joint="curve")


def _build_lower_signature_image(canvas_size: tuple[int, int], placement: ComponentPlacement, inset: int) -> Image.Image:
    from PIL import ImageDraw
    w, h = canvas_size
    total_w = max(10, round(_LOWER_TOTAL_WIDTH_FRAC * w))
    pulse_w, pulse_h = max(1, round(_LOWER_PULSE_W_FRAC * w)), max(1, round(_LOWER_PULSE_H_FRAC * h))
    line_thick = max(1, round(_LOWER_LINE_THICKNESS_FRAC * h))
    mark_w = max(1, round(_LOWER_MARK_W_FRAC * w))
    gap = max(1, round(_GAP_FRAC * w))
    mark = rasterize_nnj_mark(target_width=mark_w, red=True)
    line_len = max(10, total_w - pulse_w - mark.width - gap)

    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    y = h - inset

    if placement is ComponentPlacement.LOWER_RIGHT or placement is ComponentPlacement.UPPER_RIGHT:
        mark_x = w - inset - mark.width
        mark_y = (inset if placement is ComponentPlacement.UPPER_RIGHT else y - mark.height // 2)
        line_y = inset + mark.height // 2 if placement is ComponentPlacement.UPPER_RIGHT else y
        pulse_end_x = mark_x - gap
        pulse_start_x = pulse_end_x - pulse_w
        line_end_x = pulse_start_x
        line_start_x = line_end_x - line_len
        draw.line([(line_start_x, line_y), (line_end_x, line_y)], fill=NNJ_RED_FILL, width=line_thick)
        _draw_pulse(draw, pulse_start_x, line_y, pulse_w, pulse_h, NNJ_RED_FILL, line_thick)
        canvas.alpha_composite(mark, (mark_x, mark_y))
    else:  # LOWER_LEFT or UPPER_LEFT - built from primitives, NNJ never mirrored (Phase V2.10G/H)
        mark_x = inset
        mark_y = (inset if placement is ComponentPlacement.UPPER_LEFT else y - mark.height // 2)
        line_y = inset + mark.height // 2 if placement is ComponentPlacement.UPPER_LEFT else y
        pulse_start_x = mark_x + mark.width + gap
        line_start_x = pulse_start_x + pulse_w
        line_end_x = line_start_x + line_len
        canvas.alpha_composite(mark, (mark_x, mark_y))
        _draw_pulse(draw, pulse_start_x, line_y, pulse_w, pulse_h, NNJ_RED_FILL, line_thick)
        draw.line([(line_start_x, line_y), (line_end_x, line_y)], fill=NNJ_RED_FILL, width=line_thick)

    return canvas


def _fit_photo_to_canvas(photo: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / photo.width, target_h / photo.height)
    scaled = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.Resampling.LANCZOS)
    x0 = (scaled.width - target_w) // 2
    y0 = (scaled.height - target_h) // 2
    return scaled.crop((x0, y0, x0 + target_w, y0 + target_h))


SIGNATURE_STYLE_FUSED = "fused"        # line + pulse + mark, one fused unit (DATA / RECAP / grouped)
SIGNATURE_STYLE_MARK_ONLY = "mark_only"  # FOUNDER-VISUAL-POLISH-2: the restrained NEWS watermark


def select_master_news_branding(
    photo: Image.Image, *, subject_bbox: BoundingBox | None = None, disable_lower_signature: bool = False,
    signature_style: str = SIGNATURE_STYLE_FUSED,
) -> MasterNewsBrandingDecision:
    """The one deterministic selection function (Phase V2.10H §3/§4/§6, extended Phase V2.10I §7,
    VISUAL-SINGLE-BRAND-MARK-1 §6): evaluates the LOWER SIGNATURE first (LOWER_RIGHT ->
    LOWER_LEFT -> UPPER_RIGHT -> UPPER_LEFT, bottom-edge strongly preferred per §4) since it is
    this contract's own preferred, primary branding unit. The UPPER MARK (UPPER_RIGHT ->
    UPPER_LEFT) is evaluated ONLY as a fallback for when the lower signature could not be safely
    placed anywhere - both components draw the SAME canonical NNJ mark
    (`rasterize_nnj_mark()`), so compositing both at once would put two independently-readable
    NNJ marks on one image (VISUAL-SINGLE-BRAND-MARK-1's own "exactly one canonical brand mark"
    invariant - this is the real, live root cause that invariant is closing: prior to this phase
    the two components were placed completely independently and could both succeed on the same
    quiet photo). Never both, never neither's own placement chain shortened - the fallback still
    tries every one of its own candidate corners, exactly as before. No semantic subject detector
    is invoked; a genuinely supplied `subject_bbox` is honored as an additional exclusion.
    `disable_lower_signature=True` (Phase V2.10I §7 - see module docstring's own "EXISTING
    METADATA REUSE" section) skips lower-signature region evaluation entirely and lets the upper
    mark's own independent, spatial evaluation run as the sole candidate - a whole-image,
    non-spatial risk signal cannot certify any particular corner as safe, so no lower-signature
    region is scored at all."""
    canvas_size = (photo.width, photo.height)
    inset = max(1, round(_SAFE_INSET_FRAC * canvas_size[0]))

    if signature_style == SIGNATURE_STYLE_MARK_ONLY:
        # FOUNDER-VISUAL-POLISH-2 §2: one small canonical mark in the least-busy safe corner,
        # nothing else. No fused line, no pulse. Carried in the `lower_signature` slot so the
        # single-brand-mark / degradation-mode bookkeeping is unchanged (it is still "the one
        # branding unit"), and the upper-mark slot stays OMITTED (mutual exclusion holds).
        mark_w = max(1, round(_UPPER_MARK_W_FRAC * canvas_size[0]))
        mark_h = rasterize_nnj_mark(target_width=mark_w).height
        mark_placement, _mbox, mark_attempts = _evaluate_placements(
            photo, component_size=(mark_w, mark_h),
            candidates=(ComponentPlacement.LOWER_RIGHT, ComponentPlacement.LOWER_LEFT,
                        ComponentPlacement.UPPER_RIGHT, ComponentPlacement.UPPER_LEFT),
            inset=inset, subject_bbox=subject_bbox,
        )
        mark_image = (
            _build_corner_mark_image(canvas_size, mark_placement, inset)
            if mark_placement is not ComponentPlacement.OMITTED else None
        )
        skip = ComponentDecision(placement=ComponentPlacement.OMITTED, image=None, attempts=())
        return MasterNewsBrandingDecision(
            upper_mark=skip,
            lower_signature=ComponentDecision(
                placement=mark_placement, image=mark_image, attempts=mark_attempts,
                disabled_reason=None,
            ),
            canvas_size=canvas_size,
        )

    if disable_lower_signature:
        lower_placement = ComponentPlacement.OMITTED
        lower_attempts: tuple[RegionScore, ...] = ()
        lower_image = None
        lower_disabled_reason = "whole_image_source_risk_from_editorial_image_candidate_warnings"
    else:
        lower_mark_w = max(1, round(_LOWER_MARK_W_FRAC * canvas_size[0]))
        lower_pulse_h = max(1, round(_LOWER_PULSE_H_FRAC * canvas_size[1]))
        lower_total_w = max(10, round(_LOWER_TOTAL_WIDTH_FRAC * canvas_size[0]))
        lower_component_w = lower_total_w
        lower_component_h = max(lower_pulse_h, rasterize_nnj_mark(target_width=lower_mark_w).height)

        lower_placement, _box, lower_attempts = _evaluate_placements(
            photo, component_size=(lower_component_w, lower_component_h),
            candidates=(ComponentPlacement.LOWER_RIGHT, ComponentPlacement.LOWER_LEFT,
                        ComponentPlacement.UPPER_RIGHT, ComponentPlacement.UPPER_LEFT),
            inset=inset, subject_bbox=subject_bbox,
        )
        lower_image = _build_lower_signature_image(canvas_size, lower_placement, inset) if lower_placement is not ComponentPlacement.OMITTED else None
        lower_disabled_reason = None

    # VISUAL-SINGLE-BRAND-MARK-1 §6: mutual exclusion with the lower signature - the upper mark is
    # only ever evaluated when the lower signature ended up OMITTED (unsafe everywhere it tried,
    # or force-disabled above). A lower signature that WAS placed already supplies this image's
    # one canonical mark; scoring the upper mark's own corners in that case would only ever risk
    # adding a second one.
    upper_disabled_reason: str | None = None
    if lower_placement is not ComponentPlacement.OMITTED:
        upper_placement = ComponentPlacement.OMITTED
        upper_attempts: tuple[RegionScore, ...] = ()
        upper_image = None
        upper_disabled_reason = "single_brand_mark_contract_lower_signature_already_placed"
    else:
        upper_mark_w = max(1, round(_UPPER_MARK_W_FRAC * canvas_size[0]))
        upper_mark_h = rasterize_nnj_mark(target_width=upper_mark_w).height
        upper_placement, _ubox, upper_attempts = _evaluate_placements(
            photo, component_size=(upper_mark_w, upper_mark_h),
            candidates=(ComponentPlacement.UPPER_RIGHT, ComponentPlacement.UPPER_LEFT),
            inset=inset, subject_bbox=subject_bbox,
        )
        upper_image = _build_upper_mark_image(canvas_size, upper_placement, inset) if upper_placement is not ComponentPlacement.OMITTED else None

    return MasterNewsBrandingDecision(
        upper_mark=ComponentDecision(
            placement=upper_placement, image=upper_image, attempts=upper_attempts,
            disabled_reason=upper_disabled_reason,
        ),
        lower_signature=ComponentDecision(
            placement=lower_placement, image=lower_image, attempts=lower_attempts,
            disabled_reason=lower_disabled_reason,
        ),
        canvas_size=canvas_size,
    )


def composite_master_news_decision(
    photo_rgba: Image.Image, decision: MasterNewsBrandingDecision,
) -> Image.Image:
    """Composite a `select_master_news_branding()` decision's own canvas-sized layers onto
    `photo_rgba` (which MUST already be the exact size `decision` was computed for). The single
    shared compositing step: `apply_master_news_branding()` calls it after its 1280x720 fit, and
    `brand_renderer.render_breaking_frame()` calls it on a NATIVE-size photo (BREAKING is the same
    restrained NEWS family, not a full-frame band) - one code path, no drift
    (VISUAL-RENDERER-RECONCILIATION-1 §7). Mutual exclusion of the two components (the single-
    brand-mark invariant) is already enforced inside `select_master_news_branding()`."""
    branded = photo_rgba.copy()
    if decision.lower_signature.image is not None:
        branded.alpha_composite(decision.lower_signature.image)
    if decision.upper_mark.image is not None:
        branded.alpha_composite(decision.upper_mark.image)
    return branded


_FINALIZED_MARKER_PREFIX = b"NNJ-FINALIZED-V1:"
_FINALIZED_MARKER_BRANDED = _FINALIZED_MARKER_PREFIX + b"BRANDED"
_FINALIZED_MARKER_NO_OVERLAY = _FINALIZED_MARKER_PREFIX + b"NO_OVERLAY"


def _read_finalized_marker(photo: Image.Image) -> bool | None:
    """Reads back the JPEG COM segment `apply_master_news_branding()` embeds in every output it
    produces (see below) - structural pipeline knowledge, never visual/OCR logo detection (spec's
    own explicit "do not rely on fragile visual OCR/logo detection as the primary idempotency
    mechanism" instruction). Returns `True` if the prior run placed a mark, `False` if it
    completed as NO_OVERLAY_SAFETY, `None` if the input carries no marker at all (never
    previously finalized by this function)."""
    comment = photo.info.get("comment")
    if comment == _FINALIZED_MARKER_BRANDED:
        return True
    if comment == _FINALIZED_MARKER_NO_OVERLAY:
        return False
    return None


def apply_master_news_branding(
    source_image_bytes: bytes, *, subject_bbox: BoundingBox | None = None, disable_lower_signature: bool = False,
    signature_style: str = SIGNATURE_STYLE_MARK_ONLY,
) -> tuple[bytes, MasterNewsBrandingDecision]:
    """Phase V2.10H - the ONE production compositing entry point for the NEWS family (NEWS,
    grouped carousels, RECAP media, the Final-Post-Review preview). Fits `source_image_bytes` to
    the 1280x720 canvas, evaluates and composites exactly ONE canonical NNJ mark, and returns
    `(jpeg_bytes, decision)`.

    FOUNDER-VISUAL-POLISH-2 §2/§4: `signature_style` defaults to MARK_ONLY - the board's restrained
    "лёгкий фирменный водяной знак": one small mark in the least-busy safe corner, no connecting
    line, no pulse (the earlier fused line+pulse read as an intrusive watermark competing with the
    source photo - Founder verdict NEWS=FAIL). Pass `signature_style="fused"` only where the older
    line+pulse+mark unit is explicitly wanted. Works identically for an ORIGINAL_SOURCE
    image or a successfully-recomposed one - the caller decides which bytes to pass in; this
    function has no opinion about where they came from. `disable_lower_signature` - see
    select_master_news_branding()'s own docstring (Phase V2.10I §7).

    IDEMPOTENT (VISUAL-SINGLE-BRAND-MARK-1 §6/§7): every output this function produces carries a
    JPEG comment marker recording whether a mark was actually placed. A repeat call on bytes this
    SAME function already produced detects that marker immediately and returns the input
    completely unchanged - no re-evaluation, no re-compositing, no second mark, regardless of how
    many times it is called or what `disable_lower_signature`/`subject_bbox` the repeat call
    passes. This is the one real choke point every caller (services/media_finalizer.py,
    worker/content_cycle.py, services/final_post_review_notifier.py) already goes through, so the
    guarantee is automatic for all of them without any call-site change."""
    opened = Image.open(io.BytesIO(source_image_bytes))
    prior_had_overlay = _read_finalized_marker(opened)
    if prior_had_overlay is not None:
        skip = ComponentDecision(placement=ComponentPlacement.OMITTED, image=None, attempts=())
        decision = MasterNewsBrandingDecision(
            upper_mark=skip, lower_signature=skip, canvas_size=opened.size,
            already_finalized=True, already_finalized_had_overlay=prior_had_overlay,
        )
        return source_image_bytes, decision

    photo = opened.convert("RGBA")
    photo_fit = _fit_photo_to_canvas(photo, (_CANVAS_W, _CANVAS_H))

    decision = select_master_news_branding(
        photo_fit, subject_bbox=subject_bbox, disable_lower_signature=disable_lower_signature,
        signature_style=signature_style,
    )

    branded = composite_master_news_decision(photo_fit, decision)
    buf = io.BytesIO()
    has_mark = decision.degradation_mode != "no_overlay"
    marker = _FINALIZED_MARKER_BRANDED if has_mark else _FINALIZED_MARKER_NO_OVERLAY
    branded.convert("RGB").save(buf, "JPEG", quality=95, comment=marker)
    return buf.getvalue(), decision
