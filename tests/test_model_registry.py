"""Tests for integrations.llm_gateway.models.registry.ModelRegistry
(docs/phase7_architecture_contract.md §3). Pure unit tests, no I/O - uses ad-hoc
ModelDescriptors, not the real OpenAI catalogue, so registry-logic tests never depend on
catalogue content staying accurate."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from integrations.llm_gateway.errors import (
    DuplicateModelRegistrationError,
    ModelRegistryAlreadySealedError,
    UnknownModelError,
)
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier


def _standard_tier(input_price: str = "1.00", output_price: str = "2.00") -> PricingTier:
    return PricingTier(
        condition="standard",
        input_price_per_million=Decimal(input_price),
        output_price_per_million=Decimal(output_price),
    )


def _descriptor(model_id: str = "fake-model-a", provider_id: str = "fake-provider", **overrides: object) -> ModelDescriptor:
    fields: dict[str, object] = {
        "model_id": model_id,
        "provider_id": provider_id,
        "display_name": "Fake Model A",
        "context_window_tokens": 128_000,
        "pricing_tiers": [_standard_tier()],
    }
    fields.update(overrides)
    return ModelDescriptor(**fields)  # type: ignore[arg-type]


def test_register_then_resolve_round_trips() -> None:
    registry = ModelRegistry()
    model = _descriptor()

    registry.register(model)

    assert registry.resolve("fake-model-a") is model


def test_resolve_unknown_model_raises() -> None:
    registry = ModelRegistry()

    with pytest.raises(UnknownModelError):
        registry.resolve("does-not-exist")


def test_register_duplicate_model_id_raises() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor())

    with pytest.raises(DuplicateModelRegistrationError):
        registry.register(_descriptor())


def test_register_after_seal_raises() -> None:
    registry = ModelRegistry()
    registry.seal()

    with pytest.raises(ModelRegistryAlreadySealedError):
        registry.register(_descriptor())


def test_resolve_works_identically_before_and_after_seal() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor())
    before = registry.resolve("fake-model-a")
    registry.seal()
    after = registry.resolve("fake-model-a")

    assert before is after


def test_filter_hard_requirements() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor(model_id="no-tools", supports_tools=False))
    registry.register(_descriptor(model_id="has-tools", supports_tools=True))
    registry.seal()

    results = registry.filter(requires_tools=True)

    assert [m.model_id for m in results] == ["has-tools"]


def test_filter_excludes_deprecated_and_unavailable_by_default() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor(model_id="ga-model", availability="ga"))
    registry.register(
        _descriptor(
            model_id="deprecated-model",
            availability="deprecated",
            deprecation_note="superseded",
            replacement_model_id="ga-model",
        )
    )
    registry.register(_descriptor(model_id="beta-model", availability="beta"))
    registry.seal()

    results = {m.model_id for m in registry.filter()}

    assert results == {"ga-model", "beta-model"}


def test_filter_is_pure_and_returns_a_list() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor())
    registry.seal()

    results = registry.filter()

    assert isinstance(results, list)
    assert len(results) == 1


def test_embedding_dimension_required_when_supports_embeddings_true() -> None:
    with pytest.raises(ValidationError):
        _descriptor(supports_embeddings=True, embedding_dimension=None)


def test_embedding_dimension_accepted_when_supports_embeddings_true() -> None:
    model = _descriptor(supports_embeddings=True, embedding_dimension=1536)

    assert model.embedding_dimension == 1536


def test_pricing_tiers_must_contain_standard_entry() -> None:
    batch_only_tier = PricingTier(
        condition="batch",
        input_price_per_million=Decimal("0.50"),
        output_price_per_million=Decimal("1.00"),
    )

    with pytest.raises(ValidationError):
        _descriptor(pricing_tiers=[batch_only_tier])


def test_deprecation_requires_note_and_replacement_together() -> None:
    with pytest.raises(ValidationError):
        _descriptor(availability="deprecated")

    with pytest.raises(ValidationError):
        _descriptor(availability="deprecated", deprecation_note="note only")


def test_deprecation_with_both_fields_is_valid() -> None:
    model = _descriptor(
        availability="deprecated",
        deprecation_note="superseded by fake-model-b",
        replacement_model_id="fake-model-b",
    )

    assert model.availability == "deprecated"


def test_model_descriptor_is_frozen() -> None:
    model = _descriptor()

    with pytest.raises(ValidationError):
        model.quality_tier = 999  # type: ignore[misc]


def test_model_descriptor_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _descriptor(unexpected_field="nope")


def test_all_models_returns_every_registered_model_regardless_of_availability() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor(model_id="ga-model", availability="ga"))
    registry.register(
        _descriptor(
            model_id="deprecated-model",
            availability="deprecated",
            deprecation_note="superseded",
            replacement_model_id="ga-model",
        )
    )
    registry.seal()

    ids = {m.model_id for m in registry.all_models()}

    assert ids == {"ga-model", "deprecated-model"}
