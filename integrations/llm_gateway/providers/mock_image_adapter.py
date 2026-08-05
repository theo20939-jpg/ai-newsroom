"""MockImageAdapter (Phase 18 M5): a deterministic, zero-network, zero-cost implementation of
`ImageGenerationGateway` (docs/phase18_m5_meme_image_generation_report.md).

This is the ONLY image-generation adapter this phase ships wired up by default - no real
provider-calling adapter exists in this codebase (per the operating rule: no paid/live
image-generation call without a separate, explicit human-authorization step, and none was made
or attempted while building this phase). `MockImageAdapter` lets the entire M5-M8 pipeline
(generation -> storage -> rendering -> quality gate -> preview) be built and tested end-to-end
with real, correctly-shaped `ImageGenerationResponse` objects, at zero cost and zero external
dependency - never a stub that merely raises `NotImplementedError`.

Deterministic: the same `prompt` always produces the same PNG bytes (seeded from
`hashlib.sha256(prompt)`), which makes both this adapter's own tests and every downstream
consumer's tests fully reproducible without any random-seed plumbing.
"""
from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image, ImageDraw

from integrations.llm_gateway.image_protocol import ImageGenerationRequest, ImageGenerationResponse
from schemas.capability import CapabilityUsage

_CANVAS_SIZE = (1024, 1024)
_MOCK_MODEL_NAME = "mock-image-v1"


def _color_from_digest(digest: bytes, offset: int) -> tuple[int, int, int]:
    return (digest[offset], digest[offset + 1], digest[offset + 2])


def _render_placeholder_png(prompt: str) -> bytes:
    """Two-tone diagonal-gradient background plus a centered contrasting circle - simple, but
    visually distinct per prompt (never a single flat color that could be mistaken for a
    rendering error), and cheap to compute (no external assets, no network)."""
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    color_a = _color_from_digest(digest, 0)
    color_b = _color_from_digest(digest, 3)
    accent = _color_from_digest(digest, 6)

    width, height = _CANVAS_SIZE
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        t = y / (height - 1)
        row_color = tuple(int(color_a[i] * (1 - t) + color_b[i] * t) for i in range(3))
        for x in range(width):
            pixels[x, y] = row_color  # type: ignore[index]

    draw = ImageDraw.Draw(image)
    radius = min(width, height) // 4
    center = (width // 2, height // 2)
    draw.ellipse(
        (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        fill=accent,
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class MockImageAdapter:
    """Implements `ImageGenerationGateway`. No constructor dependencies - nothing here ever
    touches a network socket, a filesystem path outside the returned bytes, or an API key."""

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        image_bytes = _render_placeholder_png(request.prompt)
        return ImageGenerationResponse(
            image_bytes=image_bytes,
            mime_type="image/png",
            model_used=_MOCK_MODEL_NAME,
            provider="mock",
            usage=CapabilityUsage(units=1, unit_type="image"),
        )
