"""Tests for services.pricing_catalog.ModelRegistryPricingCatalog
(docs/phase7_architecture_contract.md §15.3). Pure unit tests, no I/O."""
from decimal import Decimal

import pytest

from integrations.llm_gateway.errors import UnknownModelPricingError
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from services.pricing_catalog import ModelRegistryPricingCatalog


def _registry_with_model(*, extra_tiers: list[PricingTier] | None = None) -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(
        ModelDescriptor(
            model_id="fake-model-a",
            provider_id="fake-provider",
            display_name="Fake Model A",
            context_window_tokens=128_000,
            pricing_currency="USD",
            pricing_tiers=[
                PricingTier(
                    condition="standard",
                    input_price_per_million=Decimal("1.00"),
                    output_price_per_million=Decimal("2.00"),
                ),
                *(extra_tiers or []),
            ],
        )
    )
    registry.seal()
    return registry


def test_get_tier_returns_the_standard_tier_by_default() -> None:
    catalog = ModelRegistryPricingCatalog(_registry_with_model())

    tier = catalog.get_tier("fake-model-a")

    assert tier.condition == "standard"
    assert tier.input_price_per_million == Decimal("1.00")
    assert tier.output_price_per_million == Decimal("2.00")


def test_get_tier_returns_a_non_standard_tier_when_requested_and_present() -> None:
    batch_tier = PricingTier(
        condition="batch", input_price_per_million=Decimal("0.50"), output_price_per_million=Decimal("1.00")
    )
    catalog = ModelRegistryPricingCatalog(_registry_with_model(extra_tiers=[batch_tier]))

    tier = catalog.get_tier("fake-model-a", condition="batch")

    assert tier.condition == "batch"


def test_get_tier_raises_for_unknown_model() -> None:
    catalog = ModelRegistryPricingCatalog(_registry_with_model())

    with pytest.raises(UnknownModelPricingError):
        catalog.get_tier("does-not-exist")


def test_get_tier_raises_for_absent_tier_condition() -> None:
    catalog = ModelRegistryPricingCatalog(_registry_with_model())

    with pytest.raises(UnknownModelPricingError):
        catalog.get_tier("fake-model-a", condition="batch")
