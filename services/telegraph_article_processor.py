"""TELEGRAPH Checkpoint 5: the one callable that turns an already-COMPLETED-research
`TelegraphTopicProposal` into a completed (or FAILED) TELEGRAPH_ARTICLE `EditorialTask`.

`generate_article_for_researched_proposal(proposal_id)` is the ONLY entry point this checkpoint
exposes - nothing in this codebase calls it automatically, exactly mirroring services.
telegraph_research_processor.process_approved_telegraph_proposal()'s own dormancy discipline. A
future checkpoint decides how/when a completed research task is picked up for article generation.

Exactly-once mechanism (deliberately NOT a new consumed_at-style claim column): services.
workflow_service.create_task()'s own existing one-task-per-(event_id, workflow_type) guard is
reused directly - a TELEGRAPH_ARTICLE task shares its event_id with its Story's own
TELEGRAPH_RESEARCH task (both anchor to story.first_event_id), so a second attempt at generating
an article for the same Story raises the same, existing `DuplicateActiveTaskError` any other
duplicate-task attempt in this codebase already raises. This function treats that exception as
"already handled" (looks up and returns the existing task instead of creating a second one) -
never as a hard failure, and never by retrying/overwriting.

Precondition guard (this module's own responsibility, checked BEFORE any task is created):
`proposal.research_task_id` must be set AND that task's own `status` must be `COMPLETED` - a
pending/failed/nonexistent research task means there is no Deep Research evidence to write an
article from, and this function refuses to proceed rather than letting capabilities/executor.py's
own analogous (and stricter, PermanentStepFailureError-raising) check discover it mid-workflow.
This mirrors services.telegraph_research_processor.py's own "claim first" discipline: nothing
past this guard runs (in particular, no paid article-generation call) until it passes.

Disclosed, pre-existing limitation (not introduced by this checkpoint): services.workflow_service.
create_task()'s own duplicate-active-task guard is a check-then-insert, not a single atomic
statement/unique constraint - two genuinely concurrent callers could theoretically both pass the
check and both insert a task for the same (event_id, workflow_type) before either commits. This
pre-existing gap is out of this checkpoint's scope to fix (touching a shared, already-relied-upon
function's locking behavior is not this narrow checkpoint's job) - disclosed here and in the
Checkpoint 5 report rather than silently left undocumented.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.story import Story
from database.models.telegraph_shortlist import TelegraphTopicProposal
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowType
from services import workflow_service
from services.cost_tracker import CostTracker
from services.pricing_catalog import PricingCatalog
from workflows.errors import DuplicateActiveTaskError
from workflows.runner import WorkflowRunner

# Reasoned default, matching services.telegraph_research_processor's own identical reasoning:
# a deliberate, human-triggered background task, never time-sensitive.
_TELEGRAPH_ARTICLE_TASK_PRIORITY = TaskPriority.C

ArticleGenerationStatus = Literal["not_researched", "research_not_complete", "already_exists", "generated"]


@dataclass(frozen=True)
class ArticleGenerationOutcome:
    proposal_id: UUID
    status: ArticleGenerationStatus
    task_id: UUID | None
    run_result: WorkflowRunResult | None


async def find_article_task_id(session: AsyncSession, event_id: UUID) -> UUID | None:
    """The most recent TELEGRAPH_ARTICLE task for this exact event_id, in any status - mirrors
    services.analysis_reuse.find_source_news_analysis_task_id()'s own established shape
    (identical query pattern, different workflow_name/status scope: any status here, since a
    caller may want to inspect a RUNNING/FAILED article task too, not only a COMPLETED one)."""
    stmt = (
        select(EditorialTask.id)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.TELEGRAPH_ARTICLE.value,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def generate_article_for_researched_proposal(
    session: AsyncSession,
    proposal_id: UUID,
    *,
    capability_registry: CapabilityRegistry,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> ArticleGenerationOutcome:
    """Guard -> create (or find existing) EditorialTask -> run its TELEGRAPH_ARTICLE workflow.
    Returns without ever reaching the LLM Gateway if the guard fails or a task already exists for
    this Story (structural cost boundary, exactly like services.telegraph_research_processor.py's
    own claim-first discipline)."""
    proposal = await session.get(TelegraphTopicProposal, proposal_id)
    if proposal is None or proposal.research_task_id is None:
        return ArticleGenerationOutcome(
            proposal_id=proposal_id, status="not_researched", task_id=None, run_result=None,
        )

    research_task = await session.get(EditorialTask, proposal.research_task_id)
    if research_task is None or research_task.status != TaskStatus.COMPLETED:
        return ArticleGenerationOutcome(
            proposal_id=proposal_id, status="research_not_complete", task_id=None, run_result=None,
        )

    story = await session.get(Story, proposal.story_id)
    assert story is not None  # TelegraphTopicProposal.story_id is a NOT NULL FK to a real Story

    try:
        task_read = await workflow_service.create_task(
            session,
            EditorialTaskCreate(
                event_id=story.first_event_id, workflow_type=WorkflowType.TELEGRAPH_ARTICLE,
                priority=_TELEGRAPH_ARTICLE_TASK_PRIORITY,
            ),
        )
    except DuplicateActiveTaskError:
        existing_task_id = await find_article_task_id(session, story.first_event_id)
        return ArticleGenerationOutcome(
            proposal_id=proposal_id, status="already_exists", task_id=existing_task_id, run_result=None,
        )

    executor = CapabilityExecutor(
        session, task_read.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
    )
    runner = WorkflowRunner(executor)
    run_result = await runner.run(session, task_read.id)

    return ArticleGenerationOutcome(
        proposal_id=proposal_id, status="generated", task_id=task_read.id, run_result=run_result,
    )
