"""Phase 20.7 - Editorial Content Type layer.

Written test-first: every "Case A-E" integration assertion below was confirmed FAILING against
pre-Phase-20.7 code (see docs/phase20_7_editorial_content_type_report.md's own baseline section
for the exact evidence) - this file encodes the POST-fix expected behavior.

Two tiers:
- Pure unit tests for `classify_content_type()` itself (no DB) - real title patterns, measured
  against the actual replay corpus before being chosen (docs/phase20_7_editorial_content_type_
  report.md §6), not invented.
- Integration tests (real Postgres, db_session) for the full `match_story()` gate effect, using
  the same single-candidate isolation convention as tests/test_story_memory_v2.py (content-type
  compatibility is a pure per-title comparison, unlike Checkpoint 6's document-frequency gate - no
  larger synthetic pool is needed to exercise it meaningfully).
"""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from services.editorial_content_type import (
    ANALYSIS,
    ANNOUNCEMENT,
    GUIDE,
    INTERVIEW,
    LEAK,
    NEWS,
    OPINION,
    PATCH_NOTE,
    REPORT,
    RESEARCH,
    REVIEW,
    RUMOR,
    TUTORIAL,
    classify_content_type,
    is_content_type_mismatch,
)
from services.story_memory import (
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    extract_story_signature,
    match_story,
)

_SAME_STORY_OUTCOMES = {STORY_UPDATE, SUPPORTING_SOURCE}


# --- pure classify_content_type() unit tests - real, measured title patterns -------------------


@pytest.mark.parametrize("title,expected", [
    ("Beast of Reincarnation review – a taxing reflection of human-made damage", REVIEW),
    ("iPhone 18 Pro hands-on: first impressions", REVIEW),
    ("Обзор нового процессора от AMD", REVIEW),
    ("Best projectile build in Beast of Reincarnation: a complete guide", GUIDE),
    ("How to beat the final boss in Beast of Reincarnation", TUTORIAL),
    ("Beginner's guide to the new expansion", GUIDE),
    ("How to set up your new smart thermostat: a step-by-step tutorial", TUTORIAL),
    ("OpenAI launches new voice assistant", ANNOUNCEMENT),
    ("Cloudflare unveils Kitesurf, a browser built for AI agents", ANNOUNCEMENT),
    ("Apple announces new iPhone lineup", ANNOUNCEMENT),
    ("This paper presents purely convex programs for passively safe rendezvous", RESEARCH),
    ("New arXiv paper explores robot manipulation", RESEARCH),
    ("Sundar Pichai talks to reporters about AI regulation", INTERVIEW),
    ("Exclusive interview: the CEO on what comes next", INTERVIEW),
    ("iPhone 20 leaked renders show a bigger screen", LEAK),
    ("Next iPhone rumored to get a titanium frame", RUMOR),
    ("Sources say the next iPhone will be delayed", RUMOR),
    ("Patch notes for version 2.5: bug fixes and balance changes", PATCH_NOTE),
    ("OpenAI analysis of new AI trends", ANALYSIS),
    ("Deep dive: how the new chip architecture actually works", ANALYSIS),
    ("Opinion: why this product launch matters", OPINION),
    ("Report finds AI adoption accelerating across industries", REPORT),
    ("Wildberries сообщил об атаке беспилотников на склад", NEWS),
    ("Apple confirms rollout date for the new feature", NEWS),
])
def test_classify_content_type_real_title_patterns(title: str, expected: str) -> None:
    assert classify_content_type(title) == expected


def test_classify_content_type_defaults_to_news_for_plain_headlines() -> None:
    assert classify_content_type("SpaceX made more revenue as an AI company than a space company") == NEWS


# --- is_content_type_mismatch() - the identity-relevant gate -----------------------------------


def test_mismatch_between_two_specific_different_types() -> None:
    assert is_content_type_mismatch(GUIDE, REVIEW) is True


def test_no_mismatch_between_same_specific_type() -> None:
    assert is_content_type_mismatch(ANNOUNCEMENT, ANNOUNCEMENT) is False


def test_no_mismatch_when_either_side_is_plain_news() -> None:
    """NEWS is the neutral default - it must never itself trigger a mismatch, since most
    ordinary same-story follow-up coverage has no specific editorial marker at all."""
    assert is_content_type_mismatch(NEWS, REVIEW) is False
    assert is_content_type_mismatch(ANNOUNCEMENT, NEWS) is False
    assert is_content_type_mismatch(NEWS, NEWS) is False


# --- integration: Cases A-E -----------------------------------------------------------------


async def _seed_story(session: AsyncSession, title: str, *, category: EventCategory) -> Story:
    source = NewsSource(name=f"phase20-7-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"phase20-7-test-{uuid4()}")
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


async def _match_against_only(monkeypatch: pytest.MonkeyPatch, session: AsyncSession, *, title: str, category: EventCategory, only_candidate: Story):
    import services.story_memory as story_memory_module

    async def _fake_fetch(_session: AsyncSession, *, now):  # noqa: ANN001, ARG001
        return [only_candidate]

    monkeypatch.setattr(story_memory_module, "_fetch_candidate_stories", _fake_fetch)
    return await match_story(session, title=title, category=category)


@pytest.mark.asyncio
async def test_case_a_guide_vs_review_same_game_must_not_become_story_update(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    root = await _seed_story(db_session, "Beast of Reincarnation review", category=EventCategory.AI)
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title="Beast of Reincarnation projectile build guide", category=EventCategory.AI, only_candidate=root,
    )
    assert result.outcome not in _SAME_STORY_OUTCOMES, f"got {result.outcome}: {result.similarity_reason}"


@pytest.mark.asyncio
async def test_case_b_review_vs_announcement_not_automatically_same_story(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    root = await _seed_story(db_session, "iPhone release announcement", category=EventCategory.GADGETS)
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title="Review of new iPhone model", category=EventCategory.GADGETS, only_candidate=root,
    )
    assert result.outcome not in _SAME_STORY_OUTCOMES, f"got {result.outcome}: {result.similarity_reason}"


@pytest.mark.asyncio
async def test_case_c_analysis_vs_announcement(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    root = await _seed_story(db_session, "OpenAI announces new model", category=EventCategory.AI)
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title="OpenAI analysis of new AI trends", category=EventCategory.AI, only_candidate=root,
    )
    assert result.outcome not in _SAME_STORY_OUTCOMES, f"got {result.outcome}: {result.similarity_reason}"


@pytest.mark.asyncio
async def test_case_d_research_vs_announcement(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    root = await _seed_story(db_session, "Robotics company product launch", category=EventCategory.AI)
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title="New research paper about robotics", category=EventCategory.AI, only_candidate=root,
    )
    assert result.outcome not in _SAME_STORY_OUTCOMES, f"got {result.outcome}: {result.similarity_reason}"


@pytest.mark.asyncio
async def test_case_e_negative_control_same_story_different_wording_still_links(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both sides are plain NEWS (no specific editorial marker) - the content-type gate must NOT
    be what blocks this pair.

    STORY-CONTINUITY-P0 recalibration: the two headlines share ONLY the organization "SpaceX"
    (the delta between "AI company" wordings is generic vocab). Section 7 - "organization overlap
    alone cannot establish same Story" - so this now resolves to UNCERTAIN_MATCH (a non-merging
    provisional link, continuity AMBIGUOUS), NOT a confident STORY_UPDATE. That is the intended
    P0 trade-off: the same org-only signal that linked this correct pair was what false-merged
    the Meta "Muse agent" burst into unrelated Meta Stories. The pair is not lost (matched_story_
    id is set for review); a later semantic/keyword layer can promote it. What P0 asserts here:
    the CONTENT-TYPE gate is not the blocker, and the match still attaches for observability."""
    root = await _seed_story(db_session, "SpaceX made more revenue as an AI company than a space company", category=EventCategory.GADGETS)
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title="SpaceX's first public earnings statement shows the financials of an AI company in 2026",
        category=EventCategory.GADGETS, only_candidate=root,
    )
    assert result.outcome in (*_SAME_STORY_OUTCOMES, "uncertain_match"), (
        f"content-type gate must not hard-block; got {result.outcome}: {result.similarity_reason}"
    )
    assert result.matched_story_id == root.id  # not lost - attached for review
    assert "content type" not in result.similarity_reason.lower()  # not a content-type mismatch


@pytest.mark.asyncio
async def test_case_e_announcement_vs_announcement_same_type_still_links(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both sides classify as the SAME specific type (ANNOUNCEMENT) - same-type must never be
    treated as a mismatch, only genuinely different specific types."""
    root = await _seed_story(db_session, "Cloudflare launches Kitesurf, a browser built for AI agents", category=EventCategory.STARTUPS)
    _signature, result = await _match_against_only(
        monkeypatch, db_session, title="Cloudflare introduces Kitesurf, a cloud-hosted browser for AI agents built on top of its Workers serverless service",
        category=EventCategory.TECH, only_candidate=root,
    )
    assert result.outcome in _SAME_STORY_OUTCOMES, f"same content type must not be gated, got {result.outcome}: {result.similarity_reason}"
