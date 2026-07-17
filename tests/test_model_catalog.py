"""Tests for integrations.llm_gateway.models.catalog - the real OpenAI seed catalogue."""
from decimal import Decimal

import pytest

from integrations.llm_gateway.errors import ModelRegistryAlreadySealedError, UnknownModelError
from integrations.llm_gateway.models.catalog import (
    GPT_5_6_LUNA,
    GPT_5_6_SOL,
    GPT_5_6_TERRA,
    OPENAI_MODELS,
    OPENAI_PROVIDER_ID,
    build_model_registry,
)
from integrations.llm_gateway.models.registry import ModelDescriptor


def test_build_model_registry_contains_all_three_models() -> None:
    registry = build_model_registry()

    for model in OPENAI_MODELS:
        assert registry.resolve(model.model_id) is model


def test_build_model_registry_is_sealed() -> None:
    registry = build_model_registry()

    with pytest.raises(ModelRegistryAlreadySealedError):
        registry.register(GPT_5_6_SOL)


def test_build_model_registry_resolve_unknown_raises() -> None:
    registry = build_model_registry()

    with pytest.raises(UnknownModelError):
        registry.resolve("gpt-4o")


def test_all_openai_models_share_the_openai_provider_id() -> None:
    for model in OPENAI_MODELS:
        assert model.provider_id == OPENAI_PROVIDER_ID


def test_all_openai_models_declare_a_standard_pricing_tier() -> None:
    for model in OPENAI_MODELS:
        assert any(tier.condition == "standard" for tier in model.pricing_tiers)


def test_quality_tier_ordering_reflects_sol_terra_luna() -> None:
    assert GPT_5_6_SOL.quality_tier > GPT_5_6_TERRA.quality_tier > GPT_5_6_LUNA.quality_tier


def test_pricing_reflects_sol_more_expensive_than_terra_more_than_luna() -> None:
    def standard_input_price(model: ModelDescriptor) -> Decimal:
        return next(t.input_price_per_million for t in model.pricing_tiers if t.condition == "standard")

    assert standard_input_price(GPT_5_6_SOL) > standard_input_price(GPT_5_6_TERRA) > standard_input_price(GPT_5_6_LUNA)
