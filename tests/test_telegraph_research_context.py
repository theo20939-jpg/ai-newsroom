"""TELEGRAPH Checkpoint 3: services.telegraph_research_context - deterministic article research
bundle construction. Real Postgres (db_session fixture, rolled back per test).

Reuses tests.test_telegraph_topic_candidates's own established fixtures - the same cross-file
reuse convention tests/test_telegraph_shortlist_service.py already established.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.telegraph_research_context import build_article_research_bundle, render_bundle_text
from tests.test_telegraph_shortlist_service import _require_shortlist_tables
from tests.test_telegraph_topic_candidates import _make_analyzed_event, _make_anchor_event, _make_source

_CONTEXT_SOURCE = Path("services/telegraph_research_context.py").read_text(encoding="utf-8")


async def _make_researched_event(
    db_session: AsyncSession, source: NewsSource, story: Story, *,
    match_type: str, published_at: datetime, facts: list[str], gaps: list[str],
    significance: float, angle: str, recommendation: str = "Публиковать.",
) -> NewsEvent:
    """Like tests.test_telegraph_topic_candidates._make_analyzed_event(), but with a real
    "research" step_result (facts/gaps) and an "intelligence" step_result that includes "angle" -
    that module's own fixture only ever needed scoring/significance/recommendation (Checkpoint
    1's own scope), never facts/gaps/angle, which THIS module's bundle builder also reads."""
    event = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title=f"Event {uuid.uuid4()}", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=published_at, collected_at=published_at,
    )
    db_session.add(event)
    await db_session.flush()
    db_session.add(
        NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9)
    )
    task = EditorialTask(
        id=uuid.uuid4(), event_id=event.id, priority=TaskPriority.B, status=TaskStatus.COMPLETED,
        workflow={
            "workflow_name": "NEWS_ANALYSIS",
            "step_results": [
                {
                    "step_name": "research", "status": "SUCCESS",
                    "result": {"facts": facts, "confidence": 0.9, "gaps": gaps},
                },
                {
                    "step_name": "intelligence", "status": "SUCCESS",
                    "result": {"significance": significance, "angle": angle, "recommendation": recommendation},
                },
            ],
        },
    )
    db_session.add(task)
    await db_session.flush()
    return event


async def _seed_story(
    db_session: AsyncSession, *, title: str = "Bundle test story",
) -> Story:
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title=title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    return story


@pytest.mark.asyncio
async def test_9_one_story_aggregates_contributing_events(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title="Aggregation story", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=anchor.id, event_count=2,
    )
    db_session.add(story)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="new_story", published_at=now,
        score=80, significance=7.0, acquisition_status="FULL_TEXT",
    )
    other_source = await _make_source(db_session)
    await _make_analyzed_event(
        db_session, other_source, story, match_type="story_update", published_at=now + timedelta(hours=1),
        score=85, significance=8.0, acquisition_status="FULL_TEXT",
    )

    bundle = await build_article_research_bundle(db_session, story)
    assert bundle.story_id == story.id
    assert len(bundle.chronology) == 2


@pytest.mark.asyncio
async def test_10_story_update_contributes(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="story_update", published_at=now,
        score=70, significance=6.0,
    )
    bundle = await build_article_research_bundle(db_session, story)
    match_types = {entry.match_type for entry in bundle.chronology}
    assert "story_update" in match_types


@pytest.mark.asyncio
async def test_11_supporting_source_contributes(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="supporting_source", published_at=now,
        score=70, significance=6.0,
    )
    bundle = await build_article_research_bundle(db_session, story)
    match_types = {entry.match_type for entry in bundle.chronology}
    assert "supporting_source" in match_types


@pytest.mark.asyncio
async def test_12_semantic_duplicate_not_independent_evidence(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    now = datetime.now(timezone.utc)
    dup_source = await _make_source(db_session)
    await _make_analyzed_event(
        db_session, dup_source, story, match_type="semantic_duplicate", published_at=now,
        score=99, significance=10.0,
    )
    bundle = await build_article_research_bundle(db_session, story)
    # Never appears in chronology (not contributing) - only counted as a dedup signal.
    assert all(entry.match_type != "semantic_duplicate" for entry in bundle.chronology)
    assert bundle.dedup_duplicate_count == 1


@pytest.mark.asyncio
async def test_13_uncertain_match_excluded_entirely(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="uncertain_match", published_at=now,
        score=50, significance=5.0,
    )
    bundle = await build_article_research_bundle(db_session, story)
    assert all(entry.match_type != "uncertain_match" for entry in bundle.chronology)
    # Not even counted as a dedup/history signal - fully excluded, per the checkpoint's own
    # stricter "must not be presented as confirmed evidence" requirement for this match type.
    assert bundle.dedup_duplicate_count == 0


@pytest.mark.asyncio
async def test_14_source_provenance_preserved(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="story_update", published_at=now,
        score=70, significance=6.0,
    )
    bundle = await build_article_research_bundle(db_session, story)
    assert len(bundle.source_evidence) >= 1
    assert bundle.source_evidence[0].source == source.name


@pytest.mark.asyncio
async def test_15_acquisition_status_preserved(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="story_update", published_at=now,
        score=70, significance=6.0, acquisition_status="FULL_TEXT",
    )
    bundle = await build_article_research_bundle(db_session, story)
    assert bundle.source_evidence[0].best_acquisition_status == "FULL_TEXT"


@pytest.mark.asyncio
async def test_16_prior_news_research_facts_and_gaps_reused(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_researched_event(
        db_session, source, story, match_type="story_update", published_at=now,
        facts=["Company X released product Y."], gaps=["Pricing not disclosed."],
        significance=6.0, angle="product launch",
    )
    bundle = await build_article_research_bundle(db_session, story)
    assert "Company X released product Y." in bundle.confirmed_facts
    assert "Pricing not disclosed." in bundle.known_gaps


@pytest.mark.asyncio
async def test_17_intelligence_angle_significance_recommendation_reused(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_researched_event(
        db_session, source, story, match_type="story_update", published_at=now,
        facts=["Fact A."], gaps=[], significance=8.5, angle="regulatory impact",
        recommendation="Публиковать как основную новость.",
    )
    bundle = await build_article_research_bundle(db_session, story)
    assert bundle.representative_significance == pytest.approx(8.5)
    assert bundle.representative_angle == "regulatory impact"
    assert bundle.representative_recommendation == "Публиковать как основную новость."


@pytest.mark.asyncio
async def test_18_bundle_ordering_deterministic(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    now = datetime.now(timezone.utc)
    for i in range(3):
        src = await _make_source(db_session)
        await _make_analyzed_event(
            db_session, src, story, match_type="story_update",
            published_at=now + timedelta(hours=i), score=70, significance=6.0,
        )
    first = await build_article_research_bundle(db_session, story)
    second = await build_article_research_bundle(db_session, story)
    assert [e.event_id for e in first.chronology] == [e.event_id for e in second.chronology]
    # Oldest-first ordering.
    published_ats = [e.published_at for e in first.chronology]
    assert published_ats == sorted(published_ats)


@pytest.mark.asyncio
async def test_19_bundle_is_bounded(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    now = datetime.now(timezone.utc)
    for i in range(30):
        src = await _make_source(db_session)
        await _make_analyzed_event(
            db_session, src, story, match_type="story_update",
            published_at=now + timedelta(hours=i), score=70, significance=6.0,
        )
    bundle = await build_article_research_bundle(db_session, story)
    assert len(bundle.chronology) <= 20
    text = render_bundle_text(bundle)
    assert len(text) <= 12_100  # _MAX_BUNDLE_TEXT_CHARS + truncation marker slack


@pytest.mark.asyncio
async def test_20_no_full_raw_workflow_dump_copied(db_session: AsyncSession) -> None:
    story = await _seed_story(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="story_update", published_at=now,
        score=70, significance=6.0,
    )
    bundle = await build_article_research_bundle(db_session, story)
    text = render_bundle_text(bundle)
    # Never dumps step_results/workflow JSON keys verbatim into the rendered text.
    assert "step_results" not in text
    assert "workflow_name" not in text
    assert "completed_steps" not in text


# ---------------------------------------------------------------------------------------------
# Cost-boundary structural proofs (this module has zero LLM/network reach)
# ---------------------------------------------------------------------------------------------


def test_no_llm_gateway_or_network_reference_in_context_source() -> None:
    for forbidden in (
        "LLMGateway", "call_generate", "CapabilityExecutor", "import httpx", "import requests",
        "safe_fetch",
    ):
        assert forbidden not in _CONTEXT_SOURCE, f"unexpected LLM/network reference: {forbidden}"
