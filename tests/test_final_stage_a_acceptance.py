"""Phase V2.12A/B - narrow, DB-free/provider-free tests for scripts/nnj_final_stage_a_acceptance.py.

Proves (per the phase's own Section 4 requirements): the harness cannot send Telegram, makes no
provider calls at import time, reuses real production helpers rather than duplicating their
logic, validates the source-only keyboard, validates the destination, persists a self-contained
manifest/package with correct hashes, and caps Gemini recomposition to at most one call at
runtime. No real DB session, no real Postgres/Redis, no real Gemini/OpenAI/Anthropic call
anywhere in this file - `services.editorial_recomposition.GeminiImageAdapter` is always mocked."""
from __future__ import annotations

import ast
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from PIL import Image

from core.config import settings
from schemas.capability import CapabilityUsage
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError
from services.image_persistence import EditorialImageCandidate
from services.nnj_master_news_overlay import apply_master_news_branding
from services.telegram_routing import RouteTarget
from scripts import nnj_final_stage_a_acceptance as stage_a

_SOURCE_PATH = Path(stage_a.__file__)


def _jpeg_bytes(width: int = 1600, height: int = 900) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buf, "JPEG")
    return buf.getvalue()


def _fake_candidate(*, warnings: list[str] | None = None) -> EditorialImageCandidate:
    return EditorialImageCandidate(
        id=uuid4(), candidate_id="cand-1", rank=1, relevance_score=90, quality_score=90,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=1600, height=900, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key="unused", telegram_file_id=None,
        editor_decision=None, source_url="https://example.com/img.jpg", article_url="https://example.com/article",
        warnings=warnings, is_expired=False,
    )


def _valid_gemini_response() -> ImageGenerationResponse:
    return ImageGenerationResponse(
        image_bytes=_jpeg_bytes(1376, 768), mime_type="image/jpeg",
        model_used="gemini-3.1-flash-image", provider="gemini",
        usage=CapabilityUsage(input_tokens=100, output_tokens=50, units=1, unit_type="image"),
        request_id="v1_test", cost_usd=None,
    )


# ---------------------------------------------------------------------------
# Import-time safety / zero-Telegram structural audit
# ---------------------------------------------------------------------------


def test_module_imports_without_provider_or_telegram_side_effects() -> None:
    """Importing the module must never touch DB/Redis/providers/Telegram - already proven by the
    fact this whole test module imports it successfully with zero mocks in place."""
    assert stage_a.run_stage_a is not None


def test_audit_no_telegram_send_calls_finds_none() -> None:
    assert stage_a.audit_no_telegram_send_calls() == []


def test_script_never_imports_aiogram_bot() -> None:
    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "Bot" not in imported_names


def test_script_imports_production_branding_and_keyboard_functions_not_reimplemented() -> None:
    source_text = _SOURCE_PATH.read_text(encoding="utf-8")
    assert "from services.nnj_master_news_overlay import" in source_text
    assert "apply_master_news_branding" in source_text
    assert "from bot.keyboards.image_preview import build_source_only_keyboard" in source_text
    assert "from scripts.run_content_generation import" in source_text
    tree = ast.parse(source_text)
    defined_functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    # Proves this harness never reimplements the real branding/placement selector inline.
    assert "select_master_news_branding" not in defined_functions
    assert "apply_master_news_branding" not in defined_functions


# ---------------------------------------------------------------------------
# Keyboard contract
# ---------------------------------------------------------------------------


def test_build_keyboard_is_source_only_no_cta() -> None:
    keyboard = stage_a.build_keyboard("https://example.com/real-article")
    assert keyboard is not None
    rows = keyboard.inline_keyboard
    assert len(rows) == 1
    assert len(rows[0]) == 1
    assert rows[0][0].text == "🔗 Источник"
    assert rows[0][0].url == "https://example.com/real-article"


def test_build_keyboard_returns_none_without_url() -> None:
    assert stage_a.build_keyboard(None) is None


# ---------------------------------------------------------------------------
# Destination contract
# ---------------------------------------------------------------------------


def test_resolve_destination_matches_expected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", stage_a.EXPECTED_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", stage_a.EXPECTED_TOPIC_ID)
    route = stage_a.resolve_destination()
    assert route.chat_id == stage_a.EXPECTED_CHAT_ID
    assert route.topic_id == stage_a.EXPECTED_TOPIC_ID


def test_resolve_destination_raises_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", stage_a.EXPECTED_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", 999)  # wrong topic - must fail closed
    with pytest.raises(stage_a.StageAContractError):
        stage_a.resolve_destination()


# ---------------------------------------------------------------------------
# Story selection filtering (pure function)
# ---------------------------------------------------------------------------


def test_filter_candidate_event_ids_excludes_known_calibration_story() -> None:
    excluded = next(iter(stage_a.EXCLUDED_CALIBRATION_EVENT_IDS))
    fresh = uuid4()
    result = stage_a._filter_candidate_event_ids([excluded, fresh])
    assert result == [fresh]


# ---------------------------------------------------------------------------
# Text render fails closed on non-V8.6-shaped output
# ---------------------------------------------------------------------------


def test_render_final_html_fails_closed_on_non_v8_output() -> None:
    outcome = SimpleNamespace(copywriting_output={"body": "V4-shaped output, no main_body key"})
    with pytest.raises(stage_a.StageAContractError):
        stage_a.render_final_html(outcome)


def test_render_final_html_accepts_real_v8_shaped_output() -> None:
    outcome = SimpleNamespace(copywriting_output={"title": "Real Headline", "main_body": "Real generated body.", "ending": None})
    html, plain_text = stage_a.render_final_html(outcome)
    assert "Real Headline" in html
    assert "Real generated body." in plain_text
    assert "<b>" in html  # real HTML, not the plain-text rendering


def test_render_final_html_includes_ninja_pulse_cta_exactly_once() -> None:
    """Phase V2.12I: Phase 23.1Q's footer-enabled decision is restored - the real renderer call
    must pass include_ninja_pulse_footer=True."""
    outcome = SimpleNamespace(copywriting_output={"title": "Real Headline", "main_body": "Real generated body.", "ending": None})
    html, plain_text = stage_a.render_final_html(outcome)
    assert html.count("NINJA PULSE. Подписаться 🥷") == 1
    assert plain_text.count("NINJA PULSE. Подписаться 🥷") == 1
    assert '<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>' in html


# ---------------------------------------------------------------------------
# Recomposition: capped to exactly one call, both success and failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recomposition_capped_to_one_call_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-gemini-api-key-do-not-use"))
    fake_gateway = AsyncMock()
    fake_gateway.generate_image = AsyncMock(return_value=_valid_gemini_response())
    candidate = _fake_candidate(warnings=None)

    with patch("services.editorial_recomposition.GeminiImageAdapter", return_value=fake_gateway):
        chosen_bytes, result, visual_path = await stage_a.apply_visual_path(candidate, _jpeg_bytes())

    assert visual_path == "RECOMPOSE"
    assert result is not None and result.used_recomposed_image
    assert fake_gateway.generate_image.await_count == 1
    assert chosen_bytes == result.image_bytes


@pytest.mark.asyncio
async def test_recomposition_capped_to_one_call_on_failure_falls_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-gemini-api-key-do-not-use"))
    fake_gateway = AsyncMock()
    fake_gateway.generate_image = AsyncMock(side_effect=GeminiImageAdapterError("boom"))
    candidate = _fake_candidate(warnings=None)
    source_bytes = _jpeg_bytes()

    with patch("services.editorial_recomposition.GeminiImageAdapter", return_value=fake_gateway):
        chosen_bytes, result, visual_path = await stage_a.apply_visual_path(candidate, source_bytes)

    assert visual_path == "ORIGINAL_SOURCE"
    assert fake_gateway.generate_image.await_count == 1  # attempted exactly once, never retried
    assert chosen_bytes == source_bytes


@pytest.mark.asyncio
async def test_recomposition_never_attempted_when_source_risk_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-gemini-api-key-do-not-use"))
    fake_gateway = AsyncMock()
    fake_gateway.generate_image = AsyncMock(return_value=_valid_gemini_response())
    candidate = _fake_candidate(warnings=["possible_watermark"])
    source_bytes = _jpeg_bytes()

    with patch("services.editorial_recomposition.GeminiImageAdapter", return_value=fake_gateway):
        chosen_bytes, result, visual_path = await stage_a.apply_visual_path(candidate, source_bytes)

    assert visual_path == "ORIGINAL_SOURCE"
    assert result is None
    assert fake_gateway.generate_image.await_count == 0  # never even constructed - source-risk gate
    assert chosen_bytes == source_bytes


# ---------------------------------------------------------------------------
# Manifest + package persistence round-trip (real branding, no provider call)
# ---------------------------------------------------------------------------


def test_manifest_and_persist_package_roundtrip_hashes(tmp_path: Path) -> None:
    source_bytes = _jpeg_bytes()
    final_image_bytes, branding = apply_master_news_branding(source_bytes)  # real, deterministic, no provider call
    candidate = _fake_candidate(warnings=None)
    outcome = SimpleNamespace(task_id=uuid4(), content_draft=SimpleNamespace(id=uuid4()))
    story = stage_a.StoryCandidate(
        event_id=uuid4(), title="Real Test Headline", source_domain="example.com",
        published_at=None, url="https://example.com/real-article", category="AI",
    )
    keyboard = stage_a.build_keyboard(story.url)
    destination = RouteTarget(chat_id=stage_a.EXPECTED_CHAT_ID, topic_id=stage_a.EXPECTED_TOPIC_ID)
    html = "<b>Real Test Headline</b>\nReal body."
    plain_text = "Real Test Headline\nReal body."

    manifest = stage_a.build_manifest(
        story=story, outcome=outcome, candidate=candidate, recomposition=None, visual_path="ORIGINAL_SOURCE",
        branding=branding, destination=destination, keyboard=keyboard, source_bytes=source_bytes,
        raw_recomposition_bytes=None, final_image_bytes=final_image_bytes, html=html, plain_text=plain_text,
        settings_snapshot={"copywriting_prompt_version": "8.6"},
    )

    assert manifest["checkpoint_sha"] == stage_a.CHECKPOINT_SHA
    assert manifest["event_id"] == str(story.event_id)
    assert manifest["visual_path"] == "ORIGINAL_SOURCE"
    assert manifest["telegram_sends_this_run"] == 0
    assert manifest["destination"] == {"chat_id": stage_a.EXPECTED_CHAT_ID, "topic_id": stage_a.EXPECTED_TOPIC_ID}

    output_dir = tmp_path / "package"
    hashes = stage_a.persist_package(
        output_dir, final_image_bytes=final_image_bytes, source_image_bytes=source_bytes,
        raw_recomposition_bytes=None, html=html, plain_text=plain_text, keyboard=keyboard,
        destination=destination, manifest=manifest,
    )

    for name in ("final_image.jpg", "source_image.jpg", "final_post.html", "final_post.txt",
                 "keyboard.json", "destination.json", "telemetry.json", "manifest.json"):
        path = output_dir / name
        assert path.exists()
        assert hashes[name] == hashlib.sha256(path.read_bytes()).hexdigest()

    assert hashes["final_image.jpg"] == manifest["final_image_sha256"]
    assert hashes["final_post.html"] == manifest["final_html_sha256"]
    assert "raw_recomposition.jpg" not in hashes  # no recomposition happened for this package


# ---------------------------------------------------------------------------
# Phase V2.12G/V2.12I: the final-package hard-contract gate - restored to REQUIRE the approved
# NINJA PULSE CTA (Phase 23.1Q) exactly once, alongside the unchanged source-only keyboard.
# ---------------------------------------------------------------------------

_CTA_ANCHOR = '<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>'
_CTA_TEXT = "NINJA PULSE. Подписаться 🥷"


def _valid_destination() -> RouteTarget:
    return RouteTarget(chat_id=stage_a.EXPECTED_CHAT_ID, topic_id=stage_a.EXPECTED_TOPIC_ID)


def _valid_keyboard(url: str = "https://example.com/real-article"):
    return stage_a.build_keyboard(url)


def _valid_html_and_plain_text() -> tuple[str, str]:
    """A minimal, valid final package's text: headline + body + the required CTA anchor,
    matching exactly what render_v81_news_card_html(..., include_ninja_pulse_footer=True)
    actually produces (anchor in html, bare text in the stripped plain_text)."""
    html = f"<b>Headline</b>\nBody.\n{_CTA_ANCHOR}"
    plain_text = f"Headline\nBody.\n{_CTA_TEXT}"
    return html, plain_text


def test_validate_final_package_contract_accepts_a_valid_package_with_cta() -> None:
    url = "https://example.com/real-article"
    html, plain_text = _valid_html_and_plain_text()
    stage_a.validate_final_package_contract(
        html=html, plain_text=plain_text,
        keyboard=_valid_keyboard(url), source_url=url, destination=_valid_destination(),
    )  # must not raise


def test_validate_final_package_contract_rejects_missing_cta_in_html() -> None:
    url = "https://example.com/real-article"
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html="<b>Headline</b>\nBody.", plain_text=f"Headline\nBody.\n{_CTA_TEXT}",
            keyboard=_valid_keyboard(url), source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_missing_cta_in_plain_text() -> None:
    url = "https://example.com/real-article"
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=f"<b>Headline</b>\nBody.\n{_CTA_ANCHOR}", plain_text="Headline\nBody.",
            keyboard=_valid_keyboard(url), source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_duplicate_cta_in_html() -> None:
    url = "https://example.com/real-article"
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=f"<b>Headline</b>\nBody.\n{_CTA_ANCHOR}\n{_CTA_ANCHOR}", plain_text=f"Headline\nBody.\n{_CTA_TEXT}",
            keyboard=_valid_keyboard(url), source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_bare_ninja_pulse_url_without_proper_anchor() -> None:
    """The CTA text appearing without being wrapped in the exact required anchor (e.g. a bare,
    unlinked URL substituted for the real anchor) does not satisfy the contract."""
    url = "https://example.com/real-article"
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=f"<b>Headline</b>\nBody.\n{_CTA_TEXT} https://t.me/nnjvpn",
            plain_text=f"Headline\nBody.\n{_CTA_TEXT}",
            keyboard=_valid_keyboard(url), source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_missing_keyboard() -> None:
    url = "https://example.com/real-article"
    html, plain_text = _valid_html_and_plain_text()
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=html, plain_text=plain_text,
            keyboard=None, source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_wrong_button_text() -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    url = "https://example.com/real-article"
    html, plain_text = _valid_html_and_plain_text()
    wrong_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Wrong Label", url=url)]])
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=html, plain_text=plain_text,
            keyboard=wrong_keyboard, source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_wrong_button_url() -> None:
    url = "https://example.com/real-article"
    html, plain_text = _valid_html_and_plain_text()
    keyboard_for_a_different_url = _valid_keyboard("https://example.com/a-different-article")
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=html, plain_text=plain_text,
            keyboard=keyboard_for_a_different_url, source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_multiple_buttons() -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    url = "https://example.com/real-article"
    html, plain_text = _valid_html_and_plain_text()
    two_button_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔗 Источник", url=url),
        InlineKeyboardButton(text="NINJA PULSE. Подписаться 🥷", url="https://t.me/nnjvpn"),
    ]])
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=html, plain_text=plain_text,
            keyboard=two_button_keyboard, source_url=url, destination=_valid_destination(),
        )


def test_validate_final_package_contract_rejects_wrong_destination() -> None:
    url = "https://example.com/real-article"
    html, plain_text = _valid_html_and_plain_text()
    wrong_destination = RouteTarget(chat_id=stage_a.EXPECTED_CHAT_ID, topic_id=999)
    with pytest.raises(stage_a.StageAContractError):
        stage_a.validate_final_package_contract(
            html=html, plain_text=plain_text,
            keyboard=_valid_keyboard(url), source_url=url, destination=wrong_destination,
        )
