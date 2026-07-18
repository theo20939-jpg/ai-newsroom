"""Phase 8 M8: cross-cutting regression and checkpoint - the Phase 8 equivalent of Phase 7
M20. Proves the whole Capability Layer (M0-M7 combined) composes as one real system, not just
as isolated per-milestone slices, with zero regression to the frozen Phase 6/7 stack beneath
it.

Boot-sequence note (mirrors M4's own established resolution, see
tests/test_capability_boot_wiring_e2e.py): `assemble_ai_integration_layer()` (Phase 7 M19,
frozen, never modified by Phase 8) has no provider-factory injection seam - it always
constructs a real OpenAIAdapter internally. It CAN be proven, unmodified, to resolve both
registered capabilities (mirrors tests/test_boot_assembly.py's own established
fake-credential-string pattern - client-side construction only, generate() never called, no
real network call anywhere). Actually EXECUTING both capabilities end to end in one process
uses a real RoutingGateway assembled manually with FakeProviderAdapter underneath (mirrors
tests/test_ai_integration_layer_e2e.py's and test_capability_boot_wiring_e2e.py's own
_build_gateway() pattern) - the same real Gateway class, just with a fake adapter at the
bottom instead of one requiring a genuine network call, per Phase 7's own testing discipline
(§15.5/§15.6).
"""
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from capabilities.quality_capability import CAPABILITY_NAME as QUALITY_CAPABILITY_NAME
from capabilities.quality_capability import QualityCapability
from capabilities.registry import build_registry
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from capabilities.scoring_capability import ScoringCapability
from core.config import Settings
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
from integrations.prompts.protocol import PromptRepository
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_infra import (
    AllowingBudgetGuard,
    EmptyLatencyTracker,
    InMemoryCacheStore,
    PermissiveProviderHealthStore,
)
from tests.fakes.fake_provider_adapter import FakeProviderAdapter
from uuid import uuid4

from database.models.editorial_task import TaskPriority

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _context(capability_name: str, *, preferred_model: str | None = None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title="Example headline",
                summary="A short summary.",
                content=None,
                url=None,
                category="technology",
                published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="daily_digest", workflow_version=1, completed_steps=[]
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(),
            event_id=uuid4(),
            capability_name=capability_name,
            priority=TaskPriority.B,
            attempt=1,
            iteration_count=0,
        ),
        execution=ExecutionContext(preferred_model=preferred_model),
    )


# ---------------------------------------------------------------------------
# 1. The complete, unmodified boot sequence resolves both registered capabilities.
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


def test_full_boot_sequence_resolves_both_registered_capabilities(redis_client: Redis) -> None:
    layer = assemble_ai_integration_layer(_boot_settings(), _prompt_repository(), redis_client=redis_client)

    scoring_definition, scoring_capability = layer.capability_registry.resolve(SCORING_CAPABILITY_NAME)
    quality_definition, quality_capability = layer.capability_registry.resolve(QUALITY_CAPABILITY_NAME)

    assert scoring_definition.name == SCORING_CAPABILITY_NAME
    assert isinstance(scoring_capability, ScoringCapability)
    assert quality_definition.name == QUALITY_CAPABILITY_NAME
    assert isinstance(quality_capability, QualityCapability)


# ---------------------------------------------------------------------------
# 2. Both capabilities, resolved from one CapabilityRegistry, actually execute end to end
#    through a real RoutingGateway in the same process - not isolated per-milestone slices.
# ---------------------------------------------------------------------------


def _model(model_id: str, provider_id: str, *, supports_structured_output: bool = True) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        supports_structured_output=supports_structured_output,
        pricing_tiers=[
            PricingTier(condition="standard", input_price_per_million=Decimal("1"), output_price_per_million=Decimal("1"))
        ],
    )


@pytest.mark.asyncio
async def test_both_capabilities_execute_in_one_process_through_a_real_gateway() -> None:
    scoring_provider, scoring_model = "fake_scoring_provider", "fake-scoring-model"
    quality_provider, quality_model = "fake_quality_provider", "fake-quality-model"

    scoring_adapter = FakeProviderAdapter(
        provider_id=scoring_provider, model_id=scoring_model,
        structured_output={"score": 85, "rationale": "Broadly relevant."},
    )
    quality_adapter = FakeProviderAdapter(
        provider_id=quality_provider, model_id=quality_model,
        structured_output={"passed": True, "issues": []},
    )

    providers = ProviderRegistry()
    providers.register(ProviderDescriptor(provider_id=scoring_provider, display_name=scoring_provider), scoring_adapter)
    providers.register(ProviderDescriptor(provider_id=quality_provider, display_name=quality_provider), quality_adapter)
    providers.seal()

    models = ModelRegistry()
    models.register(_model(scoring_model, scoring_provider))
    models.register(_model(quality_model, quality_provider))
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
    gateway = RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)

    registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    _, scoring_capability = registry.resolve(SCORING_CAPABILITY_NAME)
    _, quality_capability = registry.resolve(QUALITY_CAPABILITY_NAME)

    # preferred_model is the only channel a Capability has to influence routing (advisory
    # only, §6.2) - pinned here so each capability deterministically reaches its own intended
    # fake provider/model rather than an arbitrary tie-break between two equal-quality-tier
    # candidates sharing one ModelRegistry.
    scoring_result = await scoring_capability.execute(_context(SCORING_CAPABILITY_NAME, preferred_model=scoring_model))
    quality_result = await quality_capability.execute(_context(QUALITY_CAPABILITY_NAME, preferred_model=quality_model))

    assert scoring_result.status == "SUCCESS"
    assert scoring_result.structured_output == {"score": 85, "rationale": "Broadly relevant."}
    assert quality_result.status == "SUCCESS"
    assert quality_result.structured_output == {"passed": True, "issues": []}

    # each capability reached its own distinct provider/model - neither shadowed the other's
    # routing, confirming they coexist as independent, correctly-isolated call paths.
    assert scoring_adapter.call_count == 1
    assert quality_adapter.call_count == 1
    assert scoring_result.calls[0].model_used == scoring_model
    assert quality_result.calls[0].model_used == quality_model
