"""NINJA PULSE RECAP Phase R2.10 Night 2 - offline golden corpus for the readiness candidate
scanner (scripts/_recap_r2_10_readiness_candidate_scanner.py).

A compact set of representative Story shapes, each with an EXPLICIT expected scan outcome, used to
prove `scan_story_readiness()`/`rank_rows()` report exactly what the existing, real,
frozen-or-R2-owned semantics already say - never a new scoring/threshold decision of their own.
Reuses tests/test_recap_r2_9_origin_membership_projection.py's own established fixture-construction
helpers directly (this codebase's own established cross-test-file reuse convention - e.g. tests/
test_content_worker_cycle_image_preview.py importing from tests/test_content_worker_cycle.py).

NOT reproduced here (deliberately, no fabricated substitute):
  - the real production Stripe/OpenRouter Story's exact titles (not available offline verbatim;
    tests/test_recap_r2_9_origin_membership_projection.py's own Case 8 already covers its
    conservative-false-negative behavior against the frozen evaluator directly);
  - a "conflicting-evidence-shaped" Story - Phase 7's own forensic finding (R2.10 Night 2 report)
    concluded no reliable deterministic conflict signal exists yet, so there is nothing for the
    scanner to report beyond what every other row already shows.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from services.story_memory import NEW_STORY, RELATED_STORY, STORY_UPDATE, SUPPORTING_SOURCE, UNCERTAIN_MATCH  # noqa: E402
from tests.test_recap_r2_9_origin_membership_projection import (  # noqa: E402
    _NOW, _apply_related_or_uncertain_root, _attach_link, _new_event,
)

from _recap_r2_10_readiness_candidate_scanner import (  # noqa: E402
    CandidateScanRow, rank_rows, scan_story_readiness,
)


@pytest.mark.asyncio
async def test_corpus_case1_marvell_coherent_not_ready_shows_cooling(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4 genuinely distinct, on-topic, cooled-down announcements - every readiness condition
    except `research_complete` is satisfiable (mirrors R2.10A.3's own case4b fixture exactly,
    minus research_complete=True, since the scanner never supplies it - see module docstring: it
    must honestly reflect that this signal is never actually True anywhere in current production).
    Expected: story_integrity_eligible=True, readiness_state="COOLING" (never "READY"),
    recommended_for_manual_review=True."""
    origin_title = (
        "Marvell and Google expand their chip development deal, with Marvell granting Google a "
        "warrant to buy up to 58M+ shares"
    )
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    origin_event.published_at = _NOW - timedelta(hours=6)
    await db_session.flush()
    m1 = await _new_event(db_session, "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC", published_at=_NOW - timedelta(hours=5))
    m2 = await _new_event(db_session, "Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на сумму $12,2 млрд", published_at=_NOW - timedelta(hours=4))
    m3 = await _new_event(db_session, "Google's custom silicon partnership with Marvell seen as bellwether for AI chip warrant deals across the industry", published_at=_NOW - timedelta(hours=3))
    await _attach_link(db_session, m1, story, STORY_UPDATE)
    await _attach_link(db_session, m2, story, SUPPORTING_SOURCE)
    await _attach_link(db_session, m3, story, SUPPORTING_SOURCE)
    story.event_count += 3
    await db_session.flush()
    await db_session.refresh(story)

    row = await scan_story_readiness(db_session, story, now=_NOW)
    assert row.story_integrity_eligible is True
    assert row.origin_projection_status == "applied"
    assert row.announcement_count == 4
    assert row.readiness_state == "COOLING"
    assert row.recommended_for_manual_review is True
    assert row.research_complete_tracked is False


@pytest.mark.asyncio
async def test_corpus_case2_broad_llm_garbage_shows_rejected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real broad-generic-LLM-research-cluster shape (mirrors R2.9's own Case 5 fixture
    exactly) - Story Integrity must fail, never a false PASS. Expected: readiness_state=
    "REJECTED", recommended_for_manual_review=False."""
    origin_title = "Large language models increasingly rely on sampling as a driver of their own improvement in recent research"
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=UNCERTAIN_MATCH, entity_overlap=0.1, monkeypatch=monkeypatch,
    )
    member_titles = [
        "New guardrails framework aims to make large language models safer in production deployments",
        "Post-training techniques reshape how large language models are fine-tuned for downstream tasks",
        "Vision-language models struggle to reason about object attributes in cluttered visual scenes",
        "Large language models show promise as medical consultation assistants in early clinical trials",
    ]
    for i, title in enumerate(member_titles):
        event = await _new_event(db_session, title, published_at=_NOW - timedelta(hours=i + 1))
        await _attach_link(db_session, event, story, STORY_UPDATE)
    story.event_count += len(member_titles)
    await db_session.flush()
    await db_session.refresh(story)

    row = await scan_story_readiness(db_session, story, now=_NOW)
    assert row.readiness_state == "REJECTED"
    assert row.story_integrity_eligible is None
    assert row.recommended_for_manual_review is False
    assert row.rejection_reasons  # a real, non-empty reason must be present


@pytest.mark.asyncio
async def test_corpus_case3_origin_only_zero_confirmed_single_event(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero confirmed members, origin projection eligible - a legitimate single-event Story.
    Integrity trivially passes (no group to be incoherent); readiness fails on event_count alone.
    Expected: origin_projection_status="applied", story_integrity_eligible=True, readiness_state
    != "READY", event_count=1."""
    story, _origin_event = await _apply_related_or_uncertain_root(
        db_session, "Zero-confirmed origin-only story about a niche gadget teardown",
        outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    row = await scan_story_readiness(db_session, story, now=_NOW)
    assert row.origin_projection_status == "applied"
    assert row.story_integrity_eligible is True
    # event_count reports GLOBAL confirmed membership (services.recap_event.load_story_events(),
    # frozen) verbatim - deliberately 0 here, never the post-projection effective count, so the
    # scanner's own output makes the projection visible rather than hiding it.
    assert row.event_count == 0
    assert row.readiness_state != "READY"


@pytest.mark.asyncio
async def test_corpus_case4_insufficient_source_diversity_all_same_source(db_session: AsyncSession) -> None:
    """Enough events/announcements, but every event shares the same URL domain (mirrors tests/
    test_event_recap.py's own `_make_story()` construction - one collector `NewsSource`, one
    `example.com` domain for every event) - readiness_source_count stays at 1 regardless of
    announcement_count. Reuses a proven-coherent title set (already exercised by many passing
    tests in tests/test_event_recap.py) rather than a new, unverified title set. Expected:
    story_integrity_eligible=True, readiness_source_count=1, readiness_state != "READY"."""
    from tests.test_event_recap import _make_story

    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "Taiwan dividend program expands eligibility criteria for AI payout",
        "Officials detail rollout timeline for Taiwan's AI dividend scheme",
    ], match_types=[NEW_STORY, STORY_UPDATE, STORY_UPDATE, STORY_UPDATE])

    row = await scan_story_readiness(db_session, story, now=_NOW)
    assert row.origin_projection_status == "not_needed"
    assert row.story_integrity_eligible is True
    assert row.readiness_source_count == 1
    assert row.readiness_state != "READY"


def test_rank_rows_orders_ready_before_cooling_before_active_before_rejected() -> None:
    """Pure unit test of the deterministic ranking (no numeric score - module docstring)."""
    from uuid import uuid4

    rejected = CandidateScanRow(story_id=uuid4(), title="r", event_count=1, origin_projection_status="not_needed", story_integrity_eligible=None, announcement_count=None, readiness_source_count=None, readiness_state="REJECTED", rejection_reasons=["x"], research_complete_tracked=False, recommended_for_manual_review=False)
    cooling = CandidateScanRow(story_id=uuid4(), title="c", event_count=4, origin_projection_status="not_needed", story_integrity_eligible=True, announcement_count=4, readiness_source_count=3, readiness_state="COOLING", rejection_reasons=[], research_complete_tracked=False, recommended_for_manual_review=True)
    active = CandidateScanRow(story_id=uuid4(), title="a", event_count=3, origin_projection_status="not_needed", story_integrity_eligible=True, announcement_count=3, readiness_source_count=2, readiness_state="ACTIVE", rejection_reasons=[], research_complete_tracked=False, recommended_for_manual_review=False)
    ranked = rank_rows([rejected, active, cooling])
    assert [r.readiness_state for r in ranked] == ["COOLING", "ACTIVE", "REJECTED"]


def test_rank_rows_is_deterministic_across_repeated_calls() -> None:
    from uuid import uuid4

    rows = [
        CandidateScanRow(story_id=uuid4(), title=f"s{i}", event_count=i, origin_projection_status="not_needed", story_integrity_eligible=True, announcement_count=i, readiness_source_count=1, readiness_state="COOLING", rejection_reasons=[], research_complete_tracked=False, recommended_for_manual_review=True)
        for i in range(5)
    ]
    first = [r.story_id for r in rank_rows(rows)]
    second = [r.story_id for r in rank_rows(rows)]
    assert first == second


@pytest.mark.asyncio
async def test_corpus_case5_vk_apple_three_publishers_reports_raw_announcement_count(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase R2.11 addition - real production-shadow shape (exact titles from this checkpoint's
    own record). The scanner's own `announcement_count` field is R1's raw report-level cluster
    count, UNCHANGED by this checkpoint (no R2-local correction was implemented - see docs/
    r2_11_announcement_identity_findings.md). This test pins that CURRENT scanner output for a
    same-event/multi-publisher shape, and exists specifically so a future correction (if one is
    ever safely designed) has a concrete before/after regression anchor. Not asserting
    `recommended_for_manual_review` either way here - depends on the exact cooling-window timing,
    which is not this test's own point (see scan_story_readiness()'s own new Phase R2.11 docstring
    caveat for the human-reviewer-facing warning this finding produced instead of a code fix)."""
    story, _origin_event = await _apply_related_or_uncertain_root(
        db_session, "VK подала в суд на Apple и потребовала вернуть свои приложения в App Store",
        outcome=NEW_STORY, entity_overlap=0.0, monkeypatch=monkeypatch,
    )
    m1 = await _new_event(
        db_session, "VK подала иск против Apple в российский суд из-за удаления её приложений из App Store",
        published_at=_NOW - timedelta(minutes=19),
    )
    m2 = await _new_event(
        db_session, "VK решила засудить Apple за удаление приложений из App Store",
        published_at=_NOW,
    )
    await _attach_link(db_session, m1, story, STORY_UPDATE)
    await _attach_link(db_session, m2, story, STORY_UPDATE)
    story.event_count += 2
    await db_session.flush()
    await db_session.refresh(story)

    row = await scan_story_readiness(db_session, story, now=_NOW)
    assert row.story_integrity_eligible is True
    assert row.announcement_count == 3, (
        "raw R1 report-level count for 3 same-event publications - not development count; "
        "unchanged from current production behavior, characterized not corrected this checkpoint"
    )
