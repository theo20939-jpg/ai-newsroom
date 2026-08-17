"""TELEGRAPH Checkpoint 3: services.telegraph_research_processor.
process_approved_telegraph_proposal() - claim -> task creation -> Deep Research workflow run.

Real Postgres (db_session fixture, rolled back per test), real FilePromptRepository (loads the
real prompts/research/v2.yaml + v3.yaml - proves both actually load/resolve), FakeLLMGateway
(zero network, zero real cost - the LLM Gateway itself is always faked, per the checkpoint's own
explicit requirement). Real Redis only for the one cost-attribution test (test 40), mirroring
tests/test_cost_recording_integration.py's own established pattern.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.registry import CapabilityRegistry
from capabilities.research_capability import RESEARCH_CAPABILITY_DEFINITION, ResearchCapability
from database.models.ai_execution import AIExecution
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.pricing_catalog import ModelRegistryPricingCatalog
from integrations.llm_gateway.models.catalog import build_model_registry
from services.cost_tracker import RedisCostTracker
from services.telegraph_research_processor import process_approved_telegraph_proposal
from services.telegraph_shortlist_service import TelegraphShortlistService
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.test_telegraph_research_claim import _seed_proposal


async def _seed_claimable_proposal(
    db_session: AsyncSession, *, status: TelegraphProposalStatus = TelegraphProposalStatus.APPROVED,
) -> TelegraphTopicProposal:
    """Like tests.test_telegraph_research_claim._seed_proposal(), but also gives the Story's
    anchor event its own NewsEventStoryLink (match_type="new_story", pointing to itself) -
    exactly what real production data always has (services/triage_orchestrator.py::
    _apply_story_memory() links EVERY event, including the one that creates a brand-new Story,
    in the same transaction - see capabilities/executor.py's own new TELEGRAPH_RESEARCH branch
    docstring). tests.test_telegraph_topic_candidates._make_anchor_event()'s own fixture
    deliberately omits this link (Checkpoint 1 never needed it) - this helper closes that gap
    for tests that actually run the "deep_research" step, which does need it."""
    proposal = await _seed_proposal(db_session, status=status)
    story = await db_session.get(Story, proposal.story_id)
    assert story is not None
    db_session.add(
        NewsEventStoryLink(
            news_event_id=story.first_event_id, story_id=story.id, match_type="new_story", match_score=1.0,
        )
    )
    await db_session.flush()
    return proposal


_PROCESSOR_SOURCE = Path("services/telegraph_research_processor.py").read_text(encoding="utf-8")

_VALID_DEEP_RESEARCH_OUTPUT = {
    "thesis": "Does X represent a genuine shift in the market?",
    "confirmed_facts": ["Company X released product Y."],
    "timeline": ["2026-08-10: product Y announced."],
    "source_evidence": ["Source A confirms the announcement."],
    "primary_sources": ["Source A (official blog)"],
    "context_background": ["Company X previously released product Z in 2024."],
    "implications": ["Could affect competitor pricing."],
    "competing_views": [],
    "gaps": ["Pricing not disclosed."],
    "risky_claims": [],
    "suggested_article_angles": ["A deep dive on product Y's market positioning."],
    "confidence": 0.75,
}

_TRUNCATED_RESPONSE = GenerateResponse(
    text=None, structured_output=None, finish_reason="length", model_used="fake-model-v1",
    usage=CapabilityUsage(input_tokens=50, output_tokens=10),
)


def _valid_response(*, model_used: str = "fake-model-v1") -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=_VALID_DEEP_RESEARCH_OUTPUT, finish_reason="stop",
        model_used=model_used, usage=CapabilityUsage(input_tokens=500, output_tokens=800),
    )


def _prompt_repository() -> FilePromptRepository:
    return FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")


def _capability_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        RESEARCH_CAPABILITY_DEFINITION, ResearchCapability(gateway, _prompt_repository()),
    )
    registry.seal()
    return registry


# ---------------------------------------------------------------------------------------------
# Required tests 21, 22, 24, 25
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_21_successful_claim_creates_exactly_one_downstream_task(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    assert outcome.claimed is True
    assert outcome.task_id is not None
    rows = (
        await db_session.execute(select(EditorialTask).where(EditorialTask.id == outcome.task_id))
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_22_deep_research_runs_only_for_approved_claimed_proposal(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.PENDING)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    assert outcome.claimed is False
    assert outcome.task_id is None
    assert outcome.run_result is None
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_24_structured_research_output_persisted(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    assert outcome.run_result is not None and outcome.run_result.status == "COMPLETED"
    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    step_results = task.workflow["step_results"]
    deep_research = next(r for r in step_results if r["step_name"] == "deep_research")
    assert deep_research["status"] == "SUCCESS"
    assert deep_research["result"]["thesis"] == _VALID_DEEP_RESEARCH_OUTPUT["thesis"]
    assert deep_research["result"]["confirmed_facts"] == _VALID_DEEP_RESEARCH_OUTPUT["confirmed_facts"]


@pytest.mark.asyncio
async def test_25_research_output_recoverable_by_proposal_task_linkage(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.research_task_id == outcome.task_id

    task = await db_session.get(EditorialTask, reloaded.research_task_id)
    assert task is not None
    deep_research = next(r for r in task.workflow["step_results"] if r["step_name"] == "deep_research")
    assert deep_research["result"]["thesis"]


# ---------------------------------------------------------------------------------------------
# Required tests 26, 27, 28
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_26_failure_leaves_task_inspectably_failed(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    # A response missing every required key, finish_reason="stop" (not "length") -> permanent
    # ValidationCapabilityError -> the step fails immediately, never retried.
    bad_response = GenerateResponse(
        text=None, structured_output={}, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=1),
    )
    gateway = FakeLLMGateway(generate_response=bad_response)
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    assert outcome.run_result is not None and outcome.run_result.status == "FAILED"
    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    assert task.status == TaskStatus.FAILED
    assert task.workflow["failure"] is not None


@pytest.mark.asyncio
async def test_27_consumed_at_remains_set_after_failure(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    bad_response = GenerateResponse(
        text=None, structured_output={}, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=1),
    )
    gateway = FakeLLMGateway(generate_response=bad_response)
    registry = _capability_registry(gateway)

    await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.consumed_at is not None  # never reset to NULL after a failed attempt
    assert reloaded.research_task_id is not None


@pytest.mark.asyncio
async def test_28_retry_then_succeed_uses_existing_bounded_workflow_semantics(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_responses=[_TRUNCATED_RESPONSE, _valid_response()])
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    assert outcome.run_result is not None and outcome.run_result.status == "COMPLETED"
    # Two Gateway calls happened (attempt 1 failed floor validation, attempt 2 succeeded) - the
    # step's own existing max_attempts=3 bound, no new retry loop introduced.
    assert len(gateway.received_requests) == 2
    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    assert task.retry_count == 1


# ---------------------------------------------------------------------------------------------
# Required tests 29-35: no next-stage side effects; existing NEWS Research behavior unchanged
# ---------------------------------------------------------------------------------------------


def test_29_30_31_32_33_no_next_stage_or_delivery_reference_in_processor_source() -> None:
    for forbidden in (
        "CopywritingCapability", "MediaVisionReviewCapability", "run_shadow_discovery",
        "image_intelligence", "aiogram", "bot.send", "send_to_editorial_destination",
        "telegra.ph", "createPage",
    ):
        assert forbidden not in _PROCESSOR_SOURCE, f"unexpected next-stage/delivery reference: {forbidden}"


@pytest.mark.asyncio
async def test_34_no_content_draft_created(db_session: AsyncSession) -> None:
    before = (await db_session.execute(select(ContentDraft))).scalars().all()
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    after = (await db_session.execute(select(ContentDraft))).scalars().all()
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_35_existing_news_research_behavior_unchanged(db_session: AsyncSession) -> None:
    """A normal (non-TELEGRAPH) research call - context.business.telegraph_research_bundle_text
    is None - must still resolve prompt version "2" and build the request from news_event.content,
    never version "3" or the bundle-based request. Proven by inspecting the real request sent to
    the Gateway: v2's system text is the fact-extraction prompt, never v3's deep-research one."""
    from uuid import uuid4 as _uuid4

    from schemas.capability import (
        BusinessContext, CapabilityContext, ExecutionContext, NewsEventSnapshot, RuntimeContext,
        WorkflowExecutionStateSnapshot,
    )
    from database.models.editorial_task import TaskPriority as _TaskPriority

    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output={"facts": ["a"], "confidence": 0.5, "gaps": []},
            finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )
    )
    capability = ResearchCapability(gateway, _prompt_repository())
    context = CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=_uuid4(), title="A normal NEWS event", summary=None, content="Some body text.",
                url=None, category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="NEWS_ANALYSIS", workflow_version=1, completed_steps=[],
            ),
            telegraph_research_bundle_text=None,
        ),
        runtime=RuntimeContext(
            task_id=_uuid4(), event_id=_uuid4(), capability_name="research",
            priority=_TaskPriority.B, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )

    result = await capability.execute(context)
    assert result.status == "SUCCESS"
    sent = gateway.received_requests[0]
    sent_text = sent.messages[-1].content[0].text
    assert "EVIDENCE BUNDLE" not in sent_text
    assert "Some body text." in sent_text


# ---------------------------------------------------------------------------------------------
# Required tests 36-39: cost boundary
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_36_pending_proposal_zero_paid_call_fake_invocation(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.PENDING)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_37_rejected_proposal_zero_paid_call_fake_invocation(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.REJECTED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_38_already_consumed_zero_new_paid_call_fake_invocation(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    first = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert first.claimed is True
    calls_after_first = len(gateway.received_requests)
    assert calls_after_first == 1

    second = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert second.claimed is False
    assert len(gateway.received_requests) == calls_after_first  # no new invocation


@pytest.mark.asyncio
async def test_39_first_valid_approved_proposal_exactly_one_deep_research_invocation(
    db_session: AsyncSession,
) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert len(gateway.received_requests) == 1


# ---------------------------------------------------------------------------------------------
# Required test 40: cost/AIExecution attribution via the existing accounting mechanism
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_40_cost_attributed_via_existing_ai_execution_accounting(
    db_session: AsyncSession, redis_client: Redis,
) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response(model_used="gpt-5.6-luna"))
    registry = _capability_registry(gateway)
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=f"test-{uuid4()}")

    outcome = await process_approved_telegraph_proposal(
        db_session, proposal.id, capability_registry=registry,
        cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
    )

    rows = (
        await db_session.execute(select(AIExecution).where(AIExecution.task_id == outcome.task_id))
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.workflow_name == "TELEGRAPH_RESEARCH"
    assert row.capability.value == "RESEARCH"
    assert row.model == "gpt-5.6-luna"
    assert row.cost > 0


# ---------------------------------------------------------------------------------------------
# Correctness-review fix: claim + task creation + link is one atomic transaction
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_block_success_creates_and_links_task_in_one_go(db_session: AsyncSession) -> None:
    """Positive case: after a successful run, both the claim and the link are durable together -
    already covered by tests 21/24/25, restated here explicitly as the "atomic success" case."""
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.consumed_at is not None
    assert reloaded.research_task_id == outcome.task_id  # never orphaned on the success path


@pytest.mark.asyncio
async def test_task_creation_failure_never_commits_the_claim(db_session: AsyncSession) -> None:
    """Negative case, the whole point of the atomicity fix: if EditorialTask creation fails
    (services.workflow_service.create_task()'s own existing duplicate-active-task guard,
    deliberately triggered here by pre-creating a colliding TELEGRAPH_RESEARCH task for the same
    anchor event), the claim UPDATE that ran moments earlier in the SAME transaction is never
    committed either - proving "claimed but unlinked" cannot become durable from this failure.
    Before this fix, the claim's own independent commit would have left consumed_at permanently
    set with no task ever linked, regardless of what happened next.

    This test proves the failure is clean and pre-payment (the typed, existing
    DuplicateActiveTaskError propagates, zero Gateway calls ever happen) by construction: the
    single session.commit() covering claim+task+link sits AFTER task creation in the source
    (services/telegraph_research_processor.py) - a failure there cannot reach it. Verifying
    non-durability from a second, independent connection is deliberately not attempted here: the
    shared `db_session` fixture's savepoint-joined transaction (tests/conftest.py) has no
    supported way to roll back mid-test and keep reading the same session afterward (this
    codebase's own precedent for that kind of proof, tests/test_triage_orchestrator_claims.py,
    always uses a fully independent session/connection instead, which the seeded data in this
    test - itself never committed to the physical database - would not be visible from)."""
    from workflows.errors import DuplicateActiveTaskError

    from database.models.editorial_task import EditorialTask, TaskPriority
    from database.models.story import Story

    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    story = await db_session.get(Story, proposal.story_id)
    assert story is not None
    # A pre-existing TELEGRAPH_RESEARCH task for the same anchor event - create_task() will
    # refuse to create a second one for the same (event_id, workflow_type) pair.
    db_session.add(
        EditorialTask(
            event_id=story.first_event_id, priority=TaskPriority.C,
            workflow={"workflow_name": "TELEGRAPH_RESEARCH", "step_results": []},
        )
    )
    await db_session.flush()

    gateway = FakeLLMGateway(generate_response=_valid_response())
    registry = _capability_registry(gateway)

    with pytest.raises(DuplicateActiveTaskError):
        await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)

    # No Gateway call ever happened - the failure occurred before the workflow ever ran, and
    # before this block's own single commit() could ever be reached.
    assert len(gateway.received_requests) == 0
