"""TELEGRAPH Checkpoint 3 correctness-review fix: detection (never automatic repair) for a
`TelegraphTopicProposal` left in the theoretically-possible but now-extremely-narrow orphaned
state: `consumed_at IS NOT NULL AND research_task_id IS NULL`.

Since services.telegraph_research_processor.process_approved_telegraph_proposal() now performs
the claim + EditorialTask creation + linkage as ONE atomic DB transaction (commit=False threaded
through claim_approved_telegraph_proposal() / services.workflow_service.create_task() /
link_research_task(), with exactly one session.commit() covering all three - see that module's
own docstring), this state can no longer arise from any code path that runs to completion or
raises a normal, catchable exception (the whole block rolls back together). It can only still
arise from a genuine process/database crash in the infinitesimally narrow window between
Postgres durably committing that one transaction and this process's own confirmation of the
commit reaching back to the caller - a window no amount of application-level transaction
grouping can close, and one that is structurally indistinguishable from "the commit never
happened at all" without external evidence.

This module is deliberately READ-ONLY plus one narrow, provably-safe repair (re-linking a task
that genuinely exists and is unambiguously this proposal's own) - it never guesses, never
fabricates a task, and never resets `consumed_at` back to `NULL`. Automatically un-claiming an
orphaned proposal would risk violating exactly-once semantics if the "orphaned" state is actually
a false read (e.g. a transaction that is still mid-flight from this process's own point of view
but has, in fact, already committed at the database level) - the safe default is to make the
condition visible to a human/operator, never to auto-heal it speculatively.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.story import Story
from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal
from schemas.workflow import WorkflowType

_ORPHAN_SCAN_SAFETY_CAP = 500


async def find_orphaned_claimed_proposals(session: AsyncSession) -> list[TelegraphTopicProposal]:
    """`consumed_at IS NOT NULL AND research_task_id IS NULL` - the exact, deterministic
    condition this module exists to detect. Bounded (never an unbounded scan), read-only, zero
    LLM/Gateway/network calls. Ordinarily returns an empty list - a non-empty result is itself
    the alert, worth a human looking at (e.g. from a periodic ops check), not something any
    automation in this codebase currently pages on."""
    stmt = (
        select(TelegraphTopicProposal)
        .where(
            TelegraphTopicProposal.consumed_at.is_not(None),
            TelegraphTopicProposal.research_task_id.is_(None),
        )
        .order_by(TelegraphTopicProposal.consumed_at.asc())
        .limit(_ORPHAN_SCAN_SAFETY_CAP)
    )
    return list((await session.execute(stmt)).scalars().all())


RecoveryStatus = Literal["relinked", "no_orphan", "unrecoverable_needs_manual_review"]


@dataclass(frozen=True)
class RecoveryOutcome:
    proposal_id: UUID
    status: RecoveryStatus
    task_id: UUID | None = None


async def recover_orphaned_claim(session: AsyncSession, proposal_id: UUID) -> RecoveryOutcome:
    """The one safe, automatic repair this module performs: if a TELEGRAPH_RESEARCH
    `EditorialTask` genuinely exists for this proposal's own Story anchor event (`event_id ==
    story.first_event_id`, `workflow_name == "TELEGRAPH_RESEARCH"`) and is not already linked to
    a DIFFERENT proposal, re-link it - this is the one case where the "orphan" is not really lost
    data, just a missing pointer (e.g. `link_research_task()`'s own commit was the one that never
    reached this process, even though the preceding task INSERT's data is, in this specific
    scenario, still visible - a theoretical residue from before this checkpoint's own atomicity
    fix, or a future regression of it). `services.workflow_service.create_task()`'s own existing
    one-task-per-(event_id, workflow_type) uniqueness guarantee is exactly what makes "the task
    for this event_id" unambiguous - never a guess among several candidates.

    Returns "no_orphan" if the proposal is not actually in the orphaned state (fails safely -
    never mutates a proposal that isn't orphaned). Returns "unrecoverable_needs_manual_review"
    when no matching task exists at all - the honest, disclosed answer: this function will NEVER
    fabricate a task or reset `consumed_at` to `NULL` to "fix" this case. A human must inspect the
    proposal and decide (see this module's own docstring for why an automatic un-claim is
    unsafe)."""
    proposal = await session.get(TelegraphTopicProposal, proposal_id)
    if (
        proposal is None
        or proposal.consumed_at is None
        or proposal.research_task_id is not None
    ):
        return RecoveryOutcome(proposal_id=proposal_id, status="no_orphan")

    story = await session.get(Story, proposal.story_id)
    if story is None:
        return RecoveryOutcome(proposal_id=proposal_id, status="unrecoverable_needs_manual_review")

    stmt = select(EditorialTask).where(
        EditorialTask.event_id == story.first_event_id,
        EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.TELEGRAPH_RESEARCH.value,
    )
    candidate_tasks = (await session.execute(stmt)).scalars().all()
    if len(candidate_tasks) != 1:
        # Zero: no task was ever created - nothing to re-link, genuinely needs manual review.
        # More than one: should be structurally impossible (create_task()'s own duplicate-active-
        # task guard forbids it), but treated as unrecoverable-by-automation rather than guessing
        # which one is "ours", per this module's own no-guessing rule.
        return RecoveryOutcome(proposal_id=proposal_id, status="unrecoverable_needs_manual_review")

    task = candidate_tasks[0]
    already_linked_elsewhere = (
        await session.execute(
            select(TelegraphTopicProposal.id).where(
                TelegraphTopicProposal.research_task_id == task.id,
                TelegraphTopicProposal.id != proposal_id,
            )
        )
    ).scalar_one_or_none()
    if already_linked_elsewhere is not None:
        return RecoveryOutcome(proposal_id=proposal_id, status="unrecoverable_needs_manual_review")

    proposal.research_task_id = task.id
    await session.commit()
    await session.refresh(proposal)
    return RecoveryOutcome(proposal_id=proposal_id, status="relinked", task_id=task.id)


def is_task_terminal(task: EditorialTask) -> bool:
    """Small helper for an operator/ops script inspecting an orphaned or recovered proposal's
    linked task - COMPLETED/FAILED are terminal (safe to report on); CREATED/RUNNING/WAITING mean
    the task may still be legitimately in flight."""
    return task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)


def is_proposal_orphaned(proposal: TelegraphTopicProposal) -> bool:
    """Pure predicate mirroring find_orphaned_claimed_proposals()'s own WHERE clause - for a
    caller that already has one proposal loaded and doesn't want a fresh query."""
    return (
        proposal.status == TelegraphProposalStatus.APPROVED
        and proposal.consumed_at is not None
        and proposal.research_task_id is None
    )
