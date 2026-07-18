"""FakeProviderAdapter: a configurable, deterministic ProviderAdapter (LLMGateway
implementation, §2) for tests - no network, no real provider. Mirrors fake_gateway.py's
existing FakeLLMGateway style, extended with a `behavior` toggle so tests can exercise
routing/fallback across multiple distinct fake provider_ids without any real adapter
existing yet, and an optional `structured_output` (Phase 8 M4: a real, schema-validated
Capability's own tests need a response shaped to match its output_schema, which the
previous unconditional `structured_output=None` could never provide - additive,
backward-compatible with every existing caller that doesn't set it).

Only `generate()` has real, configurable behavior - matching this delivery's reduced scope
(docs/phase7_architecture_contract.md's Protocol methods stay unchanged, but
generate_stream/embed/classify/moderate/rerank are deferred past this delivery, §2 rule 5's
"generate() alone is sufficient to onboard" minimum bar). The other five methods always raise
UnsupportedGatewayCapabilityError, exactly matching what the real OpenAI adapter (a future
milestone) does for the same deferred methods.
"""
from collections.abc import AsyncIterator
from typing import Any, Literal

from integrations.llm_gateway.errors import (
    ProviderModerationBlockedError,
    ProviderPermanentIncompatibleError,
    ProviderTransientError,
)
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
    RerankRequest,
    RerankResponse,
    UnsupportedGatewayCapabilityError,
)
from schemas.capability import CapabilityUsage

FakeProviderBehavior = Literal[
    "success", "transient_failure", "permanent_incompatible", "moderation_block"
]


class FakeProviderAdapter:
    """A deterministic stand-in for a real ProviderAdapter, scoped to one fake provider_id.

    `call_count` lets a test assert exactly how many times generate() was attempted (e.g. to
    verify same-candidate retry counts once FallbackPolicy exists, M15).
    """

    def __init__(
        self,
        provider_id: str,
        model_id: str,
        behavior: FakeProviderBehavior = "success",
        *,
        structured_output: dict[str, Any] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.behavior = behavior
        self.structured_output = structured_output
        self.call_count = 0

    def _maybe_fail(self) -> None:
        if self.behavior == "transient_failure":
            raise ProviderTransientError(
                f"[{self.provider_id}/{self.model_id}] simulated transient failure"
            )
        if self.behavior == "permanent_incompatible":
            raise ProviderPermanentIncompatibleError(
                f"[{self.provider_id}/{self.model_id}] simulated permanent-incompatible failure"
            )
        if self.behavior == "moderation_block":
            raise ProviderModerationBlockedError(
                f"[{self.provider_id}/{self.model_id}] simulated moderation block"
            )

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.call_count += 1
        self._maybe_fail()
        return GenerateResponse(
            text=f"fake response from {self.model_id}",
            structured_output=self.structured_output,
            finish_reason="stop",
            model_used=self.model_id,
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )

    async def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        raise UnsupportedGatewayCapabilityError(
            f"{self.provider_id}: generate_stream() is deferred past this delivery"
        )
        yield  # pragma: no cover - unreachable; keeps this an async generator for typing

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise UnsupportedGatewayCapabilityError(
            f"{self.provider_id}: embed() is deferred past this delivery"
        )

    async def classify(self, request: ClassifyRequest) -> ClassifyResponse:
        raise UnsupportedGatewayCapabilityError(
            f"{self.provider_id}: classify() is deferred past this delivery"
        )

    async def moderate(self, request: ModerateRequest) -> ModerateResponse:
        raise UnsupportedGatewayCapabilityError(
            f"{self.provider_id}: moderate() is deferred past this delivery"
        )

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        raise UnsupportedGatewayCapabilityError(
            f"{self.provider_id}: rerank() is deferred past this delivery"
        )
