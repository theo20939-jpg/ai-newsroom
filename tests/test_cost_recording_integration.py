"""API cost optimization: proves capabilities.executor.CapabilityExecutor actually records real
per-call cost (durable AIExecution row + Redis daily ledger) when `cost_tracker`/
`pricing_catalog` are supplied at construction - the opt-in reversal of Amendment B's old
"never writes" rule. Real Postgres (db_session, rolled back) + real local Redis."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from capabilities.research_capability import ResearchCapability
from database.models.ai_execution import AICapability, AIExecution
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult, CapabilityCall, CapabilityUsage
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from services import workflow_service
from services.cost_tracker import RedisCostTracker, capability_ledger_key, global_ledger_key
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc


class _RealModelCapability:
    """Deterministic success, one real-catalog-model CapabilityCall (gpt-5.6-luna) - unlike
    tests/fakes/fake_capability.py's own "fake-model-v1", this must resolve real pricing."""

    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(UTC)
        call = CapabilityCall(
            call_id=uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
            model_used="gpt-5.6-luna", provider="openai", prompt_name="research", prompt_version="2",
            usage=CapabilityUsage(input_tokens=self._input_tokens, output_tokens=self._output_tokens),
            started_at=now, finished_at=now, duration_seconds=0.01,
        )
        return CapabilityResult(
            status="SUCCESS", structured_output={"facts": ["x"], "confidence": 0.5, "gaps": []},
            calls=[call], started_at=now, finished_at=now, duration_seconds=0.01,
        )


def _workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.NEWS_ANALYSIS, version=1,
            steps=[WorkflowStepDefinition(name="research", capability="research", timeout_seconds=10)],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _capability_registry(capability: _RealModelCapability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        capability,
    )
    registry.seal()
    return registry


async def _make_event(session: AsyncSession) -> NewsEvent:
    source = NewsSource(name=f"Cost Source {uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=f"Cost test event {uuid4()}", content="Body",
        category=EventCategory.AI, hash=f"cost-test-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_successful_call_persists_ai_execution_row_when_cost_tracker_provided(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    event = await _make_event(db_session)
    workflow_registry = _workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    namespace = f"test-{uuid4()}"
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=namespace)
    capability_registry = _capability_registry(_RealModelCapability(input_tokens=1000, output_tokens=1000))
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog
    )

    try:
        result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
        assert result.status == "COMPLETED"

        rows = (await db_session.execute(select(AIExecution).where(AIExecution.task_id == task.id))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_id == event.id
        assert row.workflow_name == "NEWS_ANALYSIS"
        assert row.model == "gpt-5.6-luna"
        assert row.input_tokens == 1000
        assert row.output_tokens == 1000
        # gpt-5.6-luna: $1.00/M in, $6.00/M out -> 1000/1e6*1.00 + 1000/1e6*6.00 = 0.007
        assert row.cost == Decimal("0.007000")
        assert row.usage_source == "provider_response"

        ledger_raw = await redis_client.get(global_ledger_key(namespace))
        assert ledger_raw is not None
        assert float(ledger_raw) == pytest.approx(0.007)
        capability_ledger_raw = await redis_client.get(capability_ledger_key(namespace, "research"))
        assert capability_ledger_raw is not None
        assert float(capability_ledger_raw) == pytest.approx(0.007)
    finally:
        await redis_client.delete(global_ledger_key(namespace))
        await redis_client.delete(capability_ledger_key(namespace, "research"))


# ---------------------------------------------------------------------------------------------
# Cost-accounting forensic fix: a real gateway call that succeeds (real provider spend, real
# usage) but whose response later fails ResearchCapability's own §9.1 floor validation - e.g. a
# truncated response - must still persist an AIExecution row for that completed call, even
# though the Capability raises rather than returns a CapabilityResult. Uses the REAL
# ResearchCapability (not a fake) driven by FakeLLMGateway, so this proves the actual production
# code path, not just the generic CapabilityExecutor mapping mechanism.
# ---------------------------------------------------------------------------------------------

_RESEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array"}, "confidence": {"type": "number"}, "gaps": {"type": "array"}},
    "required": ["facts", "confidence", "gaps"],
}


def _research_prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=RESEARCH_CAPABILITY_NAME, version="2",
            system="You are a fake research assistant for tests.", rules=["Do not invent facts."],
            output_schema=_RESEARCH_OUTPUT_SCHEMA,
        )
    )
    return repository


def _truncated_response(*, input_tokens: int = 592, output_tokens: int = 1000) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=None, finish_reason="length", model_used="gpt-5.6-luna",
        usage=CapabilityUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _research_workflow_registry(max_attempts: int) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.NEWS_ANALYSIS, version=1,
            steps=[
                WorkflowStepDefinition(
                    name="research", capability="research", max_attempts=max_attempts, timeout_seconds=10
                )
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=max_attempts, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
        )
    )
    registry.seal()
    return registry


async def _ai_execution_rows(session: AsyncSession, task_id: object) -> list[AIExecution]:
    result = await session.execute(select(AIExecution).where(AIExecution.task_id == task_id))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_truncated_research_call_is_cost_recorded_once_even_though_the_step_fails(
    db_session: AsyncSession, redis_client: Redis,
) -> None:
    """(a) A single truncated attempt (max_attempts=1, step fails immediately, no retry) must
    still persist exactly one AIExecution row - before this fix, the completed gateway call's
    real usage was silently discarded the instant ResearchCapability raised."""
    event = await _make_event(db_session)
    workflow_registry = _research_workflow_registry(max_attempts=1)
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    namespace = f"test-{uuid4()}"
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=namespace)
    gateway = FakeLLMGateway(generate_response=_truncated_response())
    capability_registry = CapabilityRegistry()
    capability_registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        ResearchCapability(gateway, _research_prompt_repository()),
    )
    capability_registry.seal()
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog
    )

    try:
        result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
        assert result.status == "FAILED"  # the step itself still fails/retries as before - unchanged

        rows = await _ai_execution_rows(db_session, task.id)
        assert len(rows) == 1
        assert rows[0].model == "gpt-5.6-luna"
        assert rows[0].input_tokens == 592
        assert rows[0].output_tokens == 1000
    finally:
        await redis_client.delete(global_ledger_key(namespace))
        await redis_client.delete(capability_ledger_key(namespace, "research"))


@pytest.mark.asyncio
async def test_three_truncation_attempts_produce_three_recorded_executions(
    db_session: AsyncSession, redis_client: Redis,
) -> None:
    """(b) Every retried attempt is its own real, separately-billed provider call - three
    truncated attempts (the exact real-world shape: task d3fe7076-e075-4003-9c26-f138bf741063
    truncated on all 3 attempts) must persist three distinct AIExecution rows, not zero, not one
    merged/deduplicated row."""
    event = await _make_event(db_session)
    workflow_registry = _research_workflow_registry(max_attempts=3)
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    namespace = f"test-{uuid4()}"
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=namespace)
    gateway = FakeLLMGateway(generate_response=_truncated_response())
    capability_registry = CapabilityRegistry()
    capability_registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        ResearchCapability(gateway, _research_prompt_repository()),
    )
    capability_registry.seal()
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog
    )

    try:
        result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
        assert result.status == "FAILED"  # exhausted all 3 attempts, all truncated - unchanged behavior
        assert len(result.step_results) == 3

        rows = await _ai_execution_rows(db_session, task.id)
        assert len(rows) == 3
        assert all(row.model == "gpt-5.6-luna" for row in rows)
        assert all(row.input_tokens == 592 and row.output_tokens == 1000 for row in rows)
    finally:
        await redis_client.delete(global_ledger_key(namespace))
        await redis_client.delete(capability_ledger_key(namespace, "research"))


@pytest.mark.asyncio
async def test_successful_research_after_the_fix_still_records_exactly_once(
    db_session: AsyncSession, redis_client: Redis,
) -> None:
    """(c) The pre-existing successful path must be completely unaffected by this fix - a valid
    response records exactly one AIExecution row via the same, unmodified success-path call to
    `_record_cost()`, never through the new exception-path recording."""
    event = await _make_event(db_session)
    workflow_registry = _research_workflow_registry(max_attempts=3)
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    namespace = f"test-{uuid4()}"
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=namespace)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output={"facts": ["x"], "confidence": 0.5, "gaps": []}, finish_reason="stop",
            model_used="gpt-5.6-luna", usage=CapabilityUsage(input_tokens=592, output_tokens=210),
        )
    )
    capability_registry = CapabilityRegistry()
    capability_registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        ResearchCapability(gateway, _research_prompt_repository()),
    )
    capability_registry.seal()
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog
    )

    try:
        result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
        assert result.status == "COMPLETED"

        rows = await _ai_execution_rows(db_session, task.id)
        assert len(rows) == 1
        assert rows[0].input_tokens == 592
        assert rows[0].output_tokens == 210
    finally:
        await redis_client.delete(global_ledger_key(namespace))
        await redis_client.delete(capability_ledger_key(namespace, "research"))


@pytest.mark.asyncio
async def test_pre_provider_configuration_failure_creates_no_ai_execution_row(
    db_session: AsyncSession, redis_client: Redis,
) -> None:
    """(d) A gateway-level failure that never reached a provider (NoRoutableCandidateError - no
    real call, no real usage, `call_generate()`'s own FAILED-status CapabilityCall has empty
    usage and is never attached to the raised error) must record zero AIExecution rows - the fix
    must never fabricate cost for a call that never happened."""
    event = await _make_event(db_session)
    workflow_registry = _research_workflow_registry(max_attempts=1)
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    namespace = f"test-{uuid4()}"
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=namespace)
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    capability_registry = CapabilityRegistry()
    capability_registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        ResearchCapability(gateway, _research_prompt_repository()),
    )
    capability_registry.seal()
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog
    )

    try:
        result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
        assert result.status == "FAILED"

        rows = await _ai_execution_rows(db_session, task.id)
        assert rows == []

        ledger_raw = await redis_client.get(global_ledger_key(namespace))
        assert ledger_raw is None  # nothing was ever recorded to cost either
    finally:
        await redis_client.delete(global_ledger_key(namespace))
        await redis_client.delete(capability_ledger_key(namespace, "research"))


def _engagement_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.NEWS_ANALYSIS, version=1,
            steps=[WorkflowStepDefinition(name="engagement", capability="engagement", timeout_seconds=10)],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _engagement_capability_registry(capability: _RealModelCapability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDefinition(
            name="engagement", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        capability,
    )
    registry.seal()
    return registry


@pytest.mark.skip(
    reason=(
        "Requires Alembic migration 8b9d649bc69b (adds ENGAGEMENT to the ai_capability Postgres "
        "enum) to be applied first - Phase 18.10 M9 ships this migration unapplied by explicit "
        "instruction (design-only; the user applies it separately). Remove this skip once the "
        "migration has been applied to the target database - until then this test would fail "
        "with 'invalid input value for enum ai_capability: \"ENGAGEMENT\"', not because the code "
        "is wrong, but because the schema hasn't been migrated yet."
    )
)
@pytest.mark.asyncio
async def test_engagement_capability_recorded_under_its_own_label_in_both_ledgers(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    """Phase 18.10 M9 cross-validation: closes the exact gap Phase 18.9's live test quantified -
    proves an engagement-capability call is now attributed consistently in both cost records.
    Before this fix, this same call would have persisted AIExecution.capability == INTELLIGENCE
    (the resolved "Amendment A" alias) while the Redis ledger already correctly bucketed it under
    "engagement" - the two ledgers disagreed on the label despite agreeing on the dollar amount.
    Now both agree the call belongs to engagement."""
    event = await _make_event(db_session)
    workflow_registry = _engagement_workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    namespace = f"test-{uuid4()}"
    cost_tracker = RedisCostTracker(redis_client, pricing_catalog, ledger_namespace=namespace)
    capability_registry = _engagement_capability_registry(
        _RealModelCapability(input_tokens=1000, output_tokens=1000)
    )
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog
    )

    try:
        result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
        assert result.status == "COMPLETED"

        rows = (await db_session.execute(select(AIExecution).where(AIExecution.task_id == task.id))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        # Postgres side: no longer mislabeled as INTELLIGENCE.
        assert row.capability == AICapability.ENGAGEMENT
        assert row.cost == Decimal("0.007000")

        # Redis side: unchanged behavior (it was always correct) - same raw capability-name key.
        capability_ledger_raw = await redis_client.get(capability_ledger_key(namespace, "engagement"))
        assert capability_ledger_raw is not None
        assert float(capability_ledger_raw) == pytest.approx(0.007)

        # Both sources agree on the dollar amount for this capability, and both now agree it is
        # "engagement" - Postgres via the enum value's name, Redis via the raw key it always used.
        assert row.capability.value.lower() == "engagement"
    finally:
        await redis_client.delete(global_ledger_key(namespace))
        await redis_client.delete(capability_ledger_key(namespace, "engagement"))


@pytest.mark.asyncio
async def test_no_ai_execution_row_when_cost_tracker_omitted(db_session: AsyncSession) -> None:
    """The default, backward-compatible path - unchanged from before this optimization."""
    event = await _make_event(db_session)
    workflow_registry = _workflow_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    capability_registry = _capability_registry(_RealModelCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)  # no cost_tracker/pricing_catalog

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
    assert result.status == "COMPLETED"

    rows = (await db_session.execute(select(AIExecution).where(AIExecution.task_id == task.id))).scalars().all()
    assert rows == []
