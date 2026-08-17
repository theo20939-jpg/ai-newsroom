"""TELEGRAPH Checkpoint 3 correctness-review fix: services.telegraph_research_recovery -
detection (and the one provably-safe re-link repair) for a proposal orphaned in the
`consumed_at IS NOT NULL AND research_task_id IS NULL` state.

Since the atomicity fix (services/telegraph_research_processor.py's single commit() covering
claim+task-creation+link) makes this state unreachable through any normal code path, these tests
construct the orphaned state directly (bypassing process_approved_telegraph_proposal()) - the
only way to exercise recovery logic without a real process crash.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.story import Story
from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal
from services.telegraph_research_recovery import (
    find_orphaned_claimed_proposals,
    is_proposal_orphaned,
    recover_orphaned_claim,
)
from services.telegraph_shortlist_service import TelegraphShortlistService
from tests.test_telegraph_research_claim import _seed_proposal

_RECOVERY_SOURCE = Path("services/telegraph_research_recovery.py").read_text(encoding="utf-8")


async def _make_orphan(db_session: AsyncSession) -> TelegraphTopicProposal:
    """Directly sets consumed_at without ever setting research_task_id - simulates the crash
    window, bypassing claim_approved_telegraph_proposal()/process_approved_telegraph_proposal()
    entirely (which, post-fix, can no longer produce this state on any normal path)."""
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    proposal.consumed_at = datetime.now(timezone.utc)
    await db_session.flush()
    return proposal


@pytest.mark.asyncio
async def test_find_orphaned_claimed_proposals_detects_the_exact_condition(db_session: AsyncSession) -> None:
    orphan = await _make_orphan(db_session)
    non_orphan = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)

    found = await find_orphaned_claimed_proposals(db_session)
    found_ids = {p.id for p in found}
    assert orphan.id in found_ids
    assert non_orphan.id not in found_ids


@pytest.mark.asyncio
async def test_find_orphaned_returns_empty_when_none_exist(db_session: AsyncSession) -> None:
    await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    await _seed_proposal(db_session, status=TelegraphProposalStatus.PENDING)

    found = await find_orphaned_claimed_proposals(db_session)
    assert found == []


@pytest.mark.asyncio
async def test_is_proposal_orphaned_predicate(db_session: AsyncSession) -> None:
    orphan = await _make_orphan(db_session)
    assert is_proposal_orphaned(orphan) is True

    normal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    assert is_proposal_orphaned(normal) is False


@pytest.mark.asyncio
async def test_recover_relinks_when_a_genuine_unlinked_task_exists(db_session: AsyncSession) -> None:
    orphan = await _make_orphan(db_session)
    story = await db_session.get(Story, orphan.story_id)
    assert story is not None
    task = EditorialTask(
        event_id=story.first_event_id, priority=TaskPriority.C,
        workflow={"workflow_name": "TELEGRAPH_RESEARCH", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()

    outcome = await recover_orphaned_claim(db_session, orphan.id)
    assert outcome.status == "relinked"
    assert outcome.task_id == task.id

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(orphan.id)
    assert reloaded is not None
    assert reloaded.research_task_id == task.id


@pytest.mark.asyncio
async def test_recover_reports_unrecoverable_when_no_task_exists(db_session: AsyncSession) -> None:
    orphan = await _make_orphan(db_session)
    outcome = await recover_orphaned_claim(db_session, orphan.id)
    assert outcome.status == "unrecoverable_needs_manual_review"
    assert outcome.task_id is None

    # Never fabricates consumed_at=NULL or a task - the proposal is untouched.
    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(orphan.id)
    assert reloaded is not None
    assert reloaded.consumed_at is not None
    assert reloaded.research_task_id is None


@pytest.mark.asyncio
async def test_recover_is_a_noop_for_a_non_orphaned_proposal(db_session: AsyncSession) -> None:
    normal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    outcome = await recover_orphaned_claim(db_session, normal.id)
    assert outcome.status == "no_orphan"

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(normal.id)
    assert reloaded is not None
    assert reloaded.consumed_at is None  # untouched - never claims on the recovery caller's behalf


@pytest.mark.asyncio
async def test_recover_nonexistent_proposal_fails_safely(db_session: AsyncSession) -> None:
    outcome = await recover_orphaned_claim(db_session, uuid.uuid4())
    assert outcome.status == "no_orphan"


@pytest.mark.asyncio
async def test_recover_never_relinks_a_task_already_linked_to_a_different_proposal(
    db_session: AsyncSession,
) -> None:
    other = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    other_story = await db_session.get(Story, other.story_id)
    assert other_story is not None
    task = EditorialTask(
        event_id=other_story.first_event_id, priority=TaskPriority.C,
        workflow={"workflow_name": "TELEGRAPH_RESEARCH", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()
    other.research_task_id = task.id
    other.consumed_at = datetime.now(timezone.utc)
    await db_session.flush()

    # A second, unrelated orphan whose OWN Story happens to reuse the same anchor event id would
    # be a structurally impossible collision (each Story has its own first_event_id) - this test
    # instead proves the "already linked elsewhere" guard directly: an orphan pointed at the SAME
    # story as `other` must never steal its task.
    orphan = await _make_orphan(db_session)
    orphan.story_id = other.story_id
    await db_session.flush()

    outcome = await recover_orphaned_claim(db_session, orphan.id)
    assert outcome.status == "unrecoverable_needs_manual_review"


# ---------------------------------------------------------------------------------------------
# Cost/side-effect boundary (structural)
# ---------------------------------------------------------------------------------------------


def test_recovery_module_never_touches_llm_gateway_or_telegram() -> None:
    for forbidden in (
        "LLMGateway", "call_generate", "CapabilityExecutor", "WorkflowRunner().run", "aiogram",
        "bot.send", "send_to_editorial_destination",
    ):
        assert forbidden not in _RECOVERY_SOURCE, f"unexpected reference: {forbidden}"


def test_recovery_module_never_resets_consumed_at() -> None:
    assert "consumed_at = None" not in _RECOVERY_SOURCE
    assert ".consumed_at=None" not in _RECOVERY_SOURCE.replace(" ", "")
