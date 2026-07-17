"""PricingCatalog (docs/phase7_architecture_contract.md §15.3): a thin, read-only accessor
over ModelRegistry.pricing_tiers - the single source of truth for pricing. CostTracker MUST
read pricing from PricingCatalog, never maintain an independent price table.
"""
from typing import Literal, Protocol

from integrations.llm_gateway.errors import UnknownModelError, UnknownModelPricingError
from integrations.llm_gateway.models.registry import ModelRegistry, PricingTier


class PricingCatalog(Protocol):
    def get_tier(
        self, model_id: str, condition: Literal["standard", "cached_input", "batch"] = "standard"
    ) -> PricingTier:
        """Reads ModelRegistry.pricing_tiers for model_id. Raises UnknownModelPricingError if
        the model or that specific tier condition is absent - unreachable for
        condition="standard" in practice, given §3 rule 3's requirement that every model
        declare a "standard" tier."""
        ...


class ModelRegistryPricingCatalog:
    """The only implementation of PricingCatalog in this delivery - backed directly by a
    ModelRegistry, mirroring its sealed state (§15.3, §18's PricingCatalog row)."""

    def __init__(self, model_registry: ModelRegistry) -> None:
        self._model_registry = model_registry

    def get_tier(
        self, model_id: str, condition: Literal["standard", "cached_input", "batch"] = "standard"
    ) -> PricingTier:
        try:
            model = self._model_registry.resolve(model_id)
        except UnknownModelError as exc:
            raise UnknownModelPricingError(
                f"No pricing available: model '{model_id}' is not registered."
            ) from exc
        for tier in model.pricing_tiers:
            if tier.condition == condition:
                return tier
        raise UnknownModelPricingError(f"Model '{model_id}' has no '{condition}' pricing tier.")
