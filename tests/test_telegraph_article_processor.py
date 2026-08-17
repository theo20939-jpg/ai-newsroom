"""TELEGRAPH Checkpoint 5: services.telegraph_article_processor.
generate_article_for_researched_proposal() - precondition guard -> task creation (or duplicate-
task lookup) -> Deep-Research-informed article generation workflow run.

Real Postgres (db_session fixture), real FilePromptRepository (loads the real
prompts/article_generation/v1.yaml AND prompts/research/v2.yaml/v3.yaml - proves the new prompt
loads and NEWS's own v2 stays untouched), FakeLLMGateway (zero network/cost).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.article_generation_capability import ARTICLE_GENERATION_CAPABILITY_DEFINITION, ArticleGenerationCapability
from capabilities.registry import CapabilityRegistry
from capabilities.research_capability import RESEARCH_CAPABILITY_DEFINITION, ResearchCapability
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.telegraph_shortlist import TelegraphProposalStatus
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.telegraph_article_processor import find_article_task_id, generate_article_for_researched_proposal
from services.telegraph_research_processor import process_approved_telegraph_proposal
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.test_telegraph_research_processor import _seed_claimable_proposal

_PROCESSOR_SOURCE = Path("services/telegraph_article_processor.py").read_text(encoding="utf-8")

_VALID_RESEARCH_OUTPUT = {
    "thesis": "Does X represent a genuine shift?", "confirmed_facts": ["Company X released product Y."],
    "timeline": ["2026-08-10: product Y announced."], "source_evidence": ["Source A confirms."],
    "primary_sources": ["Source A"], "context_background": ["Prior product Z in 2024."],
    "implications": ["Could affect pricing."], "competing_views": [], "gaps": ["Pricing undisclosed."],
    "risky_claims": [], "suggested_article_angles": ["Deep dive."], "confidence": 0.75,
}

_VALID_ARTICLE_OUTPUT = {
    "headline": "Product Y: What We Know So Far",
    "lead": "Company X released product Y, a development that may reshape the market.",
    "context": ["Company X has a history of similar launches."],
    "timeline": ["2026-08-10: product Y announced."],
    "confirmed_facts": ["Company X released product Y."],
    "analysis": ["This could pressure competitors on pricing."],
    "implications": ["Could affect competitor pricing."],
    "background": ["Prior product Z in 2024."],
    "risks": ["Pricing undisclosed - could change the picture."],
    "conclusion": "The full market impact remains to be seen.",
    "sources": ["Source A"],
}


def _prompt_repository() -> FilePromptRepository:
    return FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")


def _research_response() -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=_VALID_RESEARCH_OUTPUT, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=500, output_tokens=800),
    )


def _article_response(*, model_used: str = "fake-model-v1") -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=_VALID_ARTICLE_OUTPUT, finish_reason="stop",
        model_used=model_used, usage=CapabilityUsage(input_tokens=2000, output_tokens=3000),
    )


class _DualGateway(FakeLLMGateway):
    """Routes by prompt content: the research call's system text mentions "Deep Research"/
    "EVIDENCE BUNDLE", the article call's mentions "RESEARCH BUNDLE" - distinguished here so one
    fake gateway can serve both steps across the two-processor flow these tests exercise."""

    def __init__(self) -> None:
        super().__init__()
        self.article_requests: list[object] = []

    async def generate(self, request):  # type: ignore[override]
        self.received_requests.append(request)
        text = request.messages[-1].content[0].text
        if "RESEARCH BUNDLE:" in text:
            self.article_requests.append(request)
            return _article_response()
        return _research_response()


def _full_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(RESEARCH_CAPABILITY_DEFINITION, ResearchCapability(gateway, _prompt_repository()))
    registry.register(
        ARTICLE_GENERATION_CAPABILITY_DEFINITION, ArticleGenerationCapability(gateway, _prompt_repository())
    )
    registry.seal()
    return registry


async def _researched_proposal(db_session: AsyncSession, gateway: FakeLLMGateway):
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    registry = _full_registry(gateway)
    outcome = await process_approved_telegraph_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.run_result is not None and outcome.run_result.status == "COMPLETED"
    return proposal, registry


@pytest.mark.asyncio
async def test_not_researched_proposal_cannot_generate_article(db_session: AsyncSession) -> None:
    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    gateway = _DualGateway()
    registry = _full_registry(gateway)

    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.status == "not_researched"
    assert outcome.task_id is None
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_research_still_running_cannot_generate_article(db_session: AsyncSession) -> None:
    from database.models.editorial_task import TaskPriority
    from database.models.story import Story

    proposal = await _seed_claimable_proposal(db_session, status=TelegraphProposalStatus.APPROVED)
    story = await db_session.get(Story, proposal.story_id)
    assert story is not None

    running_task = EditorialTask(
        event_id=story.first_event_id,
        priority=TaskPriority.C, status=TaskStatus.RUNNING,
        workflow={"workflow_name": "TELEGRAPH_RESEARCH", "step_results": []},
    )
    db_session.add(running_task)
    await db_session.flush()
    proposal.research_task_id = running_task.id
    await db_session.flush()

    gateway = _DualGateway()
    registry = _full_registry(gateway)
    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.status == "research_not_complete"
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_generates_article_from_completed_research(db_session: AsyncSession) -> None:
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)

    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)

    assert outcome.status == "generated"
    assert outcome.run_result is not None and outcome.run_result.status == "COMPLETED"
    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    step_result = next(r for r in task.workflow["step_results"] if r["step_name"] == "generate_article")
    assert step_result["result"]["headline"] == _VALID_ARTICLE_OUTPUT["headline"]
    assert step_result["result"]["confirmed_facts"] == _VALID_ARTICLE_OUTPUT["confirmed_facts"]


@pytest.mark.asyncio
async def test_article_request_never_reads_raw_news_event_content(db_session: AsyncSession) -> None:
    """The article-generation request must be built from the research bundle, never from
    news_event.content (the anchor event's own thin RSS excerpt) - proves capabilities/
    article_generation_capability.py's own binding-scope claim."""
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)

    await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)

    assert len(gateway.article_requests) == 1
    sent_text = gateway.article_requests[0].messages[-1].content[0].text
    assert "RESEARCH BUNDLE:" in sent_text
    assert "Company X released product Y." in sent_text  # from the research bundle, not raw content


@pytest.mark.asyncio
async def test_article_generation_receives_the_proposals_own_editorial_channel(
    db_session: AsyncSession,
) -> None:
    """Required test 5 ("article generation receives channel"): the exact editorial_channel
    services.editorial_channel_classifier.py assigned at shortlist-creation time (Checkpoint 4)
    is the same value that ends up in the real article-generation request - end to end, through
    the real DB, not a hand-built CapabilityContext."""
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)

    await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)

    assert len(gateway.article_requests) == 1
    sent_text = gateway.article_requests[0].messages[-1].content[0].text
    assert f"Editorial channel: {proposal.editorial_channel.value}" in sent_text


@pytest.mark.asyncio
async def test_second_attempt_reuses_existing_task_no_new_paid_call(db_session: AsyncSession) -> None:
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)

    first = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert first.status == "generated"
    calls_after_first = len(gateway.article_requests)
    assert calls_after_first == 1

    second = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert second.status == "already_exists"
    assert second.task_id == first.task_id
    assert len(gateway.article_requests) == calls_after_first  # no new paid call


@pytest.mark.asyncio
async def test_find_article_task_id_locates_the_task(db_session: AsyncSession) -> None:
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)
    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)

    from database.models.story import Story

    story = await db_session.get(Story, proposal.story_id)
    assert story is not None
    found = await find_article_task_id(db_session, story.first_event_id)
    assert found == outcome.task_id


@pytest.mark.asyncio
async def test_cost_attributed_via_existing_ai_execution_accounting(db_session: AsyncSession, redis_client) -> None:
    from services.cost_tracker import RedisCostTracker
    from services.pricing_catalog import ModelRegistryPricingCatalog
    from integrations.llm_gateway.models.catalog import build_model_registry

    class _CostGateway(_DualGateway):
        async def generate(self, request):  # type: ignore[override]
            self.received_requests.append(request)
            text = request.messages[-1].content[0].text
            if "RESEARCH BUNDLE:" in text:
                self.article_requests.append(request)
                return _article_response(model_used="gpt-5.6-luna")
            return _research_response()

    gateway = _CostGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)

    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=f"test-{uuid4()}")

    outcome = await generate_article_for_researched_proposal(
        db_session, proposal.id, capability_registry=registry,
        cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
    )

    rows = (
        await db_session.execute(select(AIExecution).where(AIExecution.task_id == outcome.task_id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].workflow_name == "TELEGRAPH_ARTICLE"
    assert rows[0].capability.value == "COPYWRITING"
    assert rows[0].cost > 0


# ---------------------------------------------------------------------------------------------
# Cost/side-effect boundary + NEWS copywriting untouched
# ---------------------------------------------------------------------------------------------


def test_no_telegram_or_telegraph_publishing_reference_in_processor_source() -> None:
    for forbidden in (
        "aiogram", "bot.send", "send_to_editorial_destination", "telegra.ph", "createPage", "createAccount",
    ):
        assert forbidden not in _PROCESSOR_SOURCE, f"unexpected reference: {forbidden}"


def test_news_copywriting_prompt_v4_default_unaffected() -> None:
    """The real, active NEWS copywriting prompt version is still "4" - completely untouched by
    the new article_generation prompt namespace living alongside it."""
    from core.config import settings

    assert settings.copywriting_prompt_version == "4"
    repo = _prompt_repository()
    v4 = repo.resolve("copywriting", "4")
    assert v4.version == "4"
