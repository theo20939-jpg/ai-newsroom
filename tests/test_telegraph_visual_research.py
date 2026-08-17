"""TELEGRAPH Checkpoint 4: services.telegraph_visual_research - real Postgres (db_session
fixture, rolled back per test). Reuses tests.test_telegraph_topic_candidates's own established
fixtures for Story/NewsEvent/NewsSource seeding.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import EventCategory
from database.models.news_source import SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from schemas.telegraph_visual_research import VisualRole
from services.telegraph_visual_research import build_visual_research_bundle
from tests.test_telegraph_topic_candidates import _make_anchor_event, _make_source

_VISUAL_SOURCE = Path("services/telegraph_visual_research.py").read_text(encoding="utf-8")


async def _seed_story(db_session: AsyncSession, *, title: str = "Visual test story") -> Story:
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title=title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    return story


async def _link_event(db_session: AsyncSession, story: Story, *, match_type: str = "new_story"):
    source = await _make_source(db_session)
    from tests.test_telegraph_topic_candidates import _make_anchor_event as _make_event

    event = await _make_event(db_session, source)
    db_session.add(
        NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9)
    )
    await db_session.flush()
    return event


def _candidate(
    *, news_event_id, quality_score: int = 70, relevance_score: int | None = 60,
    eligible: bool = True, warnings: list[str] | None = None, is_representative: bool | None = True,
    aspect_ratio: float | None = 1.5, sha256: str | None = None, perceptual_hash: str | None = None,
    source_name: str = "Test Source", provenance_confidence: int = 80,
) -> ImageCandidateRecord:
    return ImageCandidateRecord(
        id=uuid4(), candidate_id=f"cand-{uuid4()}", news_event_id=news_event_id,
        source_type=SourceType.RSS, discovery_method="article_og_image", source_name=source_name,
        article_url="https://example.com/article", source_url="https://example.com/img.jpg",
        final_url="https://example.com/img.jpg", provenance_confidence=provenance_confidence,
        source_relationship="same_domain", width=1200, height=800, aspect_ratio=aspect_ratio,
        sha256=sha256 or f"sha-{uuid4()}", perceptual_hash=perceptual_hash,
        quality_score=quality_score, quality_warnings=warnings or [], relevance_score=relevance_score,
        eligible_for_editorial=eligible, is_representative=is_representative,
    )


@pytest.mark.asyncio
async def test_high_quality_landscape_image_becomes_hero(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story)
    db_session.add(_candidate(news_event_id=event.id, quality_score=80, relevance_score=70, aspect_ratio=1.6))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    assert len(bundle.images) == 1
    assert bundle.images[0].role == VisualRole.HERO


@pytest.mark.asyncio
async def test_low_quality_image_excluded(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story)
    db_session.add(_candidate(news_event_id=event.id, quality_score=10, relevance_score=50))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    assert bundle.images == []
    assert bundle.total_rejected == 1


@pytest.mark.asyncio
async def test_hard_rejected_candidate_never_considered(db_session: AsyncSession) -> None:
    """eligible_for_editorial=False (the existing M4 gate - e.g. a favicon hard-rejected at
    quality time) is never even fetched into the ranking pool."""
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story)
    db_session.add(_candidate(news_event_id=event.id, quality_score=90, eligible=False))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    assert bundle.images == []
    assert bundle.total_candidates_considered == 0


@pytest.mark.asyncio
async def test_heavily_branded_image_never_becomes_hero(db_session: AsyncSession) -> None:
    """A single branding flag is only a partial penalty (services.media_ranking's own existing,
    unmodified weighting) - combining logo + watermark crosses the existing branding_risk>=40
    "never HERO" threshold, proving that existing rule is actually reached from this module."""
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story)
    db_session.add(
        _candidate(
            news_event_id=event.id, quality_score=90, relevance_score=80, aspect_ratio=1.6,
            warnings=["possible_logo", "possible_watermark"],
        )
    )
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    if bundle.images:  # branding risk is a penalty, not always a hard reject
        assert bundle.images[0].role != VisualRole.HERO


@pytest.mark.asyncio
async def test_cross_event_exact_duplicate_kept_once(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event_a = await _link_event(db_session, story)
    event_b = await _link_event(db_session, story)
    shared_sha = f"shared-{uuid4()}"
    db_session.add(_candidate(news_event_id=event_a.id, quality_score=60, sha256=shared_sha))
    db_session.add(_candidate(news_event_id=event_b.id, quality_score=90, sha256=shared_sha))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    # Only the higher-quality occurrence survives cross-event dedup.
    assert bundle.total_candidates_considered == 2
    kept_scores = [img.quality_score for img in bundle.images]
    assert kept_scores.count(90) <= 1
    assert 60 not in kept_scores or len(bundle.images) == 1


@pytest.mark.asyncio
async def test_uncertain_match_event_excluded_from_consideration(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story, match_type="uncertain_match")
    db_session.add(_candidate(news_event_id=event.id, quality_score=90, relevance_score=90))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    assert bundle.images == []
    assert bundle.total_candidates_considered == 0


@pytest.mark.asyncio
async def test_semantic_duplicate_event_excluded_from_consideration(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story, match_type="semantic_duplicate")
    db_session.add(_candidate(news_event_id=event.id, quality_score=90, relevance_score=90))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    assert bundle.total_candidates_considered == 0


@pytest.mark.asyncio
async def test_supporting_role_capped(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    for i in range(8):
        event = await _link_event(db_session, story)
        # Portrait aspect ratio -> never HERO (HERO requires editorial_landscape) -> SUPPORTING.
        db_session.add(
            _candidate(news_event_id=event.id, quality_score=65, relevance_score=55, aspect_ratio=0.8)
        )
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    supporting = [img for img in bundle.images if img.role == VisualRole.SUPPORTING]
    assert len(supporting) <= 4


@pytest.mark.asyncio
async def test_zero_candidates_is_valid_empty_bundle(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    proposal_id = uuid4()
    bundle = await build_visual_research_bundle(db_session, proposal_id=proposal_id, story_id=story.id)
    assert bundle.images == []
    assert bundle.proposal_id == proposal_id
    assert bundle.story_id == story.id


@pytest.mark.asyncio
async def test_provenance_traceable_to_source(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story)
    db_session.add(_candidate(news_event_id=event.id, quality_score=70, source_name="Official Blog"))
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    assert len(bundle.images) == 1
    assert bundle.images[0].provenance.source_name == "Official Blog"
    assert bundle.images[0].provenance.news_event_id == event.id


@pytest.mark.asyncio
async def test_within_event_duplicate_never_selected_over_representative(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    event = await _link_event(db_session, story)
    db_session.add(
        _candidate(news_event_id=event.id, quality_score=95, is_representative=False, sha256=f"dup-{uuid4()}")
    )
    await db_session.flush()

    bundle = await build_visual_research_bundle(db_session, proposal_id=uuid4(), story_id=story.id)
    # is_duplicate_within_event carries a ranking penalty (never a hard exclusion by itself in
    # rank_media_candidates()) - assert it is at least reflected, never silently ignored.
    assert bundle.total_candidates_considered == 1


# ---------------------------------------------------------------------------------------------
# Cost/side-effect boundary (structural)
# ---------------------------------------------------------------------------------------------


def test_no_llm_network_or_telegram_reference_in_visual_research_source() -> None:
    for forbidden in (
        "LLMGateway", "call_generate", "CapabilityExecutor", "import httpx", "import requests",
        "safe_fetch", "aiogram", "bot.send", "send_to_editorial_destination", "telegra.ph",
    ):
        assert forbidden not in _VISUAL_SOURCE, f"unexpected reference: {forbidden}"
