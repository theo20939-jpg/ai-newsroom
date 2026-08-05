"""Phase 18 M5 - Meme Image Generation tests (docs/phase18_m5_meme_image_generation_report.md).

No network, no live provider call anywhere in this file - MockImageAdapter is deterministic and
local. `LocalImageStorage` writes to a temporary directory (pytest's own `tmp_path` fixture), not
`settings.image_storage_root` - fully isolated, no shared state between test runs.
"""
from __future__ import annotations

import pytest
from PIL import Image

from integrations.llm_gateway.image_protocol import ImageGenerationRequest, ImageGenerationResponse
from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import CapabilityUsage
from schemas.meme_concept import MemeConcept, MemeFormat
from schemas.meme_image import MemeImageStatus
from services.meme_image_generation import build_image_prompt, generate_meme_image

_CONCEPT = MemeConcept(
    premise="p", setup="s", punchline="pl", humor_mechanism="irony",
    visual_scene="A CEO on stage pointing at a slide reading 'Jobs are safe'.",
    characters_objects=["CEO", "presentation slide"], text_overlay_intent="intent",
    source_fact_links=["fact"], forbidden_interpretations=[], meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
)


class _FailingGateway:
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        raise RuntimeError("provider unavailable")


class _FailThenSucceedGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        return await MockImageAdapter().generate_image(request)


class _BadBytesGateway:
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            image_bytes=b"not a real image",
            model_used="fake", provider="fake", usage=CapabilityUsage(units=1, unit_type="image"),
        )


# ---------------------------------------------------------------------------
# build_image_prompt
# ---------------------------------------------------------------------------


def test_build_image_prompt_includes_visual_scene_and_objects() -> None:
    prompt = build_image_prompt(_CONCEPT)
    assert _CONCEPT.visual_scene in prompt
    assert "CEO" in prompt
    assert "presentation slide" in prompt


def test_build_image_prompt_excludes_punchline_and_instructs_no_text() -> None:
    """M0's own recommendation: image has no baked-in text - M6 overlays it deterministically."""
    prompt = build_image_prompt(_CONCEPT)
    assert _CONCEPT.punchline not in prompt
    assert "no text" in prompt.lower()


# ---------------------------------------------------------------------------
# MockImageAdapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_adapter_is_deterministic_for_the_same_prompt() -> None:
    adapter = MockImageAdapter()
    first = await adapter.generate_image(ImageGenerationRequest(prompt="A CEO on stage."))
    second = await adapter.generate_image(ImageGenerationRequest(prompt="A CEO on stage."))
    assert first.image_bytes == second.image_bytes


@pytest.mark.asyncio
async def test_mock_adapter_differs_for_different_prompts() -> None:
    adapter = MockImageAdapter()
    a = await adapter.generate_image(ImageGenerationRequest(prompt="A CEO on stage."))
    b = await adapter.generate_image(ImageGenerationRequest(prompt="A dog wearing sunglasses."))
    assert a.image_bytes != b.image_bytes


@pytest.mark.asyncio
async def test_mock_adapter_produces_a_valid_1024_square_png() -> None:
    import io

    adapter = MockImageAdapter()
    response = await adapter.generate_image(ImageGenerationRequest(prompt="test"))
    with Image.open(io.BytesIO(response.image_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (1024, 1024)


@pytest.mark.asyncio
async def test_mock_adapter_reports_zero_cost_usage() -> None:
    adapter = MockImageAdapter()
    response = await adapter.generate_image(ImageGenerationRequest(prompt="test"))
    assert response.usage.units == 1
    assert response.usage.unit_type == "image"


# ---------------------------------------------------------------------------
# generate_meme_image - mode gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_makes_zero_calls(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    class _NeverCalledGateway:
        async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
            raise AssertionError("must never be called when mode=='off'")

    result = await generate_meme_image(
        _CONCEPT, gateway=_NeverCalledGateway(), storage=storage, mode="off",
    )
    assert result.status == MemeImageStatus.OFF
    assert result.storage_key is None


@pytest.mark.asyncio
async def test_mode_dry_run_generates_and_stores(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    result = await generate_meme_image(
        _CONCEPT, gateway=MockImageAdapter(), storage=storage, mode="dry_run",
    )

    assert result.status == MemeImageStatus.GENERATED
    assert result.storage_key is not None
    assert storage.exists(result.storage_key)
    assert result.cost_usd == "0"
    assert result.width == 1024
    assert result.height == 1024
    assert result.attempt_count == 1


@pytest.mark.asyncio
async def test_generation_failure_after_bounded_attempts_returns_failed(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    result = await generate_meme_image(
        _CONCEPT, gateway=_FailingGateway(), storage=storage, mode="dry_run",
    )

    assert result.status == MemeImageStatus.FAILED
    assert result.error_code is not None
    assert result.attempt_count == 2  # _MAX_GENERATION_ATTEMPTS, bounded not unlimited


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    gateway = _FailThenSucceedGateway()

    result = await generate_meme_image(_CONCEPT, gateway=gateway, storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.GENERATED
    assert result.attempt_count == 2
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_malformed_image_bytes_from_gateway_are_handled_not_raised(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)

    result = await generate_meme_image(_CONCEPT, gateway=_BadBytesGateway(), storage=storage, mode="dry_run")

    assert result.status == MemeImageStatus.FAILED
    assert result.error_code is not None


@pytest.mark.asyncio
async def test_regenerating_the_same_concept_is_idempotent_in_storage(tmp_path) -> None:
    """Same prompt -> same bytes -> same content-addressed key -> storing twice is a safe no-op
    (LocalImageStorage's own idempotent-upsert precedent), never a duplicate file or an error."""
    storage = LocalImageStorage(tmp_path)

    first = await generate_meme_image(_CONCEPT, gateway=MockImageAdapter(), storage=storage, mode="dry_run")
    second = await generate_meme_image(_CONCEPT, gateway=MockImageAdapter(), storage=storage, mode="dry_run")

    assert first.storage_key == second.storage_key
    assert first.sha256 == second.sha256
