"""RoutingGateway: the concrete LLMGateway implementation (docs/phase7_architecture_contract.md
§1 P13, §18's "LLMGateway implementation boundary" row - the "Routing Gateway").

M17: the full §15.2 pipeline. `generate()`'s public signature stays exactly
`LLMGateway.generate` (unchanged from Phase 6 §7, per §27's compatibility guarantee).
Internally: RoutingEngine (§4.3) produces ranked candidates, then FallbackPolicy (§5) owns
everything from eligibility filtering through cache/cost/budget/rate-limit/dispatch (§5.3,
§5.4) - RateLimiter and BudgetGuard checks live inside FallbackPolicy's per-candidate loop
(see fallback/policy.py's module docstring for why rate limiting specifically is placed there
rather than as a single pre-routing step).

Confirmed with you (M17): CostTracker.record() is deliberately NOT called by this class.
Amendment C's scope is explicitly narrow - it relocates only BudgetGuard's invocation from
Capability to the Routing Gateway. CostTracker.record()'s existing signature
(task_id, capability_name, call: CapabilityCall) needs a full CapabilityCall that only
Capability.execute() can correctly assemble (§4, unchanged) - recording actual usage remains a
future Capability's post-hoc responsibility, exactly as Phase 6 §9 originally specified.

The M6 Golden Path test (tests/test_routing_gateway_golden_path.py) continues to pass,
unmodified in scenario/assertions, as the simplest regression case for this full pipeline -
its setup code was updated to construct the now-required RoutingEngine/FallbackPolicy
dependencies (a real class's constructor evolving as more of it is built is expected; the
*behavior* it proves - one provider, one model, deterministic response - is unchanged).
"""
from uuid import uuid4

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.observability import ObservabilityContext
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.llm_gateway.routing.criteria import RoutingCriteria
from integrations.llm_gateway.routing.engine import RoutingEngine


class RoutingGateway:
    """The composition root every LLMGateway call flows through. Holds RoutingEngine and
    FallbackPolicy by reference (§18); constructed once at boot (from M19 onward)."""

    def __init__(self, routing_engine: RoutingEngine, fallback_policy: FallbackPolicy) -> None:
        self._routing_engine = routing_engine
        self._fallback_policy = fallback_policy

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        observability = self._build_observability_context(request)
        criteria = self._build_routing_criteria(request)
        ranked_candidates = await self._routing_engine.route(criteria, observability)
        return await self._fallback_policy.dispatch(request, ranked_candidates, criteria, observability)

    def _build_observability_context(self, request: GenerateRequest) -> ObservabilityContext:
        """Constructs an explicit ObservabilityContext from GenerateRequest.metadata (§16.1:
        request_id travels as `metadata["request_id"]`, since LLMGateway.generate()'s
        signature is frozen and carries no separate context parameter). Falls back to a
        freshly generated id as a fallback for any field a caller didn't set, rather than
        raising - a missing id must never block a call."""
        request_id = request.metadata.get("request_id") or str(uuid4())
        trace_id = request.metadata.get("trace_id") or request_id
        capability_execution_id = request.metadata.get("capability_execution_id") or request_id
        return ObservabilityContext(
            trace_id=trace_id,
            capability_execution_id=capability_execution_id,
            request_id=request_id,
        )

    def _build_routing_criteria(self, request: GenerateRequest) -> RoutingCriteria:
        """Builds RoutingCriteria from GenerateRequest - capability_name/priority travel via
        `request.metadata` (no RoutingCriteria-shaped field exists on the frozen
        GenerateRequest), matching the same "extend via metadata" pattern already established
        for observability ids and cache_policy."""
        capability_name = str(request.metadata.get("capability_name", "unknown"))
        priority_raw = request.metadata.get("priority", TaskPriority.B.value)
        priority = priority_raw if isinstance(priority_raw, TaskPriority) else TaskPriority(priority_raw)
        excluded_providers_raw = request.metadata.get("excluded_providers", [])
        excluded_providers = list(excluded_providers_raw) if isinstance(excluded_providers_raw, list) else []

        return RoutingCriteria(
            gateway_method="generate",
            capability_name=capability_name,
            priority=priority,
            requires_tools=bool(request.tools),
            requires_vision="image" in request.modalities,
            requires_structured_output=request.response_mode == "json_schema",
            preferred_model=request.preferred_model,
            preferred_provider=request.preferred_provider,
            excluded_providers=excluded_providers,
        )
