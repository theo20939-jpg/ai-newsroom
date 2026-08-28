"""Phase V2.4G, Stage 3 (extended by Phase V2.5) - the single source-of-truth loader for the
LOCKED Candidate C overlay geometry (the user's own explicit product decision, after visually
comparing V2.4F's A/B/C candidates, then approving the V2.4G overlay-aware Gemini result). Reads
ONLY the two files persisted once by `scripts/nnj_v2_4g_lock_candidate_c.py`
(`candidate_c_overlay.png` + `manifest.json`) - never recomputes pixel geometry, never imports
anything from `scripts/` (the wrong dependency direction for a `services/` module, per this
codebase's own established convention - see services/editorial_recomposition.py's own docstring).

The prompt's protected-zone clause, collision severity classification, AND the final overlay
compositing step all read from this one module - never three separately hand-maintained copies
of the same coordinates (the same "single source of truth" discipline `services/
nnj_overlay_contract.py` established in V2.4D, applied here to the now-locked Candidate C).

Phase V2.5 wires this module's `apply_candidate_c_branding()` into `worker/content_cycle.py` as
the branding treatment for any NEWS image that Gemini successfully recomposed - gated entirely on
`settings.editorial_recomposition_mode` (default `"off"`) and `recomposition_result.
used_recomposed_image`, so nothing here executes in production while that mode stays off.
`services/brand_renderer.py` itself remains completely untouched - the legacy category/NP-code/
pulse/badge treatment there is a separate, still-default treatment for every other presentation
type and for NEWS images recomposition did not touch. Never calls Gemini or OpenAI."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image

_ASSET_DIR = (
    Path(__file__).resolve().parent.parent / "assets" / "brand" / "newsroom_visuals" / "candidate_c_locked"
)
CANDIDATE_C_OVERLAY_PNG_PATH = _ASSET_DIR / "candidate_c_overlay.png"
CANDIDATE_C_MANIFEST_PATH = _ASSET_DIR / "manifest.json"

BoundingBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class CandidateCGeometry:
    """Pixel-space geometry, in the locked Candidate C overlay's own 1280x720 canvas
    coordinates."""

    canvas_width: int
    canvas_height: int
    overlay_start_x: int
    overlay_end_x: int
    line_y: int
    pulse_bbox: BoundingBox
    logo_bbox: BoundingBox
    zone_x_start: int
    zone_y_start: int
    zone_x_end: int
    zone_y_end: int
    clearance: int

    @property
    def clearance_x_start(self) -> int:
        return max(0, self.zone_x_start - self.clearance)

    @property
    def clearance_y_start(self) -> int:
        return max(0, self.zone_y_start - self.clearance)


def load_candidate_c_geometry(manifest_path: Path = CANDIDATE_C_MANIFEST_PATH) -> CandidateCGeometry:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return CandidateCGeometry(
        canvas_width=data["canvas_width"],
        canvas_height=data["canvas_height"],
        overlay_start_x=data["overlay_start_x"],
        overlay_end_x=data["overlay_end_x"],
        line_y=data["line_y"],
        pulse_bbox=tuple(data["pulse_bbox"]),  # type: ignore[arg-type]
        logo_bbox=tuple(data["logo_bbox"]),  # type: ignore[arg-type]
        zone_x_start=data["zone_x_start"],
        zone_y_start=data["zone_y_start"],
        zone_x_end=data["zone_x_end"],
        zone_y_end=data["zone_y_end"],
        clearance=data["clearance"],
    )


def load_candidate_c_overlay_image(png_path: Path = CANDIDATE_C_OVERLAY_PNG_PATH) -> Image.Image:
    """A fresh RGBA load every call - no module-level caching, so the caller always gets the real
    persisted pixels, never a stale in-process copy."""
    return Image.open(png_path).convert("RGBA")


def build_overlay_aware_prompt_clause(geometry: CandidateCGeometry) -> str:
    """The ONE addition to the canonical recomposition prompt
    (`services/editorial_recomposition.py::build_recomposition_prompt()`, reused unchanged, never
    rewritten) - describes the LOCKED Candidate C protected region, not a full-width/full-bottom
    band (V2.4D's own rejected, too-broad rule). Parameterized entirely from the locked geometry -
    never a separately hardcoded coordinate string."""
    return (
        f"The final {geometry.canvas_width}x{geometry.canvas_height} editorial image will receive "
        "a deterministic branding element in the lower-right protected region.\n\n"
        f"Protected region: x = {geometry.zone_x_start}..{geometry.zone_x_end}, "
        f"y = {geometry.zone_y_start}..{geometry.zone_y_end}.\n\n"
        f"Keep the primary factual foreground subject outside this region with at least "
        f"{geometry.clearance}px visual clearance.\n\n"
        "The source contains an iPhone held by a real hand. Treat the iPhone + hand as one "
        "factual foreground group.\n\n"
        "You may:\n"
        "- reposition the complete group\n"
        "- slightly rescale it\n"
        "- make a small physically-plausible rotation\n"
        "- change/extend the background\n\n"
        "You must NOT:\n"
        "- erase the hand\n"
        "- crop away the hand merely to clear the branding region\n"
        "- alter finger count or grip\n"
        "- alter the iPhone\n"
        "- change camera geometry\n"
        "- invent hardware\n"
        "- change Apple branding\n\n"
        "Create clean non-essential background inside the protected branding region."
    )


def check_collision(subject_bbox: BoundingBox, geometry: CandidateCGeometry) -> bool:
    """Pure X+Y rectangle intersection against the zone PLUS its disclosed clearance buffer -
    never Y-only (V2.4D's own rejected behavior would treat a compact right-side zone as if it
    protected the entire row). Kept for backward compatibility with the V2.4G canary script;
    `assess_collision()` below is the more precise, two-level replacement Phase V2.5 introduces -
    prefer it for any new call site."""
    sx0, sy0, sx1, sy1 = subject_bbox
    zx0, zy0 = geometry.clearance_x_start, geometry.clearance_y_start
    zx1, zy1 = geometry.zone_x_end, geometry.zone_y_end
    return sx0 < zx1 and sx1 > zx0 and sy0 < zy1 and sy1 > zy0


class CollisionSeverity(str, Enum):
    """Phase V2.5 Stage 3 - the V2.4G result exposed that a single boolean collision flag
    conflates two very different situations: the subject actually touching the rendered overlay
    pixels (a real problem) vs. the subject merely sitting inside the disclosed 20px safety
    margin without touching anything real (a cosmetic near-miss, not a defect). Two levels,
    never collapsed back into one."""

    HARD_COLLISION = "hard_collision"
    SOFT_CLEARANCE_WARNING = "soft_clearance_warning"
    CLEAR = "clear"


@dataclass(frozen=True)
class CollisionAssessment:
    severity: CollisionSeverity
    hard_collision: bool
    soft_clearance_warning: bool
    # The measured gap, in px, between the subject's own edge and the zone's literal edge - only
    # populated when the subject's Y-range overlaps the zone's Y-range and the subject sits
    # entirely to one side in X (the expected relationship for this compact right-side design,
    # and the only case in which "distance to the zone" has one unambiguous meaning). `None` when
    # not measurable in that sense (module docstring's own "record where measurable" instruction -
    # never a fabricated number) or when severity is HARD_COLLISION (the gap is negative/zero,
    # not a meaningful clearance figure).
    approx_clearance_px: int | None


def _rects_intersect(a: BoundingBox, b: BoundingBox) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def assess_collision(subject_bbox: BoundingBox, geometry: CandidateCGeometry) -> CollisionAssessment:
    """The two-level classification Phase V2.5 Stage 3 requires. HARD_COLLISION: the subject
    intersects the actual rendered Candidate C zone (x=zone_x_start..zone_x_end,
    y=zone_y_start..zone_y_end) - a real defect, must fail open. SOFT_CLEARANCE_WARNING: no
    literal intersection, but the subject enters the zone's disclosed clearance buffer - a
    disclosed near-miss, never a rejection reason on its own. CLEAR: the subject stays outside
    the zone and its full clearance buffer.

    Verified against the real V2.4G measurement: subject_bbox right edge at x=815 (11px short of
    zone_x_start=826, 9px inside the 20px clearance buffer) classifies as SOFT_CLEARANCE_WARNING
    with approx_clearance_px=11 - exactly the phase's own worked example."""
    zone_bbox = (geometry.zone_x_start, geometry.zone_y_start, geometry.zone_x_end, geometry.zone_y_end)
    if _rects_intersect(subject_bbox, zone_bbox):
        return CollisionAssessment(CollisionSeverity.HARD_COLLISION, True, False, None)

    sx0, sy0, sx1, sy1 = subject_bbox
    zx0, zy0, zx1, zy1 = zone_bbox
    y_overlaps = sy0 < zy1 and sy1 > zy0
    approx_clearance_px: int | None = None
    if y_overlaps and sx1 <= zx0:
        approx_clearance_px = zx0 - sx1
    elif y_overlaps and sx0 >= zx1:
        approx_clearance_px = sx0 - zx1

    clearance_zone_bbox = (geometry.clearance_x_start, geometry.clearance_y_start, zone_bbox[2], zone_bbox[3])
    if _rects_intersect(subject_bbox, clearance_zone_bbox):
        return CollisionAssessment(CollisionSeverity.SOFT_CLEARANCE_WARNING, False, True, approx_clearance_px)

    return CollisionAssessment(CollisionSeverity.CLEAR, False, False, approx_clearance_px)


def _fit_photo_to_canvas(photo: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Identical cover-crop-to-canvas logic already proven in V2.4F/V2.4G's own scripts -
    duplicated here (not imported from `scripts/`, per this module's own dependency-direction
    rule) since it is a generic, parameter-free geometric utility, not Candidate C coordinate
    data - there is nothing here for a second copy to silently drift out of sync with."""
    target_w, target_h = size
    scale = max(target_w / photo.width, target_h / photo.height)
    scaled = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.Resampling.LANCZOS)
    x0 = (scaled.width - target_w) // 2
    y0 = (scaled.height - target_h) // 2
    return scaled.crop((x0, y0, x0 + target_w, y0 + target_h))


def apply_candidate_c_branding(source_image_bytes: bytes) -> bytes:
    """Phase V2.5 Stage 8 - the final branding treatment for a NEWS image Gemini successfully
    recomposed: fit to the locked 1280x720 canvas, then alpha-composite the real, locked
    Candidate C overlay pixels (real pulse/line pixels + canonical NNJ logo, unchanged since
    V2.4G's user-approved result) on top. This is a REPLACEMENT for
    `services.brand_renderer.render_branded_media()`'s legacy category/NP-code/bottom-left-pulse/
    red-badge NEWS treatment for this one path, never an additional layer on top of it - the
    caller must choose exactly one. Returns JPEG bytes; never raises for a decodable input (the
    caller is responsible for catching failures at the fail-open boundary, mirroring
    `render_branded_media()`'s own contract)."""
    photo = Image.open(io.BytesIO(source_image_bytes)).convert("RGBA")
    geometry = load_candidate_c_geometry()
    photo_fit = _fit_photo_to_canvas(photo, (geometry.canvas_width, geometry.canvas_height))
    overlay = load_candidate_c_overlay_image()
    branded = photo_fit.copy()
    branded.alpha_composite(overlay)
    buf = io.BytesIO()
    branded.convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue()
