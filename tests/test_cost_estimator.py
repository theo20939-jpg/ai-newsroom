"""Tests for services.cost_estimator.CostEstimator (docs/phase7_architecture_contract.md §15.1).
Pure unit tests, no I/O."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog


def _model(max_output_tokens: int | None = 4096) -> ModelDescriptor:
    return ModelDescriptor(
        model_id="fake-model-a",
        provider_id="fake-provider",
        display_name="Fake Model A",
        context_window_tokens=128_000,
        max_output_tokens=max_output_tokens,
        pricing_currency="USD",
        pricing_tiers=[
            PricingTier(
                condition="standard",
                input_price_per_million=Decimal("1.00"),
                output_price_per_million=Decimal("2.00"),
            )
        ],
    )


def _estimator_for(model: ModelDescriptor) -> CostEstimator:
    registry = ModelRegistry()
    registry.register(model)
    registry.seal()
    return CostEstimator(ModelRegistryPricingCatalog(registry))


def _request(text: str = "a" * 400, max_tokens: int | None = None) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text=text)])],
        max_tokens=max_tokens,
    )


def test_estimate_pricing_tier_used_is_always_standard() -> None:
    model = _model()
    estimator = _estimator_for(model)

    estimate = estimator.estimate(model, _request())

    assert estimate.pricing_tier_used == "standard"


def test_estimate_currency_and_model_id_match_the_candidate() -> None:
    model = _model()
    estimator = _estimator_for(model)

    estimate = estimator.estimate(model, _request())

    assert estimate.currency == "USD"
    assert estimate.model_id == "fake-model-a"


def test_input_token_heuristic_is_text_length_divided_by_four() -> None:
    model = _model()
    estimator = _estimator_for(model)
    # 400 'a' characters -> 100 input tokens by the len/4 heuristic (§15.1)
    request = _request(text="a" * 400, max_tokens=0)

    estimate = estimator.estimate(model, request)

    # worst_case = (100/1e6)*1.00 + (0/1e6)*2.00 = 0.0001
    assert estimate.worst_case == Decimal("100") / Decimal(1_000_000) * Decimal("1.00")


def test_worst_case_uses_request_max_tokens_when_set() -> None:
    model = _model(max_output_tokens=100)
    estimator = _estimator_for(model)
    request = _request(text="", max_tokens=1000)

    estimate = estimator.estimate(model, request)

    expected_output_cost = Decimal(1000) / Decimal(1_000_000) * Decimal("2.00")
    assert estimate.worst_case == expected_output_cost


def test_worst_case_falls_back_to_model_max_output_tokens_when_request_max_tokens_unset() -> None:
    model = _model(max_output_tokens=500)
    estimator = _estimator_for(model)
    request = _request(text="", max_tokens=None)

    estimate = estimator.estimate(model, request)

    expected_output_cost = Decimal(500) / Decimal(1_000_000) * Decimal("2.00")
    assert estimate.worst_case == expected_output_cost


def test_worst_case_is_zero_output_cost_when_neither_max_tokens_nor_model_limit_is_set() -> None:
    model = _model(max_output_tokens=None)
    estimator = _estimator_for(model)
    request = _request(text="", max_tokens=None)

    estimate = estimator.estimate(model, request)

    assert estimate.worst_case == Decimal("0")


def test_estimate_is_frozen_and_immutable() -> None:
    model = _model()
    estimator = _estimator_for(model)
    estimate = estimator.estimate(model, _request())

    with pytest.raises(ValidationError):
        estimate.worst_case = Decimal("999")  # type: ignore[misc]
