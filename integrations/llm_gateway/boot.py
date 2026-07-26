"""Boot-sequence assembly and validation helpers
(docs/phase7_architecture_contract.md §19, §3 rule 7, §6 rule 4).

Built up across several milestones:
  - M4: validate_registry_consistency() only.
  - M16: validate_retry_ceiling().
  - M19 (this checkpoint): assemble_ai_integration_layer(), the fixed boot sequence (§19
    rule 3), composing every already-implemented §18 component through to a sealed
    CapabilityRegistry.

M19 scope note - two dependencies `assemble_ai_integration_layer()` cannot construct itself:
`prompt_repository: PromptRepository` has no concrete implementation anywhere in this codebase
(the real Prompt Publisher is separate, not-yet-built work, per integrations/prompts/protocol.py's
own docstring - entirely outside Phase 7's scope). It is accepted as a required parameter instead
of being built internally, matching the dependency-injection discipline every other component in
this file already follows (ProviderFactory.build_credential/build_adapter, FallbackPolicy's
constructor, etc. - nothing here ever constructs its own dependencies). `redis_client` is
optional and falls back to `core.redis.get_redis_client()`'s cached singleton (the established
production default) so tests can inject a fresh, uuid-namespaced client instead (avoiding the
cross-event-loop connection-reuse bug the M8 test fixture already works around).

`ToolRegistry` (§9.2) has no such gap: it is a pure, dependency-free sealed registry (like
RoutingPolicyRegistry), so this function constructs and seals an empty one itself - no concrete
tool exists yet to register, exactly mirroring build_registry()'s own "ships empty-sealed" state.

Retry-multiplication-ceiling boot enforcement (§6 rule 4, validate_retry_ceiling() above) is
deliberately NOT wired in here: it needs each registered Capability's Workflow-level
WorkflowRetryPolicy.max_attempts cross-referenced against its Gateway-level fallback config, and
that correlation spans two separate registries (workflows.registry + capabilities.registry) that
CapabilityRegistry has no public API to enumerate. With zero concrete Capabilities registered in
this delivery there is nothing to validate against yet regardless - carried forward exactly as
M16's own log entry already predicted ("in practice this will have zero capabilities to check
against until a future phase adds one"), now correctly still true after M19.
"""
from dataclasses import dataclass

from redis.asyncio import Redis

from core.config import Settings
from core.redis import get_redis_client
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.cache.store import RedisCacheStore
from integrations.llm_gateway.errors import (
    CapabilityNegotiatorNotImplementedError,
    RegistryConsistencyError,
    RetryCeilingExceededError,
)
from integrations.llm_gateway.fallback.health_store import RedisProviderHealthStore
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.llm_gateway.models.registry import ModelRegistry
from integrations.llm_gateway.providers.base import ProviderFactory, ProviderRegistry, build_provider_registry
from integrations.llm_gateway.providers.openai_adapter import OPENAI_PROVIDER_ID, build_openai_provider_factory
from integrations.llm_gateway.rate_limit.limiter import RedisRateLimiter
from integrations.llm_gateway.routing.criteria import RoutingObjective
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.latency_tracker import RedisLatencyTracker
from integrations.llm_gateway.routing.policy import (
    BestQualityPolicy,
    FastestPolicy,
    LowestCostPolicy,
    ReasoningPolicy,
)
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.protocol import PromptRepository
from services.budget_guard import RedisBudgetGuard
from services.cost_estimator import CostEstimator
from services.cost_tracker import CostTracker, RedisCostTracker
from services.pricing_catalog import ModelRegistryPricingCatalog

from capabilities.registry import CapabilityRegistry, build_registry

DEFAULT_RETRY_MULTIPLICATION_CEILING = 30


def validate_registry_consistency(providers: ProviderRegistry, models: ModelRegistry) -> None:
    """After both ProviderRegistry and ModelRegistry seal, confirm every
    ModelDescriptor.provider_id resolves in ProviderRegistry (§3 rule 7).

    Raises RegistryConsistencyError on the first mismatch found - the process MUST fail to
    start when this is raised.
    """
    for model in models.all_models():
        if not providers.is_enabled(model.provider_id):
            raise RegistryConsistencyError(
                f"ModelDescriptor '{model.model_id}' names provider_id='{model.provider_id}', "
                "which is not registered in ProviderRegistry."
            )


def validate_retry_ceiling(
    workflow_retry_max_attempts: int,
    max_fallback_attempts: int,
    max_same_candidate_retries: int,
    *,
    ceiling: int = DEFAULT_RETRY_MULTIPLICATION_CEILING,
    capability_name: str | None = None,
) -> None:
    """§6 rule 4: pure arithmetic, no runtime cost. Computes
    WorkflowRetryPolicy.max_attempts x max_fallback_attempts x (1 + max_same_candidate_retries)
    for one Capability's effective configuration and raises RetryCeilingExceededError - not
    merely logs a warning - if the product exceeds `ceiling` (recommended default: 30).

    Called once per registered Capability at boot (at CapabilityRegistry seal time, or an
    equivalent boot-sequence validation, §19) - `capability_name` is included in the error
    message when the caller has one, to make a boot-time failure immediately actionable.
    """
    total_attempts = workflow_retry_max_attempts * max_fallback_attempts * (1 + max_same_candidate_retries)
    if total_attempts > ceiling:
        subject = f"capability '{capability_name}'" if capability_name else "this configuration"
        raise RetryCeilingExceededError(
            f"Retry-multiplication ceiling exceeded for {subject}: "
            f"{workflow_retry_max_attempts} (workflow) x {max_fallback_attempts} (fallback) x "
            f"{1 + max_same_candidate_retries} (1 + same-candidate retries) = {total_attempts} "
            f"> ceiling {ceiling}."
        )


@dataclass(frozen=True)
class AIIntegrationLayer:
    """Everything a caller needs once boot completes (§19 rule 3's final state, "process ready
    to serve"): the assembled LLMGateway implementation boundary, the sealed CapabilityRegistry
    a future Capability-executing caller (e.g. CapabilityExecutor) resolves against, and
    CostTracker - constructed per §19 rule 3's "every §18 component constructed" but not called
    by anything in this delivery (RoutingGateway.generate() deliberately never calls
    CostTracker.record(), confirmed at M17 - a future Capability's post-hoc responsibility) -
    returned here rather than discarded so that future caller has it ready to inject."""

    gateway: RoutingGateway
    capability_registry: CapabilityRegistry
    cost_tracker: CostTracker


def _build_provider_factories() -> dict[str, ProviderFactory]:
    """One entry per onboarded provider (§20.1). OpenAI (M18) is the only real adapter this
    delivery has; adding a second provider is exactly a one-line addition here (§22 rule 1) -
    zero change to this function's shape or to anything else in this module."""
    return {OPENAI_PROVIDER_ID: build_openai_provider_factory()}


def assemble_ai_integration_layer(
    settings: Settings,
    prompt_repository: PromptRepository,
    *,
    redis_client: Redis | None = None,
) -> AIIntegrationLayer:
    """The fixed boot order (§19 rule 3), in this exact sequence:

    ProviderRegistry + ModelRegistry seal -> boot-time cross-registry validation (§3 rule 7) ->
    optional CapabilityNegotiator.verify() pass (§17.3, fails loud instead - see below) ->
    every §18 component constructed -> the LLMGateway implementation boundary assembled
    (RoutingGateway) -> build_registry() called -> CapabilityRegistry sealed -> ready to serve.

    §17.3's CapabilityNegotiator pass is opt-in and gated behind
    `settings.verify_capabilities_at_boot` (default False) - but CapabilityNegotiator itself
    has no implementation anywhere in this codebase yet (deferred past this delivery, per the
    M17 hand-off's documented scope reduction). Requesting it via `verify_capabilities_at_boot
    =True` without an implementation to honor it would silently no-op if left unchecked; this
    function fails loud instead (CapabilityNegotiatorNotImplementedError), matching this
    codebase's established boot discipline (RegistryConsistencyError, MissingRedisFailurePolicy
    Error, UnknownProviderError all already fail the same way rather than silently degrading).
    """
    if settings.verify_capabilities_at_boot:
        raise CapabilityNegotiatorNotImplementedError(
            "settings.verify_capabilities_at_boot=True, but CapabilityNegotiator (§17.3) has "
            "no implementation yet in this codebase - deferred past this delivery. Set "
            "verify_capabilities_at_boot=False (the default) until a future milestone "
            "implements it."
        )

    redis = redis_client if redis_client is not None else get_redis_client()

    model_registry = build_model_registry()
    provider_registry = build_provider_registry(settings, _build_provider_factories())
    validate_registry_consistency(provider_registry, model_registry)

    health_store = RedisProviderHealthStore(redis)
    latency_tracker = RedisLatencyTracker(redis)
    rate_limiter = RedisRateLimiter(redis, settings)
    cache_coordinator = CacheCoordinator(RedisCacheStore(redis))
    pricing_catalog = ModelRegistryPricingCatalog(model_registry)
    cost_estimator = CostEstimator(pricing_catalog)
    budget_guard = RedisBudgetGuard(redis, settings)
    cost_tracker = RedisCostTracker(redis, pricing_catalog)

    policy_registry = RoutingPolicyRegistry()
    policy_registry.register(RoutingObjective.BEST_QUALITY.value, BestQualityPolicy())
    policy_registry.register(RoutingObjective.LOWEST_COST.value, LowestCostPolicy())
    policy_registry.register(RoutingObjective.FASTEST.value, FastestPolicy())
    policy_registry.register(RoutingObjective.REASONING.value, ReasoningPolicy())
    policy_registry.seal()

    routing_engine = RoutingEngine(
        model_registry=model_registry,
        provider_registry=provider_registry,
        health_store=health_store,
        latency_tracker=latency_tracker,
        policy_registry=policy_registry,
    )
    fallback_policy = FallbackPolicy(
        provider_registry=provider_registry,
        health_store=health_store,
        cache_coordinator=cache_coordinator,
        cost_estimator=cost_estimator,
        budget_guard=budget_guard,
        rate_limiter=rate_limiter,
        regional_unavailable_cooldown_seconds=settings.provider_regional_unavailable_cooldown_seconds,
    )
    gateway = RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)

    tool_registry = ToolRegistry()
    tool_registry.seal()

    capability_registry = build_registry(gateway, prompt_repository, budget_guard, tool_registry)

    return AIIntegrationLayer(
        gateway=gateway, capability_registry=capability_registry, cost_tracker=cost_tracker
    )
