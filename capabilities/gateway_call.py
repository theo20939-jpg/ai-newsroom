"""Shared Gateway-call support mechanism (Phase 8 contract §6.8/§11.5).

Centralizes the three obligations every `Capability` that calls
`LLMGateway.generate()` must satisfy identically, so no `Capability`
reimplements them independently and divergently:

- §6.4/§13.3: assemble exactly one `CapabilityCall` per Gateway invocation,
  success or failure.
- §6.5/§12: stamp `trace_id`/`capability_execution_id`/`request_id` onto the
  outgoing request, derived exactly per Phase 7 §16.1's formula.
- §6.7/§11.2: translate the externally observable Gateway failure model
  (`NoRoutableCandidateError`, `ProviderModerationBlockedError`,
  `AllProvidersFailedError`, `UnsupportedGatewayCapabilityError` - verified
  against the real `FallbackPolicy` implementation, §11.4) into the correct
  `CapabilityError` subtype.

Deliberately a plain async function plus one small immutable outcome type,
not a base class - per §19.2 Q1's instruction not to lock in a shape before
M3/M7 give real evidence of what's actually shared. `call_generate()` never
raises: it always returns a `GatewayCallOutcome` carrying the built
`CapabilityCall` plus either a `GenerateResponse` (success) or an
already-classified `CapabilityError` instance (failure, not yet raised) -
the calling `Capability` decides when to append the call to its own `calls`
list and when to raise, per §11.1.

`AllProvidersFailedError` classification note (§11.2): the real
`FallbackPolicy` implementation (`integrations/llm_gateway/fallback/
policy.py`) only ever raises this with `reason` one of
"cost_ceiling_exhausted", "all_candidates_failed", or
"all_candidates_budget_denied" - the per-candidate `FailureClass`
(TRANSIENT vs PERMANENT_INCOMPATIBLE) that would distinguish a "purely
transient exhaustion" is tracked internally during the dispatch loop but is
never threaded into the raised exception. No `reason` value is therefore
ever verifiably "purely transient", so this mechanism always takes §11.2's
default branch and classifies `AllProvidersFailedError` as
`PermanentCapabilityError`. This is a literal reading of the existing rule,
not a reinterpretation of it: the "unless...purely transient" carve-out
requires positive evidence this mechanism can never observe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityError,
    PermanentCapabilityError,
)
from integrations.llm_gateway.errors import (
    AllProvidersFailedError,
    NoRoutableCandidateError,
    ProviderModerationBlockedError,
)
from integrations.llm_gateway.protocol import (
    GenerateRequest,
    GenerateResponse,
    LLMGateway,
    UnsupportedGatewayCapabilityError,
)
from core.config import settings
from schemas.capability import CapabilityCall, CapabilityUsage, RuntimeContext


@dataclass(frozen=True)
class GatewayCallOutcome:
    """The result of one centrally-managed `LLMGateway.generate()` call.

    Always populated, never raises - `call` is present on both success and
    failure (§6.4/§13.3); exactly one of `response`/`error` is set.
    """

    call: CapabilityCall
    response: GenerateResponse | None
    error: CapabilityError | None


def _capability_execution_id(runtime: RuntimeContext) -> str:
    """Phase 7 §16.1's formula, restated per contract §12.1 - the only derivation allowed."""
    return f"{runtime.task_id}:{runtime.capability_name}:{runtime.attempt}"


def _stamp_observability_metadata(
    request: GenerateRequest, *, runtime: RuntimeContext, request_id: str
) -> GenerateRequest:
    """§6.5/§12.2: stamp trace_id/capability_execution_id/request_id onto the outgoing request.

    Phase 19 M14: also injects a per-capability routing-objective override, if one exists in
    `settings.capability_routing_objective_overrides` (empty by default - a no-op for every
    caller until that dict is explicitly populated, which is not done as part of this
    implementation). The gateway already knows how to honor `request.metadata["objective"]` -
    no change to RoutingEngine/RoutingCriteria/the gateway itself was needed."""
    metadata = {
        **request.metadata,
        "trace_id": str(runtime.task_id),
        "capability_execution_id": _capability_execution_id(runtime),
        "request_id": request_id,
    }
    objective_override = settings.capability_routing_objective_overrides.get(runtime.capability_name)
    if objective_override is not None:
        metadata["objective"] = objective_override
    return request.model_copy(update={"metadata": metadata})


def _classify_gateway_error(error: Exception) -> CapabilityError:
    """§6.7/§11.2: translate one of the four externally observable Gateway exceptions into the
    correct CapabilityError subtype. See module docstring for the AllProvidersFailedError note."""
    if isinstance(error, ProviderModerationBlockedError):
        # §11.3: never retried, never triggers fallback to a different provider/model.
        return PermanentCapabilityError(str(error))
    if isinstance(error, AllProvidersFailedError):
        return PermanentCapabilityError(str(error))
    if isinstance(error, (NoRoutableCandidateError, UnsupportedGatewayCapabilityError)):
        return CapabilityConfigurationError(str(error))
    raise AssertionError(f"not one of the four externally observable Gateway exceptions: {error!r}")


async def call_generate(
    gateway: LLMGateway,
    request: GenerateRequest,
    *,
    runtime: RuntimeContext,
    sequence: int,
) -> GatewayCallOutcome:
    """Make one `LLMGateway.generate()` call with full §6.4/§6.5/§6.7 bookkeeping.

    `request` MUST NOT already carry `trace_id`/`capability_execution_id`/`request_id` in its
    metadata - this function derives and stamps all three (§6.5/§12.2).
    """
    call_id = uuid4()
    request_id = str(call_id)
    stamped_request = _stamp_observability_metadata(request, runtime=runtime, request_id=request_id)

    started_at = datetime.now(timezone.utc)
    try:
        response = await gateway.generate(stamped_request)
    except (
        NoRoutableCandidateError,
        ProviderModerationBlockedError,
        AllProvidersFailedError,
        UnsupportedGatewayCapabilityError,
    ) as exc:
        finished_at = datetime.now(timezone.utc)
        call = CapabilityCall(
            call_id=call_id,
            sequence=sequence,
            gateway_method="generate",
            status="FAILED",
            model_used=None,
            usage=CapabilityUsage(),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            error=str(exc),
        )
        return GatewayCallOutcome(call=call, response=None, error=_classify_gateway_error(exc))

    finished_at = datetime.now(timezone.utc)
    call = CapabilityCall(
        call_id=call_id,
        sequence=sequence,
        gateway_method="generate",
        status="SUCCESS",
        model_used=response.model_used,
        usage=response.usage,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=(finished_at - started_at).total_seconds(),
    )
    return GatewayCallOutcome(call=call, response=response, error=None)
