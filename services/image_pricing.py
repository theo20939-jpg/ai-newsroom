"""Versioned paid image pricing used by the shared execution boundary.

Prices were verified against the providers' official pricing documentation on 2026-09-17.
This catalog is deliberately closed: an unknown provider/model/quality/size fails before a
provider call.  Provider adapters remain unaware of pricing.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest

IMAGE_PRICING_VERSION = "2026-09-28.openai-image-2.5-v1"


class UnknownImagePricingError(ValueError):
    pass


@dataclass(frozen=True)
class ImageExecutionProfile:
    provider: Literal["openai", "gemini"]
    model: str
    quality: str
    size: str
    operation: ImageGenerationOperation


@dataclass(frozen=True)
class ImagePriceQuote:
    pricing_version: str
    expected_cost_usd: Decimal
    worst_case_cost_usd: Decimal
    cost_semantics: str
    input_price_per_million: Decimal
    output_price_per_million: Decimal
    fixed_output_cost_usd: Decimal = Decimal("0")
    # True when the reservation is only a provisional cap: a response without token usage then cannot
    # be costed, so the executor books the worst case and refuses the image (fail closed).
    requires_reported_usage: bool = False
    text_input_price_per_million: Decimal | None = None
    image_input_price_per_million: Decimal | None = None
    requires_detailed_input_usage: bool = False

    def cost_from_usage(
        self, *, input_tokens: int | None, output_tokens: int | None,
        text_input_tokens: int | None = None, image_input_tokens: int | None = None,
    ) -> Decimal:
        """Return the best deterministic estimate supported by the provider response.

        OpenAI reports separately-priced input/output token counts, so those can be priced
        directly. Gemini's Interactions response does not separate image output tokens from
        text/thinking output tokens; the fixed 1K image charge plus all reported output at the
        text/thinking rate is therefore a conservative configured estimate, not an exact invoice.
        """
        million = Decimal(1_000_000)
        if (
            self.text_input_price_per_million is not None
            and self.image_input_price_per_million is not None
            and text_input_tokens is not None
            and image_input_tokens is not None
        ):
            input_cost = (
                Decimal(text_input_tokens) * self.text_input_price_per_million
                + Decimal(image_input_tokens) * self.image_input_price_per_million
            ) / million
        else:
            input_cost = Decimal(input_tokens or 0) / million * self.input_price_per_million
        return self.fixed_output_cost_usd + input_cost + (
            Decimal(output_tokens or 0) / million * self.output_price_per_million
        )


_OPENAI_OUTPUT_COSTS: dict[tuple[str, str], Decimal] = {
    ("low", "1024x1024"): Decimal("0.006"),
    ("low", "1024x1536"): Decimal("0.005"),
    ("low", "1536x1024"): Decimal("0.005"),
    ("medium", "1024x1024"): Decimal("0.053"),
    ("medium", "1024x1536"): Decimal("0.041"),
    ("medium", "1536x1024"): Decimal("0.041"),
    ("high", "1024x1024"): Decimal("0.211"),
    ("high", "1024x1536"): Decimal("0.165"),
    ("high", "1536x1024"): Decimal("0.165"),
}

# The boundary rejects prompts larger than this. Since every token contains at least one input
# byte, UTF-8 byte length is a conservative upper bound on prompt token count.
MAX_PRICED_PROMPT_BYTES = 16_000


# GPT Image 2.5 (gpt-image-2.5-flare / gpt-image-2.5-sunburst), official token rates verified on
# the OpenAI model/pricing pages 2026-09-28: text input $5/M, image input $8/M, image output $30/M.
# Actual usage uses the provider's text/image input breakdown at the respective official rates;
# output tokens use the image-output rate.
# PROVISIONAL CAPS (Founder decision 2026-09-28): OpenAI publishes no per-image output-token count
# or edit input-image token cap for GPT Image 2.5 (only an interactive calculator). The per-call
# reservation therefore uses explicit caps - ~2x gpt-image-1's published 6,240 output tokens for
# high/1536x1024, and a 6,000-token cap for one reference image downscaled to <= 1536 px - and the
# envelope fails the batch closed if a response's actual cost ever exceeds its reservation.
_GPT_IMAGE_2_5_MODELS = frozenset({"gpt-image-2.5-flare", "gpt-image-2.5-sunburst"})
_GPT_IMAGE_2_5_TEXT_INPUT = Decimal("5.00")
_GPT_IMAGE_2_5_IMAGE_INPUT = Decimal("8.00")
_GPT_IMAGE_2_5_IMAGE_OUTPUT = Decimal("30.00")
_GPT_IMAGE_2_5_PROVISIONAL_OUTPUT_TOKENS = 12_000
_GPT_IMAGE_2_5_PROVISIONAL_EDIT_IMAGE_INPUT_TOKENS = 6_000
_GPT_IMAGE_2_5_EXPECTED_OUTPUT_TOKENS = 5_500


class ImagePricingCatalog:
    def quote(self, profile: ImageExecutionProfile, request: ImageGenerationRequest) -> ImagePriceQuote:
        prompt_bytes = len(request.prompt.encode("utf-8"))
        if prompt_bytes > MAX_PRICED_PROMPT_BYTES:
            raise UnknownImagePricingError(
                f"image prompt exceeds priced maximum of {MAX_PRICED_PROMPT_BYTES} UTF-8 bytes"
            )
        if profile.operation != request.operation:
            raise UnknownImagePricingError("pricing profile operation does not match request")

        if profile.provider == "openai" and profile.model == "gpt-image-2":
            if profile.operation != ImageGenerationOperation.TEXT_TO_IMAGE or request.reference_images:
                raise UnknownImagePricingError("gpt-image-2 image-edit input pricing is not configured")
            output_cost = _OPENAI_OUTPUT_COSTS.get((profile.quality, profile.size))
            if output_cost is None:
                raise UnknownImagePricingError(
                    f"unknown gpt-image-2 quality/size pricing: {profile.quality}/{profile.size}"
                )
            input_rate = Decimal("2.50")
            output_rate = Decimal("15.00")
            expected_input = Decimal(prompt_bytes) / Decimal(1_000_000) * input_rate
            worst_input = Decimal(MAX_PRICED_PROMPT_BYTES) / Decimal(1_000_000) * input_rate
            return ImagePriceQuote(
                pricing_version=IMAGE_PRICING_VERSION,
                expected_cost_usd=output_cost + expected_input,
                worst_case_cost_usd=output_cost + worst_input,
                cost_semantics="configured_token_estimate",
                input_price_per_million=input_rate,
                output_price_per_million=output_rate,
            )

        if profile.provider == "openai" and profile.model in _GPT_IMAGE_2_5_MODELS:
            if (profile.quality, profile.size) != ("high", "1536x1024"):
                raise UnknownImagePricingError(
                    f"unpriced {profile.model} profile: {profile.quality}/{profile.size} (only high/1536x1024)"
                )
            edit = profile.operation == ImageGenerationOperation.IMAGE_EDIT
            if edit and len(request.reference_images) != 1:
                raise UnknownImagePricingError(f"{profile.model} edit pricing covers exactly one reference image")
            if not edit and request.reference_images:
                raise UnknownImagePricingError(f"{profile.model} text-to-image takes no reference images")
            million = Decimal(1_000_000)
            image_input_cap = _GPT_IMAGE_2_5_PROVISIONAL_EDIT_IMAGE_INPUT_TOKENS if edit else 0
            worst = (Decimal(MAX_PRICED_PROMPT_BYTES) * _GPT_IMAGE_2_5_TEXT_INPUT
                     + Decimal(image_input_cap) * _GPT_IMAGE_2_5_IMAGE_INPUT
                     + Decimal(_GPT_IMAGE_2_5_PROVISIONAL_OUTPUT_TOKENS) * _GPT_IMAGE_2_5_IMAGE_OUTPUT) / million
            expected = (Decimal(prompt_bytes) * _GPT_IMAGE_2_5_TEXT_INPUT
                        + Decimal(1_500 if edit else 0) * _GPT_IMAGE_2_5_IMAGE_INPUT
                        + Decimal(_GPT_IMAGE_2_5_EXPECTED_OUTPUT_TOKENS) * _GPT_IMAGE_2_5_IMAGE_OUTPUT) / million
            return ImagePriceQuote(
                pricing_version=IMAGE_PRICING_VERSION,
                expected_cost_usd=expected,
                worst_case_cost_usd=worst,
                cost_semantics="official_token_rates_provisional_per_call_caps",
                input_price_per_million=_GPT_IMAGE_2_5_IMAGE_INPUT,
                output_price_per_million=_GPT_IMAGE_2_5_IMAGE_OUTPUT,
                requires_reported_usage=True,
                text_input_price_per_million=_GPT_IMAGE_2_5_TEXT_INPUT,
                image_input_price_per_million=_GPT_IMAGE_2_5_IMAGE_INPUT,
                requires_detailed_input_usage=True,
            )

        if (
            profile.provider == "gemini"
            and profile.model == "gemini-3.1-flash-image"
            and profile.quality == "standard"
            and profile.size == "1K"
        ):
            # Official standard pricing: $0.50/M input, $0.067 per 1K output image. The model's
            # published 131,072 input and 32,768 output limits bound the pre-call reservation.
            # Text/thinking output is $3/M; image output itself is the fixed $0.067 component.
            input_rate = Decimal("0.50")
            expected_input = Decimal(prompt_bytes) / Decimal(1_000_000) * input_rate
            worst_input = Decimal(131_072) / Decimal(1_000_000) * input_rate
            worst_text_output = Decimal(32_768) / Decimal(1_000_000) * Decimal("3.00")
            return ImagePriceQuote(
                pricing_version=IMAGE_PRICING_VERSION,
                expected_cost_usd=Decimal("0.067") + expected_input,
                worst_case_cost_usd=Decimal("0.067") + worst_input + worst_text_output,
                cost_semantics="configured_conservative_usage_estimate",
                input_price_per_million=input_rate,
                output_price_per_million=Decimal("3.00"),
                fixed_output_cost_usd=Decimal("0.067"),
            )

        raise UnknownImagePricingError(
            f"unknown image pricing profile: {profile.provider}/{profile.model}/"
            f"{profile.quality}/{profile.size}/{profile.operation.value}"
        )
