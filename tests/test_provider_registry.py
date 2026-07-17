"""Tests for integrations.llm_gateway.providers.base.ProviderRegistry / build_provider_registry
(docs/phase7_architecture_contract.md §2). Pure unit tests, no I/O.

Uses a minimal, locally-defined dummy adapter satisfying the LLMGateway Protocol shape - the
full configurable FakeProviderAdapter (with success/failure/behavior toggles) is built in M5;
this milestone only needs *something* structurally valid to register.
"""
from collections.abc import AsyncIterator
from typing import Any

import pytest

from integrations.llm_gateway.errors import (
    DuplicateProviderRegistrationError,
    ProviderRegistryAlreadySealedError,
    UnknownProviderError,
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
)
from integrations.llm_gateway.providers.base import (
    ProviderCredential,
    ProviderDescriptor,
    ProviderFactory,
    ProviderRegistry,
    build_provider_registry,
)
from core.config import Settings


class _MinimalAdapter:
    """Structurally satisfies LLMGateway - every method is a stub, never called by these tests."""

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        raise NotImplementedError

    async def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for typing purposes

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise NotImplementedError

    async def classify(self, request: ClassifyRequest) -> ClassifyResponse:
        raise NotImplementedError

    async def moderate(self, request: ModerateRequest) -> ModerateResponse:
        raise NotImplementedError

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        raise NotImplementedError


def _descriptor(provider_id: str = "fake-provider") -> ProviderDescriptor:
    return ProviderDescriptor(provider_id=provider_id, display_name="Fake Provider")


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_register_then_resolve_round_trips() -> None:
    registry = ProviderRegistry()
    adapter = _MinimalAdapter()

    registry.register(_descriptor(), adapter)

    assert registry.resolve("fake-provider") is adapter


def test_resolve_unknown_provider_raises() -> None:
    registry = ProviderRegistry()

    with pytest.raises(UnknownProviderError):
        registry.resolve("does-not-exist")


def test_register_duplicate_provider_id_raises() -> None:
    registry = ProviderRegistry()
    registry.register(_descriptor(), _MinimalAdapter())

    with pytest.raises(DuplicateProviderRegistrationError):
        registry.register(_descriptor(), _MinimalAdapter())


def test_register_after_seal_raises() -> None:
    registry = ProviderRegistry()
    registry.seal()

    with pytest.raises(ProviderRegistryAlreadySealedError):
        registry.register(_descriptor(), _MinimalAdapter())


def test_is_enabled_true_for_registered_provider() -> None:
    registry = ProviderRegistry()
    registry.register(_descriptor(), _MinimalAdapter())

    assert registry.is_enabled("fake-provider") is True


def test_is_enabled_false_for_unregistered_provider() -> None:
    registry = ProviderRegistry()

    assert registry.is_enabled("does-not-exist") is False


def test_is_enabled_works_before_and_after_seal() -> None:
    registry = ProviderRegistry()
    registry.register(_descriptor(), _MinimalAdapter())
    before = registry.is_enabled("fake-provider")
    registry.seal()
    after = registry.is_enabled("fake-provider")

    assert before is True
    assert after is True


# --- build_provider_registry() --------------------------------------------------------


def test_build_provider_registry_registers_enabled_and_credentialed_provider() -> None:
    adapter = _MinimalAdapter()
    factory = ProviderFactory(
        descriptor=_descriptor("fake-provider"),
        build_credential=lambda settings: ProviderCredential(api_key="k"),  # type: ignore[arg-type]
        build_adapter=lambda credential: adapter,
    )
    settings = _settings(enabled_providers=["fake-provider"])

    registry = build_provider_registry(settings, {"fake-provider": factory})

    assert registry.resolve("fake-provider") is adapter
    assert registry.is_enabled("fake-provider") is True


def test_build_provider_registry_skips_provider_missing_credential() -> None:
    factory = ProviderFactory(
        descriptor=_descriptor("fake-provider"),
        build_credential=lambda settings: ProviderCredential(),
        build_adapter=lambda credential: _MinimalAdapter(),
    )
    settings = _settings(enabled_providers=["fake-provider"])

    registry = build_provider_registry(settings, {"fake-provider": factory})

    assert registry.is_enabled("fake-provider") is False
    with pytest.raises(UnknownProviderError):
        registry.resolve("fake-provider")


def test_build_provider_registry_skips_provider_absent_from_enabled_providers() -> None:
    factory = ProviderFactory(
        descriptor=_descriptor("fake-provider"),
        build_credential=lambda settings: ProviderCredential(api_key="k"),  # type: ignore[arg-type]
        build_adapter=lambda credential: _MinimalAdapter(),
    )
    settings = _settings(enabled_providers=[])

    registry = build_provider_registry(settings, {"fake-provider": factory})

    assert registry.is_enabled("fake-provider") is False


def test_build_provider_registry_raises_when_enabled_provider_has_no_factory() -> None:
    settings = _settings(enabled_providers=["ghost-provider"])

    with pytest.raises(UnknownProviderError):
        build_provider_registry(settings, {})


def test_build_provider_registry_seals_the_result() -> None:
    settings = _settings(enabled_providers=[])

    registry = build_provider_registry(settings, {})

    with pytest.raises(ProviderRegistryAlreadySealedError):
        registry.register(_descriptor(), _MinimalAdapter())
