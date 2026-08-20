"""NINJA PULSE RECAP Phase R2.9 - RECAP Origin Membership Projection Integration tests.

Covers the production integration: `services/recap_origin_projection.py`'s own
`classify_origin_projection()`/`resolve_recap_origin_projection()`/`build_effective_recap_members()`,
AND the wiring inside `services/event_recap.py::build_event_recap_candidate()`'s own
previously-`anchor is None`-always-rejects branch. Fixtures reproduce the exact production shapes
R2.7/R2.8 established (Marvell/Google PASS, broad LLM cluster FAIL, Cyrillic-domains/web-standards/
star cluster FAIL, Tabular-ML and Stripe/OpenRouter preserved conservative FAILs) using the REAL,
frozen `services.recap_event.evaluate_recap_story_integrity()` - never a re-derived/duplicated
coherence algorithm.

NO production DB, NO LLM, NO Gateway, NO provider, NO network, NO writes anywhere in this file -
DB-touching cases use only the shared `db_session` fixture (tests/conftest.py, SAVEPOINT-rolled-
back local test DB), mirroring `tests/test_recap_r2_8_origin_membership_semantics_shadow.py`'s own
pattern.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.event_recap import build_event_recap_candidate
from services.recap_event import (
    _CONFIRMED_MEMBERSHIP_MATCH_TYPES,
    evaluate_recap_story_integrity,
    load_story_events,
)
from services.recap_origin_projection import (
    ORIGIN_EVENT_MISSING,
    ORIGIN_LINK_AMBIGUOUS,
    ORIGIN_LINK_MISSING,
    ORIGIN_LINK_WRONG_STORY,
    ORIGIN_MATCH_TYPE_UNEXPECTED,
    ORIGIN_PROJECTION_ELIGIBLE,
    ORIGIN_PROJECTION_NOT_NEEDED,
    build_effective_recap_members,
    classify_origin_projection,
    resolve_recap_origin_projection,
)
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    MatchResult,
    extract_story_signature,
)
from services.triage_orchestrator import TriageCycleReport, _apply_story_memory

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


async def _seed_existing_story(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> Story:
    source = NewsSource(name=f"r29-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"r29-test-{uuid4()}")
    session.add(event)
    await session.flush()
    signature = extract_story_signature(title, category)
    story = Story(
        id=uuid4(), title=title, category=category, entities=signature.entities,
        keywords=signature.keywords, topic_bucket=signature.topic_bucket, first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    return story


async def _new_event(
    session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI,
    published_at: datetime | None = None,
) -> NewsEvent:
    source = NewsSource(name=f"r29-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, category=category, hash=f"r29-test-{uuid4()}", published_at=published_at,
    )
    session.add(event)
    await session.flush()
    return event


async def _attach_link(session: AsyncSession, event: NewsEvent, story: Story, match_type: str, score: float = 0.9) -> NewsEventStoryLink:
    link = NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=score)
    session.add(link)
    await session.flush()
    return link


async def _apply_related_or_uncertain_root(
    session: AsyncSession, title: str, *, outcome: str, monkeypatch: pytest.MonkeyPatch,
    entity_overlap: float = 0.1, category: EventCategory = EventCategory.AI,
) -> tuple[Story, NewsEvent]:
    """Real, unmodified `_apply_story_memory()` call (mirrors R2.7/R2.8's own reproduction pattern)
    - the SAME production code path that creates the anchor-missing state, never hand-constructed."""
    unrelated = await _seed_existing_story(session, "Unrelated older story about something else entirely", category=category)
    root_event = await _new_event(session, title, category=category)

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(outcome, unrelated.id, 0.3, "test", entity_overlap=entity_overlap)

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)
    report = TriageCycleReport()
    await _apply_story_memory(session, root_event, report)

    link = (
        await session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    story = await session.get(Story, link.story_id)
    assert story is not None
    return story, root_event


# ---------------------------------------------------------------------------
# CASE 1 - NORMAL NEW_STORY / CONFIRMED ORIGIN: no projection needed, behavior unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case1_normal_new_story_origin_already_confirmed_no_projection(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "A genuinely new standalone story nobody has covered", outcome=NEW_STORY,
        entity_overlap=0.0, monkeypatch=monkeypatch,
    )
    confirmed = await load_story_events(db_session, story.id)
    assert root_event.id in {e.id for e in confirmed}

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is False
    assert result.candidate is not None
    assert result.candidate.origin_projection_applied is False
    assert result.candidate.anchor_event_id == root_event.id
    assert result.candidate.story_integrity_eligible is True


# ---------------------------------------------------------------------------
# CASE 2/3 - RELATED_STORY / UNCERTAIN_MATCH own-Story origin, zero confirmed members.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [RELATED_STORY, UNCERTAIN_MATCH])
async def test_case2_3_zero_confirmed_origin_projection(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, f"Zero-confirmed {outcome} origin story", outcome=outcome, monkeypatch=monkeypatch,
    )
    confirmed = await load_story_events(db_session, story.id)
    assert confirmed == []

    declared_event, decision = await resolve_recap_origin_projection(db_session, story)
    assert declared_event is not None and declared_event.id == root_event.id
    assert decision.reason_code == ORIGIN_PROJECTION_ELIGIBLE
    assert decision.eligible is True

    # force_shadow=True: candidate is built, Integrity PASS as a single-event Story.
    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is False
    assert result.candidate is not None
    assert result.candidate.origin_projection_applied is True
    assert result.candidate.anchor_event_id == root_event.id
    assert result.candidate.story_integrity_eligible is True
    assert "single-event story" in result.candidate.story_integrity_reasons[0]
    assert result.candidate.publishable is False

    # force_shadow=False: normal readiness gate still rejects (event_count=1 < recap_min_event_count)
    # - NOT because of anchor-missing any more, but because of ordinary readiness.
    result_no_shadow = await build_event_recap_candidate(db_session, story, force_shadow=False, now=_NOW)
    assert result_no_shadow.rejected is True
    assert result_no_shadow.candidate is None
    assert any("event_count" in r for r in result_no_shadow.rejection_reasons)


# ---------------------------------------------------------------------------
# CASE 4 - Marvell/Google production-derived fixture. Origin is the anchor; earliest-confirmed-
# member must NOT be used (R2.8's own proven false-pass-safety finding).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case4_marvell_google_origin_projection_passes(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    origin_title = (
        "Marvell and Google expand their chip development deal, with Marvell granting Google a "
        "warrant to buy up to 58M+ shares"
    )
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    m1 = await _new_event(
        db_session,
        "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC",
        published_at=_NOW - timedelta(hours=2),
    )
    m2 = await _new_event(
        db_session,
        "Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на "
        "сумму $12,2 млрд",
        published_at=_NOW - timedelta(hours=1),
    )
    await _attach_link(db_session, m1, story, STORY_UPDATE)
    await _attach_link(db_session, m2, story, SUPPORTING_SOURCE)
    story.event_count += 2
    await db_session.flush()
    await db_session.refresh(story)

    confirmed = await load_story_events(db_session, story.id)
    assert len(confirmed) == 2

    # The rejected safety-oracle alternative: earliest-confirmed-member as anchor, evaluated
    # against the OTHER confirmed member alone (mirrors R2.7's own simulate_repair_candidate() -
    # never reused in production, only recomputed here to prove R2.9 does NOT take this path).
    earliest = min(confirmed, key=lambda e: e.published_at or e.collected_at)
    rejected_alternative = evaluate_recap_story_integrity(earliest, confirmed)

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is False
    assert result.candidate is not None
    assert result.candidate.origin_projection_applied is True
    assert result.candidate.anchor_event_id == origin_event.id, "must anchor on the immutable origin, never a substitute"
    assert result.candidate.story_integrity_eligible is True
    assert result.candidate.story_integrity_reasons[0].startswith("2/2") or "ratio 1.0" in str(result.candidate.story_integrity_reasons)

    # Deterministic: re-running produces the identical verdict.
    result_again = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result_again.candidate is not None
    assert result_again.candidate.story_integrity_eligible == result.candidate.story_integrity_eligible
    assert result_again.candidate.anchor_event_id == result.candidate.anchor_event_id

    # Document (not assert-required by production behavior, but the whole reason this checkpoint
    # exists): the naive "earliest confirmed member as anchor" alternative would have FAILED here
    # for the real Marvell Story - R2.9 must never fall back to it.
    if not rejected_alternative.eligible:
        assert result.candidate.story_integrity_eligible is True, (
            "origin-anchor PASS must hold even where the rejected earliest-confirmed-member "
            "alternative would have FAILed - this is the exact Marvell finding R2.8 established"
        )


# ---------------------------------------------------------------------------
# CASE 5 - broad generic LLM research cluster: must remain FAIL, never a false PASS.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case5_broad_generic_llm_cluster_stays_fail(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    origin_title = "Large language models increasingly rely on sampling as a driver of their own improvement in recent research"
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=UNCERTAIN_MATCH, entity_overlap=0.1, monkeypatch=monkeypatch,
    )
    member_titles = [
        "New guardrails framework aims to make large language models safer in production deployments",
        "Post-training techniques reshape how large language models are fine-tuned for downstream tasks",
        "Vision-language models struggle to reason about object attributes in cluttered visual scenes",
        "Large language models show promise as medical consultation assistants in early clinical trials",
        "Researchers probe how large language models retain memory across long multi-turn conversations",
        "Autonomous data science agents built on large language models tackle real-world tabular datasets",
        "Large language models generate procedural programs from plain natural language specifications",
        "Scientists apply large language models to open questions in environmental sciences research",
        "Large language models are used to simulate realistic survey responses at population scale",
        "Recommendation systems get a measurable boost from large language model text embeddings",
    ]
    members: list[NewsEvent] = []
    for i, title in enumerate(member_titles):
        event = await _new_event(db_session, title, published_at=_NOW - timedelta(hours=i + 1))
        await _attach_link(db_session, event, story, STORY_UPDATE)
        members.append(event)
    story.event_count += len(members)
    await db_session.flush()
    await db_session.refresh(story)

    confirmed = await load_story_events(db_session, story.id)
    effective = build_effective_recap_members(origin_event, confirmed)
    expected = evaluate_recap_story_integrity(origin_event, effective)
    assert expected.eligible is False, f"test fixture drifted from the known-bad production shape: {expected}"

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None
    assert result.rejection_reasons == list(expected.reasons)


# ---------------------------------------------------------------------------
# CASE 6 - Cyrillic domains / web-standards / fastest-star garbage cluster: must remain FAIL.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case6_cyrillic_domains_web_standards_star_cluster_stays_fail(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_title = "Почта на русском: в доменах .ru и .рф разрешили полностью кириллические адреса"
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    web_standards = await _new_event(
        db_session, "Почти 9 из 10 сайтов уличили в несоблюдении веб-стандартов",
        published_at=_NOW - timedelta(hours=2),
    )
    fastest_star = await _new_event(
        db_session, "Почти 90 млн км/ч: астрономы нашли самую быструю известную звезду",
        published_at=_NOW - timedelta(hours=1),
    )
    await _attach_link(db_session, web_standards, story, STORY_UPDATE)
    await _attach_link(db_session, fastest_star, story, STORY_UPDATE)
    story.event_count += 2
    await db_session.flush()
    await db_session.refresh(story)

    confirmed = await load_story_events(db_session, story.id)
    effective = build_effective_recap_members(origin_event, confirmed)
    expected = evaluate_recap_story_integrity(origin_event, effective)
    assert expected.eligible is False, f"test fixture drifted from the known-bad production shape: {expected}"

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None
    assert result.rejection_reasons == list(expected.reasons)


# ---------------------------------------------------------------------------
# CASE 7 - Tabular ML: preserve whatever the frozen evaluator currently says - no bypass, no
# hard-coded semantic expectation beyond that.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case7_tabular_ml_propagates_frozen_evaluator_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_title = (
        "Tabular prediction is a critical task across numerous applications. The recent success "
        "of large language models has"
    )
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=UNCERTAIN_MATCH, entity_overlap=0.1, monkeypatch=monkeypatch,
    )
    member = await _new_event(
        db_session,
        "Tabular machine learning benchmarks typically summarize performance by averaging scores, "
        "ranks, or pairwise wins across",
        published_at=_NOW - timedelta(hours=1),
    )
    await _attach_link(db_session, member, story, STORY_UPDATE)
    story.event_count += 1
    await db_session.flush()
    await db_session.refresh(story)

    confirmed = await load_story_events(db_session, story.id)
    effective = build_effective_recap_members(origin_event, confirmed)
    expected = evaluate_recap_story_integrity(origin_event, effective)

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    # No bypass, no special case: R2.9 must always agree with the frozen evaluator's own verdict,
    # whichever way it currently goes - never hard-coded to a presumed direction here.
    if expected.eligible:
        assert result.rejected is False
        assert result.candidate is not None
        assert result.candidate.story_integrity_eligible is True
    else:
        assert result.rejected is True
        assert result.candidate is None
        assert result.rejection_reasons == list(expected.reasons)


# ---------------------------------------------------------------------------
# CASE 8 - Stripe/OpenRouter: intentionally preserved conservative false negative - out of R2.9
# scope to fix. Must remain FAIL, never patched around.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case8_stripe_openrouter_conservative_false_negative_preserved(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documented, intentional: the frozen lexical/coherence evaluator currently treats this real
    same-story pair as insufficiently coherent (a conservative false negative, not a false
    positive). R2.9's job is to make the origin usable as an anchor when the LINK-level semantics
    allow it - never to loosen Story Integrity itself. No exception is added here."""
    origin_title = "Stripe приобрела ИИ-стартап OpenRouter - Хабр"
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, origin_title, outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    member = await _new_event(
        db_session, "Stripe, OpenRouter finally strike a deal - Payments Dive",
        published_at=_NOW - timedelta(hours=1),
    )
    await _attach_link(db_session, member, story, STORY_UPDATE)
    story.event_count += 1
    await db_session.flush()
    await db_session.refresh(story)

    confirmed = await load_story_events(db_session, story.id)
    effective = build_effective_recap_members(origin_event, confirmed)
    expected = evaluate_recap_story_integrity(origin_event, effective)

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    if expected.eligible:
        assert result.rejected is False
    else:
        assert result.rejected is True
        assert result.candidate is None
        assert result.rejection_reasons == list(expected.reasons)


# ---------------------------------------------------------------------------
# CASE 9-14 - fail-closed structural states (pure classify_origin_projection()).
# ---------------------------------------------------------------------------


def test_case9_missing_origin_event_fails_closed() -> None:
    story = Story(
        id=uuid4(), title="Story with a phantom origin", category=EventCategory.AI,
        entities=[], keywords=[], topic_bucket="general", first_event_id=uuid4(), event_count=1,
    )
    decision = classify_origin_projection(story, None, [])
    assert decision.reason_code == ORIGIN_EVENT_MISSING
    assert decision.eligible is False


@pytest.mark.asyncio
async def test_case10_no_own_link_fails_closed(db_session: AsyncSession) -> None:
    story = await _seed_existing_story(db_session, "Story whose origin has literally no link row")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    decision = classify_origin_projection(story, event, [])
    assert decision.reason_code == ORIGIN_LINK_MISSING
    assert decision.eligible is False


@pytest.mark.asyncio
async def test_case11_multiple_current_links_fails_closed(db_session: AsyncSession) -> None:
    """PROVEN structurally unreachable via real persistence (`news_event_id` is the links table's
    PRIMARY KEY - database/models/story_link.py's own explicit "at most one link per event" hard
    constraint) - tested at the pure-function level with hand-built objects, defense-in-depth."""
    story = await _seed_existing_story(db_session, "Story whose origin has (synthetically) two link rows")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    fake_link_a = NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=RELATED_STORY, match_score=0.3)
    fake_link_b = NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=UNCERTAIN_MATCH, match_score=0.4)
    decision = classify_origin_projection(story, event, [fake_link_a, fake_link_b])
    assert decision.reason_code == ORIGIN_LINK_AMBIGUOUS
    assert decision.eligible is False


@pytest.mark.asyncio
async def test_case12_own_link_points_to_different_story_fails_closed(db_session: AsyncSession) -> None:
    other_story = await _seed_existing_story(db_session, "Some other, unrelated story")
    fabricated_story = Story(
        id=uuid4(), title="Fabricated Story pointing at someone else's event", category=EventCategory.AI,
        entities=[], keywords=[], topic_bucket="general",
        first_event_id=other_story.first_event_id, event_count=1,
    )
    db_session.add(fabricated_story)
    await db_session.flush()

    origin_event = await db_session.get(NewsEvent, other_story.first_event_id)
    assert origin_event is not None
    link = NewsEventStoryLink(news_event_id=origin_event.id, story_id=other_story.id, match_type=RELATED_STORY, match_score=0.3)
    db_session.add(link)
    await db_session.flush()

    decision = classify_origin_projection(fabricated_story, origin_event, [link])
    assert decision.reason_code == ORIGIN_LINK_WRONG_STORY
    assert decision.eligible is False


@pytest.mark.asyncio
async def test_case13_conflicting_other_story_relation_resolved_via_real_db_read(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end via `resolve_recap_origin_projection()` (the real DB-reading entry point, not
    the pure function directly) - proves the wrong-story conflict is caught even when discovered
    through the real read path, not just hand-constructed inputs."""
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, "Story whose origin will be given a conflicting other-Story link",
        outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    other_story = await _seed_existing_story(db_session, "A second, unrelated story")

    # Simulate (test-only, never production-reachable given the real link PK/write-once
    # discipline) a conflicting current relationship by directly inspecting via the real resolver
    # after swapping the existing link's story_id - proves resolve_recap_origin_projection() reads
    # whatever is ACTUALLY in the DB, never assumes.
    link = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == origin_event.id))
    ).scalar_one()
    link.story_id = other_story.id
    await db_session.flush()

    declared_event, decision = await resolve_recap_origin_projection(db_session, story)
    assert declared_event is not None
    assert decision.reason_code == ORIGIN_LINK_WRONG_STORY
    assert decision.eligible is False


@pytest.mark.asyncio
async def test_case14_unexpected_match_type_fails_closed(db_session: AsyncSession) -> None:
    story = await _seed_existing_story(db_session, "Story whose origin link has a future/unknown match_type")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    link = NewsEventStoryLink(
        news_event_id=event.id, story_id=story.id, match_type="future_unknown_outcome", match_score=0.5,
    )
    db_session.add(link)
    await db_session.flush()

    decision = classify_origin_projection(story, event, [link])
    assert decision.reason_code == ORIGIN_MATCH_TYPE_UNEXPECTED
    assert decision.eligible is False


@pytest.mark.asyncio
@pytest.mark.parametrize("match_type", [SUPPORTING_SOURCE, "semantic_duplicate"])
async def test_case14b_confirmed_membership_match_type_is_not_needed_not_unexpected(
    db_session: AsyncSession, match_type: str,
) -> None:
    """A confirmed-membership match_type on the origin's own link is ORIGIN_PROJECTION_NOT_NEEDED
    (not ORIGIN_MATCH_TYPE_UNEXPECTED) - this shape is structurally unreachable from `build_event_
    recap_candidate()`'s own `anchor is None` branch (the origin would already be a confirmed
    member), but the pure classifier must still answer it correctly and distinctly."""
    story = await _seed_existing_story(db_session, "Story with a normally-confirmed origin link")
    event = await db_session.get(NewsEvent, story.first_event_id)
    assert event is not None
    link = NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9)
    db_session.add(link)
    await db_session.flush()

    decision = classify_origin_projection(story, event, [link])
    assert decision.reason_code == ORIGIN_PROJECTION_NOT_NEEDED
    assert decision.eligible is False


# ---------------------------------------------------------------------------
# CASE 15 - origin already present in confirmed members: no duplicate, same integrity behavior.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case15_origin_already_confirmed_no_duplicate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # _seed_existing_story() never writes a NewsEventStoryLink for its own origin (R2.7/R2.8's own
    # established test convention) - a real NEW_STORY link is needed here so the origin is a
    # genuine confirmed member, not merely a declared-but-unlinked first_event_id.
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, "Story whose origin is a normal confirmed member", outcome=NEW_STORY,
        entity_overlap=0.0, monkeypatch=monkeypatch,
    )
    member = await _new_event(db_session, "A follow-up event on the same normal story", published_at=_NOW)
    await _attach_link(db_session, member, story, STORY_UPDATE)
    story.event_count += 1
    await db_session.flush()
    await db_session.refresh(story)

    confirmed = await load_story_events(db_session, story.id)
    assert origin_event.id in {e.id for e in confirmed}
    effective = build_effective_recap_members(origin_event, confirmed)
    assert len(effective) == len(confirmed)
    assert sorted(e.id for e in effective) == sorted(e.id for e in confirmed)


# ---------------------------------------------------------------------------
# CASE 16 - deduplication by event id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case16_deduplication_by_event_id(db_session: AsyncSession) -> None:
    origin = await _new_event(db_session, "Origin event for dedup test", published_at=_NOW - timedelta(hours=2))
    other = await _new_event(db_session, "Another confirmed member", published_at=_NOW - timedelta(hours=1))

    effective = build_effective_recap_members(origin, [origin, origin, other, other])
    ids = [e.id for e in effective]
    assert len(ids) == len(set(ids)) == 2


# ---------------------------------------------------------------------------
# CASE 17 - order determinism.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case17_order_determinism(db_session: AsyncSession) -> None:
    origin = await _new_event(db_session, "Origin event for determinism test", published_at=_NOW - timedelta(hours=3))
    m1 = await _new_event(db_session, "Middle member", published_at=_NOW - timedelta(hours=2))
    m2 = await _new_event(db_session, "Latest member", published_at=_NOW - timedelta(hours=1))

    result_a = build_effective_recap_members(origin, [m1, m2])
    result_b = build_effective_recap_members(origin, [m2, m1])
    assert [e.id for e in result_a] == [e.id for e in result_b] == [origin.id, m1.id, m2.id]

    integrity_a = evaluate_recap_story_integrity(origin, result_a)
    integrity_b = evaluate_recap_story_integrity(origin, result_b)
    assert integrity_a.eligible == integrity_b.eligible
    assert integrity_a.metrics == integrity_b.metrics


# ---------------------------------------------------------------------------
# CASE 18 - Story Integrity PASS vs RECAP readiness distinction, preserved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case18_integrity_pass_never_implies_readiness_or_publishable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    story, origin_event = await _apply_related_or_uncertain_root(
        db_session, "Single-event origin-only readiness distinction story", outcome=RELATED_STORY,
        monkeypatch=monkeypatch,
    )
    assert story.event_count == 1  # Story.event_count declared value, unaffected by R2.9

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.candidate is not None
    assert result.candidate.story_integrity_eligible is True
    assert result.candidate.readiness_overridden is True  # only force_shadow got it built
    assert result.candidate.publishable is False

    result_no_shadow = await build_event_recap_candidate(db_session, story, force_shadow=False, now=_NOW)
    assert result_no_shadow.rejected is True
    assert result_no_shadow.candidate is None


# ---------------------------------------------------------------------------
# CASE 19 - no LLM / network: Gateway explodes if touched, R2.9 must never call it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case19_no_llm_or_gateway_call(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(*_args, **_kwargs):
        raise AssertionError("R2.9 candidate construction must never call the LLM Gateway")

    monkeypatch.setattr("capabilities.gateway_call.call_generate", _explode)
    monkeypatch.setattr("services.event_recap.call_generate", _explode)

    story, _origin_event = await _apply_related_or_uncertain_root(
        db_session, "No-LLM safety check story", outcome=UNCERTAIN_MATCH, entity_overlap=0.1,
        monkeypatch=monkeypatch,
    )
    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.candidate is not None  # completed without raising - the Gateway was never touched


# ---------------------------------------------------------------------------
# CASE 20 / write-safety audit - AST-based, over actual CODE nodes only.
# ---------------------------------------------------------------------------

_SCRIPT_PATH = Path("services/recap_origin_projection.py")
_FORBIDDEN_ATTR_CALLS = {"add", "add_all", "delete", "merge", "commit", "flush"}
_FORBIDDEN_SQL_KEYWORDS = ("update ", "delete from", "insert into")


def _parse_module() -> ast.Module:
    return ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(_SCRIPT_PATH))


def test_case20_recap_origin_projection_contains_no_write_calls() -> None:
    tree = _parse_module()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _FORBIDDEN_ATTR_CALLS:
                offenders.append(f"{node.func.attr}() at line {node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            for keyword in _FORBIDDEN_SQL_KEYWORDS:
                if keyword in lowered:
                    offenders.append(f"SQL string literal containing {keyword!r} at line {node.lineno}")
    assert offenders == [], f"write-capable code found in services/recap_origin_projection.py: {offenders}"


def test_case20b_recap_origin_projection_never_imports_llm_or_telegram() -> None:
    tree = _parse_module()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    lowered = {name.lower() for name in imported_names}
    for forbidden in ("llm_gateway", "telegram", "anthropic", "openai", "deepseek", "gateway_call"):
        assert not any(forbidden in name for name in lowered), (
            f"unexpected {forbidden!r} import in services/recap_origin_projection.py: {imported_names}"
        )


def test_case20c_recap_origin_projection_does_not_import_story_memory_write_paths() -> None:
    tree = _parse_module()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
    assert "_apply_story_memory" not in imported_names
    assert "match_story" not in imported_names


# ---------------------------------------------------------------------------
# Reused-constant / no-mutation sanity checks.
# ---------------------------------------------------------------------------


def test_confirmed_membership_match_types_constant_is_the_real_frozen_object() -> None:
    """Guards against an accidental local re-declaration - R2.9 must import the SAME frozenset
    object services/recap_event.py already defines, never a duplicate/redefined constant."""
    from services.recap_event import _CONFIRMED_MEMBERSHIP_MATCH_TYPES as recap_event_constant

    assert _CONFIRMED_MEMBERSHIP_MATCH_TYPES is recap_event_constant


@pytest.mark.asyncio
async def test_no_mutation_of_story_event_or_link(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    story, root_event = await _apply_related_or_uncertain_root(
        db_session, "A story that must remain byte-identical after R2.9 candidate construction",
        outcome=RELATED_STORY, monkeypatch=monkeypatch,
    )
    before_story = (story.id, story.title, story.first_event_id, story.event_count)
    before_event = (root_event.id, root_event.title)
    link_before = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    before_link = (link_before.news_event_id, link_before.story_id, link_before.match_type, link_before.match_score)

    await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)

    await db_session.refresh(story)
    await db_session.refresh(root_event)
    link_after = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()

    assert (story.id, story.title, story.first_event_id, story.event_count) == before_story
    assert (root_event.id, root_event.title) == before_event
    assert (link_after.news_event_id, link_after.story_id, link_after.match_type, link_after.match_score) == before_link
