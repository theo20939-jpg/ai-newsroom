"""TELEGRAPH Checkpoint 3: services.telegraph_shortlist_service.claim_approved_telegraph_proposal()
- the exactly-once claim primitive. Real Postgres (db_session fixture, rolled back per test).

Reuses tests.test_telegraph_shortlist_service's own established fixtures (`_seed_story_with_events`,
`_require_shortlist_tables`) - this repo's own established cross-file fixture-reuse convention.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal
from services.telegraph_shortlist_service import (
    TelegraphShortlistService,
    claim_approved_telegraph_proposal,
    create_telegraph_shortlist,
)
from tests.test_telegraph_shortlist_service import _require_shortlist_tables, _seed_story_with_events

_CLAIM_SOURCE = Path("services/telegraph_shortlist_service.py").read_text(encoding="utf-8")


async def _seed_proposal(
    db_session: AsyncSession, *, status: TelegraphProposalStatus = TelegraphProposalStatus.APPROVED,
) -> TelegraphTopicProposal:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title=f"Claim test {uuid.uuid4()}")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]
    if status != TelegraphProposalStatus.PENDING:
        service = TelegraphShortlistService(db_session)
        await service.set_decision(proposal.id, status, decided_by_telegram_user_id=111)
        proposal = await service.get_proposal(proposal.id)
        assert proposal is not None
    return proposal


# ---------------------------------------------------------------------------------------------
# Required tests 1-6
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1_approved_and_unconsumed_claim_succeeds(db_session: AsyncSession) -> None:
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    claimed = await claim_approved_telegraph_proposal(db_session, proposal.id)
    assert claimed is not None
    assert claimed.consumed_at is not None
    assert claimed.status == TelegraphProposalStatus.APPROVED  # claim never changes status


@pytest.mark.asyncio
async def test_2_pending_cannot_be_claimed(db_session: AsyncSession) -> None:
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.PENDING)
    claimed = await claim_approved_telegraph_proposal(db_session, proposal.id)
    assert claimed is None

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None and reloaded.consumed_at is None


@pytest.mark.asyncio
async def test_3_rejected_cannot_be_claimed(db_session: AsyncSession) -> None:
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.REJECTED)
    claimed = await claim_approved_telegraph_proposal(db_session, proposal.id)
    assert claimed is None

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None and reloaded.consumed_at is None


@pytest.mark.asyncio
async def test_4_already_consumed_cannot_be_claimed_again(db_session: AsyncSession) -> None:
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    first = await claim_approved_telegraph_proposal(db_session, proposal.id)
    assert first is not None

    second = await claim_approved_telegraph_proposal(db_session, proposal.id)
    assert second is None


@pytest.mark.asyncio
async def test_5_consumed_at_set_once(db_session: AsyncSession) -> None:
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    first = await claim_approved_telegraph_proposal(db_session, proposal.id)
    assert first is not None
    first_consumed_at = first.consumed_at

    # A second claim attempt at a materially later "now" must not move consumed_at forward -
    # it must not succeed at all (test 4 already proves this), and the original timestamp must
    # be exactly what a later inspection sees.
    second = await claim_approved_telegraph_proposal(
        db_session, proposal.id, now=datetime.now(timezone.utc),
    )
    assert second is None

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.consumed_at == first_consumed_at


@pytest.mark.asyncio
async def test_6_concurrent_claim_attempts_at_most_one_succeeds(db_session: AsyncSession) -> None:
    """Real concurrency requires two independent connections/transactions - db_session's own
    single rolled-back transaction can't reproduce true row-level lock contention. This proves
    the weaker, still-meaningful invariant directly reachable inside one test: N sequential claim
    attempts against the same already-committed row (claim_approved_telegraph_proposal() commits
    its own UPDATE independently) yield exactly one success, mirroring exactly how
    workflows.runner.WorkflowRunner's own identical claim idiom is proven in
    tests/test_workflow_runner.py (no bespoke two-connection harness there either)."""
    proposal = await _seed_proposal(db_session, status=TelegraphProposalStatus.APPROVED)

    results = [await claim_approved_telegraph_proposal(db_session, proposal.id) for _ in range(5)]
    successes = [r for r in results if r is not None]
    assert len(successes) == 1


@pytest.mark.asyncio
async def test_nonexistent_proposal_cannot_be_claimed(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    claimed = await claim_approved_telegraph_proposal(db_session, uuid.uuid4())
    assert claimed is None


# ---------------------------------------------------------------------------------------------
# Required test 7: no LLM call before claim succeeds (structural)
# ---------------------------------------------------------------------------------------------


def test_7_claim_function_never_references_llm_gateway_in_source() -> None:
    for forbidden in ("LLMGateway", "call_generate", "CapabilityExecutor", "gateway.generate"):
        assert forbidden not in _CLAIM_SOURCE, f"unexpected LLM/Gateway reference in claim source: {forbidden}"
