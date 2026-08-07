"""Phase 19 M8: services.source_intelligence.classify_source_role() - pure, deterministic,
no DB/network."""
from __future__ import annotations

from services.source_intelligence import (
    POSSIBLE_AGGREGATION,
    POSSIBLE_ANALYSIS,
    POSSIBLE_CONFIRMATION,
    POSSIBLE_ORIGINAL,
    UNKNOWN,
    classify_source_role,
)


def test_first_in_story_is_possible_original() -> None:
    role = classify_source_role(is_first_in_story=True, match_type="new_story", title="Acme launches widget")
    assert role == POSSIBLE_ORIGINAL


def test_semantic_duplicate_is_possible_confirmation() -> None:
    role = classify_source_role(
        is_first_in_story=False, match_type="semantic_duplicate", title="Acme launches widget, report says",
    )
    assert role == POSSIBLE_CONFIRMATION


def test_supporting_source_is_possible_confirmation() -> None:
    role = classify_source_role(
        is_first_in_story=False, match_type="supporting_source", title="Acme confirms widget launch",
    )
    assert role == POSSIBLE_CONFIRMATION


def test_story_update_is_possible_aggregation() -> None:
    role = classify_source_role(
        is_first_in_story=False, match_type="story_update", title="Acme widget gets new features",
    )
    assert role == POSSIBLE_AGGREGATION


def test_uncertain_match_is_unknown() -> None:
    role = classify_source_role(
        is_first_in_story=False, match_type="uncertain_match", title="Something related to Acme",
    )
    assert role == UNKNOWN


def test_missing_match_type_is_unknown() -> None:
    role = classify_source_role(is_first_in_story=False, match_type=None, title="Some other headline")
    assert role == UNKNOWN


def test_analysis_keyword_wins_even_when_first_in_story() -> None:
    role = classify_source_role(
        is_first_in_story=True, match_type="new_story", title="Opinion: why Acme's widget matters",
    )
    assert role == POSSIBLE_ANALYSIS


def test_analysis_keyword_wins_over_confirmation() -> None:
    role = classify_source_role(
        is_first_in_story=False, match_type="semantic_duplicate", title="Explained: Acme's widget launch",
    )
    assert role == POSSIBLE_ANALYSIS


def test_never_returns_a_definitive_unhedged_label() -> None:
    """Every possible return value must start with POSSIBLE_ or be UNKNOWN - never a bare,
    unhedged factual claim like "ORIGINAL_SOURCE" or "CONFIRMED"."""
    cases = [
        (True, "new_story", "A headline"),
        (False, "semantic_duplicate", "A headline"),
        (False, "supporting_source", "A headline"),
        (False, "story_update", "A headline"),
        (False, "uncertain_match", "A headline"),
        (False, None, "A headline"),
    ]
    for is_first, match_type, title in cases:
        role = classify_source_role(is_first_in_story=is_first, match_type=match_type, title=title)
        assert role.startswith("POSSIBLE_") or role == UNKNOWN
