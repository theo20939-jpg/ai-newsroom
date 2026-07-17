"""ObservabilityContext and the Gateway-internal id-derivation helpers
(docs/phase7_architecture_contract.md §16.1).

Identifier hierarchy (§16.1):
    trace_id                  <- CapabilityContext.runtime.task_id (Phase 6, reused - carried in,
                                  never derived here)
    capability_execution_id   <- derived by CapabilityExecutor (Phase 6 layer, not this one):
                                  f"{task_id}:{capability_name}:{attempt}"
    request_id                <- CapabilityCall.call_id (Phase 6, reused - carried in)
    provider_attempt_id       <- derived here: f"{request_id}:{attempt_index}"
    model_route_id            <- derived here: f"{provider_attempt_id}:{provider_id}:{model_id}"
    tool_call_id              <- derived by the (deferred, not part of this delivery) ToolRegistry
                                  layer, not this module

Only the two Gateway-internal derivations (provider_attempt_id, model_route_id) live here -
trace_id/capability_execution_id/request_id are produced upstream and simply carried by
ObservabilityContext; tool_call_id belongs to ToolExecutionRequest, deferred with the rest of
the tool-calling framework (§9) past this delivery.
"""
from pydantic import BaseModel, ConfigDict


class ObservabilityContext(BaseModel):
    """A lightweight, immutable, read-only value object carrying the id hierarchy.

    MUST be threaded through every layer via explicit parameter passing at construction
    time - MUST NEVER become an implicit thread-local/contextvar, and MUST NEVER itself
    emit anything; each layer that emits a log/metric reads whatever ids it needs from the
    context it was handed (§16.1 binding rule).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    capability_execution_id: str
    request_id: str | None = None


def derive_provider_attempt_id(request_id: str, attempt_index: int) -> str:
    """One per FallbackPolicy candidate attempt within one request_id (§16.1)."""
    return f"{request_id}:{attempt_index}"


def derive_model_route_id(provider_attempt_id: str, provider_id: str, model_id: str) -> str:
    """The specific provider+model an attempt targeted (§16.1)."""
    return f"{provider_attempt_id}:{provider_id}:{model_id}"
