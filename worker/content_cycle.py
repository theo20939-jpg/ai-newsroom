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
from sqlalchemy import exists, func, select
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
    # Phase 15 M5.8: counts drafts whose live send was withheld specifically because of a
    # "review"/"block" fact-safety verdict under fact_safety_mode == "enforce" - a strict subset
    # of dry_run_rendered (every fact-safety-suppressed send is also counted there), kept
    # separately so a cycle's own logs distinguish "global dry-run" from "fact safety intervened".
    # Always 0 outside "enforce" mode.
    fact_safety_suppressed: int = 0
    event_ids: list[UUID] = field(default_factory=list)


def _fact_safety_delivery_decision(
    base_dry_run: bool, fact_safety_mode: str, fact_safety_status: str | None
) -> tuple[bool, bool]:
    """Phase 15 M5.8 enforcement design, factored out as a pure function for direct unit testing.

    Returns `(effective_dry_run, was_fact_safety_suppressed)`. Suppression only ever applies
    under `fact_safety_mode == "enforce"` and only for a "review"/"block" verdict - a "pass"
    verdict, or any mode other than "enforce" (including a missing/None status - fact safety
    never ran), always leaves `base_dry_run` untouched."""
    suppressed = fact_safety_mode == "enforce" and fact_safety_status in ("review", "block")
    return (base_dry_run or suppressed), suppressed


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
    Plan's own §0/§3, never an editorial-freshness control - unchanged by Phase 15 M5.2, still
    `EditorialTask.updated_at >= cutoff`), ordering, and a scan-limit cap are all evaluated by
    Postgres. Only the final, capped result rows are ever materialized into Python, for the
    score-threshold check below - the worker never loads an unbounded number of NEWS_ANALYSIS
    tasks (Plan §3's own scan-limit guarantee).

    Phase 15 M5.2: ordering changed from `EditorialTask.updated_at.asc()` (oldest-task-COMPLETED-
    first - a technical FIFO, not an editorial signal) to freshest-EDITORIAL-content-first, using
    the exact same `coalesce(NewsEvent.published_at, NewsEvent.collected_at)` anchor
    `worker/analysis_cycle.py::_select_eligible_task_ids()` already established as this
    codebase's one authoritative freshness field - not a new convention. Root cause this fixes
    (docs/phase15_m5_fact_safety_report.md, "M5.2..."): after any sustained processing gap (a
    provider outage, a burst of collection), old-task-completion-first ordering can starve
    genuinely fresh, high-scoring stories behind a backlog of older-but-still-cutoff-eligible
    tasks once that backlog exceeds `content_generation_scan_limit` - freshest-first ordering
    means a truly fresh eligible story is never pushed out of the scan window by an older one,
    regardless of backlog depth. The eligibility WHERE clause (which rows qualify at all) is
    completely unchanged - only the ordering of already-eligible rows, before LIMIT, changed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.content_generation_freshness_cutoff_hours)
    ContentGenTask = aliased(EditorialTask)
    anchor = func.coalesce(NewsEvent.published_at, NewsEvent.collected_at)

    stmt = (
        select(EditorialTask.id, EditorialTask.event_id, EditorialTask.workflow)
        .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
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
        .order_by(anchor.desc(), EditorialTask.id.asc())
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
        )  # scripts/run_content_generation.py - imported, not copied (Phase 15 M5 extends its
           # ContentGenerationOutcome with fact_safety_status; the call site here is unchanged)
        if outcome.content_draft is None:
            result.failed += 1
            continue
        result.completed += 1

        async with session_factory() as session:
            event = await session.get(NewsEvent, event_id)
        assert event is not None  # guaranteed by the FK the selecting query itself already joined on

        # Phase 15 M5.8 enforcement design: the safest existing non-public mechanism is the
        # notifier's own, already-established dry_run branch (renders and logs, never calls the
        # Telegram API) - reused verbatim here, never a new suppression code path. Inert (always
        # False) unless fact_safety_mode == "enforce"; a "pass" verdict never suppresses.
        effective_dry_run, fact_safety_suppressed = _fact_safety_delivery_decision(
            settings.content_generation_dry_run, settings.fact_safety_mode, outcome.fact_safety_status
        )
        if fact_safety_suppressed:
            result.fact_safety_suppressed += 1
            logger.info(
                "content_notification_suppressed_by_fact_safety",
                extra={
                    "event_id": str(event_id), "draft_id": str(outcome.content_draft.id),
                    "fact_safety_status": outcome.fact_safety_status,
                },
            )

        notification = await send_editorial_card(
            bot, settings.editorial_chat_id, outcome.content_draft, event,
            dry_run=effective_dry_run,
        )  # never raises - always returns a NotificationOutcome, dry-run or live
        if effective_dry_run:
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
            "fact_safety_suppressed": result.fact_safety_suppressed,
        },
    )
    return result
