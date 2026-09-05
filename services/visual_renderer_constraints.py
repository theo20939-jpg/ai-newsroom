"""PRODUCTION-SOURCE-RECONCILIATION-1B §14/§15: a truthful, read-only summary of the CURRENT,
CONFIRMED-LIVE renderer's own safe-zone/placement behavior, for `VisualDirectorContext.
renderer_constraints_summary` (services/visual_creative_direction.py) - previously always a
caller-supplied `str` defaulting to the literal `"unknown"` (services/visual_design_loop.py), with
no real derivation from the renderer at all.

`services/nnj_overlay_contract.py` is NOT this codebase's live overlay geometry source - its own
module docstring says so explicitly ("NOT YET wired into services/brand_renderer.py or worker/
content_cycle.py - this is proof-phase infrastructure only, pending user visual approval of the
canonical derivative itself"), and its manifest asset does not exist in either production image
(confirmed in docs/production_source_reconciliation_v1.md). It is reachable only via
services/nnj_candidate_c_contract.py -> services/editorial_recomposition.py, gated by
`editorial_recomposition_mode="off"` (default, never overridden in production) - a non-live,
off-by-default experimental "Candidate C" feature, not the renderer this codebase actually ships.

The real, confirmed-live geometry lives in code, not a JSON manifest:
- `services/nnj_master_news_overlay.py::apply_master_news_branding()` - "the ONE production
  compositing entry point for the locked MASTER NEWS contract" (that function's own docstring),
  confirmed called from `worker/content_cycle.py` for every real NEWS/BREAKING send. Every
  fraction below is read directly from that module's own live constants - never re-typed/
  hand-derived numbers that could silently drift from what is actually rendered.
- `services/brand_renderer.py::render_data_card()` - DATA's own bottom-only signature, confirmed
  live this same reconciliation phase (the MEDIA-PROD-1 guaranteed-branding-fallback recovery).
  Reuses MASTER's own `_CANVAS_W`/`_CANVAS_H`/`_SAFE_INSET_FRAC` constants directly (imported, not
  duplicated) so DATA and NEWS/BREAKING always describe the same canvas/inset.

This module has NO authority over placement - it only reports, in prose, what the real renderers
already decide for themselves. The Visual Design Director never gets to choose a corner; it only
learns, after the fact via this summary, what constraints the deterministic renderer already
enforces."""
from __future__ import annotations

from services.brand_renderer import _DATA_SIGNATURE_CANDIDATE_PLACEMENTS
from services.nnj_master_news_overlay import (
    _CANVAS_H,
    _CANVAS_W,
    _LOWER_TOTAL_WIDTH_FRAC,
    _SAFE_INSET_FRAC,
    _UPPER_MARK_W_FRAC,
)

_MASTER_LOWER_CANDIDATE_ORDER = "lower-right, then lower-left, then upper-right, then upper-left"
_MASTER_UPPER_CANDIDATE_ORDER = "upper-right, then upper-left"
_DATA_CANDIDATE_ORDER = ", then ".join(p.value.replace("_", "-") for p in _DATA_SIGNATURE_CANDIDATE_PLACEMENTS)


def get_current_renderer_constraints() -> str:
    """A stable, read-only, code-derived summary of the current canonical renderer's own
    safe-zone/placement behavior - see this module's own docstring for exactly which functions it
    describes and why `nnj_overlay_contract.py` is deliberately not one of them. Every number is
    computed from the real live constants at call time, so this string can never drift from what
    `apply_master_news_branding()`/`render_data_card()` actually do."""
    inset_pct = round(_SAFE_INSET_FRAC * 100, 1)
    lower_width_pct = round(_LOWER_TOTAL_WIDTH_FRAC * 100)
    upper_width_pct = round(_UPPER_MARK_W_FRAC * 100)
    return (
        f"Canvas {_CANVAS_W}x{_CANVAS_H}, safe edge inset {inset_pct}% of canvas width. "
        f"NEWS/BREAKING (apply_master_news_branding): a lower brand signature "
        f"(~{lower_width_pct}% of canvas width) and an independent upper mark "
        f"(~{upper_width_pct}% of canvas width) are each placed only in a corner whose real pixels "
        f"pass an edge-density/visibility/detail-risk safety check and do not collide with any "
        f"known subject bounding box; corners are tried in order {_MASTER_LOWER_CANDIDATE_ORDER} "
        f"for the lower signature and {_MASTER_UPPER_CANDIDATE_ORDER} for the upper mark - either "
        f"or both are OMITTED entirely if no corner is safe (never forced onto unsafe content). "
        f"DATA (render_data_card): a single bottom-only signature is tried in order "
        f"{_DATA_CANDIDATE_ORDER} only (never an upper corner); if every corner fails the same "
        f"safety check, a small, fixed-footprint guaranteed-branding fallback still renders in the "
        f"lower-right corner on an opaque scrim (never zero branding). A compact stat block is "
        f"then placed in whichever remaining safe corner does not collide with the signature's own "
        f"drawn footprint, or omitted if none qualifies. No renderer ever covers the visual center "
        f"of the frame with any branding element."
    )
