"""One automation-content cycle: query eligible NEWS_ANALYSIS(COMPLETED) events, generate
CONTENT_GENERATION content for each via the existing, unmodified scripts/run_content_generation.py
pipeline, and send a Telegram notification for each resulting ContentDraft. No business logic of
its own - orchestration only (docs/phase14_autonomous_newsroom_implementation_plan.md §4)."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from aiogram import Bot
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.workflow import WorkflowType
from scripts.run_content_generation import run_content_generation_for_event
from services.telegram_notifier import send_editorial_card

logger = logging.getLogger(__name__)


@dataclass
class ContentCycleResult:
    eligible_found: int = 0
    completed: int = 0
    failed: int = 0
    notified: int = 0
    notification_failed: int = 0
    dry_run_rendered: int = 0
    event_ids: list[UUID] = field(default_factory=list)


def _extract_scoring_result(workflow: dict[str, Any] | None) -> int | None:
    """Locate the "scoring" entry in EditorialTask.workflow["step_results"] and return its
    result["score"] - None if absent (a task whose scoring step never ran or was skipped is
    defensively excluded, never defaulted to "pass"). Duplicated intentionally rather than
    imported from services/content_draft_service.py's own _copywriting_output() - that helper
    is scoped to "copywriting", a different step name and a different failure mode (raises
    instead of returning None), not a shared abstraction worth factoring out for one caller
    each (mirrors this codebase's own established per-module floor-validation duplication
    convention, e.g. capabilities/engagement_capability.py's own docstring)."""
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


async def _select_eligible_events(session: AsyncSession) -> list[UUID]:
    """SQL-side: status, workflow-name match, duplicate exclusion (§3 of the Plan - the entire
    duplicate-prevention mechanism), freshness bound (a technical safety boundary only - see the
    Plan's own §0/§3, never an editorial-freshness control), ordering, and a scan-limit cap are
    all evaluated by Postgres. Only the final, capped result rows are ever materialized into
    Python, for the score-threshold check below - the worker never loads an unbounded number of
    NEWS_ANALYSIS tasks (Plan §3's own scan-limit guarantee)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.content_generation_freshness_cutoff_hours)
    ContentGenTask = aliased(EditorialTask)

    stmt = (
        select(EditorialTask.id, EditorialTask.event_id, EditorialTask.workflow)
        .where(
            EditorialTask.status == TaskStatus.COMPLETED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.updated_at >= cutoff,
            ~exists(
                select(1)
                .select_from(ContentGenTask)
                .where(
                    ContentGenTask.event_id == EditorialTask.event_id,
                    ContentGenTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
                )
            ),
        )
        .order_by(EditorialTask.updated_at.asc(), EditorialTask.id.asc())
        .limit(settings.content_generation_scan_limit)
    )
    rows = (await session.execute(stmt)).all()

    # Score threshold applied here, in Python, over the already SQL-capped candidate set only -
    # NOT an unbounded backlog scan (bounded above by content_generation_scan_limit). Score
    # cannot be expressed in the same SQL statement: it lives at
    # workflow["step_results"][i]["result"]["score"] for the entry whose step_name == "scoring" -
    # locating an array element by a sibling field's value, then reading a nested key, inside a
    # generic (non-JSONB) JSON column is not cleanly expressible with this stack.
    eligible: list[UUID] = []
    for _task_id, event_id, workflow in rows:
        score = _extract_scoring_result(workflow)
        if score is not None and score >= settings.content_generation_min_score:
            eligible.append(event_id)
        if len(eligible) >= settings.content_generation_batch_size:
            break
    return eligible


async def run_content_cycle(
    capability_registry: CapabilityRegistry,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> ContentCycleResult:
    result = ContentCycleResult()

    async with session_factory() as session:
        event_ids = await _select_eligible_events(session)
    result.eligible_found = len(event_ids)
    result.event_ids = event_ids

    # Attempted one at a time, in selection order - identical convention to
    # worker/analysis_cycle.py, and for the same reason: bounded, predictable work per cycle;
    # no refill if one is skipped/fails.
    for event_id in event_ids:
        outcome = await run_content_generation_for_event(
            event_id, capability_registry=capability_registry, session_factory=session_factory,
        )  # scripts/run_content_generation.py - UNMODIFIED, imported not copied
        if outcome.content_draft is None:
            result.failed += 1
            continue
        result.completed += 1

        async with session_factory() as session:
            event = await session.get(NewsEvent, event_id)
        assert event is not None  # guaranteed by the FK the selecting query itself already joined on

        notification = await send_editorial_card(
            bot, settings.editorial_chat_id, outcome.content_draft, event,
            dry_run=settings.content_generation_dry_run,
        )  # never raises - always returns a NotificationOutcome, dry-run or live
        if settings.content_generation_dry_run:
            result.dry_run_rendered += 1  # expected outcome in dry-run mode, not a failure
        elif notification.sent:
            result.notified += 1
        else:
            result.notification_failed += 1
            # ContentDraft already committed - a failed notification is never rolled back and
            # never actively retried (no duplicate-notification protection for MVP; /news
            # remains the durable fallback for a lost push notification).

    logger.info(
        "content_cycle_finished",
        extra={
            "eligible_found": result.eligible_found,
            "completed": result.completed,
            "failed": result.failed,
            "notified": result.notified,
            "notification_failed": result.notification_failed,
            "dry_run_rendered": result.dry_run_rendered,
        },
    )
    return result
