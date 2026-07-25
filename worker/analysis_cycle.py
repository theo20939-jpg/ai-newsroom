"""One automation-analysis cycle: query eligible NEWS_ANALYSIS tasks, claim and execute up to
news_analysis_batch_size of them, sequentially. No business logic of its own."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.workflow import WorkflowType
from workflows.errors import TaskAlreadyCompletedError, TaskAlreadyRunningError, TaskNotFoundError
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)


@dataclass
class AnalysisCycleResult:
    eligible_found: int = 0
    claimed: int = 0
    lost_races: int = 0
    completed: int = 0
    failed: int = 0
    task_ids: list[UUID] = field(default_factory=list)


async def _select_eligible_task_ids(session: AsyncSession) -> list[UUID]:
    """SQL-side filtering only - status, workflow-name JSON match, and freshness cutoff are all
    evaluated by Postgres itself; only the final, already-batch-capped result rows are ever
    materialized into Python. Never loads the full CREATED backlog.

    Uses .as_string() (not .astext, not cast(..., String)) - the generic sqlalchemy.JSON
    column's own purpose-built scalar-text extractor, compiling to Postgres's `->>` operator.
    `.astext` does not exist on this column's comparator (JSONB-only); `cast(..., String)`
    compiles but is semantically wrong (preserves JSON quoting via the `->` operator) - both
    were empirically proven broken during planning and must not be reintroduced."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.news_analysis_freshness_cutoff_hours
    )
    anchor = func.coalesce(NewsEvent.published_at, NewsEvent.collected_at)

    stmt = (
        select(EditorialTask.id)
        .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
        .where(
            EditorialTask.status == TaskStatus.CREATED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            anchor >= cutoff,
        )
        .order_by(EditorialTask.created_at.asc(), EditorialTask.id.asc())
        .limit(settings.news_analysis_batch_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def run_analysis_cycle(
    capability_registry: CapabilityRegistry,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> AnalysisCycleResult:
    result = AnalysisCycleResult()

    async with session_factory() as session:
        eligible_ids = await _select_eligible_task_ids(session)
    result.eligible_found = len(eligible_ids)
    result.task_ids = eligible_ids

    # Exactly the originally-selected candidates are attempted - never more. A lost race (another
    # worker/cycle claimed one first) is not backfilled with a replacement candidate - this keeps
    # per-cycle work exposure deterministic at <= 5 attempted claims, regardless of how many
    # actually succeed.
    for task_id in eligible_ids:
        async with session_factory() as session:
            executor = CapabilityExecutor(session, task_id, capability_registry)
            runner = WorkflowRunner(executor)
            try:
                run_result = await runner.run(session, task_id)
            except (TaskAlreadyRunningError, TaskAlreadyCompletedError):
                # Lost the race to another worker/cycle since the eligibility query ran, or the
                # task was already handled - not a cycle failure, not an error.
                result.lost_races += 1
                continue
            except TaskNotFoundError:
                # Should not occur (tasks are never deleted) - logged, not fatal to the cycle.
                logger.exception("analysis_task_vanished", extra={"task_id": str(task_id)})
                continue

            result.claimed += 1
            if run_result.status == "COMPLETED":
                result.completed += 1
            else:
                result.failed += 1

    logger.info(
        "analysis_cycle_finished",
        extra={
            "eligible_found": result.eligible_found,
            "claimed": result.claimed,
            "lost_races": result.lost_races,
            "completed": result.completed,
            "failed": result.failed,
        },
    )
    return result
