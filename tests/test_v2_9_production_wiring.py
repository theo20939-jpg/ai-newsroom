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
from datetime import UTC, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiogram.types import BufferedInputFile
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import CapabilityUsage
from services import image_persistence
from services.editorial_treatment import STANDARD, EditorialTreatmentDecision
from services.image_persistence import EditorialImageCandidate
from services.presentation_director import DATA as PRESENTATION_DATA
from services.presentation_director import PresentationDecision
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401
    test_source,  # noqa: F401
)
from tests.test_editorial_delivery_mode import _v6_capability_registry
from tests.test_router_media_integration import _v82_capability_registry
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
    # Phase V2.10R: the recomposition tests below patch `GeminiImageAdapter` itself so no real
    # network call ever happens, but `maybe_recompose()` (services/editorial_recomposition.py)
    # checks `settings.gemini_api_key` and fail-opens to ORIGINAL_SOURCE with
    # fallback_reason="gemini_api_key_absent" *before* ever constructing/calling that mock if the
    # key is falsy - a real, previously-silent dependency on whatever ambient `.env` the test
    # happened to run under (present and non-empty on this dev machine, confirmed absent on the
    # VPS ephemeral test container - the actual root cause of the real VPS failure in
    # test_recomposed_image_receives_adaptive_branding). A dummy, deterministic key here makes
    # every test in this file self-contained regardless of environment.
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-gemini-api-key-do-not-use"))
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


def _stored_candidate_with_cached_file_id(
    tmp_path, monkeypatch: pytest.MonkeyPatch, *, warnings: list | None = None,
) -> EditorialImageCandidate:
    """Phase V2.16: the exact mirror-image counterpart to `_stored_candidate()` - a real,
    locally-stored candidate that ALSO carries a cached `telegram_file_id`, so
    `resolve_photo_input()` (bot/image_preview_media.py) returns that cached string instead of a
    `BufferedInputFile`, reproducing the exact real-production condition
    `worker/content_cycle.py`'s own `source_bytes = photo_input.data if isinstance(photo_input,
    BufferedInputFile) else None` line left `source_bytes` at `None` for. `read_candidate_bytes()`
    still resolves real bytes for this same candidate via `storage_key` - Telegram delivery
    representation and recomposition source bytes are independently resolvable, exactly as
    `resolve_recomposition_source_bytes()`'s own docstring already documents."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    storage = LocalImageStorage(tmp_path)
    data = _jpeg_bytes()
    sha = hashlib.sha256(data).hexdigest()
    stored = storage.store_validated_image(data, sha256=sha, image_format="JPEG", max_bytes=10_000_000)
    return EditorialImageCandidate(
        id=uuid4(), candidate_id="cand-cached-1", rank=1, relevance_score=90, quality_score=90,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=1600, height=900, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key=stored.storage_key, telegram_file_id="cached-tg-file-id-123",
        editor_decision=None, source_url="https://example.com/cached-img.jpg",
        article_url="https://example.com/cached-article", warnings=warnings, is_expired=False,
    )


def _stored_media_group_candidates(tmp_path, monkeypatch: pytest.MonkeyPatch, *, count: int) -> list[EditorialImageCandidate]:
    """Phase V2.25 Part B: `count` distinct, independently-stored real candidates (distinct pixel
    content, storage_key, candidate_id, rank, source_url) with no cached telegram_file_id - real
    enough to drive `services.image_preview_notifier.build_rich_media_plan()`'s own real
    `resolve_photo_input()` calls into an actual multi-item media group, and real enough for
    `apply_master_news_branding()` to run on each one's own real bytes (not a fabricated/stubbed
    result)."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    storage = LocalImageStorage(tmp_path)
    candidates = []
    for i in range(count):
        data = _jpeg_bytes(1600 + i, 900)  # distinct dimensions -> distinct bytes -> distinct storage_key
        sha = hashlib.sha256(data).hexdigest()
        stored = storage.store_validated_image(data, sha256=sha, image_format="JPEG", max_bytes=10_000_000)
        candidates.append(EditorialImageCandidate(
            id=uuid4(), candidate_id=f"group-cand-{i}", rank=i + 1, relevance_score=90 - i, quality_score=90 - i,
            discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
            width=1600 + i, height=900, observed_mime="image/jpeg", image_format="JPEG",
            storage_status="stored", storage_key=stored.storage_key, telegram_file_id=None,
            editor_decision=None, source_url=f"https://example.com/group-img-{i}.jpg",
            article_url="https://example.com/article", warnings=None, is_expired=False,
        ))
    return candidates


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
    # Phase V2.25: the import grew to three names (the branding function plus the explicit
    # diagnostic-status constants) and is therefore now parenthesized/multi-line.
    assert "from services.nnj_master_news_overlay import (" in source_text
    assert "apply_master_news_branding,\n)" in source_text


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
    # Phase V2.10R: `overlay_mode` was never a real field on this log record - the actual
    # production statement (worker/content_cycle.py, the `master_news_branding_applied` logger.
    # info() call) only ever attaches `degradation_mode` (services/nnj_master_news_overlay.py::
    # MasterNewsBrandingDecision.degradation_mode), whose only possible values are
    # "upper_and_lower"/"lower_signature_only"/"upper_mark_only"/"no_overlay" - a stale assertion
    # left over from this file's own pre-V2.10H terminology, missed by the V2.10I update pass.
    assert branding_records[0].degradation_mode in (
        "upper_and_lower", "lower_signature_only", "upper_mark_only", "no_overlay",
    )


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
        event = await _make_event(session, source, published_at=datetime.now(UTC))
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


# ---------------------------------------------------------------------------
# Phase V2.16: cached Telegram file_id must not starve MASTER NEWS branding of the
# already-selected candidate's real original bytes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_file_id_candidate_still_receives_master_news_branding(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """The real production gap: `resolve_photo_input()` returns a cached `telegram_file_id`
    (a plain str) whenever one exists, so `worker/content_cycle.py`'s own `source_bytes =
    photo_input.data if isinstance(photo_input, BufferedInputFile) else None` line left
    `source_bytes` at `None` even though `resolve_recomposition_source_bytes()` (a few lines
    below) had already independently resolved the exact same candidate's real bytes via
    `read_candidate_bytes()`. With `editorial_recomposition_mode = 'off'`, recomposition fails
    open (`used_recomposed_image = False`), so the pre-fix code never promoted those bytes and
    branding was skipped (`brand_render_skipped` / `cached_file_id_no_local_bytes`), sending the
    raw cached file_id with NO NNJ overlay. Proves the fix: `apply_master_news_branding()` now
    still runs on `ORIGINAL_SOURCE` bytes, and Telegram receives the branded `BufferedInputFile`
    (not the cached file_id) as a result."""
    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate_with_cached_file_id(tmp_path, monkeypatch)

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    fake_bot.send_photo.assert_called_once()

    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1  # no longer skipped
    assert branding_records[0].visual_path == "ORIGINAL_SOURCE"

    skip_records = [r for r in caplog.records if r.msg == "brand_render_skipped"]
    assert skip_records == []  # cached_file_id_no_local_bytes must not fire when bytes exist

    # Telegram must receive the branded bytes, not the cached file_id string.
    photo_arg = fake_bot.send_photo.call_args.kwargs["photo"]
    assert isinstance(photo_arg, BufferedInputFile)


@pytest.mark.asyncio
async def test_cached_file_id_with_source_risk_still_brands_with_lower_signature_disabled(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """Same cached-file_id gap, combined with a real source-risk warning: `maybe_recompose()`
    must never even be called (zero Gemini calls, the risk gate skips it entirely, unchanged by
    this phase), yet MASTER NEWS branding must still run on the promoted ORIGINAL_SOURCE bytes,
    with `disable_lower_signature=True` exactly as the pre-existing risk contract requires."""
    _common_settings(monkeypatch)  # already sets a dummy gemini_api_key via monkeypatch
    settings.editorial_recomposition_mode = "live"  # proves the risk gate - not the mode - is why Gemini is skipped
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate_with_cached_file_id(tmp_path, monkeypatch, warnings=["possible_watermark"])

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("services.editorial_recomposition.GeminiImageAdapter") as mock_adapter_class,
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    mock_adapter_class.assert_not_called()  # zero Gemini calls - the risk gate skips it entirely

    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1
    assert branding_records[0].visual_path == "ORIGINAL_SOURCE"
    assert branding_records[0].lower_signature_disabled_reason is not None


# ---------------------------------------------------------------------------
# Phase V2.25 Part B: the real accidental bypass - a NEWS media-group (album) send previously
# branded only media_group_items[0], leaving every OTHER photo in the group completely untouched
# by apply_master_news_branding() with no exception, no safety rejection, and no diagnostic.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_photos_in_a_real_media_group_receive_master_news_branding(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """The real production gap this phase fixed: before Phase V2.25 Part B, only
    media_group_items[0] was ever passed to apply_master_news_branding() - the second (and any
    later) photo in a real NEWS media group shipped to Telegram completely unbranded, silently.
    Two independently-stored real candidates, routed through the real is_v8 rich-media path
    (build_rich_media_plan(), never stubbed), must BOTH produce their own real
    master_news_branding_applied log record."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.editorial_recomposition_mode = "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = [MagicMock(message_id=300), MagicMock(message_id=301)]
    candidates = _stored_media_group_candidates(tmp_path, monkeypatch, count=2)

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2
    # Both items sent to Telegram must be real branded bytes, never a bare unbranded resolution.
    for media_item in kwargs["media"]:
        assert isinstance(media_item.media, BufferedInputFile)

    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 2, (
        "both media-group photos must independently reach apply_master_news_branding() - "
        f"got {len(branding_records)}, proving the fix regressed if this is 1"
    )
    group_indices = sorted(getattr(r, "media_group_index", -1) for r in branding_records)
    assert group_indices == [-1, 1]  # primary image carries no media_group_index; the second is index 1
    for r in branding_records:
        assert r.news_branding_status in ("BRANDED", "NO_OVERLAY_SAFETY")

    # No silent-bypass diagnostic for either image - both were genuinely branded or safety-skipped.
    no_source_records = [
        r for r in caplog.records
        if r.msg in ("brand_render_skipped", "brand_render_attempted")
        and getattr(r, "news_branding_status", None) in ("NO_OVERLAY_NO_SOURCE_BYTES", "ORIGINAL_SOURCE_BRANDING_FAILURE")
    ]
    assert no_source_records == []


@pytest.mark.asyncio
async def test_master_news_branding_exception_falls_back_to_original_source_never_blocks_send(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """TEST 3 (Phase V2.25 spec): a real exception inside apply_master_news_branding() must never
    block the send (spec §29's own fail-safe boundary, unchanged by this phase) - Telegram must
    still receive the original (unbranded) source image, and the explicit diagnostic must record
    ORIGINAL_SOURCE_BRANDING_FAILURE, never a silently-unlabeled skip."""
    _common_settings(monkeypatch)
    settings.editorial_recomposition_mode = "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111
    candidate = _stored_candidate(tmp_path, monkeypatch)

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("worker.content_cycle.apply_master_news_branding", side_effect=RuntimeError("synthetic decode failure")),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    fake_bot.send_photo.assert_called_once()  # the send itself was never blocked

    attempted_records = [r for r in caplog.records if r.msg == "brand_render_attempted"]
    assert len(attempted_records) == 1
    assert attempted_records[0].brand_applied is False
    assert attempted_records[0].news_branding_status == "ORIGINAL_SOURCE_BRANDING_FAILURE"
    assert "synthetic decode failure" in attempted_records[0].brand_skip_reason

    # The bytes actually sent must be the original candidate's real bytes, not a crash artifact.
    photo_arg = fake_bot.send_photo.call_args.kwargs["photo"]
    assert isinstance(photo_arg, BufferedInputFile)


# ---------------------------------------------------------------------------
# Phase V2.27 - native Telegram video upload for YouTube/Vimeo, and video-only NEWS delivery.
# End-to-end via the real worker.content_cycle.run_content_cycle() - errors locally (no reachable
# local Postgres, an established, disclosed, session-wide limitation - see every other DB-backed
# test in this file), NOT fabricated as passing; structurally correct for CI/a real database.
# ---------------------------------------------------------------------------


def _eligible_video_candidate(*, platform: str, validation_status: str, remote_url: str):
    from services.video_discovery_persistence import EligibleVideoCandidate

    return EligibleVideoCandidate(
        id=uuid4(), event_id=uuid4(), content_draft_id=None, discovery_method="open_graph_video",
        remote_url=remote_url, platform=platform, declared_width=1280, declared_height=720,
        declared_mime_type=None, declared_duration_seconds=30, validation_status=validation_status,
        detected_container=None, byte_size=None, error_code=None,
    )


def _hosted_video_download_result_ready(*, byte_size: int = 500_000, duration: int = 30):
    from services.hosted_video_download import HOSTED_VIDEO_NATIVE_READY, HostedVideoDownloadResult

    return HostedVideoDownloadResult(
        outcome=HOSTED_VIDEO_NATIVE_READY, video_bytes=b"x" * byte_size, source_format="avc1/mp4a/mp4",
        final_format="mp4/h264/aac", remuxed=True, transcoded=False, byte_size=byte_size,
        duration_seconds=duration, reason=None,
    )


@pytest.mark.asyncio
async def test_video_only_news_dispatches_via_send_video(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, caplog,
) -> None:
    """TEST 9 (Phase V2.27 spec): zero usable images + one downloaded YouTube video must reach
    Telegram as a real single native video (bot.send_video), never send_photo, never dropped to
    text-only."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "rich_media_mode", "enforce")
    monkeypatch.setattr(settings, "hosted_video_download_mode", "enforce")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_video.return_value.message_id = 500
    video_candidate = _eligible_video_candidate(
        platform="youtube", validation_status="unvalidated_hosted_platform",
        remote_url="https://www.youtube.com/watch?v=abc123",
    )

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[])),
        patch("worker.content_cycle.get_video_candidates_for_event", new=AsyncMock(return_value=[video_candidate])),
        patch("worker.content_cycle.download_hosted_video", new=AsyncMock(return_value=_hosted_video_download_result_ready())),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    assert result.router_video_only_sent == 1
    fake_bot.send_video.assert_called_once()
    fake_bot.send_photo.assert_not_called()
    fake_bot.send_media_group.assert_not_called()
    _, kwargs = fake_bot.send_video.call_args
    assert isinstance(kwargs["video"], BufferedInputFile)

    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert branding_records == []  # video must never pass through apply_master_news_branding()


@pytest.mark.asyncio
async def test_one_image_plus_downloaded_youtube_video_sends_media_group(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """TEST 7 (Phase V2.27 spec): 1 image + 1 downloaded video -> a real 2-item Telegram media
    group, photo branded (Phase V2.25), video native and untouched by branding."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "rich_media_mode", "enforce")
    monkeypatch.setattr(settings, "hosted_video_download_mode", "enforce")
    settings.editorial_recomposition_mode = "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = [MagicMock(message_id=600), MagicMock(message_id=601)]
    candidate = _stored_candidate(tmp_path, monkeypatch)
    video_candidate = _eligible_video_candidate(
        platform="youtube", validation_status="unvalidated_hosted_platform",
        remote_url="https://www.youtube.com/watch?v=abc123",
    )

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("worker.content_cycle.get_video_candidates_for_event", new=AsyncMock(return_value=[video_candidate])),
        patch("worker.content_cycle.download_hosted_video", new=AsyncMock(return_value=_hosted_video_download_result_ready())),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    assert result.router_media_group_sent == 1
    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2
    assert isinstance(kwargs["media"][0].media, BufferedInputFile)  # the branded photo
    assert isinstance(kwargs["media"][1].media, BufferedInputFile)  # the native video

    branding_records = [r for r in caplog.records if r.msg == "master_news_branding_applied"]
    assert len(branding_records) == 1  # exactly the photo, never the video


@pytest.mark.asyncio
async def test_video_download_failure_falls_back_to_images_only_never_a_link(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """Phase V2.27 §4/§7 failure policy: with hosted_video_download_mode='enforce', a failed
    download must drop the video entirely (images-only fallback) - never the old caption-link
    behavior, and must never block the image send itself."""
    from services.hosted_video_download import HOSTED_VIDEO_DOWNLOAD_FAILED, HostedVideoDownloadResult

    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "rich_media_mode", "enforce")
    monkeypatch.setattr(settings, "hosted_video_download_mode", "enforce")
    settings.editorial_recomposition_mode = "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 700
    candidate = _stored_candidate(tmp_path, monkeypatch)
    video_candidate = _eligible_video_candidate(
        platform="youtube", validation_status="unvalidated_hosted_platform",
        remote_url="https://www.youtube.com/watch?v=abc123",
    )
    failed_result = HostedVideoDownloadResult(
        outcome=HOSTED_VIDEO_DOWNLOAD_FAILED, video_bytes=None, source_format=None, final_format=None,
        remuxed=False, transcoded=False, byte_size=None, duration_seconds=None, reason="timeout",
    )

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("worker.content_cycle.get_video_candidates_for_event", new=AsyncMock(return_value=[video_candidate])),
        patch("worker.content_cycle.download_hosted_video", new=AsyncMock(return_value=failed_result)),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    fake_bot.send_photo.assert_called_once()  # images-only fallback, never blocked
    fake_bot.send_media_group.assert_not_called()

    caption = fake_bot.send_photo.call_args.kwargs["caption"]
    assert "youtube.com" not in caption  # no raw-link fallback once native delivery is opted into


@pytest.mark.asyncio
async def test_direct_hosted_video_still_works_unaffected_by_v2_27(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog,
) -> None:
    """TEST 14 (Phase V2.27 spec): DIRECT_HOSTED non-regression - never touches
    hosted_video_download_mode/download_hosted_video() at all, Telegram fetches the URL itself."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "rich_media_mode", "enforce")
    monkeypatch.setattr(settings, "hosted_video_download_mode", "enforce")
    settings.editorial_recomposition_mode = "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = [MagicMock(message_id=800), MagicMock(message_id=801)]
    candidate = _stored_candidate(tmp_path, monkeypatch)
    video_candidate = _eligible_video_candidate(
        platform="direct_hosted", validation_status="valid", remote_url="https://cdn.example.com/clip.mp4",
    )

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[candidate])),
        patch("worker.content_cycle.get_video_candidates_for_event", new=AsyncMock(return_value=[video_candidate])),
        patch("worker.content_cycle.download_hosted_video") as mock_download,
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    fake_bot.send_media_group.assert_called_once()
    mock_download.assert_not_called()  # never invoked for DIRECT_HOSTED
    _, kwargs = fake_bot.send_media_group.call_args
    assert kwargs["media"][1].media == "https://cdn.example.com/clip.mp4"  # URL passed straight through


def test_video_only_input_never_reaches_apply_master_news_branding() -> None:
    """TEST 10 (Phase V2.27 spec) structural proof: video_only_input is a variable completely
    separate from photo_input/source_bytes in worker/content_cycle.py - grep-verified it is never
    assigned to photo_input and never passed to apply_master_news_branding()."""
    source = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "video_only_input: str | BufferedInputFile | None = None" in source
    assert "photo_input = video_only_input" not in source
    assert "apply_master_news_branding(video_only_input" not in source
    assert "send_video_to_editorial_destination(" in source
