"""INSTAGRAM GROWTH ENGINE v2, spec §47: Creative Fatigue V2 - graded, dimension-agnostic fatigue."""
from __future__ import annotations

from services.instagram_content_brain import FatigueState, evaluate_fatigue_state
from services.instagram_hook_intelligence import evaluate_hook_fatigue_state


def test_fatigue_state_is_graded_across_any_dimension() -> None:
    for dimension in ("format", "topic", "cta", "trend_mechanic", "campaign_angle", "series", "visual_family"):
        assert evaluate_fatigue_state(dimension=dimension, repetition_count=1, window_days=14) == FatigueState.FRESH
        assert evaluate_fatigue_state(dimension=dimension, repetition_count=10, window_days=14) == FatigueState.OVERUSED


def test_hook_family_wrapper_matches_the_generic_scale() -> None:
    assert evaluate_hook_fatigue_state(repetition_count=4, window_days=14) == evaluate_fatigue_state(
        dimension="hook_family", repetition_count=4, window_days=14,
    )
