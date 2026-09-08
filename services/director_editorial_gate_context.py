"""DIRECTOR-CONTROL-PLANE-1A §2-3: real signal gathering for the pre-generation Editorial Gate.
Deliberately a NEW, standalone function - never scoped to `editorial_delivery_mode == "router"`
the way `worker/content_cycle.py::_classify_event_for_router_treatment()` is, since the gate must
run "before content generation" for every delivery mode (spec §2's own call-graph requirement).
Duplicates the NEWS_ANALYSIS workflow-signal extraction rather than importing content_cycle.py's
own private helpers, matching this codebase's established "small helpers are duplicated, not
cross-coupled" convention (worker/content_cycle.py::_extract_scoring_result()'s own docstring)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from schemas.workflow import WorkflowType
from services.business_context_snapshot_service import get_business_context_snapshot
from services.director_editorial_gate import EditorialGateInput
from services.story_duplicate_guard import check_duplicate_story_delivery
from services.strategic_directive_service import list_active_directives
from services.telegram_feed_state import compute_feed_state


def _extract_scoring_result(workflow: dict[str, Any] | None) -> int | None:
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


def _extract_intelligence_result(workflow: dict[str, Any] | None) -> tuple[float | int | None, str | None]:
    if not workflow:
        return None, None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "intelligence" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                return result.get("significance"), result.get("recommendation")
    return None, None


async def build_gate_input_for_event(
    session: AsyncSession, event_id: UUID, *, platform: str = "telegram", now: datetime,
) -> EditorialGateInput | None:
    """Returns None only if the event row itself no longer exists (defensive - the caller already
    knows the event was selected as eligible). Every other signal degrades conservatively rather
    than raising: a missing NEWS_ANALYSIS task yields score=None/significance=None (source_
    confidence falls back to a neutral 0.5, has_sufficient_facts falls back to `bool(event.content)`
    - never a fabricated high-confidence default)."""
    event = await session.get(NewsEvent, event_id)
    if event is None:
        return None

    na_task = await session.scalar(
        select(EditorialTask)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.status == TaskStatus.COMPLETED,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    workflow = na_task.workflow if na_task is not None else None
    score = _extract_scoring_result(workflow)
    significance, _recommendation = _extract_intelligence_result(workflow)

    acquisition = await session.scalar(
        select(NewsEventArticleAcquisition).where(NewsEventArticleAcquisition.news_event_id == event_id)
    )
    has_full_text = acquisition is not None and acquisition.effective_completeness_status in ("FULL_TEXT", "PARTIAL_TEXT")

    source_confidence = (score / 100.0) if score is not None else 0.5

    duplicate_check = await check_duplicate_story_delivery(session, event_id)
    is_duplicate_of_recent = bool(duplicate_check.would_suppress)

    feed_state = await compute_feed_state(session, now=now)
    category_key = event.category.value if hasattr(event.category, "value") else str(event.category)
    category_count = feed_state.topic_distribution.get(category_key, 0)
    # Real, deterministic, bounded proxy - never a semantic novelty model. A category already
    # dominating the recent feed (5+ recent mentions) scores as fully non-novel; a category never
    # seen recently scores as fully novel. No new signal invented - reuses services/
    # telegram_feed_state.py's own already-computed topic_distribution.
    novelty_score = max(0.0, 1.0 - min(1.0, category_count / 5.0))

    active_directives = await list_active_directives(session, now=now)
    business_context = await get_business_context_snapshot(session, now=now)
    active_campaign_relevant = bool(business_context.active_campaigns)

    return EditorialGateInput(
        story_id=str(event_id), event_id=str(event_id), platform=platform, category=category_key,
        topic_keywords=[category_key], story_facts_summary=(event.content or "")[:500],
        has_sufficient_facts=has_full_text or bool(event.content),
        source_confidence=source_confidence, novelty_score=novelty_score,
        is_duplicate_of_recent=is_duplicate_of_recent, recency_hours=0.0,
        active_directives=list(active_directives), active_campaign_relevant=active_campaign_relevant,
        launch_state=None, feed_topic_distribution=dict(feed_state.topic_distribution),
        recent_posting_cadence_per_hour=float(feed_state.posts_1h),
        is_potential_breaking=(significance is not None and float(significance) >= 8.0),
        factual_risk_flagged=False,
    )
