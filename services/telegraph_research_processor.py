"""TELEGRAPH Checkpoint 3: the one callable that turns an APPROVED, unclaimed
`TelegraphTopicProposal` into a claimed proposal + a completed (or FAILED) TELEGRAPH_RESEARCH
`EditorialTask`.

`process_approved_telegraph_proposal(proposal_id)` is the ONLY entry point this checkpoint
exposes for downstream processing - nothing in this codebase calls it automatically (no
scheduler/worker/cron, no change to bot/handlers/telegraph_shortlist.py's own APPROVED-only
callback). A future checkpoint decides how/when approved proposals are picked up; this one only
proves the mechanism is correct for exactly one, explicitly-selected proposal at a time.

Failure/retry semantics (Checkpoint 3 brief's own explicit requirement): `consumed_at` means
"claimed for downstream processing," never "research succeeded." Once claimed, `consumed_at` is
NEVER reset to NULL by this module, regardless of what happens next - not on task-creation
failure, not on a research call failure, not on a workflow timeout. The linked `EditorialTask`
(`proposal.research_task_id`) is the durable, inspectable record of what was actually attempted:
COMPLETED means the deep-research call succeeded and its structured output is in
`task.workflow["step_results"]`; FAILED means it did not, with the real error preserved on
`task.workflow["failure"]` (workflows.runner.WorkflowRunner's own existing, unmodified failure
persistence). Retrying a FAILED task's own step attempts is governed entirely by the existing,
unmodified `WorkflowStepDefinition.max_attempts` bounded-retry mechanism inside WorkflowRunner -
no new retry loop is introduced here. Proposal-claim exactly-once-ness and task-level bounded
retry are deliberately distinct: the proposal is claimed once, ever; the one task attached to it
may retry its own step attempts up to its own bound before finally succeeding or failing.

Correctness-review fix (post-Checkpoint-3): claim, task creation, and linkage are now ONE atomic
DB transaction, not three independent commits. `claim_approved_telegraph_proposal()`, `services.
workflow_service.create_task()`, and `link_research_task()` each gained an additive, backward-
compatible `commit: bool = True` parameter (every pre-existing caller/test is unaffected - the
default is unchanged); this module is the only caller that passes `commit=False` to all three,
then issues exactly one `session.commit()` covering all of them. If the process crashes or an
exception is raised anywhere inside that block, NOTHING in it is durable - Postgres rolls the
whole uncommitted transaction back, so the proposal is never left claimed without its task. The
"claimed but unlinked" state (`consumed_at IS NOT NULL AND research_task_id IS NULL`) can
therefore no longer arise from any code path that runs to completion or raises a normal
exception - only a true crash between Postgres durably committing the transaction and this
process's own confirmation of that commit could still produce it (an infinitesimally narrow
window no application-level transaction grouping can close, since it also cannot be
disambiguated from "the commit never happened at all"). services.
telegraph_research_recovery.py provides read-only DETECTION for that residual case (a monitoring
query, not an auto-healer - see that module's own docstring for why silently guessing what to do
next would be unsafe).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from database.models.editorial_task import TaskPriority
from database.models.story import Story
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowType
from services import workflow_service
from services.cost_tracker import CostTracker
from services.pricing_catalog import PricingCatalog
from services.telegraph_shortlist_service import claim_approved_telegraph_proposal, link_research_task
from workflows.runner import WorkflowRunner

# Reasoned default (TaskPriority.C, the lowest tier): TELEGRAPH deep research is a deliberate,
# human-triggered background task, never time-sensitive the way NEWS_ANALYSIS/CONTENT_GENERATION
# are - not fit to any real prioritization data yet, matching this codebase's own established
# "reasoned default, refine later" convention.
_TELEGRAPH_RESEARCH_TASK_PRIORITY = TaskPriority.C


@dataclass(frozen=True)
class TelegraphResearchProcessingOutcome:
    """The result `process_approved_telegraph_proposal()` returns. `claimed=False` means the
    proposal was not claimable (pending/rejected/already-consumed/nonexistent) - `task_id` and
    `run_result` are both `None` in that case, and (this is the structurally-enforced cost
    boundary) no LLM Gateway call was ever attempted."""

    claimed: bool
    proposal_id: UUID
    task_id: UUID | None
    run_result: WorkflowRunResult | None


async def process_approved_telegraph_proposal(
    session: AsyncSession,
    proposal_id: UUID,
    *,
    capability_registry: CapabilityRegistry,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
    now: datetime | None = None,
) -> TelegraphResearchProcessingOutcome:
    """Claim -> create+link EditorialTask -> run its TELEGRAPH_RESEARCH workflow. Returns without
    ever reaching the LLM Gateway if the claim itself fails (test boundary: pending/rejected/
    already-consumed proposals produce zero Gateway invocations, structurally, not by convention -
    the claim always happens first and always short-circuits).

    `cost_tracker`/`pricing_catalog` are optional, mirroring `CapabilityExecutor`'s own
    constructor - omitting them means no `AIExecution` row is recorded (the safe default for
    tests); a real caller passes the same `AIIntegrationLayer.cost_tracker`/`pricing_catalog`
    every other workflow's real call site already uses, so TELEGRAPH research spend is
    attributed through the exact same `AIExecution` table (task_id/event_id/workflow_name=
    "TELEGRAPH_RESEARCH"/capability=RESEARCH), never a parallel ledger.
    """
    # Atomic block (correctness-review fix): claim + task creation + linkage share ONE
    # transaction. Every step below passes commit=False; the single session.commit() after the
    # block is what makes all three durable together, or none of them at all. Deliberately no
    # try/except-rollback wrapper here: this codebase's own convention (WorkflowRunner,
    # CapabilityExecutor) is that the CALLER owns session lifecycle around a call that can raise -
    # an exception here simply means this block's own session.commit() was never reached, so
    # nothing it did is durable; the caller's session teardown (a fresh session per real attempt,
    # matching worker/analysis_cycle.py's/scripts/run_content_generation.py's own established
    # per-cycle session pattern) is what actually discards the uncommitted work. Never a partial
    # commit, never two commits.
    claimed = await claim_approved_telegraph_proposal(session, proposal_id, now=now, commit=False)
    if claimed is None:
        return TelegraphResearchProcessingOutcome(
            claimed=False, proposal_id=proposal_id, task_id=None, run_result=None,
        )

    story = await session.get(Story, claimed.story_id)
    assert story is not None  # TelegraphTopicProposal.story_id is a NOT NULL FK to a real Story

    # Reuses services.workflow_service.create_task() - the same, unmodified function every other
    # real EditorialTask creation path in this codebase already uses (never a hand-rolled
    # EditorialTask insert here) - it resolves the TELEGRAPH_RESEARCH WorkflowDefinition from the
    # registry itself (workflow_version, first step name), and its own existing duplicate-active-
    # task guard (one task per (event_id, workflow_type)) applies here exactly as it does
    # everywhere else. If this raises (e.g. DuplicateActiveTaskError), the claim UPDATE above is
    # NOT yet committed - it propagates up undone, together with the failed task creation.
    task_read = await workflow_service.create_task(
        session,
        EditorialTaskCreate(
            event_id=story.first_event_id, workflow_type=WorkflowType.TELEGRAPH_RESEARCH,
            priority=_TELEGRAPH_RESEARCH_TASK_PRIORITY,
        ),
        commit=False,
    )

    linked = await link_research_task(session, proposal_id, task_read.id, commit=False)
    assert linked is not None  # proposal_id was just resolved via a successful claim above

    await session.commit()  # atomic: claim + task creation + link, all together or none

    executor = CapabilityExecutor(
        session, task_read.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
    )
    runner = WorkflowRunner(executor)
    run_result = await runner.run(session, task_read.id)

    return TelegraphResearchProcessingOutcome(
        claimed=True, proposal_id=proposal_id, task_id=task_read.id, run_result=run_result,
    )
