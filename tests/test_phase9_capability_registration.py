"""Phase 9 M6: capability registration / boot wiring.

Proves `build_registry()` resolves `ResearchCapability`/`IntelligenceCapability` by their
Contract-frozen names (`"research"`/`"intelligence"`), coexisting correctly alongside the
pre-existing Phase 8 `ScoringCapability`/`QualityCapability`, with zero change to
`capabilities/capability_mapping.py`, `integrations/llm_gateway/boot.py`, `ProviderRegistry`,
or `ModelRegistry`.

Kept as a small, new, Phase-9-scoped file rather than editing
`tests/test_capability_boot_wiring_e2e.py` (Phase 8 M4's own file) - mirrors
`tests/test_phase8_cross_cutting_regression.py`'s own decision to add a new file rather than
grow M4's file further, and matches the Plan's own "add a small, focused new test file"
option (§ M6 bullet 3).
"""
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from capabilities.errors import DuplicateCapabilityRegistrationError, UnknownCapabilityError
from capabilities.intelligence_capability import CAPABILITY_NAME as INTELLIGENCE_CAPABILITY_NAME
from capabilities.intelligence_capability import INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability
from capabilities.quality_capability import CAPABILITY_NAME as QUALITY_CAPABILITY_NAME
from capabilities.quality_capability import QualityCapability
from capabilities.registry import CapabilityRegistry, build_registry
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from capabilities.research_capability import RESEARCH_CAPABILITY_DEFINITION, ResearchCapability
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from capabilities.scoring_capability import ScoringCapability
from database.models.editorial_task import TaskPriority
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
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


# ---------------------------------------------------------------------------
# 1. build_registry() resolves all four Capabilities; unknown names still rejected.
# ---------------------------------------------------------------------------


def test_build_registry_resolves_all_four_capabilities_and_rejects_unknown() -> None:
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type] # never called in this test - construction only
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    scoring_definition, scoring_capability = registry.resolve(SCORING_CAPABILITY_NAME)
    quality_definition, quality_capability = registry.resolve(QUALITY_CAPABILITY_NAME)
    research_definition, research_capability = registry.resolve(RESEARCH_CAPABILITY_NAME)
    intelligence_definition, intelligence_capability = registry.resolve(INTELLIGENCE_CAPABILITY_NAME)

    assert scoring_definition.name == SCORING_CAPABILITY_NAME
    assert isinstance(scoring_capability, ScoringCapability)
    assert quality_definition.name == QUALITY_CAPABILITY_NAME
    assert isinstance(quality_capability, QualityCapability)
    assert research_definition.name == RESEARCH_CAPABILITY_NAME
    assert isinstance(research_capability, ResearchCapability)
    assert intelligence_definition.name == INTELLIGENCE_CAPABILITY_NAME
    assert isinstance(intelligence_capability, IntelligenceCapability)

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("no_such_capability")


# ---------------------------------------------------------------------------
# 2. Duplicate registration of either new Capability is rejected, mirroring the existing
#    test pattern already proven for the first two Capabilities (symmetry, not a new
#    mechanism to prove).
# ---------------------------------------------------------------------------


def test_registering_research_or_intelligence_twice_raises_duplicate_registration_error() -> None:
    registry = CapabilityRegistry()
    registry.register(RESEARCH_CAPABILITY_DEFINITION, ResearchCapability(None, _prompt_repository()))  # type: ignore[arg-type]
    registry.register(INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability(None, _prompt_repository()))  # type: ignore[arg-type]

    with pytest.raises(DuplicateCapabilityRegistrationError):
        registry.register(RESEARCH_CAPABILITY_DEFINITION, ResearchCapability(None, _prompt_repository()))  # type: ignore[arg-type]

    with pytest.raises(DuplicateCapabilityRegistrationError):
        registry.register(INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability(None, _prompt_repository()))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. All four Capabilities, resolved from one CapabilityRegistry, actually execute end to end
#    through a real RoutingGateway in the same process (mirrors
#    tests/test_phase8_cross_cutting_regression.py's own pattern, extended to four) - proves
#    no ambiguous-routing failure now that two more Capabilities share the registry/gateway.
# ---------------------------------------------------------------------------


def _model(model_id: str, provider_id: str) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        supports_structured_output=True,
        pricing_tiers=[
            PricingTier(condition="standard", input_price_per_million=Decimal("1"), output_price_per_million=Decimal("1"))
        ],
    )


def _context(capability_name: str, *, preferred_model: str, step_results: dict[str, dict[str, object]] | None = None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title="Example headline",
                summary="A short summary.",
                content="Example body text.",
                url=None,
                category="technology",
                published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="daily_digest",
                workflow_version=1,
                completed_steps=list(step_results.keys()) if step_results else [],
                step_results=step_results or {},
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


@pytest.mark.asyncio
async def test_four_capabilities_execute_in_one_process_through_a_real_gateway() -> None:
    specs = {
        SCORING_CAPABILITY_NAME: ("fake_scoring_provider", "fake-scoring-model", {"score": 85, "rationale": "Broadly relevant."}),
        QUALITY_CAPABILITY_NAME: ("fake_quality_provider", "fake-quality-model", {"passed": True, "issues": []}),
        RESEARCH_CAPABILITY_NAME: ("fake_research_provider", "fake-research-model", CANONICAL_RESEARCH_OUTPUT),
        INTELLIGENCE_CAPABILITY_NAME: (
            "fake_intelligence_provider",
            "fake-intelligence-model",
            {
                "significance": 0.7,
                "angle": "Market impact",
                "audience_relevance": "General audience",
                "recommendation": "Publish",
            },
        ),
    }

    providers = ProviderRegistry()
    adapters: dict[str, FakeProviderAdapter] = {}
    models = ModelRegistry()
    for name, (provider_id, model_id, structured_output) in specs.items():
        adapter = FakeProviderAdapter(provider_id=provider_id, model_id=model_id, structured_output=structured_output)
        adapters[name] = adapter
        providers.register(ProviderDescriptor(provider_id=provider_id, display_name=provider_id), adapter)
        models.register(_model(model_id, provider_id))
    providers.seal()
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

    for name, (_, model_id, expected_output) in specs.items():
        _, capability = registry.resolve(name)
        step_results = {"research": CANONICAL_RESEARCH_OUTPUT} if name == INTELLIGENCE_CAPABILITY_NAME else None
        result = await capability.execute(_context(name, preferred_model=model_id, step_results=step_results))

        assert result.status == "SUCCESS"
        assert result.structured_output == expected_output
        assert result.calls[0].model_used == model_id

    # each capability reached its own distinct provider/model - none shadowed another's routing.
    for adapter in adapters.values():
        assert adapter.call_count == 1
