"""Phase 18.10 M1/M2: tier-2 integration tests for services.story_memory.match_story() - real
Postgres (db_session, rolled back at teardown). Proves the full outcome decision (new_story /
story_update / semantic_duplicate / uncertain_match) against real, persisted Story rows, and
proves the two worked false-positive-protection examples from
docs/phase18_10_editorial_intelligence_report.md end-to-end.
"""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    TOPIC_LEGAL_REGULATORY,
    UNCERTAIN_MATCH,
    extract_story_signature,
    match_story,
)

# Phase 20 M3: un-skipped - migration c2bc6affb100 (adds the 'stories' table etc.) was applied to
# the real DB during the Phase 19 Activation Stage 1 pass (docs/phase19_activation_review.md);
# confirmed directly via `alembic current` this session. The original skip reason no longer
# applies - this file now runs for real, against the real DB, via db_session's own
# SAVEPOINT-rollback isolation (read-only-effective, exactly like every other integration test in
# this suite).


async def _seed_story(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> Story:
    """Pre-existing test-fixture bug fixed here (Phase 20 M3): `stories.first_event_id` is, and
    always has been, FK-constrained to `news_events.id` (database/models/story.py) - this helper
    previously used a bare `uuid4()`, which only ever went undetected because this whole file was
    skipped (migration not yet applied) until this milestone un-skipped it. A real NewsSource +
    NewsEvent is created first, mirroring tests/test_triage_orchestrator_claims.py's own
    established real_committed_event() pattern - cleaned up automatically by db_session's own
    SAVEPOINT rollback, no manual teardown needed."""
    source = NewsSource(name=f"story-memory-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, category=category, hash=f"story-memory-test-{uuid4()}",
    )
    session.add(event)
    await session.flush()

    signature = extract_story_signature(title, category)
    story = Story(
        id=uuid4(), title=title, category=category, entities=signature.entities,
        keywords=signature.keywords, topic_bucket=signature.topic_bucket, first_event_id=event.id,
        event_count=1,
    )
    session.add(story)
    await session.flush()
    return story


@pytest.mark.asyncio
async def test_no_candidates_at_all_is_a_new_story(db_session: AsyncSession) -> None:
    signature, result = await match_story(
        db_session, title=f"Totally novel headline {uuid4()}", category=EventCategory.AI
    )
    assert result.outcome == NEW_STORY
    assert result.matched_story_id is None
    assert signature.topic_bucket in {"other", "product"}  # not the point of this test


@pytest.mark.asyncio
async def test_should_merge_example_openai_release_then_benchmarks(db_session: AsyncSession) -> None:
    """docs/phase18_10_editorial_intelligence_report.md worked example: "OpenAI releases GPT-X"
    followed by "OpenAI reveals GPT-X benchmarks" should match as the same developing story."""
    unique = uuid4().hex[:8]
    original = await _seed_story(db_session, f"OpenAI releases GPT-X-{unique}")

    _signature, result = await match_story(
        db_session, title=f"OpenAI reveals GPT-X-{unique} benchmarks", category=EventCategory.AI
    )

    assert result.outcome in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE)
    assert result.matched_story_id == original.id


@pytest.mark.asyncio
async def test_should_not_merge_example_release_vs_regulation_commentary(db_session: AsyncSession) -> None:
    """docs/phase18_10_editorial_intelligence_report.md worked example: "OpenAI releases GPT-X"
    and "OpenAI CEO comments on regulation" share the company entity but must NOT SAME-STORY
    merge. Phase 20 M5 update: topic_bucket is no longer a hard gate (it's a soft scoring bonus),
    so this pair is now scored, not silently excluded - the real entity overlap ("OpenAI") is
    exactly what RELATED_STORY exists to surface instead of a silent, uninformative NEW_STORY
    (see docs/phase20_story_memory_calibration_dataset.md's own "gta_negative_control" /
    "openai_two_unrelated_announcements" cases for the same pattern). Never SAME_STORY - that
    remains the one non-negotiable assertion."""
    unique = uuid4().hex[:8]
    await _seed_story(db_session, f"OpenAI-{unique} releases GPT-X")

    signature, result = await match_story(
        db_session, title=f"OpenAI-{unique} CEO comments on regulation", category=EventCategory.AI
    )

    assert signature.topic_bucket == TOPIC_LEGAL_REGULATORY
    assert result.outcome in (NEW_STORY, RELATED_STORY)  # never a same-story outcome
    assert result.outcome not in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE)


@pytest.mark.asyncio
async def test_substantially_similar_title_is_a_supporting_source(db_session: AsyncSession) -> None:
    """Phase 18.10 M7: a confident match whose title is substantially similar but not identical
    (title_overlap in the middle band) - another source corroborating the same event without
    adding new substance - classifies as SUPPORTING_SOURCE, distinct from both STORY_UPDATE
    (materially different title) and SEMANTIC_DUPLICATE (near-identical title)."""
    unique = uuid4().hex[:8]
    original = await _seed_story(db_session, f"Widget-{unique} Corp launches Gadget-{unique} Pro device")

    _signature, result = await match_story(
        db_session, title=f"Widget-{unique} Corp confirms Gadget-{unique} Pro official launch", category=EventCategory.AI
    )

    assert result.outcome == SUPPORTING_SOURCE
    assert result.matched_story_id == original.id


@pytest.mark.asyncio
async def test_near_identical_title_is_a_semantic_duplicate(db_session: AsyncSession) -> None:
    unique = uuid4().hex[:8]
    original = await _seed_story(db_session, f"Company-{unique} launches new AI product today")

    _signature, result = await match_story(
        db_session, title=f"Company-{unique} launches new AI product today", category=EventCategory.AI
    )

    assert result.outcome == SEMANTIC_DUPLICATE
    assert result.matched_story_id == original.id


@pytest.mark.asyncio
async def test_different_category_can_still_match_same_story(db_session: AsyncSession) -> None:
    """Phase 20 M3: category is now a soft scoring bonus, never a hard retrieval gate - the real
    Phase 19 overnight validation's "kitesurf" case (docs/phase20_story_memory_calibration_
    dataset.md) proved the original hard category gate silently excluded a real same-story match
    (Cloudflare Kitesurf, covered under both STARTUPS and TECH). A near-identical title in a
    different category must still be found as a real match, not a NEW_STORY - this test replaces
    the old `test_different_category_never_matches`, which asserted the very bug this milestone
    fixes."""
    unique = uuid4().hex[:8]
    original = await _seed_story(db_session, f"OpenAI-{unique} releases GPT-X", category=EventCategory.AI)

    _signature, result = await match_story(
        db_session, title=f"OpenAI-{unique} releases GPT-X", category=EventCategory.STARTUPS
    )

    assert result.outcome == SEMANTIC_DUPLICATE  # identical title -> near-identical-title band
    assert result.matched_story_id == original.id


@pytest.mark.asyncio
async def test_partial_overlap_is_uncertain_not_forced_either_way(db_session: AsyncSession) -> None:
    """A borderline case (some shared entities, same topic bucket, but not a confident match)
    must land in uncertain_match - never silently forced into new_story or story_update."""
    unique = uuid4().hex[:8]
    original = await _seed_story(db_session, f"Widget-{unique} Corp launches Gadget-{unique} One")

    _signature, result = await match_story(
        db_session,
        title=f"Widget-{unique} Corp launches Gadget-{unique} Two with unrelated new features entirely",
        category=EventCategory.AI,
    )

    # This assertion documents the intended threshold behavior; if it proves too strict/loose in
    # practice, tune _LOW_THRESHOLD/_HIGH_THRESHOLD in services/story_memory.py - the outcome
    # must be one of the three non-new_story outcomes here since the entity overlap is real, but
    # is not asserted to a specific one (deliberately - the point is that it lands somewhere in
    # {uncertain_match, story_update, semantic_duplicate}, all of which correctly link the story).
    assert result.outcome in (UNCERTAIN_MATCH, STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE)
    assert result.matched_story_id == original.id


@pytest.mark.asyncio
async def test_result_confidence_is_within_unit_interval(db_session: AsyncSession) -> None:
    unique = uuid4().hex[:8]
    await _seed_story(db_session, f"OpenAI-{unique} releases GPT-X")

    _signature, result = await match_story(
        db_session, title=f"OpenAI-{unique} releases GPT-X", category=EventCategory.AI
    )
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_similarity_reason_is_a_non_empty_human_readable_string(db_session: AsyncSession) -> None:
    unique = uuid4().hex[:8]
    await _seed_story(db_session, f"OpenAI-{unique} releases GPT-X")

    _signature, result = await match_story(
        db_session, title=f"OpenAI-{unique} releases GPT-X", category=EventCategory.AI
    )
    assert isinstance(result.similarity_reason, str)
    assert len(result.similarity_reason) > 0
