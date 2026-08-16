"""TELEGRAPH Checkpoint 1: services.telegraph_topic_candidates.

Two layers of coverage:
- Pure unit tests for `evaluate_story_topic_candidate()` and `_summarize_story()` - hand-built
  `StoryEvidenceSummary`/`StoryTimelineEntry` inputs, no DB, no I/O of any kind.
- A small number of real-Postgres integration tests for `build_telegraph_topic_candidates()`/
  `build_story_evidence_summary()` - proves the batched SQL actually works end-to-end (one
  candidate per Story regardless of how many events are linked, recency cutoff, limit, ordering).

No LLM Gateway call, no Telegram call, no web/article fetch anywhere in this module - see the
three structural source-scan tests at the bottom (mirrors tests/test_meme_pipeline_not_live.py's
own established "read the module's own source text" convention for proving a negative).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_context import StoryTimelineEntry
from services.telegraph_topic_candidates import (
    StoryEvidenceSummary,
    TelegraphTopicCandidate,
    TopicCandidateRejection,
    _classify_evidence,
    _summarize_story,
    build_story_evidence_summary,
    build_telegraph_topic_candidates,
    evaluate_story_topic_candidate,
)

_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

_MODULE_SOURCE = Path("services/telegraph_topic_candidates.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Pure unit tests: evaluate_story_topic_candidate()
# ---------------------------------------------------------------------------------------------


def _summary(**overrides: Any) -> StoryEvidenceSummary:
    """A strong, fully-eligible default - each test overrides only the field(s) it cares about,
    mirroring this codebase's own established fixture-factory convention (e.g. tests/
    test_router_media_integration.py::_fake_candidate())."""
    defaults: dict[str, Any] = dict(
        story_id=uuid4(), story_title="Strong story", story_category=EventCategory.AI,
        topic_bucket="product", event_count=2, total_linked_event_count=2,
        latest_event_at=_NOW - timedelta(hours=2), source_diversity_proxy=2,
        match_type_counts={"new_story": 1, "story_update": 1}, max_score=85, max_significance=8.0,
        representative_recommendation="Публиковать.", has_negative_recommendation=False,
        max_engagement_potential_score=70.0, best_evidence_status="FULL_TEXT",
        events_with_full_text=1, events_with_any_acquisition=1, analyzed_event_count=2,
    )
    defaults.update(overrides)
    return StoryEvidenceSummary(**defaults)


def _evaluate(summary: StoryEvidenceSummary, **kwargs: Any) -> TelegraphTopicCandidate | TopicCandidateRejection:
    kwargs.setdefault("now", _NOW)
    kwargs.setdefault("recency_cutoff_hours", 72.0)
    return evaluate_story_topic_candidate(summary, **kwargs)


def test_1_strong_multi_event_story_becomes_a_candidate() -> None:
    decision = _evaluate(_summary())
    assert isinstance(decision, TelegraphTopicCandidate)
    assert decision.topic_score > 0


def test_2_strong_single_event_story_can_still_candidate() -> None:
    decision = _evaluate(
        _summary(
            event_count=1, total_linked_event_count=1, source_diversity_proxy=1,
            match_type_counts={"new_story": 1}, max_significance=9.0, best_evidence_status="FULL_TEXT",
            analyzed_event_count=1,
        )
    )
    assert isinstance(decision, TelegraphTopicCandidate)


def test_3_high_news_score_with_weak_evidence_is_excluded() -> None:
    decision = _evaluate(
        _summary(
            max_score=95, best_evidence_status="HEADLINE_ONLY", source_diversity_proxy=1,
            events_with_full_text=0,
        )
    )
    assert isinstance(decision, TopicCandidateRejection)
    assert "evidence" in decision.reason


def test_4_low_significance_is_excluded() -> None:
    decision = _evaluate(_summary(max_significance=3.0))
    assert isinstance(decision, TopicCandidateRejection)
    assert "significance" in decision.reason


def test_4b_low_significance_ranks_below_a_stronger_topic_when_both_somehow_compared() -> None:
    """Even where a very low significance sits just above a hypothetical looser floor, it must
    never outscore a genuinely strong topic - proven here via the actual topic_score gap between
    a floor-clearing-but-weak significance and the strong default."""
    weak = _evaluate(_summary(max_significance=5.1, max_score=40, source_diversity_proxy=1, max_engagement_potential_score=None))
    strong = _evaluate(_summary())
    assert isinstance(weak, TelegraphTopicCandidate)
    assert isinstance(strong, TelegraphTopicCandidate)
    assert weak.topic_score < strong.topic_score


def test_5_explicit_negative_recommendation_with_non_strong_evidence_is_excluded() -> None:
    decision = _evaluate(
        _summary(has_negative_recommendation=True, best_evidence_status="PARTIAL_TEXT", source_diversity_proxy=1)
    )
    assert isinstance(decision, TopicCandidateRejection)
    assert "negative" in decision.reason


def test_5b_negative_recommendation_with_strong_evidence_is_penalized_not_excluded() -> None:
    decision = _evaluate(_summary(has_negative_recommendation=True, best_evidence_status="FULL_TEXT"))
    assert isinstance(decision, TelegraphTopicCandidate)
    assert decision.signals.negative_recommendation_penalty > 0
    baseline = _evaluate(_summary())
    assert isinstance(baseline, TelegraphTopicCandidate)
    assert decision.topic_score < baseline.topic_score


def test_9_stable_deterministic_ordering_via_sort_key_components() -> None:
    """Two otherwise-strong candidates with a deliberately different topic_score must always sort
    higher-score-first - proven directly against the exact key build_telegraph_topic_candidates()
    uses (topic_score DESC, freshness DESC, story_id ASC)."""
    weaker = _evaluate(_summary(max_score=40, max_engagement_potential_score=None))
    stronger = _evaluate(_summary())
    assert isinstance(weaker, TelegraphTopicCandidate)
    assert isinstance(stronger, TelegraphTopicCandidate)
    ordered = sorted(
        [weaker, stronger],
        key=lambda c: (-c.topic_score, -c.summary.latest_event_at.timestamp(), str(c.story_id)),
    )
    assert ordered == [stronger, weaker]


def test_10_tie_break_is_deterministic_by_story_id() -> None:
    story_id_a = UUID("00000000-0000-0000-0000-000000000001")
    story_id_b = UUID("00000000-0000-0000-0000-000000000002")
    a = _evaluate(_summary(story_id=story_id_a))
    b = _evaluate(_summary(story_id=story_id_b))
    assert isinstance(a, TelegraphTopicCandidate)
    assert isinstance(b, TelegraphTopicCandidate)
    assert a.topic_score == b.topic_score  # identical inputs but story_id -> genuine tie
    key = lambda c: (-c.topic_score, -c.summary.latest_event_at.timestamp(), str(c.story_id))  # noqa: E731
    ordered_once = sorted([b, a], key=key)
    ordered_again = sorted([a, b], key=key)
    assert [c.story_id for c in ordered_once] == [c.story_id for c in ordered_again] == [story_id_a, story_id_b]


def test_14_story_within_the_recency_window_is_not_stale() -> None:
    decision = _evaluate(
        _summary(latest_event_at=_NOW - timedelta(hours=48)), recency_cutoff_hours=72.0,
    )
    assert isinstance(decision, TelegraphTopicCandidate)


def test_15_story_older_than_the_recency_window_is_excluded() -> None:
    decision = _evaluate(
        _summary(latest_event_at=_NOW - timedelta(hours=200)), recency_cutoff_hours=72.0,
    )
    assert isinstance(decision, TopicCandidateRejection)
    assert "stale" in decision.reason


def test_16_missing_scoring_result_is_handled_conservatively_not_excluded() -> None:
    """Scoring is a secondary/ranking signal only (the phase brief's own explicit "article-
    worthiness is not NEWS score") - a Story with no scoring result at all (e.g. the scoring step
    failed/skipped for every contributing event) must still be eligible on significance/evidence
    alone."""
    decision = _evaluate(_summary(max_score=None))
    assert isinstance(decision, TelegraphTopicCandidate)
    assert decision.signals.score_component == 0


def test_17_missing_intelligence_is_handled_conservatively_and_excluded() -> None:
    decision = _evaluate(_summary(max_significance=None))
    assert isinstance(decision, TopicCandidateRejection)
    assert "significance" in decision.reason


def test_18_no_acquisition_data_and_no_corroboration_is_excluded() -> None:
    decision = _evaluate(
        _summary(best_evidence_status=None, source_diversity_proxy=1, events_with_any_acquisition=0)
    )
    assert isinstance(decision, TopicCandidateRejection)
    assert "evidence" in decision.reason


def test_18b_no_acquisition_data_but_several_independent_sources_is_not_excluded() -> None:
    decision = _evaluate(
        _summary(
            best_evidence_status=None, source_diversity_proxy=3, events_with_any_acquisition=0,
            event_count=3, total_linked_event_count=3,
        )
    )
    assert isinstance(decision, TelegraphTopicCandidate)
    assert decision.signals.evidence_tier == "moderate"


def test_19_already_proposed_story_is_excluded() -> None:
    story_id = uuid4()
    decision = _evaluate(_summary(story_id=story_id), already_proposed_story_ids=frozenset({story_id}))
    assert isinstance(decision, TopicCandidateRejection)
    assert "already proposed" in decision.reason


def test_missing_scoring_and_intelligence_together_is_insufficient_data() -> None:
    decision = _evaluate(_summary(analyzed_event_count=0, max_score=None, max_significance=None))
    assert isinstance(decision, TopicCandidateRejection)
    assert "insufficient data" in decision.reason


def test_evaluation_never_reads_the_wall_clock() -> None:
    """No wall-clock dependence except the explicit `now` parameter - the same call with two
    different explicit `now` values must classify a fixed `latest_event_at` differently in a
    fully predictable, deterministic way (proving `now` - not `datetime.now()` - drives the
    recency decision)."""
    fixed_latest = _NOW - timedelta(hours=100)
    still_fresh = _evaluate(_summary(latest_event_at=fixed_latest), now=_NOW, recency_cutoff_hours=200.0)
    now_stale = _evaluate(_summary(latest_event_at=fixed_latest), now=_NOW, recency_cutoff_hours=50.0)
    assert isinstance(still_fresh, TelegraphTopicCandidate)
    assert isinstance(now_stale, TopicCandidateRejection)


def test_topic_bucket_no_longer_contributes_to_topic_score() -> None:
    """2026-08-16 correctness review (Part B): two summaries identical except `topic_bucket` must
    now score IDENTICALLY - the earlier topic_bucket -> score bonus (security_incident/
    legal_regulatory weighted highest) was removed after review found no pre-existing codebase/
    docs precedent for that specific editorial-importance hierarchy. `topic_bucket` still appears
    in the rationale string (informational), just never in the numeric score."""
    security = _evaluate(_summary(topic_bucket="security_incident"))
    product = _evaluate(_summary(topic_bucket="product"))
    assert isinstance(security, TelegraphTopicCandidate)
    assert isinstance(product, TelegraphTopicCandidate)
    assert security.topic_score == product.topic_score
    assert not hasattr(security.signals, "topic_bucket_bonus")
    assert "security_incident" in security.rationale
    assert "informational only" in security.rationale


# ---------------------------------------------------------------------------------------------
# Pure unit tests: _summarize_story() - proves duplicate/uncertain events never inflate a
# Story's own signals, and that supporting sources strengthen rather than spawn a new candidate.
# ---------------------------------------------------------------------------------------------


def _entry(
    *, event_id: UUID | None = None, source: str | None = "Source A", match_type: str = "new_story",
    published_at: datetime | None = None,
) -> StoryTimelineEntry:
    return StoryTimelineEntry(
        event_id=event_id or uuid4(), source=source, published_at=published_at or _NOW,
        collected_at=_NOW, match_type=match_type, match_score=0.9, source_role=None,
        content_draft_id=None, telegram_message_id=None, delta="new_information",
        already_published=False, introduced_new_facts=[], confirmed_existing_facts=[],
    )


def _story(**overrides: Any) -> Story:
    defaults: dict[str, Any] = dict(
        id=uuid4(), title="Story title", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=uuid4(), event_count=1, created_at=_NOW,
    )
    defaults.update(overrides)
    return Story(**defaults)


def _workflow(*, score: int | None = None, significance: float | None = None, recommendation: str | None = None) -> dict[str, Any]:
    step_results = []
    if score is not None:
        step_results.append({"step_name": "scoring", "status": "SUCCESS", "result": {"score": score}})
    if significance is not None:
        step_results.append(
            {
                "step_name": "intelligence", "status": "SUCCESS",
                "result": {"significance": significance, "recommendation": recommendation},
            }
        )
    return {"workflow_name": "NEWS_ANALYSIS", "step_results": step_results}


def test_6_semantic_duplicates_do_not_inflate_the_story_summary() -> None:
    root = _entry(match_type="new_story", source="Source A")
    dup1 = _entry(match_type="semantic_duplicate", source="Source B")
    dup2 = _entry(match_type="semantic_duplicate", source="Source C")
    story = _story()
    workflows = {
        root.event_id: _workflow(score=60, significance=6.0),
        # The duplicates carry a deliberately much higher score/significance - if these leaked
        # into the aggregate, max_score/max_significance would exceed the root's own values.
        dup1.event_id: _workflow(score=99, significance=10.0),
        dup2.event_id: _workflow(score=98, significance=9.5),
    }
    summary = _summarize_story(story, [root, dup1, dup2], workflows, {})
    assert summary.event_count == 1
    assert summary.source_diversity_proxy == 1
    assert summary.max_score == 60
    assert summary.max_significance == 6.0
    assert summary.total_linked_event_count == 3


def test_6b_latest_event_at_ignores_a_fresher_non_contributing_duplicate() -> None:
    """2026-08-16 correctness review (Part A/B): the required guarantee that "old Story + only
    fresh SEMANTIC_DUPLICATE/UNCERTAIN_MATCH does NOT incorrectly become article-worthy merely
    because those match types are non-contributing" - proven directly at the `latest_event_at`
    computation itself, with DISTINCT timestamps (test_6 above uses identical timestamps for all
    entries, which cannot distinguish this from the pre-fix bug where latest_event_at was computed
    from the full timeline instead of `contributing` only)."""
    old_root_time = _NOW - timedelta(days=10)
    fresh_dup_time = _NOW
    root = _entry(match_type="new_story", source="Source A", published_at=old_root_time)
    fresh_duplicate = _entry(match_type="semantic_duplicate", source="Source B", published_at=fresh_dup_time)
    fresh_uncertain = _entry(match_type="uncertain_match", source="Source C", published_at=fresh_dup_time)
    story = _story()
    workflows = {root.event_id: _workflow(score=70, significance=7.0)}

    summary = _summarize_story(story, [root, fresh_duplicate, fresh_uncertain], workflows, {})

    assert summary.latest_event_at == old_root_time  # never the fresher non-contributing entries
    decision = evaluate_story_topic_candidate(summary, now=_NOW, recency_cutoff_hours=72.0)
    assert isinstance(decision, TopicCandidateRejection)
    assert "stale" in decision.reason


def test_7_supporting_source_strengthens_but_is_not_a_separate_candidate_input() -> None:
    root = _entry(match_type="new_story", source="Source A")
    supporting = _entry(match_type="supporting_source", source="Source B")
    story = _story()
    workflows = {
        root.event_id: _workflow(score=70, significance=7.0),
        supporting.event_id: _workflow(score=50, significance=5.0),
    }
    summary = _summarize_story(story, [root, supporting], workflows, {})
    assert summary.event_count == 2
    assert summary.source_diversity_proxy == 2
    # The stronger of the two contributing events' significance wins the "max" aggregate.
    assert summary.max_significance == 7.0


def test_negative_recommendation_detected_from_any_contributing_event() -> None:
    root = _entry(match_type="new_story", source="Source A")
    update = _entry(match_type="story_update", source="Source B")
    story = _story()
    workflows = {
        root.event_id: _workflow(score=70, significance=6.0, recommendation="Публиковать."),
        update.event_id: _workflow(
            score=60, significance=5.0, recommendation="Не использовать как самостоятельную новость.",
        ),
    }
    summary = _summarize_story(story, [root, update], workflows, {})
    assert summary.has_negative_recommendation is True


def test_uncertain_match_does_not_contribute() -> None:
    root = _entry(match_type="new_story", source="Source A")
    uncertain = _entry(match_type="uncertain_match", source="Source B")
    story = _story()
    workflows = {
        root.event_id: _workflow(score=60, significance=6.0),
        uncertain.event_id: _workflow(score=90, significance=9.0),
    }
    summary = _summarize_story(story, [root, uncertain], workflows, {})
    assert summary.event_count == 1
    assert summary.max_score == 60


def test_evidence_status_picks_the_strongest_across_contributing_events() -> None:
    root = _entry(match_type="new_story", event_id=uuid4())
    update = _entry(match_type="story_update", event_id=uuid4(), source="Source B")
    story = _story()
    acquisitions = {root.event_id: "HEADLINE_ONLY", update.event_id: "FULL_TEXT"}
    summary = _summarize_story(story, [root, update], {}, acquisitions)
    assert summary.best_evidence_status == "FULL_TEXT"
    assert summary.events_with_full_text == 1
    assert summary.events_with_any_acquisition == 2


@pytest.mark.parametrize(
    ("status", "diversity", "expected"),
    [
        ("FULL_TEXT", 1, "strong"),
        ("SUBSTANTIAL_TEXT", 1, "strong"),
        ("PARTIAL_TEXT", 1, "moderate"),
        ("PARTIAL_TEXT", 2, "strong"),
        (None, 1, "weak"),
        (None, 2, "weak"),
        (None, 3, "moderate"),
        ("HEADLINE_ONLY", 1, "weak"),
        ("FETCH_FAILED", 5, "moderate"),
    ],
)
def test_classify_evidence_tiers(status: str | None, diversity: int, expected: str) -> None:
    assert _classify_evidence(status, diversity) == expected


# ---------------------------------------------------------------------------------------------
# Real-Postgres integration tests: build_telegraph_topic_candidates() / build_story_evidence_
# summary() - proves the batched SQL, one-candidate-per-Story guarantee, recency cutoff, and
# limit/ordering behavior end-to-end. Rolled back automatically (db_session fixture).
# ---------------------------------------------------------------------------------------------


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


async def _require_tables(session: AsyncSession) -> None:
    for table in ("stories", "news_event_story_links", "editorial_tasks", "news_event_article_acquisitions"):
        if not await _table_exists(session, table):
            pytest.skip(f"{table} table not present on this DB - migration not applied here.")


async def _make_source(session: AsyncSession) -> NewsSource:
    source = NewsSource(id=uuid.uuid4(), name=f"Source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    return source


async def _make_anchor_event(session: AsyncSession, source: NewsSource) -> NewsEvent:
    """A plain, real NewsEvent solely to satisfy Story.first_event_id's FK - never itself linked
    via NewsEventStoryLink, mirroring tests/test_story_context.py's own established pattern of
    using a real event_early as both the anchor and (there) a linked event; here the anchor is
    deliberately separate from whatever events _make_analyzed_event() links under the story, since
    these tests care about the LINKED events' aggregation, not the anchor itself."""
    event = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title=f"Anchor {uuid.uuid4()}", category=EventCategory.AI,
        hash=f"anchor-{uuid.uuid4()}", published_at=datetime.now(timezone.utc), collected_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


async def _make_analyzed_event(
    session: AsyncSession, source: NewsSource, story: Story, *,
    match_type: str, published_at: datetime, score: int | None = 75,
    significance: float | None = 7.0, recommendation: str | None = "Публиковать.",
    acquisition_status: str | None = None,
) -> NewsEvent:
    event = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title=f"Event {uuid.uuid4()}", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=published_at, collected_at=published_at,
    )
    session.add(event)
    await session.flush()

    session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9))

    step_results = []
    if score is not None:
        step_results.append({"step_name": "scoring", "status": "SUCCESS", "result": {"score": score}})
    if significance is not None:
        step_results.append(
            {
                "step_name": "intelligence", "status": "SUCCESS",
                "result": {"significance": significance, "recommendation": recommendation},
            }
        )
    task = EditorialTask(
        id=uuid.uuid4(), event_id=event.id, priority=TaskPriority.B, status=TaskStatus.COMPLETED,
        workflow={"workflow_name": "NEWS_ANALYSIS", "step_results": step_results},
    )
    session.add(task)

    if acquisition_status is not None:
        session.add(
            NewsEventArticleAcquisition(
                news_event_id=event.id, acquisition_status=acquisition_status,
                effective_completeness_status=acquisition_status, triggered_by="content_generation_selected",
            )
        )
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_8_several_events_for_one_story_yield_exactly_one_candidate(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title="Multi-event story", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="legal_regulatory", first_event_id=anchor.id, event_count=3,
    )
    db_session.add(story)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="new_story", published_at=now - timedelta(hours=3),
        score=80, significance=7.5, acquisition_status="FULL_TEXT",
    )
    await _make_analyzed_event(
        db_session, source, story, match_type="story_update", published_at=now - timedelta(hours=1),
        score=70, significance=6.5,
    )
    other_source = await _make_source(db_session)
    await _make_analyzed_event(
        db_session, other_source, story, match_type="supporting_source", published_at=now - timedelta(hours=2),
        score=65, significance=6.0,
    )

    candidates = await build_telegraph_topic_candidates(db_session, limit=10, now=now, recency_cutoff_hours=72.0)
    matching = [c for c in candidates if c.story_id == story.id]
    assert len(matching) == 1
    assert matching[0].summary.event_count == 3
    assert matching[0].summary.source_diversity_proxy == 2


@pytest.mark.asyncio
async def test_limit_is_respected_and_never_padded(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    story_ids = []
    for i in range(4):
        anchor = await _make_anchor_event(db_session, source)
        story = Story(
            id=uuid.uuid4(), title=f"Story {i}", category=EventCategory.AI, entities=[], keywords=[],
            topic_bucket="product", first_event_id=anchor.id, event_count=1,
        )
        db_session.add(story)
        await db_session.flush()
        story_ids.append(story.id)
        await _make_analyzed_event(
            db_session, source, story, match_type="new_story", published_at=now - timedelta(hours=1),
            score=70 + i, significance=7.0, acquisition_status="FULL_TEXT",
        )

    candidates = await build_telegraph_topic_candidates(db_session, limit=2, now=now, recency_cutoff_hours=72.0)
    matching = [c for c in candidates if c.story_id in story_ids]
    assert len(matching) <= 2


@pytest.mark.asyncio
async def test_zero_candidates_is_valid_when_every_story_is_weak(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title="Weak story", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    await _make_analyzed_event(
        db_session, source, story, match_type="new_story", published_at=now - timedelta(hours=1),
        score=90, significance=2.0,  # high score, very low significance - must not qualify
    )

    candidates = await build_telegraph_topic_candidates(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    assert story.id not in [c.story_id for c in candidates]


@pytest.mark.asyncio
async def test_recency_cutoff_excludes_a_story_outside_the_sql_scan_window(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    anchor = await _make_anchor_event(db_session, source)
    stale_story = Story(
        id=uuid.uuid4(), title="Old story", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=anchor.id, event_count=1,
        updated_at=now - timedelta(hours=500),
    )
    db_session.add(stale_story)
    await db_session.flush()
    await _make_analyzed_event(
        db_session, source, stale_story, match_type="new_story", published_at=now - timedelta(hours=500),
        score=90, significance=9.0, acquisition_status="FULL_TEXT",
    )

    candidates = await build_telegraph_topic_candidates(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    assert stale_story.id not in [c.story_id for c in candidates]


@pytest.mark.asyncio
async def test_story_updated_at_is_bumped_when_a_contributing_event_is_linked(db_session: AsyncSession) -> None:
    """2026-08-16 correctness review (Part A): empirically reproduces services/triage_
    orchestrator.py::_apply_story_memory()'s own real STORY_UPDATE/SUPPORTING_SOURCE write-path
    mutation (`matched_story.event_count += 1`, in the same transaction as the new
    NewsEventStoryLink) against the real schema - proves Story.updated_at's onupdate=func.now()
    actually fires as a result (not just argued from SQLAlchemy semantics), and that the SQL
    recency prefilter (_fetch_recent_stories(), bounded by Story.updated_at) therefore still
    includes an "old" Story once a genuinely fresh contributing event is linked to it - the exact
    "old Story row + fresh contributing NewsEvent -> Story is still considered" guarantee."""
    await _require_tables(db_session)
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    old_time = datetime.now(timezone.utc) - timedelta(days=5)
    story = Story(
        id=uuid.uuid4(), title="Old story, about to get a fresh update", category=EventCategory.AI,
        entities=[], keywords=[], topic_bucket="product", first_event_id=anchor.id, event_count=1,
        created_at=old_time, updated_at=old_time,
    )
    db_session.add(story)
    await db_session.flush()

    fresh_now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="story_update", published_at=fresh_now,
        score=80, significance=8.0, acquisition_status="FULL_TEXT",
    )
    # The exact real write-path mutation - services/triage_orchestrator.py's own STORY_UPDATE/
    # SUPPORTING_SOURCE branch, in the same transaction as the NewsEventStoryLink insert above.
    story.event_count += 1
    await db_session.flush()
    await db_session.refresh(story)

    assert story.updated_at > old_time + timedelta(hours=1)  # actually bumped, not still old

    candidates = await build_telegraph_topic_candidates(
        db_session, limit=10, now=fresh_now, recency_cutoff_hours=72.0,
    )
    assert story.id in [c.story_id for c in candidates]


@pytest.mark.asyncio
async def test_old_story_with_only_a_fresh_duplicate_is_not_article_worthy(db_session: AsyncSession) -> None:
    """2026-08-16 correctness review (Part A): end-to-end proof that a fresh SEMANTIC_DUPLICATE
    link cannot make an otherwise-stale Story pass the recency gate. The SQL prefilter DOES
    (correctly, safely) include this Story - the duplicate link still bumps Story.updated_at, per
    services/triage_orchestrator.py's own write path - but the pure, contributing-only
    `latest_event_at` computed in _summarize_story() must still reject it as stale."""
    await _require_tables(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title="Old story with a fresh rehash", category=EventCategory.AI,
        entities=[], keywords=[], topic_bucket="product", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()

    # The Story's only real substance is old - well outside the 72h recency window.
    await _make_analyzed_event(
        db_session, source, story, match_type="new_story", published_at=now - timedelta(days=10),
        score=85, significance=8.5, acquisition_status="FULL_TEXT",
    )
    # A fresh semantic_duplicate is linked today - this is real Story Memory behavior (a
    # syndicated rehash arriving later) and DOES bump Story.updated_at (see the write-path
    # analysis above), but must not resurrect the Story as a TELEGRAPH candidate.
    await _make_analyzed_event(
        db_session, source, story, match_type="semantic_duplicate", published_at=now,
        score=99, significance=10.0, acquisition_status="FULL_TEXT",
    )

    candidates = await build_telegraph_topic_candidates(db_session, limit=10, now=now, recency_cutoff_hours=72.0)
    assert story.id not in [c.story_id for c in candidates]


@pytest.mark.asyncio
async def test_build_story_evidence_summary_reads_real_persisted_data(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title="Single event story", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="security_incident", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    await _make_analyzed_event(
        db_session, source, story, match_type="new_story", published_at=now - timedelta(hours=1),
        score=88, significance=8.5, acquisition_status="SUBSTANTIAL_TEXT",
    )

    summary = await build_story_evidence_summary(db_session, story)
    assert summary.story_id == story.id
    assert summary.event_count == 1
    assert summary.max_score == 88
    assert summary.max_significance == 8.5
    assert summary.best_evidence_status == "SUBSTANTIAL_TEXT"
    assert summary.topic_bucket == "security_incident"


# ---------------------------------------------------------------------------------------------
# Structural: no LLM/Gateway call, no Telegram call, no web/article-fetch call anywhere in this
# module - source-scanned, mirroring tests/test_meme_pipeline_not_live.py's own convention.
# ---------------------------------------------------------------------------------------------


def test_20_no_llm_gateway_call_in_module_source() -> None:
    for forbidden in ("call_generate", "LLMGateway", "gateway.generate", "capabilities.executor", "WorkflowRunner"):
        assert forbidden not in _MODULE_SOURCE, f"unexpected LLM/Gateway/workflow-execution reference: {forbidden}"


def test_21_no_telegram_call_in_module_source() -> None:
    for forbidden in ("aiogram", "bot.send", "Bot(", "telegram_routing", "send_to_editorial_destination"):
        assert forbidden not in _MODULE_SOURCE, f"unexpected Telegram reference: {forbidden}"


def test_22_no_web_or_article_fetch_call_in_module_source() -> None:
    # Checked as import statements, not bare substrings: the module's own docstrings/comments
    # legitimately name get_or_acquire()/acquire_article() (services/article_acquisition.py's own
    # fetch-triggering functions) when explaining that THIS module never calls them - a naive
    # substring check would false-positive on that explanatory text itself.
    for forbidden in ("import safe_fetch", "import httpx", "import requests"):
        assert forbidden not in _MODULE_SOURCE, f"unexpected network/fetch reference: {forbidden}"
    assert "from services.article_acquisition import" not in _MODULE_SOURCE
    assert "from integrations.http" not in _MODULE_SOURCE
