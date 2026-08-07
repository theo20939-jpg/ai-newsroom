"""Tests for capabilities.gateway_call - the shared §6.8 Gateway-call support mechanism.

Uses a small test-local stub gateway (not tests/fakes/fake_gateway.py's
FakeLLMGateway) since configuring per-call success/failure/exception
behavior is this milestone's own concern; the shared fixture formalization
is M6's job, not this milestone's.
"""
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from capabilities.errors import CapabilityConfigurationError, PermanentCapabilityError
from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import AllProvidersFailedError, NoRoutableCandidateError, ProviderModerationBlockedError
from integrations.llm_gateway.protocol import (
    ClassifyRequest,
    ClassifyResponse,
    EmbedRequest,
    EmbedResponse,
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    ModerateRequest,
    ModerateResponse,
    Message,
    ContentPart,
    RerankRequest,
    RerankResponse,
    UnsupportedGatewayCapabilityError,
)
from schemas.capability import CapabilityUsage, RuntimeContext


class _StubGateway:
    """Implements LLMGateway. `generate()` either returns a fixed response or raises a
    pre-configured exception, and records every stamped request it received."""

    def __init__(self, *, response: GenerateResponse | None = None, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.received_requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.received_requests.append(request)
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return self._response

    async def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        raise NotImplementedError
        yield  # pragma: no cover - unreachable; makes this an async generator for typing

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise NotImplementedError

    async def classify(self, request: ClassifyRequest) -> ClassifyResponse:
        raise NotImplementedError

    async def moderate(self, request: ModerateRequest) -> ModerateResponse:
        raise NotImplementedError

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        raise NotImplementedError


def _runtime(*, attempt: int = 1) -> RuntimeContext:
    return RuntimeContext(
        task_id=uuid4(),
        event_id=uuid4(),
        capability_name="test_capability",
        priority=TaskPriority.B,
        attempt=attempt,
        iteration_count=0,
    )


def _request() -> GenerateRequest:
    return GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])])


def _success_response() -> GenerateResponse:
    return GenerateResponse(
        text="ok",
        structured_output=None,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


@pytest.mark.asyncio
async def test_success_call_produces_success_capability_call_and_response() -> None:
    gateway = _StubGateway(response=_success_response())
    runtime = _runtime()

    outcome = await call_generate(gateway, _request(), runtime=runtime, sequence=0)

    assert outcome.error is None
    assert outcome.response is not None
    assert outcome.response.model_used == "fake-model-v1"
    assert outcome.call.status == "SUCCESS"
    assert outcome.call.sequence == 0
    assert outcome.call.gateway_method == "generate"
    assert outcome.call.model_used == "fake-model-v1"
    assert outcome.call.usage.input_tokens == 10
    assert outcome.call.error is None


@pytest.mark.asyncio
async def test_sequence_number_and_timing_are_correct_across_multiple_calls() -> None:
    gateway = _StubGateway(response=_success_response())
    runtime = _runtime()

    first = await call_generate(gateway, _request(), runtime=runtime, sequence=0)
    second = await call_generate(gateway, _request(), runtime=runtime, sequence=1)

    assert first.call.sequence == 0
    assert second.call.sequence == 1
    assert first.call.call_id != second.call.call_id
    for outcome in (first, second):
        assert outcome.call.started_at <= outcome.call.finished_at
        assert outcome.call.duration_seconds >= 0


@pytest.mark.asyncio
async def test_observability_metadata_matches_phase7_16_1_formula() -> None:
    gateway = _StubGateway(response=_success_response())
    runtime = _runtime(attempt=3)

    outcome = await call_generate(gateway, _request(), runtime=runtime, sequence=0)

    assert len(gateway.received_requests) == 1
    stamped = gateway.received_requests[0]
    assert stamped.metadata["trace_id"] == str(runtime.task_id)
    assert stamped.metadata["capability_execution_id"] == f"{runtime.task_id}:test_capability:3"
    assert stamped.metadata["request_id"] == str(outcome.call.call_id)


@pytest.mark.asyncio
async def test_no_objective_override_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 19 M14: capability_routing_objective_overrides defaults empty - metadata["objective"]
    must never appear unless explicitly configured."""
    from core.config import settings

    monkeypatch.setattr(settings, "capability_routing_objective_overrides", {})
    gateway = _StubGateway(response=_success_response())

    await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

    assert "objective" not in gateway.received_requests[0].metadata


@pytest.mark.asyncio
async def test_objective_override_is_injected_when_configured_for_this_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "capability_routing_objective_overrides", {"test_capability": "best_quality"})
    gateway = _StubGateway(response=_success_response())

    await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

    assert gateway.received_requests[0].metadata["objective"] == "best_quality"


@pytest.mark.asyncio
async def test_objective_override_only_applies_to_the_matching_capability_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "capability_routing_objective_overrides", {"some_other_capability": "fastest"})
    gateway = _StubGateway(response=_success_response())

    await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

    assert "objective" not in gateway.received_requests[0].metadata


@pytest.mark.asyncio
async def test_no_routable_candidate_error_maps_to_configuration_error() -> None:
    gateway = _StubGateway(raises=NoRoutableCandidateError("no candidates"))

    outcome = await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

    assert outcome.response is None
    assert isinstance(outcome.error, CapabilityConfigurationError)
    assert outcome.call.status == "FAILED"
    assert outcome.call.error is not None


@pytest.mark.asyncio
async def test_unsupported_gateway_capability_error_maps_to_configuration_error() -> None:
    gateway = _StubGateway(raises=UnsupportedGatewayCapabilityError("unsupported"))

    outcome = await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

    assert isinstance(outcome.error, CapabilityConfigurationError)
    assert outcome.call.status == "FAILED"


@pytest.mark.asyncio
async def test_provider_moderation_blocked_error_maps_to_permanent_and_is_non_retryable() -> None:
    gateway = _StubGateway(raises=ProviderModerationBlockedError("blocked"))

    outcome = await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

    assert isinstance(outcome.error, PermanentCapabilityError)
    assert not isinstance(outcome.error, CapabilityConfigurationError)
    assert outcome.call.status == "FAILED"


@pytest.mark.asyncio
async def test_all_providers_failed_error_always_maps_to_permanent() -> None:
    """§11.2 note: no `reason` value is ever verifiably "purely transient" against the real
    FallbackPolicy implementation, so this always takes the default (Permanent) branch."""
    for reason in ("cost_ceiling_exhausted", "all_candidates_failed", "all_candidates_budget_denied"):
        gateway = _StubGateway(raises=AllProvidersFailedError("exhausted", reason=reason))

        outcome = await call_generate(gateway, _request(), runtime=_runtime(), sequence=0)

        assert isinstance(outcome.error, PermanentCapabilityError), reason
        assert outcome.call.status == "FAILED"


def test_internal_gateway_errors_never_referenced_by_this_module() -> None:
    """Guards against reintroducing the corrected contract §11.4 misconception: these four
    exceptions are caught internally by FallbackPolicy and never cross the Gateway boundary."""
    import capabilities.gateway_call as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as f:
        content = f.read()

    for forbidden_name in (
        "ProviderTransientError",
        "ProviderPermanentIncompatibleError",
        "RateLimitExceededError",
        "BudgetExceededError",
    ):
        assert forbidden_name not in content, f"{forbidden_name} must not be referenced"
