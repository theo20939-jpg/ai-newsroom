"""NINJA PULSE RECAP Phase R2 integration, Phase C.0: the one callable that turns a Story into a
completed (or FAILED) EVENT_RECAP `EditorialTask`. Direct structural sibling of services.
telegraph_article_processor.generate_article_for_researched_proposal() - same shape, same
discipline, adapted for the one real difference: EVENT_RECAP's input is already a Story directly
(no separate proposal/shortlist indirection - services/event_recap.py's own R1/R2 layer already
does the "is this Story worth recapping" determination deterministically, inside the workflow
itself, not as a caller-side artifact to look up first).

`generate_recap_for_story(story_id)` is the ONLY entry point this checkpoint exposes - nothing in
this codebase calls it automatically, exactly mirroring services.telegraph_research_processor.
process_approved_telegraph_proposal()'s own dormancy discipline (and services.
telegraph_article_processor.py's own identical one). A future checkpoint decides how/when a Story
is picked up for recap generation (scheduler/worker/CLI - explicitly out of this checkpoint's
scope).

Exactly-once mechanism (deliberately NOT a new consumed_at-style claim column, mirroring
services.telegraph_article_processor.py's own identical reasoning): services.workflow_service.
create_task()'s own existing one-task-per-(event_id, workflow_type) guard is reused directly - an
EVENT_RECAP task is anchored to `story.first_event_id` (the same anchor
`services.event_recap.EventRecapCandidate.anchor_event_id` already uses), so a second attempt at
recapping the same Story raises the same, existing `DuplicateActiveTaskError` any other
duplicate-task attempt in this codebase already raises. This function treats that exception as
"already handled" (looks up and returns the existing task instead of creating a second one) -
never as a hard failure, and never by retrying/overwriting.

No caller-side precondition guard exists here, unlike services.telegraph_article_processor.py's
own "research_task_id set AND COMPLETED" check: EVENT_RECAP has no equivalent cheap, separately-
checkable prior artifact to look up - the real "is this Story recap-eligible" determination is
`services.event_recap.build_event_recap_candidate()`'s own readiness/Story-Integrity logic,
already invoked (unmodified) inside `capabilities/executor.py`'s own EVENT_RECAP branch the moment
the workflow actually runs. Duplicating that full deterministic computation here, only to decide
whether to bother creating a task, would recompute the identical clustering/readiness work a
second time for no cost savings (it is deterministic and free, never an LLM/network call) - so a
genuinely ineligible Story is allowed to reach `CREATED` and then fail closed as `FAILED`
(`PermanentStepFailureError`, surfaced in the returned `WorkflowRunResult.step_results`), exactly
the same fail-closed outcome, one layer later than Telegraph's own equivalent check. Disclosed
here explicitly, not left implicit - a future checkpoint may choose to add a cheaper pre-check if
this turns out to matter in practice.

Disclosed, pre-existing limitation (not introduced by this checkpoint, mirrors services.
telegraph_article_processor.py's own identical disclosure): services.workflow_service.
create_task()'s own duplicate-active-task guard is a check-then-insert, not a single atomic
statement/unique constraint - two genuinely concurrent callers could theoretically both pass the
check and both insert a task for the same (event_id, workflow_type) before either commits. Out of
this checkpoint's scope to fix.

Nothing here touches services/event_recap.py, capabilities/executor.py, any workflow definition,
any worker/scheduler, Telegram, or any DB model - this file only orchestrates the already-existing
EditorialTask/WorkflowRunner/CapabilityExecutor machinery for one more WorkflowType, exactly as
services/telegraph_article_processor.py already does for TELEGRAPH_ARTICLE.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.story import Story
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowType
from services import workflow_service
from services.cost_tracker import CostTracker
from services.pricing_catalog import PricingCatalog
from workflows.errors import DuplicateActiveTaskError
from workflows.runner import WorkflowRunner

# Reasoned default, matching services.telegraph_article_processor's own identical reasoning: a
# deliberate, human-triggered background task, never time-sensitive.
_EVENT_RECAP_TASK_PRIORITY = TaskPriority.C

EventRecapGenerationStatus = Literal["story_not_found", "already_exists", "generated"]


@dataclass(frozen=True)
class EventRecapGenerationOutcome:
    story_id: UUID
    status: EventRecapGenerationStatus
    task_id: UUID | None
    run_result: WorkflowRunResult | None


async def find_event_recap_task_id(session: AsyncSession, event_id: UUID) -> UUID | None:
    """The most recent EVENT_RECAP task for this exact event_id, in any status - mirrors
    services.telegraph_article_processor.find_article_task_id()'s own established shape exactly
    (identical query pattern, different workflow_name scope: any status here, since a caller may
    want to inspect a RUNNING/FAILED recap task too, not only a COMPLETED one)."""
    stmt = (
        select(EditorialTask.id)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.EVENT_RECAP.value,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def generate_recap_for_story(
    session: AsyncSession,
    story_id: UUID,
    *,
    capability_registry: CapabilityRegistry,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> EventRecapGenerationOutcome:
    """Story lookup -> create (or find existing) EditorialTask -> run its EVENT_RECAP workflow.
    Returns without ever reaching the LLM Gateway if the Story does not exist or a task already
    exists for it (structural cost boundary, exactly like services.telegraph_article_processor.py's
    own claim-first discipline)."""
    story = await session.get(Story, story_id)
    if story is None:
        return EventRecapGenerationOutcome(
            story_id=story_id, status="story_not_found", task_id=None, run_result=None,
        )

    try:
        task_read = await workflow_service.create_task(
            session,
            EditorialTaskCreate(
                event_id=story.first_event_id, workflow_type=WorkflowType.EVENT_RECAP,
                priority=_EVENT_RECAP_TASK_PRIORITY,
            ),
        )
    except DuplicateActiveTaskError:
        existing_task_id = await find_event_recap_task_id(session, story.first_event_id)
        return EventRecapGenerationOutcome(
            story_id=story_id, status="already_exists", task_id=existing_task_id, run_result=None,
        )

    executor = CapabilityExecutor(
        session, task_read.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
    )
    runner = WorkflowRunner(executor)
    run_result = await runner.run(session, task_read.id)

    return EventRecapGenerationOutcome(
        story_id=story_id, status="generated", task_id=task_read.id, run_result=run_result,
    )
