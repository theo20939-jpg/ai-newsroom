"""Phase V2.3 - services/editorial_recomposition.py tests. No real network call anywhere in this
file - LIVE-path tests inject a fake `ImageGenerationGateway`-shaped double, never a real
`GeminiImageAdapter` with a real client."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from integrations.llm_gateway.image_protocol import (
    ImageGenerationOperation,
    ImageGenerationResponse,
)
from schemas.capability import CapabilityUsage
from services.editorial_recomposition import (
    build_recomposition_prompt,
    evaluate_eligibility,
    maybe_recompose,
)
from scripts.nnj_visual_recomposition_bakeoff import build_recomposition_prompt as bakeoff_build_recomposition_prompt


def _jpeg_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(buf, "JPEG")
    return buf.getvalue()


def _png_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


# A clean, single-product-shaped candidate: strong resolution (GOOD, shortest side >= 600) and an
# editorial-landscape aspect ratio (ratio in (1.33, 2.2]).
_ELIGIBLE_PRODUCT_BYTES = _jpeg_bytes(1600, 900)  # ratio 1.78 - editorial_landscape, shortest=900 - GOOD


class _FakeGateway:
    """Minimal ImageGenerationGateway-shaped test double."""

    def __init__(self, response: ImageGenerationResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list = []

    async def generate_image(self, request):
        self.calls.append(request)
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _valid_response(image_bytes: bytes | None = None) -> ImageGenerationResponse:
    return ImageGenerationResponse(
        image_bytes=image_bytes or _jpeg_bytes(1600, 900),
        mime_type="image/jpeg",
        model_used="gemini-3.1-flash-image",
        provider="gemini",
        usage=CapabilityUsage(units=1, unit_type="image"),
        request_id="int-test-1",
        cost_usd=None,
    )


# ---------------------------------------------------------------------------
# Canonical prompt
# ---------------------------------------------------------------------------


def test_prompt_matches_canonical_bakeoff_prompt() -> None:
    assert build_recomposition_prompt() == bakeoff_build_recomposition_prompt()


# ---------------------------------------------------------------------------
# OFF mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_mode_makes_zero_gateway_calls_and_returns_original_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "off")
    gateway = _FakeGateway(response=_valid_response())

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert gateway.calls == []
    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert result.mode == "off"
    assert result.eligibility.eligible is False
    assert result.eligibility.reason == "mode_off"


# ---------------------------------------------------------------------------
# DRY_RUN mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_evaluates_eligibility_makes_zero_calls_returns_original_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "dry_run")
    gateway = _FakeGateway(response=_valid_response())

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert gateway.calls == []
    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert result.mode == "dry_run"
    assert result.eligibility.eligible is True
    assert result.provider == "gemini"
    assert result.model == "gemini-3.1-flash-image"


@pytest.mark.asyncio
async def test_dry_run_on_ineligible_image_is_still_zero_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "dry_run")
    gateway = _FakeGateway(response=_valid_response())
    portrait_bytes = _jpeg_bytes(600, 900)  # ratio 0.67 - portrait band

    result = await maybe_recompose(source_image_bytes=portrait_bytes, gateway=gateway)

    assert gateway.calls == []
    assert result.eligibility.eligible is False
    assert result.image_bytes == portrait_bytes


# ---------------------------------------------------------------------------
# LIVE - success (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_success_calls_gateway_exactly_once_with_gemini_flash(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    recomposed = _jpeg_bytes(1600, 900)
    gateway = _FakeGateway(response=_valid_response(recomposed))

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert len(gateway.calls) == 1
    request = gateway.calls[0]
    assert request.operation == ImageGenerationOperation.IMAGE_EDIT
    assert result.used_recomposed_image is True
    assert result.image_bytes == recomposed
    assert result.model == "gemini-3.1-flash-image"
    assert result.provider == "gemini"
    assert result.result_sha256 is not None


@pytest.mark.asyncio
async def test_live_success_never_touches_media_selection_only_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """RecompositionResult carries only bytes/metadata - nothing that could influence which
    media was selected upstream."""
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(response=_valid_response())

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert set(vars(result).keys()) == {
        "used_recomposed_image", "image_bytes", "mode", "eligibility", "provider", "model",
        "source_sha256", "result_sha256", "fallback_reason", "latency_ms",
        # Phase V2.5 Stage 6: real provider telemetry, propagated when the response reports it.
        "request_id", "input_tokens", "output_tokens", "units", "unit_type",
    }


# ---------------------------------------------------------------------------
# LIVE - failure (mocked) - fail-open contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_provider_error_fails_open_to_original_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=GeminiImageAdapterError("Gemini interactions request returned HTTP 500"))

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert result.fallback_reason == "GeminiImageAdapterError"
    assert result.provider == "gemini"
    assert result.model == "gemini-3.1-flash-image"


@pytest.mark.asyncio
async def test_live_timeout_fails_open_to_original_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=GeminiImageAdapterError("Gemini interaction int-x polling timed out after 90.0s"))

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert "GeminiImageAdapterError" == result.fallback_reason


@pytest.mark.asyncio
async def test_live_unexpected_exception_still_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """A boundary error the typed GeminiImageAdapterError doesn't cover - the generic Exception
    catch must still fail open, never propagate and block the send path."""
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=RuntimeError("some unexpected boundary failure"))

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert result.fallback_reason == "unexpected_error:RuntimeError"


@pytest.mark.asyncio
async def test_live_empty_image_bytes_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    empty_response = ImageGenerationResponse(
        image_bytes=b"x", mime_type="image/jpeg", model_used="gemini-3.1-flash-image", provider="gemini",
        usage=CapabilityUsage(units=1, unit_type="image"), request_id="int-empty", cost_usd=None,
    )
    gateway = _FakeGateway(response=empty_response)

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert result.fallback_reason == "undecodable_result_image"


@pytest.mark.asyncio
async def test_live_undecodable_image_bytes_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    malformed_response = ImageGenerationResponse(
        image_bytes=b"not-a-real-image-just-garbage-bytes", mime_type="image/jpeg",
        model_used="gemini-3.1-flash-image", provider="gemini",
        usage=CapabilityUsage(units=1, unit_type="image"), request_id="int-bad", cost_usd=None,
    )
    gateway = _FakeGateway(response=malformed_response)

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert result.used_recomposed_image is False
    assert result.image_bytes == _ELIGIBLE_PRODUCT_BYTES
    assert result.fallback_reason == "undecodable_result_image"


@pytest.mark.asyncio
async def test_live_failure_never_falls_back_to_pro_or_gpt(monkeypatch: pytest.MonkeyPatch) -> None:
    """No code path in this module ever references gemini-3-pro-image or gpt-image-2 - a live
    failure's only possible outcome is the original bytes, never a second, more-creative model."""
    from core.config import settings
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=GeminiImageAdapterError("boom"))

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    assert result.model != "gemini-3-pro-image"
    assert result.model != "gpt-image-2"
    assert result.model == "gemini-3.1-flash-image"


def test_module_never_imports_pro_or_gpt_adapters() -> None:
    """The docstring itself explains the no-escalation rule in prose (mentions both model names
    deliberately, as a disclosure) - what must never appear is an actual import or usable
    reference to either as a real code symbol."""
    import services.editorial_recomposition as mod

    assert not hasattr(mod, "GEMINI_3_PRO_IMAGE")
    assert not hasattr(mod, "OpenAIImageAdapter")
    assert not hasattr(mod, "GPT_IMAGE_2")
    import ast

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "GEMINI_3_PRO_IMAGE" not in imported_names
    assert "OpenAIImageAdapter" not in imported_names
    assert "GPT_IMAGE_2" not in imported_names


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def test_eligible_clean_single_product_landscape_case() -> None:
    decision = evaluate_eligibility(_ELIGIBLE_PRODUCT_BYTES)
    assert decision.eligible is True


def test_ineligible_portrait_orientation() -> None:
    decision = evaluate_eligibility(_jpeg_bytes(700, 1200))  # ratio 0.58 - portrait band
    assert decision.eligible is False
    assert decision.reason == "aspect_ratio_not_editorial_landscape"


def test_ineligible_square_ui_heavy_proxy() -> None:
    """Square aspect ratio is the deterministic proxy this module uses for screenshot/UI-heavy
    imagery (module docstring's own disclosed limitation - not a real UI detector)."""
    decision = evaluate_eligibility(_jpeg_bytes(1000, 1000))  # ratio 1.0 - square band
    assert decision.eligible is False
    assert decision.reason == "aspect_ratio_not_editorial_landscape"


def test_ineligible_low_quality_small_image() -> None:
    decision = evaluate_eligibility(_jpeg_bytes(400, 250))  # shortest=250, below GOOD and ADEQUATE
    assert decision.eligible is False
    assert decision.reason == "resolution_band_not_good"


def test_ineligible_ambiguous_extreme_wide_case() -> None:
    """An extreme-wide banner-shaped image (a proxy for an ambiguous/ad-like scene, not a clean
    single-subject product shot) is rejected."""
    decision = evaluate_eligibility(_jpeg_bytes(3000, 400))  # ratio 7.5 - extreme_wide band
    assert decision.eligible is False


def test_ineligible_undecodable_bytes() -> None:
    decision = evaluate_eligibility(b"totally not an image")
    assert decision.eligible is False
    assert decision.reason == "undecodable_or_unsupported_format"


def test_eligible_png_also_supported() -> None:
    decision = evaluate_eligibility(_png_bytes(1600, 900))
    assert decision.eligible is True


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_repr_never_contains_raw_image_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A RecompositionResult's own repr (as would appear in any accidental log/debug print) must
    never contain the actual image bytes - only a length, per its custom __repr__."""
    from core.config import settings

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    recomposed = _jpeg_bytes(1600, 900)
    gateway = _FakeGateway(response=_valid_response(recomposed))

    result = await maybe_recompose(source_image_bytes=_ELIGIBLE_PRODUCT_BYTES, gateway=gateway)

    rendered = repr(result)
    assert recomposed not in rendered.encode("latin-1", errors="ignore")
    assert "bytes>" in rendered
    assert result.source_sha256 in rendered
