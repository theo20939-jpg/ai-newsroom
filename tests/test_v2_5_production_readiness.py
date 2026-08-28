"""Phase V2.5 - Production Contract Freeze + Runtime Readiness Repair.

Covers, per that phase's own Stage 11 groups: A) the locked Candidate C contract, B) the
production overlay-aware prompt, C) the two-level collision classifier, D) runtime mode/fallback
policy, E) telemetry propagation, F) the source-bytes/storage fix, G) branding suppression. No
real network call anywhere in this file - LIVE-path tests inject a fake `ImageGenerationGateway`-
shaped double, never a real `GeminiImageAdapter`."""
from __future__ import annotations

import ast
import io
import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from aiogram.types import BufferedInputFile

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import CapabilityUsage
from services import image_persistence
from services.editorial_recomposition import (
    RecompositionResult,
    build_overlay_aware_recomposition_prompt,
    build_recomposition_prompt,
    maybe_recompose,
)
from services.image_persistence import EditorialImageCandidate
from services.nnj_candidate_c_contract import (
    CANDIDATE_C_MANIFEST_PATH,
    CANDIDATE_C_OVERLAY_PNG_PATH,
    CandidateCGeometry,
    CollisionSeverity,
    apply_candidate_c_branding,
    assess_collision,
    build_overlay_aware_prompt_clause,
    load_candidate_c_geometry,
)
from worker.content_cycle import resolve_recomposition_source_bytes


_DEFAULT_CANDIDATE = EditorialImageCandidate(
    id=uuid.uuid4(), candidate_id="c1", rank=1, relevance_score=80, quality_score=80,
    discovery_method="open_graph_image", source_relationship="same_article",
    relevance_reason="strong metadata overlap", width=1600, height=800,
    observed_mime="image/jpeg", image_format="JPEG", storage_status="not_requested",
    storage_key=None, telegram_file_id=None, editor_decision=None,
    source_url="https://example.com/a", article_url="https://example.com/article",
    warnings=None, is_expired=False,
)


def _fake_candidate(**overrides: object) -> EditorialImageCandidate:
    return replace(_DEFAULT_CANDIDATE, id=uuid.uuid4(), **overrides)  # type: ignore[arg-type]


def _jpeg_bytes(width: int = 1600, height: int = 900, color=(200, 120, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG")
    return buf.getvalue()


class _FakeGateway:
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


_DEFAULT_RESPONSE = ImageGenerationResponse(
    image_bytes=b"placeholder",
    mime_type="image/jpeg", model_used="gemini-3.1-flash-image", provider="gemini",
    usage=CapabilityUsage(input_tokens=744, output_tokens=1441, units=1, unit_type="image"),
    request_id="v1_test-request-id",
    cost_usd=None,
)


def _valid_response(image_bytes: bytes | None = None, **overrides: object) -> ImageGenerationResponse:
    update = {"image_bytes": image_bytes or _jpeg_bytes(1376, 768), **overrides}
    return _DEFAULT_RESPONSE.model_copy(update=update)


# ---------------------------------------------------------------------------
# A. Candidate C contract
# ---------------------------------------------------------------------------


def test_locked_asset_loads() -> None:
    assert CANDIDATE_C_OVERLAY_PNG_PATH.exists()
    assert CANDIDATE_C_MANIFEST_PATH.exists()
    geometry = load_candidate_c_geometry()
    assert isinstance(geometry, CandidateCGeometry)


def test_exact_authoritative_geometry() -> None:
    geometry = load_candidate_c_geometry()
    assert geometry.canvas_width == 1280
    assert geometry.canvas_height == 720
    assert geometry.overlay_start_x == 826
    assert geometry.overlay_end_x == 1248
    assert geometry.line_y == 662
    assert geometry.pulse_bbox == (989, 623, 1033, 682)
    assert geometry.logo_bbox == (1212, 644, 1248, 680)
    assert (geometry.zone_x_start, geometry.zone_y_start, geometry.zone_x_end, geometry.zone_y_end) == (826, 623, 1248, 682)
    assert geometry.clearance == 20


def test_canonical_logo_used_not_recreated() -> None:
    manifest = json.loads(CANDIDATE_C_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "load_brand_mark" in manifest["canonical_logo_source"]
    assert manifest["contains_trusted_branding"] is True


def test_no_untrusted_old_wordmark() -> None:
    manifest = json.loads(CANDIDATE_C_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["embedded_v1_wordmark_included"] is False
    assert manifest["signal_bars_icon_included"] is False


def test_no_a_b_fallback_parameter_exists() -> None:
    """load_candidate_c_geometry() takes only a manifest path, with a fixed default pointing at
    the one locked asset - there is no width_fraction/candidate-letter parameter anywhere in this
    module's public surface that could silently substitute A or B for the frozen C geometry."""
    import inspect

    sig = inspect.signature(load_candidate_c_geometry)
    assert set(sig.parameters.keys()) == {"manifest_path"}
    assert sig.parameters["manifest_path"].default == CANDIDATE_C_MANIFEST_PATH


# ---------------------------------------------------------------------------
# B. Production prompt integration
# ---------------------------------------------------------------------------


def test_factual_fidelity_base_contract_unchanged() -> None:
    combined = build_overlay_aware_recomposition_prompt()
    assert combined.startswith(build_recomposition_prompt())


def test_overlay_aware_clause_included_from_candidate_c_contract() -> None:
    geometry = load_candidate_c_geometry()
    expected_clause = build_overlay_aware_prompt_clause(geometry)
    combined = build_overlay_aware_recomposition_prompt()
    assert expected_clause in combined
    assert f"x = {geometry.zone_x_start}..{geometry.zone_x_end}" in combined
    assert f"y = {geometry.zone_y_start}..{geometry.zone_y_end}" in combined


def test_hand_and_product_treated_as_one_factual_group() -> None:
    combined = build_overlay_aware_recomposition_prompt()
    assert "one factual foreground group" in combined
    assert "iPhone" in combined and "hand" in combined


def test_gemini_never_instructed_to_draw_branding() -> None:
    combined = build_overlay_aware_recomposition_prompt()
    assert "NNJ BRAND RULE" in combined
    assert "Do not generate NNJ branding, the NNJ logo, or the pulse line" in combined


# ---------------------------------------------------------------------------
# C. Collision severity classification
# ---------------------------------------------------------------------------


def test_literal_zone_intersection_is_hard_collision() -> None:
    geometry = load_candidate_c_geometry()
    subject = (900, 640, 1000, 700)  # deep inside the zone
    assessment = assess_collision(subject, geometry)
    assert assessment.severity == CollisionSeverity.HARD_COLLISION
    assert assessment.hard_collision is True
    assert assessment.soft_clearance_warning is False


def test_one_pixel_literal_zone_intersection_is_hard_collision() -> None:
    geometry = load_candidate_c_geometry()
    subject = (geometry.zone_x_start - 5, geometry.zone_y_start + 1, geometry.zone_x_start + 1, geometry.zone_y_end - 1)
    assessment = assess_collision(subject, geometry)
    assert assessment.severity == CollisionSeverity.HARD_COLLISION


def test_no_literal_collision_but_under_20px_is_soft_warning() -> None:
    geometry = load_candidate_c_geometry()
    subject_right_edge = geometry.zone_x_start - 10  # 10px short of the zone, inside the 20px buffer
    subject = (subject_right_edge - 100, geometry.zone_y_start + 5, subject_right_edge, geometry.zone_y_end - 5)
    assessment = assess_collision(subject, geometry)
    assert assessment.severity == CollisionSeverity.SOFT_CLEARANCE_WARNING
    assert assessment.hard_collision is False
    assert assessment.soft_clearance_warning is True
    assert assessment.approx_clearance_px == 10


def test_20px_or_more_clearance_is_clear() -> None:
    geometry = load_candidate_c_geometry()
    subject_right_edge = geometry.zone_x_start - 20
    subject = (subject_right_edge - 100, geometry.zone_y_start + 5, subject_right_edge, geometry.zone_y_end - 5)
    assessment = assess_collision(subject, geometry)
    assert assessment.severity == CollisionSeverity.CLEAR
    assert assessment.approx_clearance_px == 20


def test_v2_4g_recorded_geometry_is_soft_warning_not_hard_collision() -> None:
    """The exact real measurement from the approved V2.4G result: subject right edge at x=815,
    11px short of zone_x_start=826 - a real, disclosed near-miss, never a hard collision."""
    geometry = load_candidate_c_geometry()
    subject = (180, 80, 815, 720)
    assessment = assess_collision(subject, geometry)
    assert assessment.severity == CollisionSeverity.SOFT_CLEARANCE_WARNING
    assert assessment.hard_collision is False
    assert assessment.approx_clearance_px == 11


# ---------------------------------------------------------------------------
# D. Runtime mode / fallback policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_zero_provider_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "off")
    gateway = _FakeGateway(response=_valid_response())
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.used_recomposed_image is False
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_mode_dry_run_zero_provider_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "dry_run")
    gateway = _FakeGateway(response=_valid_response())
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.used_recomposed_image is False
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_live_success_calls_flash_exactly_once_with_overlay_aware_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(response=_valid_response())
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.used_recomposed_image is True
    assert len(gateway.calls) == 1
    assert gateway.calls[0].prompt == build_overlay_aware_recomposition_prompt()
    assert result.model == "gemini-3.1-flash-image"


@pytest.mark.asyncio
async def test_provider_failure_fails_open_to_original_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=GeminiImageAdapterError("HTTP 500"))
    source = _jpeg_bytes()
    result = await maybe_recompose(source_image_bytes=source, gateway=gateway)
    assert result.used_recomposed_image is False
    assert result.image_bytes == source


@pytest.mark.asyncio
async def test_no_automatic_pro_or_gpt_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=GeminiImageAdapterError("boom"))
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.model in (None, "gemini-3.1-flash-image")
    assert result.model != "gemini-3-pro-image"


def test_no_pro_or_gpt_import_anywhere_in_editorial_recomposition() -> None:
    tree = ast.parse(Path("services/editorial_recomposition.py").read_text(encoding="utf-8"))
    source_text = Path("services/editorial_recomposition.py").read_text(encoding="utf-8")
    assert "gemini-3-pro-image" not in source_text or "GEMINI_3_PRO_IMAGE" not in source_text
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any("openai" in m.lower() for m in imported)


# ---------------------------------------------------------------------------
# E. Telemetry propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_id_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(response=_valid_response(request_id="v1_abc123"))
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.request_id == "v1_abc123"


@pytest.mark.asyncio
async def test_usage_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    usage = CapabilityUsage(input_tokens=744, output_tokens=1441, units=1, unit_type="image")
    gateway = _FakeGateway(response=_valid_response(usage=usage))
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.input_tokens == 744
    assert result.output_tokens == 1441
    assert result.units == 1
    assert result.unit_type == "image"


@pytest.mark.asyncio
async def test_missing_metadata_remains_none_when_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "off")
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=_FakeGateway(response=_valid_response()))
    assert result.request_id is None
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.units is None
    assert result.unit_type is None


@pytest.mark.asyncio
async def test_missing_metadata_remains_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    gateway = _FakeGateway(exc=GeminiImageAdapterError("boom"))
    result = await maybe_recompose(source_image_bytes=_jpeg_bytes(), gateway=gateway)
    assert result.request_id is None
    assert result.input_tokens is None


def test_repr_never_exposes_image_bytes_or_secrets() -> None:
    result = RecompositionResult(
        used_recomposed_image=True, image_bytes=b"\xff\xd8\xff" * 5000, mode="live",
        eligibility=__import__("services.editorial_recomposition", fromlist=["EligibilityDecision"]).EligibilityDecision(True, "ok"),
        provider="gemini", model="gemini-3.1-flash-image", source_sha256="a" * 64, result_sha256="b" * 64,
        fallback_reason=None, latency_ms=100.0, request_id="v1_x", input_tokens=1, output_tokens=1, units=1, unit_type="image",
    )
    text = repr(result)
    assert b"\xff\xd8\xff".hex() not in text  # raw bytes never dumped
    assert "bytes>" in text
    assert "api_key" not in text.lower()
    assert "authorization" not in text.lower()


# ---------------------------------------------------------------------------
# F. Storage / source-bytes fix
# ---------------------------------------------------------------------------


def test_selected_stored_candidate_bytes_reachable_via_bufferedinputfile() -> None:
    data = _jpeg_bytes()
    photo_input = BufferedInputFile(data, filename="x.jpg")
    result = resolve_recomposition_source_bytes(photo_input, candidate=None)
    assert result == data


def test_telegram_file_id_path_does_not_suppress_recomposition_bytes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact V2.5 §7 fix: a cached Telegram file_id (str) must not prevent recomposition from
    obtaining the real stored bytes belonging to the same already-selected candidate."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    storage = LocalImageStorage(tmp_path)
    data = _jpeg_bytes()
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    stored = storage.store_validated_image(data, sha256=sha, image_format="JPEG", max_bytes=10_000_000)

    candidate = _fake_candidate(storage_status="stored", storage_key=stored.storage_key, telegram_file_id="AgACAgCACHED123")

    # resolve_photo_input() itself still prefers the cached file_id (unchanged, still the
    # optimization for SENDING) - but recomposition must still see the real bytes.
    from bot.image_preview_media import resolve_photo_input

    photo_input = resolve_photo_input(candidate)
    assert photo_input == "AgACAgCACHED123"  # the cached file_id, exactly as before this phase

    recomposition_bytes = resolve_recomposition_source_bytes(photo_input, candidate)
    assert recomposition_bytes == data


def test_byte_identity_hash_preserved(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    storage = LocalImageStorage(tmp_path)
    data = _jpeg_bytes()
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    stored = storage.store_validated_image(data, sha256=sha, image_format="JPEG", max_bytes=10_000_000)
    candidate = _fake_candidate(storage_status="stored", storage_key=stored.storage_key, telegram_file_id="cached")

    recomposition_bytes = resolve_recomposition_source_bytes("cached", candidate)
    assert recomposition_bytes is not None
    assert hashlib.sha256(recomposition_bytes).hexdigest() == sha


def test_unavailable_bytes_safe_fail_open() -> None:
    assert resolve_recomposition_source_bytes(None, None) is None
    assert resolve_recomposition_source_bytes("cached_file_id_only", None) is None
    candidate = _fake_candidate(storage_status="not_requested", storage_key=None, telegram_file_id="cached")
    assert resolve_recomposition_source_bytes("cached", candidate) is None


# ---------------------------------------------------------------------------
# G. Branding
# ---------------------------------------------------------------------------


def test_recomposed_news_receives_candidate_c() -> None:
    source = _jpeg_bytes(1376, 768)
    branded = apply_candidate_c_branding(source)
    img = Image.open(io.BytesIO(branded))
    assert img.size == (1280, 720)
    assert img.format == "JPEG"


def test_legacy_programmatic_branding_not_additionally_applied() -> None:
    manifest = json.loads(CANDIDATE_C_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["embedded_v1_wordmark_included"] is False
    assert manifest["signal_bars_icon_included"] is False


def test_brand_renderer_module_itself_untouched_by_candidate_c() -> None:
    """services/brand_renderer.py stays a completely separate, still-default treatment - it must
    never import anything from the Candidate C contract module."""
    tree = ast.parse(Path("services/brand_renderer.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any("nnj_candidate_c_contract" in m for m in imported)


def test_content_cycle_wires_candidate_c_only_for_successful_news_recomposition() -> None:
    """Phase V2.9 §2 superseded the V2.5-era direct `apply_candidate_c_branding()` call with the
    adaptive overlay director (`services.nnj_adaptive_overlay.apply_adaptive_nnj_branding()`),
    which composites the SAME trusted, locked Candidate C pixels (still the primary/lower-right
    entry in its own placement table) - this is a real, intentional, documented supersession
    (tests/test_v2_9_production_wiring.py covers it directly), not a regression. Updated here to
    assert the current wiring rather than the now-superseded one."""
    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "apply_adaptive_nnj_branding" in source_text
    assert "resolve_recomposition_source_bytes" in source_text
    # The legacy render_branded_media() call site remains present and reachable (the "else"
    # branch) - never deleted, never bypassed for DATA/QUOTE/BREAKING.
    assert "render_branded_media(" in source_text
