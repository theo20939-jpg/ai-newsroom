"""Typed exception hierarchy for the AI Integration Layer (Phase 7).

Standalone hierarchy - does NOT subclass `capabilities.errors.CapabilityError`.
The Gateway boundary must never import upward into `capabilities/`
(docs/phase7_architecture_contract.md §1: "LLMGateway implementation boundary
-> Capability / CapabilityExecutor / Workflow FORBIDDEN"), so these exceptions
cannot themselves be CapabilityError subtypes. Where the contract states a
mapping to a CapabilityError subtype (e.g. "RateLimitExceededError MUST map to
RetryableCapabilityError"), that mapping is a future Capability author's
responsibility at the point a real Capability catches a Gateway exception and
re-raises the corresponding CapabilityError subtype - it is not performed
inside this module or anywhere in this layer.
"""


class GatewayError(Exception):
    """Base class for every typed exception raised by the AI Integration Layer."""


class UnknownProviderError(GatewayError):
    """Raised by ProviderRegistry.resolve()/is_enabled() for an unregistered provider_id
    (docs/phase7_architecture_contract.md §2)."""


class DuplicateProviderRegistrationError(GatewayError):
    """Raised by ProviderRegistry.register() when provider_id is already registered (§2)."""


class ProviderRegistryAlreadySealedError(GatewayError):
    """Raised by ProviderRegistry.register() once seal() has been called (§2, P18)."""


class UnknownModelError(GatewayError):
    """Raised by ModelRegistry.resolve() for an unregistered model_id (§3)."""


class DuplicateModelRegistrationError(GatewayError):
    """Raised by ModelRegistry.register() when model_id is already registered (§3)."""


class ModelRegistryAlreadySealedError(GatewayError):
    """Raised by ModelRegistry.register() once seal() has been called (§3, P18)."""


class RegistryConsistencyError(GatewayError):
    """Raised at boot if a ModelDescriptor.provider_id does not resolve in ProviderRegistry
    (§3 rule 7). The process MUST fail to start when this is raised."""


class UnknownModelPricingError(GatewayError):
    """Raised when PricingCatalog/CostEstimator cannot find a required PricingTier for a
    model (§15.1, §15.3). Unreachable in practice given §3 rule 3's requirement that every
    model declare a "standard" tier - a violation indicates a ModelRegistry data error."""


class NoRoutableCandidateError(GatewayError):
    """Raised by RoutingEngine when zero candidates survive the §4.3 hard/enabled/exclusion/
    health filters. A non-retryable configuration-flavored failure (§4.3 step 5) - future
    Capability authors are expected to map this to CapabilityConfigurationError."""


class UnknownRoutingObjectiveError(GatewayError):
    """Raised by RoutingPolicyRegistry.resolve() for an unregistered RoutingObjective (§4.5)."""


class RoutingPolicyRegistryAlreadySealedError(GatewayError):
    """Raised by RoutingPolicyRegistry.register() once seal() has been called (§4.5, P18)."""


class AllProvidersFailedError(GatewayError):
    """Raised by FallbackPolicy when its bounded attempt sequence is exhausted (§5.5).

    `reason` is one of "cost_ceiling_exhausted", "all_candidates_failed", or
    "all_candidates_budget_denied" - preserved for CapabilityCall.error diagnostics (§16).
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class RateLimitExceededError(GatewayError):
    """Raised by RateLimiter.acquire() naming the exhausted key(s) (§14). A future Capability
    author is expected to map this to RetryableCapabilityError - by definition transient."""


class MissingRedisFailurePolicyError(GatewayError):
    """Raised at construction (i.e. at boot) by any Redis-backed component whose behavior on
    Redis unavailability is safety-relevant (RateLimiter, the CostTracker ledger) when
    `settings.redis_unavailable_policy` is unset. Per §28 Q1's binding provisional rule: this
    is the one item where "unimplemented, pending decision" is itself the required behavior -
    such a component MUST raise a boot-time configuration error rather than silently picking
    fail-open or fail-closed."""


class RetryCeilingExceededError(GatewayError):
    """Raised at boot (§6 rule 4) when
    WorkflowRetryPolicy.max_attempts x max_fallback_attempts x (1 + max_same_candidate_retries)
    exceeds the configured ceiling (recommended default: 30). Pure arithmetic, no runtime cost."""


class ProviderTransientError(GatewayError):
    """Raised by a ProviderAdapter for a transient dispatch failure - auth (this attempt
    only), rate limit, timeout, 5xx (§5.2). FallbackPolicy classifies this as
    FailureClass.TRANSIENT: mark (provider_id, model_id) unhealthy with TTL, move to the next
    candidate (§5.4)."""


class ProviderPermanentIncompatibleError(GatewayError):
    """Raised by a ProviderAdapter when a claimed capability is not actually supported by the
    candidate that was dispatched to (§5.2). FallbackPolicy classifies this as
    FailureClass.PERMANENT_INCOMPATIBLE: mark (provider_id, model_id) runtime_unavailable with
    no TTL, move to the next candidate (§5.4).

    Reserved for genuinely permanent configuration failures: an unknown model id
    (`NotFoundError`), a request shape the model rejects (`UnprocessableEntityError`, a
    non-moderation `BadRequestError`). A regional/account-level permission failure
    (`PermissionDeniedError`) is deliberately NOT included here - see
    `ProviderRegionalUnavailableError` below (docs/phase15_runtime_reliability_report.md)."""


class ProviderRegionalUnavailableError(GatewayError):
    """Phase 15 runtime reliability fix. Raised by a ProviderAdapter for a `PermissionDeniedError`
    (HTTP 403) specifically - historically observed (docs/llm_runtime_availability_recovery_
    report.md) as an account/region-scoped condition that a direct re-probe hours later found
    already resolved, i.e. NOT the same kind of failure as an invalid model id or a rejected
    request shape (`ProviderPermanentIncompatibleError`), which never self-resolve. FallbackPolicy
    classifies this as a bounded-cooldown latch: mark (provider_id, model_id) runtime_unavailable
    WITH a TTL (`settings.provider_regional_unavailable_cooldown_seconds`), not the permanent,
    no-TTL, manual-clear-only latch used for genuinely permanent configuration errors."""


class ProviderModerationBlockedError(GatewayError):
    """Raised by a ProviderAdapter when content is blocked by moderation (§5.2) - a
    PERMANENT_INCOMPATIBLE-flavored failure FallbackPolicy MUST NOT continue past: it MUST
    raise immediately, never falling back to a different provider/model for the same
    disallowed content (§5.4)."""


class UnknownToolError(GatewayError):
    """Raised by ToolRegistry.resolve() for an unregistered tool name (§9.2)."""


class DuplicateToolRegistrationError(GatewayError):
    """Raised by ToolRegistry.register() when a tool name is already registered (§9.2)."""


class ToolRegistryAlreadySealedError(GatewayError):
    """Raised by ToolRegistry.register() once seal() has been called (§9.2, P18)."""


class CapabilityNegotiatorNotImplementedError(GatewayError):
    """Raised at boot (M19's assemble_ai_integration_layer()) if
    settings.verify_capabilities_at_boot=True but no CapabilityNegotiator implementation
    exists yet (§17.3 is opt-in and deferred past this delivery, per the M17 hand-off's
    documented scope reduction). Boot MUST fail loud on a requested-but-unhonorable
    configuration, never silently no-op it."""
