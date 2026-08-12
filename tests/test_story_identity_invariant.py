"""Phase 20 M11.1 — Story Identity Invariant.

Written BEFORE the dispatch fix in services/triage_orchestrator.py::_apply_story_memory(), per
the explicit instruction to reproduce the failure first. See docs/phase20_m11_1_story_identity_
investigation.md for the full investigation and chosen design.

Invariant under test: a real NewsEvent must not permanently lose the ability to become the
root/anchor of its own Story merely because its first comparison against older Stories is
uncertain or only loosely related - without blindly creating a new Story for every
UNCERTAIN_MATCH (which would regress cases like the Moscow pair and worsen candidate-pool
dilution).

Integration-tier: real Postgres (db_session, SAVEPOINT-rolled-back), match_story() monkeypatched
to return controlled MatchResult values - isolates _apply_story_memory()'s own dispatch logic
from services/story_memory.py's real scoring, exactly like tests/test_story_memory_v2.py's own
_match_against_only() isolation convention.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_memory import (
    RELATED_STORY,
    STORY_UPDATE,
    UNCERTAIN_MATCH,
    MatchResult,
    extract_story_signature,
)
from services.triage_orchestrator import TriageCycleReport, _apply_story_memory

_RELATED_STORY_ENTITY_FLOOR = 0.2  # mirrors services/story_memory.py's own existing constant


async def _seed_existing_story(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> Story:
    source = NewsSource(name=f"phase20-identity-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"phase20-identity-test-{uuid4()}")
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


async def _new_event(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> NewsEvent:
    source = NewsSource(name=f"phase20-identity-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"phase20-identity-test-{uuid4()}")
    session.add(event)
    await session.flush()
    return event


async def _link_for(session: AsyncSession, event_id) -> NewsEventStoryLink:
    return (
        await session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == event_id))
    ).scalar_one()


# --- 1. Kitesurf root RELATED_STORY case -----------------------------------------------------


@pytest.mark.asyncio
async def test_related_story_root_event_gets_its_own_story(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact Kitesurf failure mode: a genuinely new story's root event scores RELATED_STORY
    against some unrelated older story. It must get its own Story, not be silently absorbed into
    the unrelated one."""
    unrelated = await _seed_existing_story(db_session, "Unrelated older story about something else entirely")
    new_event = await _new_event(db_session, "Cloudflare launches Kitesurf, a browser built for AI agents")

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            RELATED_STORY, unrelated.id, 0.25, "test: related but not same story", entity_overlap=0.25,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)

    report = TriageCycleReport()
    await _apply_story_memory(db_session, new_event, report)

    link = await _link_for(db_session, new_event.id)
    assert link.match_type == RELATED_STORY
    assert link.story_id != unrelated.id, "must not be silently absorbed into the unrelated story"

    own_story = await db_session.get(Story, link.story_id)
    assert own_story is not None
    assert own_story.first_event_id == new_event.id

    await db_session.refresh(unrelated)
    assert unrelated.event_count == 1, "the unrelated story must not be treated as merged/updated"


# --- 2. Olympiad root UNCERTAIN_MATCH case ----------------------------------------------------


@pytest.mark.asyncio
async def test_uncertain_match_with_weak_entity_overlap_gets_its_own_story(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact AI Olympiad root-event failure mode: the first event of a genuinely new cluster
    has no real candidate yet, and coincidentally crosses the low threshold against something
    wholly unrelated (weak entity_overlap, well under the 0.2 floor). It must get its own Story."""
    unrelated = await _seed_existing_story(db_session, "Some unrelated older story, coincidentally similar wording")
    new_event = await _new_event(
        db_session, "Российские школьники в третий раз стали чемпионами на Международной олимпиаде по ИИ",
    )

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            UNCERTAIN_MATCH, unrelated.id, 0.46, "test: coincidental uncertain match", entity_overlap=0.1,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)

    report = TriageCycleReport()
    await _apply_story_memory(db_session, new_event, report)

    link = await _link_for(db_session, new_event.id)
    assert link.match_type == UNCERTAIN_MATCH
    assert link.story_id != unrelated.id, "must not be silently absorbed into the unrelated story"

    own_story = await db_session.get(Story, link.story_id)
    assert own_story is not None
    assert own_story.first_event_id == new_event.id

    await db_session.refresh(unrelated)
    assert unrelated.event_count == 1


# --- 3. Unrelated same-company event must not become merged -----------------------------------


@pytest.mark.asyncio
async def test_related_story_dispatch_never_merges_the_unrelated_story(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GTA-VI-vs-GTA-6-style entity-overlap trap: even after the RELATED_STORY fix gives the
    new event its own story, the pre-existing "related" story's own identity/counters must stay
    completely untouched - never treated as though a merge happened."""
    other_product_story = await _seed_existing_story(db_session, "Tesla launches new Model Y refresh with longer range")
    new_event = await _new_event(db_session, "Tesla faces new regulatory investigation over Autopilot claims")

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            RELATED_STORY, other_product_story.id, 0.22, "test: same entity family, different event", entity_overlap=0.22,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)

    report = TriageCycleReport()
    await _apply_story_memory(db_session, new_event, report)

    await db_session.refresh(other_product_story)
    assert other_product_story.event_count == 1
    assert other_product_story.first_event_id != new_event.id


# --- 4. Later strong evidence can converge onto the correct Story -----------------------------


@pytest.mark.asyncio
async def test_later_strong_evidence_converges_onto_the_provisional_story(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No explicit merge machinery exists or is added - convergence happens for free because a
    later, more decisive event is scored against ALL recent stories (fragmented provisional ones
    included) by the existing retrieval/classification pipeline. This test simulates that second
    step directly: once a provisional story exists (from the UNCERTAIN_MATCH weak-overlap case),
    a later confident STORY_UPDATE against it must bump its event_count normally - proving the
    provisional story is a completely ordinary Story, fully able to receive future real growth."""
    unrelated = await _seed_existing_story(db_session, "Some unrelated older story")
    first_event = await _new_event(db_session, "Школьная сборная России стала чемпионом на олимпиаде по ИИ")

    async def _fake_uncertain(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            UNCERTAIN_MATCH, unrelated.id, 0.46, "test: coincidental uncertain match", entity_overlap=0.1,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_uncertain)
    report = TriageCycleReport()
    await _apply_story_memory(db_session, first_event, report)
    provisional_link = await _link_for(db_session, first_event.id)
    provisional_story_id = provisional_link.story_id
    assert provisional_story_id != unrelated.id

    second_event = await _new_event(db_session, "Школьная сборная России во второй раз подряд стала чемпионом на олимпиаде по ИИ")

    async def _fake_confident_update(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            STORY_UPDATE, provisional_story_id, 0.71, "test: later strong evidence", entity_overlap=0.55,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_confident_update)
    await _apply_story_memory(db_session, second_event, report)

    second_link = await _link_for(db_session, second_event.id)
    assert second_link.story_id == provisional_story_id

    provisional_story = await db_session.get(Story, provisional_story_id)
    assert provisional_story.event_count == 2, "the provisional story must be able to receive real future growth"


# --- 5. Provisional/uncertain identity must not create duplicate permanent Stories unnecessarily


@pytest.mark.asyncio
async def test_uncertain_match_with_strong_entity_overlap_does_not_fragment(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Moscow-pair case: a real, substantial entity_overlap (>= the existing 0.2
    RELATED_STORY floor) in the uncertain band must NOT fragment into a needless new story - the
    existing attach-without-bumping behavior is preserved exactly, since this is a case where the
    candidate genuinely might be (and, per the calibration dataset, likely is) the same story."""
    true_story = await _seed_existing_story(
        db_session, "Московский школьник завоевал золото на Международной олимпиаде по ИИ - Собянин",
    )
    new_event = await _new_event(
        db_session, "Собянин: Московский школьник победил на олимпиаде по искусственному интеллекту",
    )

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            UNCERTAIN_MATCH, true_story.id, 0.528, "test: genuine uncertain match, real entity overlap", entity_overlap=0.4,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)

    report = TriageCycleReport()
    await _apply_story_memory(db_session, new_event, report)

    link = await _link_for(db_session, new_event.id)
    assert link.story_id == true_story.id, "must attach to the existing candidate, not fragment"

    await db_session.refresh(true_story)
    assert true_story.event_count == 1, "UNCERTAIN_MATCH still never bumps event_count - not a confirmed continuation"

    # No new Story was created rooted at this event (scoped check - the real dev DB has other,
    # unrelated pre-existing Story rows, so a global COUNT(*) would not be a meaningful assertion).
    own_stories = (
        await db_session.execute(select(Story).where(Story.first_event_id == new_event.id))
    ).scalars().all()
    assert own_stories == []
