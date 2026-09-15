"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4: NEWS_DIGEST - ONE Instagram carousel every 72h
summarizing the newsroom's OWN strongest recent stories, replacing the old per-story
MAJOR-treatment NEWS->Instagram trigger (removed in the SAME step, worker/content_cycle.py -
"do NOT leave both paths live"). A normal individual NEWS story may still reach Instagram, but
only through the future TREND lane's own independent evidence - never through NEWS treatment
alone.

Cold-start rule ("Founder Plan Review" constraint #3): on first activation, the durable
`digest_schedule_state` row is initialized to the ACTIVATION timestamp, never backfilled from the
preceding 72h of historical stories - `HISTORICAL_DIGEST_BACKFILL_AUTOMATIC=false` is a hard
invariant of `get_or_initialize_schedule()` below. The first automatic digest fires 72 real hours
AFTER activation, not immediately.

Story selection: reuses the SAME scoring/topic-relevance signals `worker/content_cycle.py`'s own
NEWS eligibility scan already uses (`_extract_scoring_result()`/`classify_editorial_relevance()`,
`settings.content_generation_min_score`) - duplicated here rather than imported (this codebase's
own established per-module floor-validation convention, see `_extract_scoring_result()`'s own
docstring in worker/content_cycle.py for the precedent), since importing from `worker.*` into a
`services.*` module would be a backwards dependency. Story-deduplicates via the EXISTING
`NewsEventStoryLink` table when story_memory has ever linked any of the candidate events
(a real no-op today - story_memory_mode is "off" in production) - never a second clustering
mechanism. Never pads with weak stories: fewer than `min_stories` strong candidates in the window
is a valid, honest outcome (returns an empty list, no digest built that cycle)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.digest_schedule_state import DigestScheduleState
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.story_link import NewsEventStoryLink
from schemas.workflow import WorkflowType
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.news_editorial_relevance import OUT_OF_SCOPE, classify_editorial_relevance

DIGEST_SCHEDULE_KEY = "instagram_news_digest"
DEFAULT_DIGEST_CADENCE = timedelta(hours=72)
_MIN_STORIES = 5
_MAX_STORIES = 8


def _extract_scoring_result(workflow: dict[str, Any] | None) -> int | None:
    """Duplicated from worker/content_cycle.py's own function of the same name/shape
    intentionally - see this module's own docstring for why."""
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "scoring" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                score = result.get("score")
                if isinstance(score, int):
                    return score
    return None


def _extract_research_facts(workflow: dict[str, Any] | None) -> list[str]:
    """Duplicated from worker/content_cycle.py's own function of the same name/shape
    intentionally - see this module's own docstring for why."""
    if not workflow:
        return []
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "research" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                facts = result.get("facts")
                if isinstance(facts, list):
                    return [f for f in facts if isinstance(f, str)]
    return []


async def get_or_initialize_schedule(session: AsyncSession, *, now: datetime) -> DigestScheduleState:
    """The ONLY place a `digest_schedule_state` row is ever created. `HISTORICAL_DIGEST_BACKFILL_
    AUTOMATIC=false`: a first-ever call initializes `last_run_at=now` (the activation moment), so
    `is_digest_due()` reports False until a full cadence has elapsed AFTER activation - never
    True on the very first check."""
    row = await session.get(DigestScheduleState, DIGEST_SCHEDULE_KEY)
    if row is None:
        row = DigestScheduleState(schedule_key=DIGEST_SCHEDULE_KEY, last_run_at=now)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def is_digest_due(
    session: AsyncSession, *, now: datetime, cadence: timedelta = DEFAULT_DIGEST_CADENCE,
) -> bool:
    schedule = await get_or_initialize_schedule(session, now=now)
    return (now - schedule.last_run_at) >= cadence


async def mark_digest_run(session: AsyncSession, *, now: datetime) -> None:
    schedule = await get_or_initialize_schedule(session, now=now)
    schedule.last_run_at = now
    await session.commit()


@dataclass(frozen=True)
class DigestStoryCandidate:
    event_id: UUID
    title: str
    score: int
    facts: list[str] = field(default_factory=list)


async def select_digest_stories(
    session: AsyncSession, *, now: datetime, window: timedelta = DEFAULT_DIGEST_CADENCE,
    min_stories: int = _MIN_STORIES, max_stories: int = _MAX_STORIES,
) -> list[DigestStoryCandidate]:
    """Every COMPLETED NEWS_ANALYSIS event in the last `window`, score-eligible
    (`settings.content_generation_min_score`, the SAME real threshold NEWS eligibility already
    uses) and topically in-scope (`classify_editorial_relevance()`, the SAME real EN/RU tech-news
    classifier), Story-deduplicated (best-scoring event per Story cluster), ranked by score
    DESC, capped at `max_stories`. Returns `[]` - a legitimate outcome, not an error - whenever
    fewer than `min_stories` strong candidates exist; NEVER pads with a weaker story to reach the
    minimum."""
    cutoff = now - window
    stmt = (
        select(EditorialTask.event_id, EditorialTask.workflow, NewsEvent.title, NewsEvent.content)
        .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
        .where(
            EditorialTask.status == TaskStatus.COMPLETED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.updated_at >= cutoff,
        )
        .order_by(EditorialTask.updated_at.desc())
    )
    rows = (await session.execute(stmt)).all()

    scored: list[DigestStoryCandidate] = []
    seen_event_ids: set[UUID] = set()
    for event_id, workflow, title, content in rows:
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        score = _extract_scoring_result(workflow)
        if score is None or score < settings.content_generation_min_score:
            continue
        if classify_editorial_relevance(title, content).tier == OUT_OF_SCOPE:
            continue
        scored.append(DigestStoryCandidate(event_id=event_id, title=title, score=score, facts=_extract_research_facts(workflow)))

    story_by_event: dict[UUID, Any] = {}
    if scored:
        event_ids = [c.event_id for c in scored]
        link_rows = (await session.execute(
            select(NewsEventStoryLink.news_event_id, NewsEventStoryLink.story_id)
            .where(NewsEventStoryLink.news_event_id.in_(event_ids))
        )).all()
        story_by_event = {news_event_id: story_id for news_event_id, story_id in link_rows}

    return rank_and_gate_candidates(
        scored, story_by_event=story_by_event, min_stories=min_stories, max_stories=max_stories,
    )


def rank_and_gate_candidates(
    candidates: list[DigestStoryCandidate], *, story_by_event: dict[UUID, Any] | None = None,
    min_stories: int = _MIN_STORIES, max_stories: int = _MAX_STORIES,
) -> list[DigestStoryCandidate]:
    """The pure decision core of `select_digest_stories()` - Story-deduplication (best-scoring
    event per Story cluster), rank-by-score, the min/max gate. Split out from the DB-querying
    function above so this decision logic is directly, deterministically unit-testable with a
    plain Python list of candidates, independent of database state."""
    story_by_event = story_by_event or {}
    deduplicated = list(candidates)
    if story_by_event:
        best_per_story: dict[Any, DigestStoryCandidate] = {}
        standalone: list[DigestStoryCandidate] = []
        for candidate in candidates:
            story_id = story_by_event.get(candidate.event_id)
            if story_id is None:
                standalone.append(candidate)
                continue
            current_best = best_per_story.get(story_id)
            if current_best is None or candidate.score > current_best.score:
                best_per_story[story_id] = candidate
        deduplicated = standalone + list(best_per_story.values())

    deduplicated.sort(key=lambda c: c.score, reverse=True)
    # Never pads with weak stories: fewer than `min_stories` real, score-eligible candidates is a
    # valid, honest outcome - returns [] rather than shipping a thin digest.
    if len(deduplicated) < min_stories:
        return []
    return deduplicated[:max_stories]


def build_digest_opportunity(stories: list[DigestStoryCandidate], *, now: datetime) -> ContentOpportunity:
    """Assembles the ONE `ContentOpportunity(source_type=NEWS_DIGEST)` a batch of selected stories
    produces - `id` is derived from the window boundary (not a random uuid) so a re-run within the
    same cadence window (e.g. a crash-and-retry) computes the SAME identity, letting the EXISTING
    `InstagramEditorialDelivery.package_identity` idempotency mechanism (no new table) prevent a
    duplicate digest. `evidence` carries every selected story's title + real research facts -
    never a fabricated summary."""
    evidence: list[str] = []
    for story in stories:
        evidence.append(f"story: {story.title}")
        evidence.extend(story.facts)
    avg_confidence = round(sum(min(s.score, 100) / 100 for s in stories) / len(stories), 3) if stories else 0.2

    return ContentOpportunity(
        id=f"news_digest:{now.date().isoformat()}", source_type=OpportunitySourceType.NEWS_DIGEST,
        news_value=0.6, product_mention_allowed=False, evidence=evidence, confidence=avg_confidence,
    )
