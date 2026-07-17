"""Tests for integrations.llm_gateway.boot.validate_registry_consistency
(docs/phase7_architecture_contract.md §3 rule 7). Pure unit tests against fake registries."""
from decimal import Decimal
from typing import Any

import pytest

from integrations.llm_gateway.boot import validate_registry_consistency
from integrations.llm_gateway.errors import RegistryConsistencyError
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry


class _DummyAdapter:
    """Never called by these tests - ProviderRegistry.register() only stores a reference,
    it does not invoke any LLMGateway method."""


def _adapter() -> Any:
    return _DummyAdapter()


def _model(model_id: str, provider_id: str) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        pricing_tiers=[
            PricingTier(
                condition="standard",
                input_price_per_million=Decimal("1.00"),
                output_price_per_million=Decimal("2.00"),
            )
        ],
    )


def test_consistent_registries_pass_validation() -> None:
    providers = ProviderRegistry()
    providers.register(ProviderDescriptor(provider_id="fake", display_name="Fake"), _adapter())
    providers.seal()

    models = ModelRegistry()
    models.register(_model("fake-model", "fake"))
    models.seal()

    validate_registry_consistency(providers, models)  # must not raise


def test_dangling_provider_id_raises() -> None:
    providers = ProviderRegistry()
    providers.seal()  # nothing registered

    models = ModelRegistry()
    models.register(_model("orphan-model", "nonexistent-provider"))
    models.seal()

    with pytest.raises(RegistryConsistencyError):
        validate_registry_consistency(providers, models)


def test_empty_model_registry_always_passes() -> None:
    providers = ProviderRegistry()
    providers.seal()

    models = ModelRegistry()
    models.seal()

    validate_registry_consistency(providers, models)  # must not raise
