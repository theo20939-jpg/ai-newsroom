"""INSTAGRAM GROWTH ENGINE v2, spec §67: Hook Intelligence tests."""
from __future__ import annotations

from services.instagram_content_brain import EvidenceStage, PerformancePattern
from services.instagram_format_director import ContentFormat
from services.instagram_hook_intelligence import (
    FatigueState,
    Hook,
    HookFamily,
    evaluate_hook_evidence,
    evaluate_hook_fatigue,
    evaluate_hook_fatigue_state,
    recommend_hooks_for_objective,
)
from services.instagram_objectives import ContentObjective


def test_hook_family_taxonomy_is_valid_enum() -> None:
    assert HookFamily.CONTRARIAN.value == "contrarian"
    assert len(set(HookFamily)) == 14


def test_hook_objective_and_format_fit() -> None:
    hook = Hook(
        family=HookFamily.QUESTION, mechanic="open with a direct question", objective_fit=[ContentObjective.COMMENTS],
        format_fit=[ContentFormat.SINGLE, ContentFormat.CAROUSEL],
    )
    recommended = recommend_hooks_for_objective([hook], objective=ContentObjective.COMMENTS, content_format=ContentFormat.SINGLE)
    assert hook in recommended
    assert recommend_hooks_for_objective([hook], objective=ContentObjective.REACH) == []


def test_fatigued_hook_excluded_from_recommendations() -> None:
    hook = Hook(family=HookFamily.REVEAL, mechanic="x", objective_fit=[ContentObjective.REACH], fatigue=FatigueState.FATIGUED)
    assert recommend_hooks_for_objective([hook], objective=ContentObjective.REACH) == []


def test_hook_fatigue_state_is_graded_not_boolean() -> None:
    assert evaluate_hook_fatigue_state(repetition_count=1, window_days=14) == FatigueState.FRESH
    assert evaluate_hook_fatigue_state(repetition_count=4, window_days=14) == FatigueState.REPEATED
    assert evaluate_hook_fatigue_state(repetition_count=10, window_days=14) == FatigueState.OVERUSED


def test_hook_fatigue_only_tracks_hook_family_dimension() -> None:
    signal = evaluate_hook_fatigue(family=HookFamily.CURIOSITY_GAP, repetition_count=5, window_days=14)
    assert signal.dimension == "hook_family"
    assert signal.value == "curiosity_gap"


def test_thin_performance_sample_cannot_create_stable_hook_rule() -> None:
    thin = PerformancePattern(description="x", sample_size=2, effect_size=0.9, confidence=0.9, repeatability=1, baseline=0.1, recency_days=1)
    assert evaluate_hook_evidence(thin) == EvidenceStage.ANOMALY
