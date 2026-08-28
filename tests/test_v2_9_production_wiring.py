"""Phase V2.9 - Production Wiring Freeze (superseded by Phase V2.10H/I - see below). Proves the
real `worker.content_cycle.run_content_cycle()` router-mode NEWS path calls the one intended
branding director for BOTH ORIGINAL_SOURCE and successfully-recomposed images - never the old
fixed `apply_candidate_c_branding()`, never silently demoting ORIGINAL_SOURCE to the legacy
category/NP-code/pulse/badge treatment. That intended director was Phase V2.9's own
`services.nnj_adaptive_overlay.apply_adaptive_nnj_branding()` (Candidate C) at the time this file
was written; Phase V2.10H replaced it with `services.nnj_master_news_overlay.
apply_master_news_branding()` (the MASTER NEWS contract) as an intentional, user-approved product
decision - Candidate C remains in the repository as historical/fallback evidence, untouched, just
no longer called from this path. The tests below were updated in Phase V2.10I to assert the
CURRENT director while preserving the ORIGINAL invariant this file established. No real
Gemini/OpenAI/Anthropic/Telegram call anywhere in this file - LIVE-path tests inject a fake
`ImageGenerationGateway`-shaped double.

Reuses tests/test_content_worker_cycle.py's and tests/test_router_media_integration.py's own
already-established fixtures/helpers directly - never duplicated."""
from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import CapabilityUsage
from services import image_persistence
from services.editorial_treatment import STANDARD, EditorialTreatmentDecision
from services.image_persistence import EditorialImageCandidate
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401,F811
    test_source,  # noqa: F401,F811
)
from services.presentation_director import DATA as PRESENTATION_DATA
from services.presentation_director import PresentationDecision
from tests.test_editorial_delivery_mode import _v6_capability_registry
from worker.content_cycle import run_content_cycle

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2


@pytest.fixture(autouse=True)
def _reset_delivery_mode() -> None:
    original_delivery = settings.editorial_delivery_mode
    original_presentation = settings.presentation_director_mode
    original_pulse = settings.pulse_brand_enabled
    original_recomposition = settings.editorial_recomposition_mode
    yield
    settings.editorial_delivery_mode = original_delivery
    settings.presentation_director_mode = original_presentation
    settings.pulse_brand_enabled = original_pulse
    settings.editorial_recomposition_mode = original_recomposition


async def _seed_eligible_event(factory_: async_sessionmaker[AsyncSession], source: object) -> None:
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)


def _common_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.editorial_delivery_mode = "router"
    settings.presentation_director_mode = "enforce"
    settings.pulse_brand_enabled = True
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")


def _standard_decision() -> EditorialTreatmentDecision:
    return EditorialTreatmentDecision(STANDARD, human_review_required=False, reason="test")


def _jpeg_bytes(width: int = 1600, height: int = 900) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buf, "JPEG")
    return buf.getvalue()


def _stored_candidate(tmp_path, monkeypatch: pytest.MonkeyPatch, *, warnings: list | None = None) -> EditorialImageCandidate:
    """A real, locally-stored candidate with NO cached telegram_file_id - forces
    resolve_photo_input() to read real bytes via read_candidate_bytes(), so `source_bytes`
    (content_cycle.py's own local var) is genuinely populated, exactly like a real, never-before-
    sent candidate."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    storage = LocalImageStorage(tmp_path)
    data = _jpeg_bytes()
    sha = hashlib.sha256(data).hexdigest()
    stored = storage.store_validated_image(data, sha256=sha, image_format="JPEG", max_bytes=10_000_000)
    return EditorialImageCandidate(
        id=uuid4(), candidate_id="cand-1", rank=1, relevance_score=90, quality_score=90,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=1600, height=900, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key=stored.storage_key, telegram_file_id=None,
        editor_decision=None, source_url="https://example.com/img.jpg", article_url="https://example.com/article",
        warnings=warnings, is_expired=False,
    )


def _valid_response(image_bytes: bytes | None = None) -> ImageGenerationResponse:
    return ImageGenerationResponse(
        image_bytes=image_bytes or _jpeg_bytes(1376, 768), mime_type="image/jpeg",
        model_used="gemini-3.1-flash-image", provider="gemini",
        usage=CapabilityUsage(input_tokens=100, output_tokens=50, units=1, unit_type="image"),
        request_id="v1_test", cost_usd=None,
    )


# ---------------------------------------------------------------------------
# 1/2 - structural: old fixed call gone, new adaptive call present
# ---------------------------------------------------------------------------


def test_old_fixed_candidate_c_branding_no_longer_used_in_content_cycle() -> None:
    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "apply_candidate_c_branding" not in source_text


def test_master_news_overlay_director_is_the_production_branding_call() -> None:
    """Phase V2.10I - updated for the Phase V2.10H contract change: the intended NEWS branding
    director is now services.nnj_master_news_overlay (MASTER_BALANCED + boxless canonical NNJ),
    not V2.9's own Candidate C adaptive director - that module remains in the repository as
    historical/fallback evidence (see tests/test_v2_10h_master_news_production.py's own
    `test_nnj_adaptive_overlay_module_itself_untouched_and_importable`) but is no longer the one
    reachable from worker/content_cycle.py. This test preserves the ORIGINAL invariant this file
    established (exactly one normal NEWS branding production path, real and reachable from
    content_cycle.py, never reimplemented inline) - only WHICH director satisfies it has changed."""
    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "apply_master_news_branding" in source_text
    assert "from services.nnj_master_news_overlay import apply_master_news_branding" in source_text


def test_content_cycle_never_duplicates_placement_selection_logic() -> None:
    """Proves worker/content_cycle.py imports the real selection function rather than
    reimplementing placement/scale/collision logic inline - updated Phase V2.10I to check for the
    current director's own selector name (select_master_news_branding), not V2.9's superseded one."""
    tree = ast.parse(Path("worker/content_cycle.py").read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.FunctionDef) and "select_overlay_placement" in node.name for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.FunctionDef) and "select_master_news_branding" in node.name for node in ast.walk(tree)
    )


# ---------------------------------------------------------------------------
# 3 - ORIGINAL_SOURCE -> adaptive branding, zero provider calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_original_source_receives_adaptive_branding_without_recomposition_gateway(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "off"  # matches the real production default
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate(tmp_path, monkeypatch)

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    assert result.router_image_sent == 1
    fake_bot.send_photo.assert_called_once()

    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1
    assert branding_records[0].visual_path == "ORIGINAL_SOURCE"
    assert branding_records[0].overlay_mode in ("full_signature", "logo_only", "no_overlay")


# ---------------------------------------------------------------------------
# 4/5 - RECOMPOSE success -> adaptive branding; recomposition failure -> ORIGINAL_SOURCE -> adaptive branding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recomposed_image_receives_adaptive_branding(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "live"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate(tmp_path, monkeypatch)

    fake_image_gateway = AsyncMock()
    fake_image_gateway.generate_image = AsyncMock(return_value=_valid_response())

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("services.editorial_recomposition.GeminiImageAdapter", return_value=fake_image_gateway),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1
    assert branding_records[0].visual_path == "RECOMPOSE"


@pytest.mark.asyncio
async def test_recomposition_failure_falls_open_to_original_source_then_adaptive_branding(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "live"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate(tmp_path, monkeypatch)

    fake_image_gateway = AsyncMock()
    fake_image_gateway.generate_image = AsyncMock(side_effect=GeminiImageAdapterError("boom"))

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("services.editorial_recomposition.GeminiImageAdapter", return_value=fake_image_gateway),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1  # never blocked by a recomposition failure
    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1
    assert branding_records[0].visual_path == "ORIGINAL_SOURCE"  # fail-open, never Pro/GPT


# ---------------------------------------------------------------------------
# 6 - no automatic Pro/GPT escalation (structural, mirrors V2.5's own established check)
# ---------------------------------------------------------------------------


def test_no_automatic_pro_or_gpt_escalation_in_recomposition_module() -> None:
    """The module's own docstring legitimately DISCLOSES it never falls back to these models
    ("never gemini-3-pro-image or gpt-image-2") - checked structurally (imports only) rather than
    by a raw substring scan, which would false-positive on that very disclosure."""
    tree = ast.parse(Path("services/editorial_recomposition.py").read_text(encoding="utf-8"))
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "GEMINI_3_PRO_IMAGE" not in imported_names
    assert "GPTImageAdapter" not in imported_names


# ---------------------------------------------------------------------------
# 7 - Phase V2.10N: NEWS branding must never imply the legacy CTA keyboard
# ---------------------------------------------------------------------------


async def _seed_eligible_event_with_url(
    factory_: async_sessionmaker[AsyncSession], source: object, *, url: str,
) -> None:
    """Mirrors `_seed_eligible_event()` exactly, except it also sets `NewsEvent.url` - the field
    `build_source_only_keyboard()`/`build_source_and_cta_keyboard()` both key off - so the real
    keyboard produced by a real run_content_cycle() pass can be asserted against a known value.
    `_make_event()` itself never sets `url` (defaults to `None`, which `build_source_only_
    keyboard()` would turn into "no keyboard at all" - useless for this test's own assertions)."""
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        event.url = url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)


@pytest.mark.asyncio
async def test_news_enforce_keyboard_is_source_only_no_cta(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """Phase V2.10N §4 assertion A: NEWS + presentation_director_mode=='enforce' +
    pulse_brand_enabled=True must reach apply_master_news_branding() (proven by the existing
    branding_records assertion, mirroring the sibling tests above) AND send exactly the
    source-only "🔗 Источник" keyboard - never the CTA button, never a second button, never the
    NINJA PULSE URL - closing the real coupling worker/content_cycle.py had before this phase."""
    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "off"
    source_url = "https://example.com/real-news-article"
    await _seed_eligible_event_with_url(factory, test_source, url=source_url)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate(tmp_path, monkeypatch)

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1  # apply_master_news_branding() was genuinely reached

    fake_bot.send_photo.assert_called_once()
    keyboard = fake_bot.send_photo.call_args.kwargs["reply_markup"]
    assert keyboard is not None
    rows = keyboard.inline_keyboard
    assert len(rows) == 1
    assert len(rows[0]) == 1
    button = rows[0][0]
    assert button.text == "🔗 Источник"
    assert button.url == source_url

    all_button_text = " ".join(b.text for row in rows for b in row)
    all_button_urls = [b.url for row in rows for b in row if b.url]
    assert "NINJA PULSE" not in all_button_text
    assert "https://t.me/nnjvpn" not in all_button_urls


@pytest.mark.asyncio
async def test_news_off_mode_keyboard_unchanged_source_only(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """Phase V2.10N §4 assertion B: presentation_director_mode == 'off' (today's real production
    default) never enters the enforce branch this phase touched at all - the pre-existing
    source-only keyboard set at the top of the router-mode NEWS branch is untouched, exactly as
    before this phase's fix."""
    _common_settings(monkeypatch)
    settings.presentation_director_mode = "off"
    settings.editorial_recomposition_mode = "off"
    source_url = "https://example.com/off-mode-article"
    await _seed_eligible_event_with_url(factory, test_source, url=source_url)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate(tmp_path, monkeypatch)

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    # presentation_director_mode == "off" never reaches apply_master_news_branding() (documented,
    # unchanged, pre-existing behavior - not this phase's concern) - only the keyboard is asserted.
    fake_bot.send_photo.assert_called_once()
    keyboard = fake_bot.send_photo.call_args.kwargs["reply_markup"]
    assert keyboard is not None
    rows = keyboard.inline_keyboard
    assert len(rows) == 1
    assert len(rows[0]) == 1
    assert rows[0][0].text == "🔗 Источник"
    assert rows[0][0].url == source_url


@pytest.mark.asyncio
async def test_non_news_presentation_type_keeps_cta_keyboard_in_enforce_mode(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, caplog,
) -> None:
    """Phase V2.10N §4 assertion C: this phase's fix is scoped to NEWS only - a non-NEWS
    presentation_type (DATA/QUOTE/BREAKING) reached in enforce mode must keep receiving the
    existing CTA keyboard unchanged, proving no regression for those post types. Forces the
    decision via a direct patch of `decide_presentation()` (the same "swap in a controlled
    result" technique this suite already uses for `_classify_event_for_router_treatment`) rather
    than fabricating title/content text that happens to score as DATA - deterministic, not
    incidental."""
    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "off"
    source_url = "https://example.com/data-card-article"
    await _seed_eligible_event_with_url(factory, test_source, url=source_url)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 111

    forced_decision = PresentationDecision(
        presentation_type=PRESENTATION_DATA, category="TECH", caption_position="BELOW",
        branding_strength="MINIMAL", brand_media=False, visual_priority=1,
        data_candidate=None, quote_candidate=None, reason="test_forced_data",
    )

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[])),
        patch("worker.content_cycle.decide_presentation", return_value=forced_decision),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 0  # non-NEWS never reaches the MASTER NEWS director

    fake_bot.send_message.assert_called_once()
    keyboard = fake_bot.send_message.call_args.kwargs["reply_markup"]
    assert keyboard is not None
    rows = keyboard.inline_keyboard
    all_button_text = " ".join(b.text for row in rows for b in row)
    assert "NINJA PULSE" in all_button_text  # CTA keyboard unchanged for non-NEWS - no regression
