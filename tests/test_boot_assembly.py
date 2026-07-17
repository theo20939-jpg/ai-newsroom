"""Tests for integrations.llm_gateway.boot.assemble_ai_integration_layer()
(docs/phase7_architecture_contract.md §19 rule 3 - the fixed boot order). Integration tests
against real local Redis (docker-compose already provisions it) - every test injects the
shared `redis_client` fixture (fresh per test, uuid-free here since nothing this module writes
needs namespacing: RateLimiter/BudgetGuard/CostTracker are only constructed, never invoked).

No real network call anywhere in this file: OpenAIAdapter's AsyncOpenAI client construction is
pure client-side object setup (no request is ever made) - `generate()` itself is never called
here. A fake, clearly-non-functional API key string is used only to satisfy
`ProviderCredential`'s "is present" check so `build_provider_registry()` actually registers the
adapter and `validate_registry_consistency()` has something to validate against - never a real
credential (per instruction: never add a real credential to tests).
"""
import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from capabilities.errors import UnknownCapabilityError
from core.config import Settings
from integrations.llm_gateway.boot import AIIntegrationLayer, assemble_ai_integration_layer
from integrations.llm_gateway.errors import (
    CapabilityNegotiatorNotImplementedError,
    MissingRedisFailurePolicyError,
    RegistryConsistencyError,
)
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from services.cost_tracker import RedisCostTracker


class _FakePromptRepository:
    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        return RenderedPrompt(
            name=name, version=version or "1", system="You are a fake.", rules=[], output_schema={}
        )


def _prompt_repository() -> PromptRepository:
    return _FakePromptRepository()


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "enabled_providers": ["openai"],
        "openai_api_key": SecretStr("sk-test-not-a-real-key-0000000000"),
        "redis_unavailable_policy": "fail_open",
        "verify_capabilities_at_boot": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[call-arg]


def test_assembles_a_working_gateway_and_empty_sealed_capability_registry(redis_client: Redis) -> None:
    layer = assemble_ai_integration_layer(_settings(), _prompt_repository(), redis_client=redis_client)

    assert isinstance(layer, AIIntegrationLayer)
    assert isinstance(layer.gateway, RoutingGateway)
    assert isinstance(layer.cost_tracker, RedisCostTracker)

    with pytest.raises(UnknownCapabilityError):
        layer.capability_registry.resolve("research")


def test_verify_capabilities_at_boot_true_fails_loud_without_an_implementation(redis_client: Redis) -> None:
    with pytest.raises(CapabilityNegotiatorNotImplementedError):
        assemble_ai_integration_layer(
            _settings(verify_capabilities_at_boot=True), _prompt_repository(), redis_client=redis_client
        )


def test_missing_redis_unavailable_policy_fails_loud_at_construction(redis_client: Redis) -> None:
    with pytest.raises(MissingRedisFailurePolicyError):
        assemble_ai_integration_layer(
            _settings(redis_unavailable_policy=None), _prompt_repository(), redis_client=redis_client
        )


def test_model_registered_for_a_disabled_provider_fails_registry_consistency(redis_client: Redis) -> None:
    """§3 rule 7: the static ModelRegistry names provider_id="openai" for every catalogue
    entry; leaving `enabled_providers` empty (no credential registered for "openai" at all)
    must fail boot loud, never silently produce a Gateway that can't route to anything."""
    with pytest.raises(RegistryConsistencyError):
        assemble_ai_integration_layer(
            _settings(enabled_providers=[]), _prompt_repository(), redis_client=redis_client
        )


def test_redis_client_override_is_actually_used_not_the_cached_singleton(redis_client: Redis) -> None:
    """Proves the injected `redis_client` parameter is honored end to end (constructed
    components hold a reference to it), not silently ignored in favor of
    core.redis.get_redis_client()'s module-level cached singleton."""
    layer = assemble_ai_integration_layer(_settings(), _prompt_repository(), redis_client=redis_client)

    assert layer.cost_tracker._redis is redis_client  # type: ignore[attr-defined]
