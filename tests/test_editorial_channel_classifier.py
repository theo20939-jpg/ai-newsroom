"""TELEGRAPH editorial channel split: services.editorial_channel_classifier - pure unit tests,
no DB, no LLM, no I/O. Mirrors tests/test_telegraph_topic_candidates.py's own pure-unit-test
style for scoring functions exactly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from database.models.news_event import EventCategory
from schemas.editorial import EditorialChannel
from services.editorial_channel_classifier import classify_editorial_channel
from services.telegraph_topic_candidates import StoryEvidenceSummary

_CLASSIFIER_SOURCE = Path("services/editorial_channel_classifier.py").read_text(encoding="utf-8")


def _summary(title: str, *, recommendation: str | None = None) -> StoryEvidenceSummary:
    return StoryEvidenceSummary(
        story_id=uuid4(), story_title=title, story_category=EventCategory.AI, topic_bucket="product",
        event_count=1, total_linked_event_count=1, latest_event_at=datetime.now(timezone.utc),
        source_diversity_proxy=1, match_type_counts={}, max_score=80, max_significance=8.0,
        representative_recommendation=recommendation, has_negative_recommendation=False,
        max_engagement_potential_score=50.0, best_evidence_status="FULL_TEXT",
        events_with_full_text=1, events_with_any_acquisition=1, analyzed_event_count=1,
    )


# ---------------------------------------------------------------------------------------------
# Required test 1: AI story -> NINJA_AI
# ---------------------------------------------------------------------------------------------


def test_1_ai_tutorial_story_classifies_as_ninja_ai() -> None:
    decision = classify_editorial_channel(_summary("Как использовать новую функцию Claude"))
    assert decision.channel == EditorialChannel.NINJA_AI
    assert decision.ninja_ai_score > decision.ninja_pulse_score


def test_ai_prompt_story_classifies_as_ninja_ai() -> None:
    decision = classify_editorial_channel(_summary("10 промтов для аналитика в ChatGPT"))
    assert decision.channel == EditorialChannel.NINJA_AI


def test_ai_automation_story_classifies_as_ninja_ai() -> None:
    decision = classify_editorial_channel(_summary("5 способов автоматизировать работу через AI"))
    assert decision.channel == EditorialChannel.NINJA_AI


def test_ai_new_model_story_classifies_as_ninja_ai() -> None:
    decision = classify_editorial_channel(_summary("Что изменилось в GPT-5 и как этим пользоваться"))
    assert decision.channel == EditorialChannel.NINJA_AI


# ---------------------------------------------------------------------------------------------
# Required test 2: hardware story -> NINJA_PULSE
# ---------------------------------------------------------------------------------------------


def test_2_hardware_story_classifies_as_ninja_pulse() -> None:
    decision = classify_editorial_channel(_summary("Apple представила новый iPhone"))
    assert decision.channel == EditorialChannel.NINJA_PULSE
    assert decision.ninja_pulse_score > decision.ninja_ai_score


def test_gpu_story_classifies_as_ninja_pulse() -> None:
    decision = classify_editorial_channel(_summary("RTX 6090: что изменилось"))
    assert decision.channel == EditorialChannel.NINJA_PULSE


def test_processor_story_classifies_as_ninja_pulse() -> None:
    decision = classify_editorial_channel(_summary("Почему новый процессор Qualcomm важен"))
    assert decision.channel == EditorialChannel.NINJA_PULSE


# ---------------------------------------------------------------------------------------------
# Required test 3: ambiguous story -> NINJA_PULSE (tie-break default)
# ---------------------------------------------------------------------------------------------


def test_3_ambiguous_story_with_no_signals_defaults_to_ninja_pulse() -> None:
    decision = classify_editorial_channel(_summary("Совершенно нейтральная новость без явных сигналов"))
    assert decision.channel == EditorialChannel.NINJA_PULSE
    assert decision.ninja_ai_score == 0
    assert decision.ninja_pulse_score == 0


def test_close_score_within_margin_defaults_to_ninja_pulse() -> None:
    """A story matching exactly one signal on each side, of equal weight (15 == 15, diff=0),
    must still resolve to NINJA_PULSE - the margin rule wins even at a true tie, not just when
    one side has zero signals."""
    decision = classify_editorial_channel(_summary("релиз модели и презентация"))
    assert decision.ninja_ai_score == decision.ninja_pulse_score == 15
    assert decision.channel == EditorialChannel.NINJA_PULSE


# ---------------------------------------------------------------------------------------------
# Scoring transparency / rubric checks
# ---------------------------------------------------------------------------------------------


def test_rationale_names_the_channel_and_matched_signals() -> None:
    decision = classify_editorial_channel(_summary("Как использовать новую функцию Claude"))
    assert "NINJA_AI" in decision.rationale
    assert "tutorial/instruction signal" in decision.rationale or "AI keywords" in decision.rationale


def test_rationale_discloses_tie_break_when_applied() -> None:
    decision = classify_editorial_channel(_summary("Совершенно нейтральная новость"))
    assert "запасной выбор" in decision.rationale


def test_matched_signal_lists_are_populated_and_bounded() -> None:
    decision = classify_editorial_channel(_summary("Apple представила новый iPhone"))
    assert set(decision.matched_ninja_pulse_signals) <= {
        "gadget", "hardware company", "device", "market/industry", "technology event",
    }
    assert decision.matched_ninja_ai_signals == ()


def test_representative_recommendation_also_contributes_to_scoring() -> None:
    """The classifier scores story_title + representative_recommendation together - a
    recommendation-only signal (title itself neutral) must still be picked up."""
    decision = classify_editorial_channel(
        _summary("Нейтральный заголовок", recommendation="Инструкция: как использовать промпт"),
    )
    assert decision.channel == EditorialChannel.NINJA_AI


def test_classification_is_deterministic() -> None:
    summary = _summary("Как использовать новую функцию Claude")
    first = classify_editorial_channel(summary)
    second = classify_editorial_channel(summary)
    assert first == second


# ---------------------------------------------------------------------------------------------
# Cost boundary (structural) - no LLM/network anywhere in this module
# ---------------------------------------------------------------------------------------------


def test_no_llm_gateway_or_network_reference_in_classifier_source() -> None:
    # Deliberately excludes "openai"/"anthropic" - both are legitimate NINJA_AI_KEYWORDS entries
    # (company names as classification data), never an import or API call.
    for forbidden in (
        "LLMGateway", "call_generate", "CapabilityExecutor", "import httpx", "import requests",
        "import openai", "import anthropic", "GenerateRequest",
    ):
        assert forbidden not in _CLASSIFIER_SOURCE, f"unexpected reference: {forbidden}"
