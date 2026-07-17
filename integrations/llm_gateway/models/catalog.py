"""Static OpenAI model catalogue (docs/phase7_architecture_contract.md §3 rule 2: "a single,
explicit, code-reviewed, statically-typed Python module - never inferred from a provider's
live model-listing endpoint, never a database table").

Model IDs, context windows, max output tokens, and standard-tier pricing below were verified
against OpenAI's official API documentation (developers.openai.com/api/docs/pricing and
/models) on 2026-07-17, cross-corroborated against multiple independent third-party pricing
trackers. This is notably NOT the gpt-4o/gpt-4o-mini family a pre-2026 knowledge cutoff would
assume - OpenAI shipped a new GPT-5.6 family (Sol/Terra/Luna) on 2026-07-09, days before this
catalogue was written. See docs/phase7_implementation_log.md's M3 entry for the full
verification trail. Update this module by hand - and re-verify against official docs again -
whenever OpenAI's lineup or pricing changes; nothing here is fetched at runtime.

Only the "standard" PricingTier is populated: batch/cached-input pricing for this family was
not confirmed against an official source at the time of writing, and Phase 7 contract §15.1
requires estimation to use the "standard" tier only regardless, so omitting the other two
tiers costs nothing.
"""
from decimal import Decimal

from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier

OPENAI_PROVIDER_ID = "openai"

_CONTEXT_WINDOW_TOKENS = 1_050_000  # 1.05M tokens, shared across the whole GPT-5.6 family
_MAX_OUTPUT_TOKENS = 128_000  # 128K, shared across the whole GPT-5.6 family

GPT_5_6_SOL = ModelDescriptor(
    model_id="gpt-5.6-sol",
    provider_id=OPENAI_PROVIDER_ID,
    display_name="GPT-5.6 Sol (flagship)",
    context_window_tokens=_CONTEXT_WINDOW_TOKENS,
    max_output_tokens=_MAX_OUTPUT_TOKENS,
    supports_tools=True,
    supports_streaming=True,
    supports_vision=True,
    supports_structured_output=True,
    supports_embeddings=False,
    reasoning_tier="standard",
    quality_tier=100,
    pricing_tiers=[
        PricingTier(
            condition="standard",
            input_price_per_million=Decimal("5.00"),
            output_price_per_million=Decimal("30.00"),
        )
    ],
    pricing_currency="USD",
    availability="ga",
)

GPT_5_6_TERRA = ModelDescriptor(
    model_id="gpt-5.6-terra",
    provider_id=OPENAI_PROVIDER_ID,
    display_name="GPT-5.6 Terra (balanced)",
    context_window_tokens=_CONTEXT_WINDOW_TOKENS,
    max_output_tokens=_MAX_OUTPUT_TOKENS,
    supports_tools=True,
    supports_streaming=True,
    supports_vision=True,
    supports_structured_output=True,
    supports_embeddings=False,
    reasoning_tier="standard",
    quality_tier=70,
    pricing_tiers=[
        PricingTier(
            condition="standard",
            input_price_per_million=Decimal("2.50"),
            output_price_per_million=Decimal("15.00"),
        )
    ],
    pricing_currency="USD",
    availability="ga",
)

GPT_5_6_LUNA = ModelDescriptor(
    model_id="gpt-5.6-luna",
    provider_id=OPENAI_PROVIDER_ID,
    display_name="GPT-5.6 Luna (cost-sensitive)",
    context_window_tokens=_CONTEXT_WINDOW_TOKENS,
    max_output_tokens=_MAX_OUTPUT_TOKENS,
    supports_tools=True,
    supports_streaming=True,
    supports_vision=True,
    supports_structured_output=True,
    supports_embeddings=False,
    reasoning_tier="standard",
    quality_tier=40,
    pricing_tiers=[
        PricingTier(
            condition="standard",
            input_price_per_million=Decimal("1.00"),
            output_price_per_million=Decimal("6.00"),
        )
    ],
    pricing_currency="USD",
    availability="ga",
)

OPENAI_MODELS: tuple[ModelDescriptor, ...] = (GPT_5_6_SOL, GPT_5_6_TERRA, GPT_5_6_LUNA)


def build_model_registry() -> ModelRegistry:
    """Build and seal a ModelRegistry containing the OpenAI catalogue above.

    Mirrors the naming convention of capabilities.registry.build_registry() and
    workflows.registry's build_registry() precedent.
    """
    registry = ModelRegistry()
    for model in OPENAI_MODELS:
        registry.register(model)
    registry.seal()
    return registry
