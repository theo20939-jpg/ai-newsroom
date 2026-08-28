"""Phase V2.4D (docs/nnj_source_faithful_editorial_visual_recomposition_v1.md): the single
source-of-truth geometry contract for the canonical white NNJ overlay - the AUTHORITATIVE
successor to Phase V2.4C's own derivative, which was explicitly REJECTED (its crop-only 4:5->16:9
adaptation produced a ~47%-of-frame protected zone, far heavier than the approved V1 minimal
design). V2.4D's own product decision: a genuine 16:9 FORMAT DERIVATIVE (adapted scale/spacing,
not a raw pixel crop) with an authoritative bottom-14% protected band. See
`scripts/nnj_v2_4d_canonical_16x9_overlay.py` for exactly how the derivative/manifest below were
produced from the real `universal_minimal_01.png` pulse pixels.

Renderer placement, the recomposition prompt's protected-zone clause, and offline collision
validation all derive from the SAME measured geometry - never three separately hand-maintained
copies of the same coordinates (V2.4C's own Stage 7 instruction, still authoritative). That single
source of truth is `canonical_overlay_white_16x9_manifest.json`, shipped alongside the canonical
derivative PNG it describes - both produced once, directly from real, measured overlay pixels
(never hand-invented numbers). Every field this module returns is loaded from that JSON.

NOT YET wired into `services/brand_renderer.py` or `worker/content_cycle.py` - this is proof-phase
infrastructure only, pending user visual approval of the canonical derivative itself."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_ASSET_DIR = (
    Path(__file__).resolve().parent.parent / "assets" / "brand" / "newsroom_visuals" / "v2_4d_canonical_16x9_overlay"
)
CANONICAL_OVERLAY_WHITE_16X9_PATH = _DEFAULT_ASSET_DIR / "canonical_overlay_white_16x9.png"
CANONICAL_OVERLAY_WHITE_16X9_MANIFEST_PATH = _DEFAULT_ASSET_DIR / "canonical_overlay_white_16x9_manifest.json"

BoundingBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class SafeZoneGeometry:
    """Pixel-space geometry, in the canonical derivative's own canvas coordinates."""

    overlay_id: str
    canvas_width: int
    canvas_height: int
    protected_y_start: int
    protected_y_end: int
    protected_fraction: float
    line_y: int
    pulse_bbox: BoundingBox
    logo_bbox: BoundingBox
    minimum_subject_clearance_px: int

    @property
    def clearance_y_start(self) -> int:
        """The Y coordinate a subject's own bounding box must stay entirely above - the protected
        zone's own top edge minus the disclosed clearance margin."""
        return max(0, self.protected_y_start - self.minimum_subject_clearance_px)

    def normalized(self) -> dict[str, float]:
        """0-1 normalized coordinates - what `build_overlay_aware_prompt_clause()` actually uses,
        since the recomposition prompt is provider-neutral and must never assume a fixed pixel
        canvas size."""
        return {
            "protected_y_start_frac": self.clearance_y_start / self.canvas_height,
            "protected_y_end_frac": self.protected_y_end / self.canvas_height,
        }


def load_safe_zone_geometry(
    manifest_path: Path = CANONICAL_OVERLAY_WHITE_16X9_MANIFEST_PATH,
) -> SafeZoneGeometry:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return SafeZoneGeometry(
        overlay_id=data["overlay_id"],
        canvas_width=data["canvas_width"],
        canvas_height=data["canvas_height"],
        protected_y_start=data["protected_y_start"],
        protected_y_end=data["protected_y_end"],
        protected_fraction=data["protected_fraction"],
        line_y=data["line_y"],
        pulse_bbox=tuple(data["pulse_bbox"]),  # type: ignore[arg-type]
        logo_bbox=tuple(data["logo_bbox"]),  # type: ignore[arg-type]
        minimum_subject_clearance_px=data["minimum_subject_clearance_px"],
    )


def build_overlay_aware_prompt_clause(safe_zone: SafeZoneGeometry) -> str:
    """The ONE addition to the canonical recomposition prompt - the existing factual-fidelity
    rules in `services/editorial_recomposition.py::build_recomposition_prompt()` are never
    rewritten; this clause is appended, never replacing anything. Parameterized entirely from the
    measured safe-zone geometry - never a separately hardcoded percentage string."""
    protected_pct = round(safe_zone.protected_fraction * 100)
    return (
        f"OVERLAY SAFE ZONE: Reserve the lower {protected_pct}% of the image as clean branding "
        "space. Keep the primary product, any hand holding it, faces, important source logos, "
        "source text, and factual objects above this protected area. If necessary, reposition or "
        "slightly scale the complete factual subject group while preserving its geometry and "
        "relationships. Do not delete real foreground elements merely to clear the branding area."
    )


def check_collision(subject_bbox: BoundingBox, safe_zone: SafeZoneGeometry) -> bool:
    """Pure geometry only - no ML/vision classifier. `subject_bbox` is a caller-supplied
    (x0, y0, x1, y1) bounding box, in the same canvas-coordinate space as `safe_zone`. Returns True
    (COLLISION) iff the subject box's own Y-extent intersects the clearance-adjusted protected
    band at all."""
    _x0, y0, _x1, y1 = subject_bbox
    return y1 > safe_zone.clearance_y_start and y0 < safe_zone.protected_y_end
