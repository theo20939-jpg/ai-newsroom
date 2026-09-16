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

IMAGE_PRICING_VERSION = "2026-09-17.v1"


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
    output_price_per_million: Decimal | None

    def cost_from_usage(self, *, input_tokens: int | None, output_tokens: int | None) -> Decimal:
        """Return the best deterministic estimate supported by the provider response.

        OpenAI reports separately-priced input/output token counts, so those can be priced
        directly. Gemini's Interactions response does not separate image output tokens from
        text/thinking output tokens; its configured expected charge therefore remains the honest
        accounting value rather than fabricating a precise provider invoice.
        """
        if self.output_price_per_million is None:
            return self.expected_cost_usd
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens or 0) / million * self.input_price_per_million
            + Decimal(output_tokens or 0) / million * self.output_price_per_million
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
                cost_semantics="configured_provider_estimate",
                input_price_per_million=input_rate,
                output_price_per_million=None,
            )

        raise UnknownImagePricingError(
            f"unknown image pricing profile: {profile.provider}/{profile.model}/"
            f"{profile.quality}/{profile.size}/{profile.operation.value}"
        )
