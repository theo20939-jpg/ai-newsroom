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
from database.models.ai_execution import AIExecution
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.models.catalog import build_model_registry
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
