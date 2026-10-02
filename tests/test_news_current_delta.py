"""KAGE daily NEWS current-delta regressions; deterministic, no providers or Telegram."""
from datetime import UTC, datetime

import pytest

from services.kage_editorial_usefulness import evaluate_editorial_usefulness
from services.news_current_delta import (
    FRESH_CURRENT_EVENT,
    OLD_EVENT_MATERIAL_NEW_DEVELOPMENT,
    OLD_EVENT_NO_MATERIAL_DELTA,
    OLD_EVENT_WEAK_DISCLOSURE,
    evaluate_current_delta,
)
from services.news_editorial_relevance import evaluate_pre_generation_candidate

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
BAD_SOURCE_TITLE = (
    "OpenAI says it learned this week that its AI agent hacked Australia's NSW state "
    "government in June, following a similar hack on Australia's federal government"
)
BAD_SOURCE_CONTENT = (
    "Attack accessing historical data on bushfires occurred in June but was not disclosed "
    "by the tech company until Thursday."
)
BAD_TITLE = "ИИ-агент взломал правительство Нового Южного Уэльса — OpenAI узнала об этом на этой неделе"
BAD_BODY = "Атака произошла в июне. До этого похожий взлом затронул федеральное правительство Австралии."


def test_exact_live_bad_story_is_rejected_before_generation_despite_today_article_and_score_82() -> None:
    decision = evaluate_pre_generation_candidate(
        title=BAD_SOURCE_TITLE,
        content=BAD_SOURCE_CONTENT,
        standard_score=82,
        standard_threshold=70,
        source_reliability=0.8,
        published_at=NOW,
        now=NOW,
        require_source_detail=False,
        product_loop=True,
    )
    assert decision.current_delta.classification == OLD_EVENT_WEAK_DISCLOSURE
    assert decision.current_delta.reason == "old_event_weak_disclosure_no_material_current_delta"
    assert not decision.current_delta.eligible
    assert not decision.standard_eligible and not decision.viral.eligible
    assert not decision.final_eligible and decision.selection_path == "REJECT"


def test_exact_founder_visible_copy_is_fail_closed_by_pre_send_usefulness_guard() -> None:
    result = evaluate_editorial_usefulness(
        title=BAD_TITLE,
        body=BAD_BODY,
        research={"facts": [BAD_SOURCE_TITLE]},
        intelligence={"angle": BAD_SOURCE_TITLE, "recommendation": "PUBLISH"},
        source_headline=BAD_SOURCE_TITLE,
        now=NOW,
    )
    assert result["current_delta_classification"] == OLD_EVENT_WEAK_DISCLOSURE
    assert result["applicable"] and not result["passed"]
    assert result["reason"] == "old_event_weak_disclosure_no_material_current_delta"


def _rendered(title: str, body: str):
    return evaluate_current_delta(
        title=title,
        content=body,
        now=NOW,
        require_headline_delta=True,
        require_body_delta=True,
    )


def test_genuinely_fresh_current_incident_remains_publishable() -> None:
    result = _rendered(
        "Attackers exploit a zero-day in Acme systems today",
        "The active incident affects production systems; Acme is isolating them now.",
    )
    assert result.classification == FRESH_CURRENT_EVENT and result.eligible


@pytest.mark.parametrize(
    "title,body",
    [
        (
            "New disclosure: 2 million users affected by March breach",
            "The company disclosed this week that attackers stole 2 million account records in March.",
        ),
        (
            "Mandiant identifies APT28 as attacker behind March breach",
            "Investigators identified APT28 this week and linked the group to the March intrusion.",
        ),
        (
            "Regulator fines Acme $50 million over March breach",
            "The regulator fined Acme today and ordered security remediation after the March incident.",
        ),
        (
            "Investigation reveals SQL injection behind March government breach",
            "The new investigation found that attackers used SQL injection to steal 800,000 records.",
        ),
    ],
    ids=["major-impact", "identified-attacker", "legal-consequence", "retrospective-new-facts"],
)
def test_old_event_with_material_new_development_remains_publishable(title: str, body: str) -> None:
    result = _rendered(title, body)
    assert result.classification == OLD_EVENT_MATERIAL_NEW_DEVELOPMENT
    assert result.material_current_delta and result.eligible
    assert result.headline_foregrounds_delta and result.body_explains_delta


@pytest.mark.parametrize(
    "title,body,classification",
    [
        (
            "Report published today retells March cyberattack",
            "The attack happened in March; the article repeats the original background.",
            OLD_EVENT_NO_MATERIAL_DELTA,
        ),
        (
            "Company learned this week about March breach",
            "The company says only that it became aware of the March incident.",
            OLD_EVENT_WEAK_DISCLOSURE,
        ),
        (
            "Vendor acknowledges March security incident",
            "The vendor acknowledged the March incident without describing a new consequence.",
            OLD_EVENT_WEAK_DISCLOSURE,
        ),
        (
            "March outage returns to the headlines",
            "A new article retells the March outage and its existing background.",
            OLD_EVENT_NO_MATERIAL_DELTA,
        ),
        (
            "Company comments on March hack",
            "The March hack happened months ago; no substantive new fact is reported.",
            OLD_EVENT_NO_MATERIAL_DELTA,
        ),
    ],
    ids=["article-today", "learned-now", "weak-acknowledgment", "repackaged-background", "no-delta"],
)
def test_old_event_without_material_delta_is_blocked(title: str, body: str, classification: str) -> None:
    result = _rendered(title, body)
    assert result.classification == classification
    assert not result.material_current_delta and not result.eligible


def test_material_delta_must_be_foregrounded_in_old_event_headline() -> None:
    result = _rendered(
        "Company discusses March breach",
        "A new investigation found that attackers stole 2 million account records.",
    )
    assert result.material_current_delta and not result.eligible
    assert result.reason == "material_current_delta_not_foregrounded_in_headline"


def test_material_delta_must_be_explained_in_old_event_body() -> None:
    result = _rendered(
        "New investigation reveals 2 million records stolen in March breach",
        "The attack happened in March.",
    )
    assert result.material_current_delta and not result.eligible
    assert result.reason == "body_does_not_explain_material_current_delta"
