"""ModelRegistry: the sealed, in-memory model_id -> ModelDescriptor registry
(docs/phase7_architecture_contract.md §3).
"""
from collections import defaultdict
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from integrations.llm_gateway.errors import (
    DuplicateModelRegistrationError,
    ModelRegistryAlreadySealedError,
    UnknownModelError,
)


class PricingTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["standard", "cached_input", "batch"] = "standard"
    input_price_per_million: Decimal
    output_price_per_million: Decimal


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str  # opaque string, never validated against a closed enum anywhere
    provider_id: str  # FK into ProviderRegistry, in-memory only - never a DB constraint
    display_name: str

    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int | None = None

    supports_tools: bool = False
    supports_streaming: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False
    embedding_dimension: int | None = None  # required (non-None) when supports_embeddings=True
    max_images_per_request: int | None = None  # None = no declared limit
    max_file_size_mb: float | None = None
    max_pdf_pages: int | None = None
    reasoning_tier: Literal["none", "standard", "extended"] = "none"
    quality_tier: int = Field(default=0)  # static, curated, code-reviewed; higher = better

    pricing_tiers: list[PricingTier] = Field(min_length=1)  # "standard" tier is REQUIRED
    pricing_currency: str = "USD"

    availability: Literal["ga", "beta", "deprecated", "unavailable"] = "ga"
    deprecation_note: str | None = None  # set when availability transitions to "deprecated"
    replacement_model_id: str | None = None  # set when availability transitions to "deprecated"

    @model_validator(mode="after")
    def _validate_binding_rules(self) -> "ModelDescriptor":
        # §3 rule 4: embedding_dimension MUST be non-None whenever supports_embeddings=True.
        if self.supports_embeddings and self.embedding_dimension is None:
            raise ValueError(
                "embedding_dimension must be set when supports_embeddings=True "
                f"(model_id='{self.model_id}')"
            )
        # §3 rule 3: pricing_tiers MUST contain a "standard" entry.
        if not any(tier.condition == "standard" for tier in self.pricing_tiers):
            raise ValueError(
                f"pricing_tiers must contain a 'standard' entry (model_id='{self.model_id}')"
            )
        # §3 rule 9: deprecation REQUIRES deprecation_note and replacement_model_id together.
        if self.availability == "deprecated" and (
            self.deprecation_note is None or self.replacement_model_id is None
        ):
            raise ValueError(
                "deprecation_note and replacement_model_id are both required when "
                f"availability='deprecated' (model_id='{self.model_id}')"
            )
        return self


def standard_combined_price(model: ModelDescriptor) -> Decimal:
    """The "standard"-tier input_price_per_million + output_price_per_million, combined into
    a single per-model rate figure. Shared by LowestCostPolicy's ranking (§4.2) and
    FallbackPolicy's eligibility-filtering cost anchor (§5.1) - both need a lightweight,
    request-independent "how expensive is this model" comparison, distinct from
    CostEstimator's full per-request worst_case/expected computation (§15.1), which MUST NOT
    be invoked merely to filter candidates (a cache hit must skip CostEstimator entirely, P15
    - eligibility filtering runs before any cache lookup, so it cannot depend on it).

    A model with no "standard" tier (never possible per §3 rule 3's validator) would return
    infinity, sorting/filtering it last; unreachable in practice.
    """
    for tier in model.pricing_tiers:
        if tier.condition == "standard":
            return tier.input_price_per_million + tier.output_price_per_million
    return Decimal("Infinity")


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelDescriptor] = {}
        self._by_provider: dict[str, list[str]] = defaultdict(list)
        self._sealed = False

    def register(self, model: ModelDescriptor) -> None:
        """Raises ModelRegistryAlreadySealedError if seal() has already been called,
        or DuplicateModelRegistrationError if model.model_id is already registered."""
        if self._sealed:
            raise ModelRegistryAlreadySealedError(
                f"Cannot register model '{model.model_id}': this ModelRegistry is sealed "
                "and accepts no further registrations."
            )
        if model.model_id in self._models:
            raise DuplicateModelRegistrationError(
                f"Model '{model.model_id}' is already registered."
            )
        self._models[model.model_id] = model
        self._by_provider[model.provider_id].append(model.model_id)

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, model_id: str) -> ModelDescriptor:
        """Raises UnknownModelError if model_id is not registered."""
        model = self._models.get(model_id)
        if model is None:
            raise UnknownModelError(f"No ModelDescriptor registered for model_id '{model_id}'")
        return model

    def all_models(self) -> list[ModelDescriptor]:
        """Every registered model, regardless of availability. Used only by boot-time
        registry-consistency validation (§3 rule 7) - RoutingEngine and everything else
        MUST use filter() instead, never this."""
        return list(self._models.values())

    def filter(
        self,
        *,
        requires_tools: bool = False,
        requires_vision: bool = False,
        requires_streaming: bool = False,
        requires_structured_output: bool = False,
        availability: set[Literal["ga", "beta"]] | None = None,
    ) -> list[ModelDescriptor]:
        """Pure in-memory filter - the RoutingEngine's primary query. No I/O."""
        allowed_availability = availability if availability is not None else {"ga", "beta"}
        results: list[ModelDescriptor] = []
        for model in self._models.values():
            if requires_tools and not model.supports_tools:
                continue
            if requires_vision and not model.supports_vision:
                continue
            if requires_streaming and not model.supports_streaming:
                continue
            if requires_structured_output and not model.supports_structured_output:
                continue
            if model.availability not in allowed_availability:
                continue
            results.append(model)
        return results
