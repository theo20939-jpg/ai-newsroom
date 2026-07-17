"""CostEstimator (docs/phase7_architecture_contract.md §15.1): a pure function - no I/O, no
persistence, reading only PricingCatalog (§15.3) and the candidate ModelDescriptor.
"""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from integrations.llm_gateway.models.registry import ModelDescriptor
from integrations.llm_gateway.protocol import GenerateRequest
from services.pricing_catalog import PricingCatalog


class CostEstimate(BaseModel):
    """Formalizes the value CostEstimator produces (§15.1, audited). `currency` and `model_id`
    are carried through unchanged from the candidate ModelDescriptor/PricingTier that produced
    the estimate; `pricing_tier_used` is always "standard" per the rule below."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: Decimal
    worst_case: Decimal
    currency: str
    model_id: str
    pricing_tier_used: Literal["standard", "cached_input", "batch"]


def _count_input_tokens(request: GenerateRequest) -> int:
    """len(concatenated message text) / 4 - an explicitly approximate heuristic (§15.1),
    never a billing-accuracy claim."""
    concatenated = "".join(
        part.text or ""
        for message in request.messages
        for part in message.content
        if part.type == "text"
    )
    return len(concatenated) // 4


class CostEstimator:
    """Pure function object - no I/O, no persistence (§15.1). Estimation MUST always be
    computed against the model's "standard" PricingTier, never "cached_input"/"batch", even
    when the request might qualify, since this delivery performs no automatic
    cache-eligibility detection. Overestimating is the required, safe default."""

    def __init__(self, pricing_catalog: PricingCatalog) -> None:
        self._pricing_catalog = pricing_catalog

    def estimate(self, model: ModelDescriptor, request: GenerateRequest) -> CostEstimate:
        tier = self._pricing_catalog.get_tier(model.model_id, condition="standard")

        input_tokens = _count_input_tokens(request)
        worst_case_output_tokens = (
            request.max_tokens if request.max_tokens is not None else (model.max_output_tokens or 0)
        )

        million = Decimal(1_000_000)
        worst_case_cost = (
            Decimal(input_tokens) / million * tier.input_price_per_million
            + Decimal(worst_case_output_tokens) / million * tier.output_price_per_million
        )
        # §15.1 explicitly specifies the worst_case output-token source (request.max_tokens,
        # else ModelDescriptor.max_output_tokens) but gives no distinct formula for
        # `expected`'s output-token count. `expected` never gates anything - BudgetGuard
        # always checks worst_case (§15.2) - it exists only for the cost_estimate_variance
        # observability event (§16.2). Rather than invent an unstated "typical case"
        # heuristic, this implementation conservatively mirrors worst_case for expected too.
        expected_cost = worst_case_cost

        return CostEstimate(
            expected=expected_cost,
            worst_case=worst_case_cost,
            currency=model.pricing_currency,
            model_id=model.model_id,
            pricing_tier_used="standard",
        )
