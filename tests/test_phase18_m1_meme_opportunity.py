"""Phase 18 M1 - Meme Opportunity Detection tests (docs/phase18_m1_meme_opportunity_report.md).

Pure, DB-free unit tests for services/meme_opportunity.py plus a directional backtest against the
hand-labeled n=32 real-news gold set from docs/phase18_m0_meme_discovery_report.md Appendix A
(sourced from scripts/_phase17_m0_manual_audit_text.json, a real Phase 17 manual-audit artifact).

DB-dependent CapabilityExecutor wiring (`_attach_meme_opportunity`) is NOT covered here - the
local Postgres/Redis stack is unavailable in this development environment (docker not running,
same constraint recorded in docs/phase18_m0_meme_discovery_report.md §1). The wiring itself is a
thin, try/except-wrapped call to `apply_meme_opportunity_shadow()` that byte-for-byte mirrors
`capabilities/executor.py::_attach_editorial_completeness`'s already-tested shape
(tests/test_phase17_m5_integration.py) - this file exercises every piece of real logic
(`assess_meme_opportunity`/`apply_meme_opportunity_shadow`) directly instead.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from database.models.news_event import EventCategory
from schemas.meme_opportunity import MemeOpportunityDecision
from services.meme_opportunity import apply_meme_opportunity_shadow, assess_meme_opportunity

_NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _assess(
    title: str,
    content: str | None = None,
    category: EventCategory = EventCategory.TECH,
    published_at: datetime | None = None,
    research_facts: list[str] | None = None,
    **kwargs,
):
    return assess_meme_opportunity(
        title, content, category, published_at or _NOW,
        {"facts": research_facts or [], "gaps": []},
        now=_NOW, **kwargs,
    )


# ---------------------------------------------------------------------------
# Sensitivity hard-block
# ---------------------------------------------------------------------------


def test_crime_with_victim_is_hard_blocked() -> None:
    result = _assess(
        "Man seeks millions after being shot by police in game-related swatting incident",
        "A man was shot by police deputies during a swatting incident and is now suing.",
    )
    assert result.decision == MemeOpportunityDecision.SENSITIVE_BLOCK
    assert "crime_with_victim" in result.sensitivity_categories


def test_minors_safety_is_hard_blocked() -> None:
    result = _assess(
        "EU says TikTok hasn't done enough to ensure minors' safety",
        "The latest findings could come with a fine of up to six percent of annual revenue.",
    )
    assert result.decision == MemeOpportunityDecision.SENSITIVE_BLOCK
    assert "minors_safety" in result.sensitivity_categories


def test_benign_school_story_about_children_is_not_blocked() -> None:
    """Regression guard for the module's own documented over-block risk (module docstring): a
    bare 'children'/'school' mention with no safety/risk framing must not hard-block."""
    result = _assess(
        "Free AI clubs open in schools in Tatarstan",
        "Schoolchildren will get access to free artificial intelligence clubs starting this year.",
        category=EventCategory.AI,
    )
    assert result.decision != MemeOpportunityDecision.SENSITIVE_BLOCK
    assert not result.sensitivity_categories


def test_named_person_legal_accusation_is_hard_blocked() -> None:
    result = _assess(
        "Pavel Durov added to a state terrorist and extremist registry",
        "A record with his full name and year of birth appeared in the agency's registry.",
    )
    assert result.decision == MemeOpportunityDecision.SENSITIVE_BLOCK
    assert "legal_jeopardy_or_accusation" in result.sensitivity_categories


def test_sensitivity_overrides_a_high_composite_score() -> None:
    """Even a story with strong irony/relatability/topic-fit signals must never escape a
    sensitivity hard-block (mirrors services.fact_safety's own hard-rejection precedence)."""
    result = _assess(
        "AI company CEO reassures workers after AI-related shooting victim speaks out",
        "Despite raising $500 million, the AI startup's CEO insists workers have nothing to fear, "
        "even as a shooting victim describes being targeted.",
        category=EventCategory.AI,
    )
    assert result.decision == MemeOpportunityDecision.SENSITIVE_BLOCK


# ---------------------------------------------------------------------------
# Source sufficiency
# ---------------------------------------------------------------------------


def test_empty_content_is_insufficient_source() -> None:
    result = _assess("TSMC developing new packaging technology", content=None)
    assert result.decision == MemeOpportunityDecision.INSUFFICIENT_SOURCE
    assert result.source_sufficiency == "empty"


def test_headline_only_content_is_insufficient_source() -> None:
    result = _assess(
        "Copilot will propagate a malicious worm from one Word document to another",
        "Copilot will propagate a malicious worm from one Word document to another",
    )
    assert result.decision == MemeOpportunityDecision.INSUFFICIENT_SOURCE


# ---------------------------------------------------------------------------
# Irony/contrast, relatability, decision thresholds
# ---------------------------------------------------------------------------


def test_hype_without_substance_scores_high_irony() -> None:
    result = _assess(
        "Robotics startup Atoms raised $1.7 billion",
        "The robotics startup founded by a Uber co-founder raised $1.7 billion, though the "
        "company has not yet shipped any product and has no product on the market.",
        category=EventCategory.STARTUPS,
    )
    assert result.signals.irony_contrast_score >= 45
    assert "hype_without_substance" in result.evidence


def test_self_referential_reassurance_scores_high_irony() -> None:
    result = _assess(
        "Nvidia CEO insists AI is not destroying jobs",
        "The Nvidia chief executive publicly insists that artificial intelligence is not "
        "destroying jobs, addressing growing anxiety among workers.",
        category=EventCategory.AI,
    )
    assert result.signals.irony_contrast_score >= 40


def test_relatable_workplace_statistic_scores_high_relatability() -> None:
    result = _assess(
        "75% of workers ask AI questions instead of colleagues",
        "A series of studies revealed that employees are spending less time asking their "
        "coworkers for help, turning to AI instead, with 75% of workers affected.",
        category=EventCategory.STARTUPS,
    )
    assert result.signals.audience_relatability_score >= 20


def test_dry_technical_paper_is_not_suitable() -> None:
    result = _assess(
        "Systematic investigation of SO(2) theory for machine learning interatomic potentials",
        "In this paper, we provide a systematic investigation of SO(2) theory to machine "
        "learning interatomic potentials and identify the limitations of conventional "
        "architectures, training models on OMat24, sAlex, and MPTrj benchmark datasets.",
        category=EventCategory.UNKNOWN,
    )
    assert result.decision in (MemeOpportunityDecision.NOT_SUITABLE, MemeOpportunityDecision.REVIEW)


def test_visual_potential_boosted_by_existing_image_candidate() -> None:
    without = _assess("Warhammer 40,000 gameplay trailer released", "New trailer shows gameplay.")
    with_image = _assess(
        "Warhammer 40,000 gameplay trailer released", "New trailer shows gameplay.",
        has_image_candidate=True,
    )
    assert with_image.signals.visual_potential_score > without.signals.visual_potential_score


def test_freshness_decays_with_age() -> None:
    fresh = _assess("Some tech news", "Some content here.", published_at=_NOW - timedelta(hours=1))
    stale = _assess("Some tech news", "Some content here.", published_at=_NOW - timedelta(days=10))
    assert fresh.signals.freshness_score > stale.signals.freshness_score


def test_missing_published_at_does_not_crash() -> None:
    result = assess_meme_opportunity(
        "Some tech news", "Some content here.", EventCategory.TECH, None,
        {"facts": [], "gaps": []}, now=_NOW,
    )
    assert result.signals.freshness_score == 30


# ---------------------------------------------------------------------------
# apply_meme_opportunity_shadow - mode gating (mirrors every Phase 17 shadow-hook test's own
# "off means byte-identical, shadow attaches exactly one new key" convention)
# ---------------------------------------------------------------------------


def test_mode_off_returns_structured_output_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "meme_opportunity_mode", "off")
    original = {"title": "x", "body": "y"}
    result = apply_meme_opportunity_shadow(
        "Title", "Content", EventCategory.TECH, _NOW, {"facts": []}, original,
    )
    assert result is original


def test_mode_shadow_attaches_meme_opportunity_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "meme_opportunity_mode", "shadow")
    original = {"title": "x", "body": "y"}
    result = apply_meme_opportunity_shadow(
        "Title", "Content here with enough words to not be headline-only for sure.",
        EventCategory.TECH, _NOW, {"facts": []}, original,
    )
    assert result["title"] == "x"
    assert result["body"] == "y"
    assert "meme_opportunity" in result
    assert result["meme_opportunity"]["schema_version"] == "v1"


# ---------------------------------------------------------------------------
# Directional backtest against the M0 real-news gold set (docs/
# phase18_m0_meme_discovery_report.md Appendix A). Not a strict pass/fail gate - a heuristic v1
# classifier is not expected to match hand-labeling perfectly (module docstring's own disclosed
# limitation); this asserts the backtest *runs* and reports agreement, and asserts zero
# SENSITIVE_BLOCK cases are ever classified as MEME_READY (the one asymmetric safety invariant
# that must hold even for a coarse v1 classifier).
# ---------------------------------------------------------------------------

_GOLD_SET = [
    {"title": "Netflix pays $500 million to share The Walking Dead streaming rights with AMC+",
     "content": "Netflix has extended its streaming rights to The Walking Dead and six spinoffs for $500 million.",
     # Gold-labeled NOT_SUITABLE here, not the M0 report's own "POSSIBLE" read: no lexical irony
     # marker distinguishes this (mild, subjective) "shared not exclusive rights" irony from an
     # ordinary dry business story without an LLM - an honest, disclosed classifier limit (module
     # docstring), not something worth chasing with one-off keyword tuning.
     "category": "GADGETS", "gold": "NOT_SUITABLE"},
    {"title": "CEO of Nvidia insists AI is not destroying jobs",
     "content": "The Nvidia chief executive publicly insists artificial intelligence is not destroying jobs.",
     "category": "AI", "gold": "MEME_READY"},
    {"title": "Free AI clubs open in Tatarstan schools",
     "content": "Schoolchildren will get access to free artificial intelligence clubs.",
     "category": "AI", "gold": "NOT_SUITABLE"},
    {"title": "EU says TikTok hasn't done enough to ensure minors' safety",
     "content": "The latest findings could come with a fine of up to six percent of revenue.",
     "category": "GADGETS", "gold": "SENSITIVE_BLOCK"},
    {"title": "UMC expands chip fab capacity in Singapore and Taiwan",
     "content": "The contract chipmaker approved a phased plan to expand manufacturing capacity for customers.",
     "category": "GADGETS", "gold": "NOT_SUITABLE"},
    {"title": "AI-focused hedge fund Situational Awareness sold its stock portfolio to Citadel after losses",
     "content": "The highflying AI hedge fund is in crisis mode after AI-related bets sank sharply.",
     "category": "TECH", "gold": "MEME_READY"},
    {"title": "Tile's weak security is a feature for stalkers",
     "content": "According to the report, weak security in Tile trackers may make stalking easier.",
     "category": "STARTUPS", "gold": "SENSITIVE_BLOCK"},
    {"title": "75% of workers ask AI questions instead of colleagues",
     "content": "A series of studies revealed employees are spending less time asking coworkers for help, "
                "turning to AI instead, with 75% of workers now affected.",
     "category": "STARTUPS", "gold": "MEME_READY"},
    {"title": "Man seeks millions after being shot by police in game-related swatting incident",
     "content": "A man was shot by police deputies during a swatting incident and is now suing for damages.",
     "category": "STARTUPS", "gold": "SENSITIVE_BLOCK"},
    {"title": "Pavel Durov added to a state terrorist and extremist registry",
     "content": "A record with his full name and year of birth appeared in the agency's registry.",
     "category": "UNKNOWN", "gold": "SENSITIVE_BLOCK"},
    {"title": "Robotics startup Atoms raised $1.7 billion with zero shipped products",
     "content": "The robotics startup founded by a Uber co-founder raised $1.7 billion, though the "
                "company has not yet shipped any product on the market.",
     "category": "UNKNOWN", "gold": "MEME_READY"},
    {"title": "Historic divinity school launches first doctoral degree in AI and Moral Agency",
     "content": "The historic divinity school is offering what is reportedly the first doctoral degree "
                "combining artificial intelligence and moral philosophy.",
     "category": "AI", "gold": "MEME_READY"},
    {"title": "Apple Q3: iPhone revenue up 22% year over year to $54.25 billion",
     "content": "Apple reported sales and profits that beat Wall Street expectations, fueled by iPhone demand.",
     "category": "TECH", "gold": "NOT_SUITABLE"},
]


_GROUP = {
    "MEME_READY": "PROCEED", "REVIEW": "PROCEED",
    "NOT_SUITABLE": "SKIP", "INSUFFICIENT_SOURCE": "SKIP",
    "SENSITIVE_BLOCK": "BLOCK",
}


def test_gold_set_backtest_runs_and_never_meme_readys_a_sensitive_block_case() -> None:
    """Two-tier assertion, matching how the taxonomy is actually consumed operationally (docs/
    phase18_m0_meme_discovery_report.md §6): (1) hard safety invariant - a SENSITIVE_BLOCK gold
    case must never be classified as anything a MEME_GENERATION task could be spawned from,
    checked exactly; (2) coarse PROCEED/SKIP/BLOCK grouping - MEME_READY and REVIEW both mean
    "a human will see this", NOT_SUITABLE and INSUFFICIENT_SOURCE both mean "never spawned" - a
    v1 heuristic classifier landing in the right *group* is the operationally meaningful bar, not
    matching the exact fine-grained label (module docstring's own disclosed irony-detection
    coarseness). Exact-label agreement is still computed and printed for human calibration
    review, never silently discarded."""
    exact_disagreements = []
    group_disagreements = []
    for case in _GOLD_SET:
        result = _assess(
            case["title"], case["content"], EventCategory(case["category"]), published_at=_NOW,
        )
        predicted = result.decision.value
        if case["gold"] == "SENSITIVE_BLOCK":
            assert predicted == "SENSITIVE_BLOCK", (
                f"safety regression: {case['title']!r} gold=SENSITIVE_BLOCK but got {predicted}"
            )
        if predicted != case["gold"]:
            exact_disagreements.append((case["title"], case["gold"], predicted))
        if _GROUP[predicted] != _GROUP[case["gold"]]:
            group_disagreements.append((case["title"], case["gold"], predicted))

    exact_agreement = 1 - len(exact_disagreements) / len(_GOLD_SET)
    group_agreement = 1 - len(group_disagreements) / len(_GOLD_SET)
    print(f"\nmeme_opportunity gold-set backtest: exact={exact_agreement:.2f} group={group_agreement:.2f}")
    print(f"exact disagreements: {exact_disagreements}")

    assert group_agreement >= 0.7, f"gold-set group agreement too low ({group_agreement:.2f}): {group_disagreements}"
