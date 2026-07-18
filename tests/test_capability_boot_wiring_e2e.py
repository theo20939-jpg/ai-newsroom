"""Phase 8 M4: proves the full, real stack composes end to end -
CapabilityExecutor -> CapabilityRegistry -> Capability -> LLMGateway (a real RoutingGateway) ->
FakeProviderAdapter - not just in isolated unit tests (M1-M3). No real network call anywhere:
every provider is a FakeProviderAdapter, mirroring Phase 7's own testing discipline (§15.5) and
tests/test_ai_integration_layer_e2e.py's established _build_gateway() pattern.

Also proves build_registry() itself resolves the M3 ScoringCapability by name and still raises
UnknownCapabilityError for anything else, and (mirroring tests/test_boot_assembly.py's own
established pattern for exercising assemble_ai_integration_layer() without a real network call)
that the complete boot sequence reaches the same registered capability.
"""
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.errors import UnknownCapabilityError
from capabilities.executor import CapabilityExecutor
from capabilities.registry import build_registry
from capabilities.scoring_capability import CAPABILITY_NAME, ScoringCapability
from core.config import Settings
from database.models.editorial_task import TaskPriority
from database.models.news_event import NewsEvent
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.editorial_task import EditorialTaskCreate, EditorialTaskRead
from schemas.workflow import WorkflowDefinition, WorkflowRetryPolicy, WorkflowStepDefinition, WorkflowType
from services import workflow_service
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_infra import (
    AllowingBudgetGuard,
    EmptyLatencyTracker,
    InMemoryCacheStore,
    PermissiveProviderHealthStore,
)
from tests.fakes.fake_provider_adapter import FakeProviderAdapter
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

_PROVIDER_ID = "fake_provider"
_MODEL_ID = "fake-model"
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


class _FakePromptRepository:
    """Test-local stub PromptRepository - only used where real prompt content is not the
    point of the test (the build_registry() smoke test below). The E2E tests use the real M2
    FilePromptRepository against the real prompts/ directory instead."""

    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        return RenderedPrompt(name=name, version=version or "1", system="fake", rules=[], output_schema={})


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _model() -> ModelDescriptor:
    return ModelDescriptor(
        model_id=_MODEL_ID,
        provider_id=_PROVIDER_ID,
        display_name=_MODEL_ID,
        context_window_tokens=128_000,
        supports_structured_output=True,  # ScoringCapability requests response_mode="json_schema"
        pricing_tiers=[
            PricingTier(
                condition="standard", input_price_per_million=Decimal("1"), output_price_per_million=Decimal("1")
            )
        ],
    )


def _build_gateway(adapter: FakeProviderAdapter) -> RoutingGateway:
    """Mirrors tests/test_ai_integration_layer_e2e.py's own _build_gateway() helper - a real
    RoutingGateway assembled from real Phase 7 components, with a FakeProviderAdapter at the
    bottom instead of a real HTTP-calling adapter (Phase 7's own testing discipline, §15.5)."""
    providers = ProviderRegistry()
    providers.register(ProviderDescriptor(provider_id=_PROVIDER_ID, display_name=_PROVIDER_ID), adapter)
    providers.seal()

    models = ModelRegistry()
    models.register(_model())
    models.seal()

    health_store = PermissiveProviderHealthStore()
    routing_engine = RoutingEngine(
        model_registry=models,
        provider_registry=providers,
        health_store=health_store,  # type: ignore[arg-type]
        latency_tracker=EmptyLatencyTracker(),
        policy_registry=RoutingPolicyRegistry(),
    )
    fallback_policy = FallbackPolicy(
        provider_registry=providers,
        health_store=health_store,  # type: ignore[arg-type]
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
        cost_estimator=CostEstimator(ModelRegistryPricingCatalog(models)),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
    )
    return RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)


def _single_scoring_step_workflow_registry(max_attempts: int = 2) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[
                WorkflowStepDefinition(
                    name="score_step", capability=CAPABILITY_NAME, max_attempts=max_attempts, timeout_seconds=10
                )
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=max_attempts, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


async def _created_task(
    session: AsyncSession, event: NewsEvent, workflow_registry: WorkflowRegistry
) -> EditorialTaskRead:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    return await workflow_service.create_task(session, command, registry=workflow_registry)


# ---------------------------------------------------------------------------
# 1. build_registry() itself: resolves the registered M3 capability, still rejects unknowns.
# ---------------------------------------------------------------------------


def test_build_registry_resolves_scoring_and_rejects_unknown() -> None:
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type] # never called in this test - construction only
        prompt_repository=_FakePromptRepository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    definition, capability = registry.resolve(CAPABILITY_NAME)
    assert definition.name == CAPABILITY_NAME
    assert isinstance(capability, ScoringCapability)

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("no_such_capability")


# ---------------------------------------------------------------------------
# 2. Full stack, success path: CapabilityExecutor -> CapabilityRegistry -> ScoringCapability ->
#    a real RoutingGateway -> FakeProviderAdapter.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_executor_executes_scoring_through_a_real_routing_gateway(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    adapter = FakeProviderAdapter(
        provider_id=_PROVIDER_ID, model_id=_MODEL_ID, structured_output={"score": 91, "rationale": "Major story."}
    )
    gateway = _build_gateway(adapter)
    registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]

    workflow_registry = _single_scoring_step_workflow_registry()
    task = await _created_task(db_session, real_news_event, workflow_registry)
    executor = CapabilityExecutor(db_session, task.id, registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].result == {"score": 91, "rationale": "Major story."}
    assert adapter.call_count == 1


# ---------------------------------------------------------------------------
# 3. Full stack, Gateway-layer failure: proves the full §11 translation chain end to end, not
#    just in M1's isolated unit tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_layer_failure_surfaces_as_permanent_step_failure(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    adapter = FakeProviderAdapter(provider_id=_PROVIDER_ID, model_id=_MODEL_ID, behavior="transient_failure")
    gateway = _build_gateway(adapter)
    registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]

    workflow_registry = _single_scoring_step_workflow_registry()
    task = await _created_task(db_session, real_news_event, workflow_registry)
    executor = CapabilityExecutor(db_session, task.id, registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    # AllProvidersFailedError -> PermanentCapabilityError (M1's classification, this
    # milestone's own recorded rule) -> CapabilityExecutor's PermanentStepFailureError mapping
    # -> WorkflowRunner never retries and marks the task FAILED, not COMPLETED. WorkflowRunner's
    # own per-step status/retry-count classification is driven directly by which
    # workflows.errors type was raised (StepExecutionError retries; PermanentStepFailureError
    # does not) - status="FAILED" with exactly one step_result is the complete, sufficient
    # proof that PermanentStepFailureError (not StepExecutionError) crossed that boundary.
    assert result.status == "FAILED"
    assert len(result.step_results) == 1  # no retry for a permanent failure
    assert result.step_results[0].status == "FAILED"


# ---------------------------------------------------------------------------
# 4. The complete boot sequence (assemble_ai_integration_layer(), unmodified) reaches the same
#    registered capability - mirrors tests/test_boot_assembly.py's own established pattern
#    (fake, non-functional credential string; OpenAIAdapter client-side construction only,
#    generate() never called; no real network call anywhere).
# ---------------------------------------------------------------------------


def _boot_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "enabled_providers": ["openai"],
        "openai_api_key": SecretStr("sk-test-not-a-real-key-0000000000"),
        "redis_unavailable_policy": "fail_open",
        "verify_capabilities_at_boot": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[call-arg, arg-type]


def test_full_boot_sequence_resolves_scoring_capability(redis_client: Redis) -> None:
    layer = assemble_ai_integration_layer(_boot_settings(), _prompt_repository(), redis_client=redis_client)

    definition, capability = layer.capability_registry.resolve(CAPABILITY_NAME)
    assert definition.name == CAPABILITY_NAME
    assert isinstance(capability, ScoringCapability)
