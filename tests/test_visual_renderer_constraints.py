"""PRODUCTION-SOURCE-RECONCILIATION-1B §14/§15: get_current_renderer_constraints() must describe
the real, confirmed-live renderer (services/nnj_master_news_overlay.py + services/
brand_renderer.py::render_data_card()), never the non-live services/nnj_overlay_contract.py."""
from __future__ import annotations

from services.brand_renderer import _CANVAS_H, _CANVAS_W
from services.visual_renderer_constraints import get_current_renderer_constraints


def test_summary_names_the_real_canvas_size() -> None:
    summary = get_current_renderer_constraints()
    assert f"{_CANVAS_W}x{_CANVAS_H}" in summary


def test_summary_describes_both_news_and_data_placement_rules() -> None:
    summary = get_current_renderer_constraints()
    assert "NEWS/BREAKING" in summary
    assert "DATA" in summary
    assert "OMITTED" in summary  # NEWS/BREAKING may omit branding entirely - never forced
    assert "guaranteed-branding fallback" in summary  # DATA never ships with zero branding


def test_summary_never_mentions_the_non_live_overlay_contract() -> None:
    """nnj_overlay_contract.py is confirmed non-live (off-by-default editorial_recomposition_mode)
    - this summary must never cite it as though it were the real renderer."""
    summary = get_current_renderer_constraints()
    assert "overlay_contract" not in summary.lower()
    assert "candidate c" not in summary.lower()


def test_summary_inset_percentage_matches_the_real_live_constant() -> None:
    """Proof this is a live derivation, not a hand-typed number: the percentage in the summary
    must equal the real _SAFE_INSET_FRAC MASTER NEWS/DATA actually render with, recomputed here
    independently rather than copy-pasted from the module under test."""
    from services.nnj_master_news_overlay import _SAFE_INSET_FRAC

    summary = get_current_renderer_constraints()
    expected_pct = round(_SAFE_INSET_FRAC * 100, 1)
    assert f"{expected_pct}%" in summary
