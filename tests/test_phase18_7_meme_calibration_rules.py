"""Phase 18.7 - Meme Intelligence Calibration Update tests (docs/
phase18_7_calibration_results.md).

Pure, DB-free unit tests. `services/meme_calibration_rules.py` never touches the database, the
network, or an LLM Gateway - it only wraps `services.meme_opportunity`'s own unmodified v1
functions with an additive calibration delta / context-exception filter.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database.models.news_event import EventCategory
from schemas.meme_calibration_rules import (
    MemeOpportunityAssessmentV2,
    SafetyContextExceptionResultV2,
)
from schemas.meme_opportunity import MemeOpportunityDecision
from services.meme_calibration_rules import (
    assess_meme_opportunity_v2,
    compute_calibration_delta,
    detect_sensitive_categories_v2,
)
from services.meme_opportunity import _READY_THRESHOLD, _REVIEW_THRESHOLD, detect_sensitive_categories

_NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)
_RESEARCH_OUTPUT: dict[str, list[str]] = {"facts": [], "gaps": []}


# ---------------------------------------------------------------------------
# Threshold drift guard - services/meme_calibration_rules.py imports v1's own private threshold
# constants directly rather than redefining them, specifically so it is structurally impossible
# for the two to silently drift apart. This test documents and pins the values themselves.
# ---------------------------------------------------------------------------


def test_v1_thresholds_are_55_and_35() -> None:
    assert _READY_THRESHOLD == 55
    assert _REVIEW_THRESHOLD == 35


# ---------------------------------------------------------------------------
# M1 - Finding 1: research-paper / academic-abstract penalty
# ---------------------------------------------------------------------------


def test_arxiv_paper_reduces_medium_score_to_low() -> None:
    title = "Existing multimodal agents use external memory"
    content = (
        "However, we propose a new benchmark for evaluation. We show that our method outperforms "
        "the baseline in this paper, achieving state-of-the-art results on the dataset."
    )
    result = assess_meme_opportunity_v2(
        title, content, EventCategory.AI, _NOW, _RESEARCH_OUTPUT, source_name="arXiv cs.CL", now=_NOW,
    )
    assert result.base_decision == MemeOpportunityDecision.REVIEW
    assert result.decision in (MemeOpportunityDecision.NOT_SUITABLE,)
    assert result.adjusted_composite_score < result.base_composite_score
    assert "research_paper:arxiv_source" in result.calibration_evidence


def test_technical_abstract_reduces_score_even_without_arxiv_source() -> None:
    delta, evidence = compute_calibration_delta(
        "however, this methodology relies on a new benchmark dataset for evaluation metric comparison",
        source_name="Some Blog",
    )
    assert delta < 0
    assert "research_paper:arxiv_source" not in evidence
    assert any(e.startswith("research_paper:") for e in evidence)


def test_research_paper_penalty_is_capped_at_30() -> None:
    text = (
        "however we propose we show that we demonstrate in this paper we present our approach "
        "methodology experiment dataset benchmark evaluation metric ablation study "
        "state-of-the-art sota outperforms baseline theorem proof equation hypothesis"
    )
    delta, evidence = compute_calibration_delta(text, source_name="arXiv cs.LG")
    assert delta == -30


def test_non_research_text_gets_no_research_penalty() -> None:
    delta, evidence = compute_calibration_delta("apple launched a new iphone today", source_name="TechCrunch")
    assert not any(e.startswith("research_paper:") for e in evidence)


# ---------------------------------------------------------------------------
# M1 - Finding 2: missing positive signals
# ---------------------------------------------------------------------------


def test_company_drama_increases_score() -> None:
    delta, evidence = compute_calibration_delta(
        "the company faces backlash after the launch failed to meet expectations", source_name=None,
    )
    assert delta > 0
    assert "positive_signal:company_drama" in evidence


def test_gaming_controversy_increases_score() -> None:
    delta, evidence = compute_calibration_delta(
        "the new update caused player backlash and fans furious over pricing complaints", source_name=None,
    )
    assert delta > 0
    assert "positive_signal:gaming_controversy" in evidence


def test_recognizable_brand_with_conflict_increases_score() -> None:
    delta, evidence = compute_calibration_delta(
        "nvidia faces backlash after the launch failed to meet expectations", source_name=None,
    )
    assert any(e.startswith("positive_signal:brand_conflict:nvidia") for e in evidence)
    assert delta > 0


def test_recognizable_brand_alone_without_conflict_gets_no_brand_bonus() -> None:
    delta, evidence = compute_calibration_delta("apple released a new iphone today", source_name=None)
    assert not any(e.startswith("positive_signal:brand_conflict") for e in evidence)


def test_human_emotion_signal_increases_score() -> None:
    delta, evidence = compute_calibration_delta(
        "workers were furious and disappointed after the announcement", source_name=None,
    )
    assert delta > 0
    assert "positive_signal:human_emotion" in evidence


def test_total_positive_delta_is_capped_at_25() -> None:
    text = (
        "frustrated furious stunned shocked disappointed thrilled excited backlash outcry "
        "went viral trending public outrage launch failed botched launch under fire faces "
        "backlash player backlash fans furious review bombed apple nvidia"
    )
    delta, _ = compute_calibration_delta(text, source_name=None)
    assert delta == 25


# ---------------------------------------------------------------------------
# M1 - calibration never overrides a hard v1 short-circuit
# ---------------------------------------------------------------------------


def test_sensitive_block_passes_through_v2_unchanged() -> None:
    result = assess_meme_opportunity_v2(
        "War crime accusations mount", "Investigators confirm a war crime took place.",
        EventCategory.TECH, _NOW, _RESEARCH_OUTPUT, now=_NOW,
    )
    assert result.base_decision == MemeOpportunityDecision.SENSITIVE_BLOCK
    assert result.decision == MemeOpportunityDecision.SENSITIVE_BLOCK
    assert result.calibration_score_delta == 0
    assert result.calibration_evidence == []


def test_insufficient_source_passes_through_v2_unchanged() -> None:
    result = assess_meme_opportunity_v2(
        "Short headline", None, EventCategory.UNKNOWN, _NOW, _RESEARCH_OUTPUT, now=_NOW,
    )
    assert result.base_decision == MemeOpportunityDecision.INSUFFICIENT_SOURCE
    assert result.decision == MemeOpportunityDecision.INSUFFICIENT_SOURCE
    assert result.calibration_score_delta == 0


# ---------------------------------------------------------------------------
# M3/M1 shared sensitivity scan - Finding 3: context exceptions (allowed cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "God of War is getting a new sequel next year",
    "Nvidia released a driver update supporting Gears of War: E-Day multiplayer beta",
    "Total War: Warhammer just got a huge balance patch",
])
def test_game_franchise_titles_are_not_blocked_for_war(text: str) -> None:
    base_categories, _ = detect_sensitive_categories(text.lower())
    assert "war" in base_categories  # confirms v1 itself would have blocked this
    result = detect_sensitive_categories_v2(text.lower())
    assert "war" not in result.categories
    assert any(e == "war:war" for e in result.suppressed_evidence)


def test_shooting_trajectory_is_not_blocked() -> None:
    text = "the game simulates realistic bullet shooting trajectory physics".lower()
    result = detect_sensitive_categories_v2(text)
    assert "crime_with_victim" not in result.categories


def test_process_died_is_not_blocked() -> None:
    text = "the background process died unexpectedly and was automatically restarted".lower()
    result = detect_sensitive_categories_v2(text)
    assert "death_or_tragedy" not in result.categories


def test_app_killed_in_background_is_not_blocked() -> None:
    text = "the app killed the background download task to save battery".lower()
    result = detect_sensitive_categories_v2(text)
    assert "death_or_tragedy" not in result.categories


# ---------------------------------------------------------------------------
# M3/M1 shared sensitivity scan - Finding 4: stay conservative (blocked cases)
# ---------------------------------------------------------------------------


def test_real_shooting_incident_stays_blocked() -> None:
    text = "a shooting incident downtown left one victim dead, police said".lower()
    result = detect_sensitive_categories_v2(text)
    assert "crime_with_victim" in result.categories


def test_child_abuse_article_stays_blocked() -> None:
    text = "authorities investigate a child abuse case at the local school".lower()
    result = detect_sensitive_categories_v2(text)
    assert "minors_safety" in result.categories
    assert result.suppressed_evidence == []


def test_real_disaster_stays_blocked() -> None:
    text = "the earthquake left thousands homeless across the region".lower()
    result = detect_sensitive_categories_v2(text)
    assert "disaster" in result.categories
    assert result.suppressed_evidence == []


def test_real_death_event_stays_blocked() -> None:
    text = "the actor died yesterday, his family confirmed the tragedy".lower()
    result = detect_sensitive_categories_v2(text)
    assert "death_or_tragedy" in result.categories


def test_war_override_marker_cancels_the_exception() -> None:
    text = "gears of war fans watch as russia launched an invasion in the region".lower()
    result = detect_sensitive_categories_v2(text)
    assert "war" in result.categories
    assert result.suppressed_evidence == []


def test_died_override_marker_cancels_the_exception() -> None:
    text = "the process died - he was found dead at the hospital after the incident".lower()
    result = detect_sensitive_categories_v2(text)
    assert "death_or_tragedy" in result.categories


def test_partial_suppression_keeps_category_when_another_phrase_still_matches() -> None:
    """The background process died (exempted) in the same story as a real reported death - the
    category must still fire on the second, non-exempted phrase match."""
    text = "the server process died during the outage; separately, a worker was found dead nearby".lower()
    result = detect_sensitive_categories_v2(text)
    assert "death_or_tragedy" in result.categories
    assert "death_or_tragedy:died" in result.suppressed_evidence
    assert any(e.startswith("death_or_tragedy:") and e != "death_or_tragedy:died" for e in result.evidence)


# ---------------------------------------------------------------------------
# Previously-reported false positives (Phase 18.5 M4 §6) - real regression guards
# ---------------------------------------------------------------------------


def test_gears_of_war_nvidia_driver_false_positive_is_fixed() -> None:
    """The exact real, previously-flagged Phase 18.5 false positive."""
    text = (
        "Nvidia выпустила драйвер с поддержкой Halo: Campaign Evolved и беты мультиплеера "
        "Gears of War: E-Day"
    ).lower()
    base_categories, _ = detect_sensitive_categories(text)
    assert "war" in base_categories
    result = detect_sensitive_categories_v2(text)
    assert "war" not in result.categories


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_opportunity_assessment_v2_is_frozen_and_forbids_extra_fields() -> None:
    assessment = MemeOpportunityAssessmentV2(
        base_decision=MemeOpportunityDecision.REVIEW, base_composite_score=40,
        decision=MemeOpportunityDecision.NOT_SUITABLE, adjusted_composite_score=20,
        calibration_score_delta=-20, calibration_evidence=["research_paper:arxiv_source"],
    )
    with pytest.raises(Exception):
        assessment.decision = MemeOpportunityDecision.MEME_READY  # type: ignore[misc]
    with pytest.raises(ValueError):
        MemeOpportunityAssessmentV2.model_validate({
            "base_decision": "REVIEW", "base_composite_score": 40, "decision": "NOT_SUITABLE",
            "adjusted_composite_score": 20, "calibration_score_delta": -20, "unexpected": "nope",
        })


def test_safety_context_exception_result_v2_is_frozen_and_forbids_extra_fields() -> None:
    result = SafetyContextExceptionResultV2(
        base_categories=["war"], categories=[], evidence=[], suppressed_evidence=["war:war"],
    )
    with pytest.raises(Exception):
        result.categories = ["war"]  # type: ignore[misc]
    with pytest.raises(ValueError):
        SafetyContextExceptionResultV2.model_validate({
            "base_categories": ["war"], "categories": [], "evidence": [], "suppressed_evidence": [],
            "unexpected": "nope",
        })


# ---------------------------------------------------------------------------
# Import-boundary / no-new-dependency checks
# ---------------------------------------------------------------------------


def test_no_forbidden_imports() -> None:
    import ast
    from pathlib import Path

    source = Path("services/meme_calibration_rules.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_substrings = (
        "capabilities.executor", "workflows.runner", "bot.", "llm_gateway", "meme_image_generation",
        "meme_preview_notifier", "meme_candidate_service", "database.session",
    )
    for module in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in module, f"must never import {module!r}"


def test_v1_classifier_files_are_untouched_by_this_module() -> None:
    """This module must never redefine v1's own lexicon or scoring logic - it only imports and
    wraps it. A crude but effective guard: the calibration module must not contain a duplicate
    `_SENSITIVE_PATTERNS` or `_COMPOSITE_WEIGHTS` definition of its own."""
    from pathlib import Path

    source = Path("services/meme_calibration_rules.py").read_text(encoding="utf-8")
    assert "_SENSITIVE_PATTERNS" not in source
    assert "_COMPOSITE_WEIGHTS" not in source
