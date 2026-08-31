"""Phase 18 M8 - Telegram Meme Editorial Preview tests (docs/
phase18_m8_telegram_editorial_preview_report.md).

Pure, DB-free, no-live-Telegram tests: keyboard encode/parse, caption rendering, summary
builders, and `send_meme_preview()`'s dry-run contract (a `FakeBot` that raises if any send
method is ever called - the strongest possible proof no Telegram API contact occurs). The DB-
backed callback handler (`bot/handlers/meme_preview.py`) is not covered here - same disclosed
constraint as every DB-dependent piece of M1-M7 (local Postgres/Redis stack unavailable).
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from bot.keyboards.meme_preview import (
    build_decided_keyboard,
    build_meme_preview_keyboard,
    encode_callback_data,
    parse_callback_data,
)
from bot.meme_preview_formatting import MemePreviewCaptionTooLongError, render_meme_preview_caption
from integrations.storage.image_storage import LocalImageStorage
from schemas.meme_preview import MemePreviewCard
from schemas.meme_quality import MemeQualityAssessment, MemeQualityChecks, MemeQualityDecision
from schemas.meme_safety import (
    MemeGateDecision,
    MemeOriginalityAssessment,
    MemeSafetyAssessment,
    MemeSafetyOriginalityGateResult,
)
from services.meme_preview_notifier import send_meme_preview
from services.meme_preview_summary import build_quality_summary, build_safety_summary

_CANDIDATE_ID = uuid4()


def _card(**overrides) -> MemePreviewCard:
    base = dict(
        candidate_id=_CANDIDATE_ID,
        news_title="Nvidia CEO insists AI is not destroying jobs",
        news_url="https://example.com/story",
        news_category="AI",
        top_text="AI WON'T TAKE YOUR JOB",
        bottom_text="SAYS GUY WHOSE JOB IS AI",
        telegram_caption="From today's keynote.",
        editor_explanation="Plays on the irony.",
        alt_text="A CEO on stage.",
        image_storage_key=None,
        safety_summary="Safety: PASS | Originality: PASS",
        quality_summary="Quality: READY_FOR_EDITOR (all checks passed)",
    )
    return MemePreviewCard(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Keyboard encode/parse
# ---------------------------------------------------------------------------


def test_encode_and_parse_roundtrip() -> None:
    data = encode_callback_data("approve", _CANDIDATE_ID)
    parsed = parse_callback_data(data)
    assert parsed == ("approve", _CANDIDATE_ID)


def test_parse_rejects_wrong_prefix() -> None:
    assert parse_callback_data(f"imgprev:approve:{_CANDIDATE_ID}") is None


def test_parse_rejects_unknown_action() -> None:
    assert parse_callback_data(f"memeprev:launch_nukes:{_CANDIDATE_ID}") is None


def test_parse_rejects_malformed_uuid() -> None:
    assert parse_callback_data("memeprev:approve:not-a-uuid") is None


def test_parse_rejects_wrong_part_count() -> None:
    assert parse_callback_data("memeprev:approve") is None


@pytest.mark.parametrize(
    "action", ["approve", "reject", "regen_concept", "regen_image", "regen_text", "fallback"],
)
def test_every_documented_action_round_trips(action: str) -> None:
    assert parse_callback_data(encode_callback_data(action, _CANDIDATE_ID)) == (action, _CANDIDATE_ID)


def test_build_meme_preview_keyboard_includes_every_action_and_source_link() -> None:
    keyboard = build_meme_preview_keyboard(_CANDIDATE_ID, source_url="https://example.com/story")
    all_callback_data = [
        button.callback_data
        for row in keyboard.inline_keyboard for button in row if button.callback_data
    ]
    for action in ("approve", "reject", "regen_concept", "regen_image", "regen_text", "fallback"):
        assert encode_callback_data(action, _CANDIDATE_ID) in all_callback_data
    all_urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert "https://example.com/story" in all_urls


def test_build_meme_preview_keyboard_without_source_url_has_no_url_button() -> None:
    keyboard = build_meme_preview_keyboard(_CANDIDATE_ID, source_url=None)
    all_urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert all_urls == []


def test_build_decided_keyboard_none_without_url() -> None:
    assert build_decided_keyboard(None) is None


def test_build_decided_keyboard_has_only_source_button() -> None:
    keyboard = build_decided_keyboard("https://example.com/story")
    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].url == "https://example.com/story"


# ---------------------------------------------------------------------------
# Caption rendering
# ---------------------------------------------------------------------------


def test_render_caption_is_minimal_meme_and_headline_only() -> None:
    """MEME PRODUCTION PIPELINE: the caption is now "😂 MEME\\n\\n<headline>" only - on-image
    text/safety/quality diagnostics are deliberately NOT duplicated in the caption anymore (they
    remain in structured logs and on the MemeCandidate row itself)."""
    caption = render_meme_preview_caption(_card())
    assert caption == "😂 MEME\n\nNvidia CEO insists AI is not destroying jobs"
    assert "AI WON'T TAKE YOUR JOB" not in caption
    assert "Safety: PASS" not in caption


def test_render_caption_never_duplicates_full_article() -> None:
    caption = render_meme_preview_caption(_card())
    assert "keynote" not in caption  # telegram_caption's own old text - never shown here anymore


def test_render_caption_too_long_raises() -> None:
    with pytest.raises(MemePreviewCaptionTooLongError):
        render_meme_preview_caption(_card(news_title="x" * 2000))


# ---------------------------------------------------------------------------
# Summary builders
# ---------------------------------------------------------------------------


def _safety_gate(safety_decision=MemeGateDecision.PASS, originality_decision=MemeGateDecision.PASS,
                  sensitivity_categories=None) -> MemeSafetyOriginalityGateResult:
    safety = MemeSafetyAssessment(decision=safety_decision, sensitivity_categories=sensitivity_categories or [])
    originality = MemeOriginalityAssessment(decision=originality_decision)
    ranks = {MemeGateDecision.PASS: 0, MemeGateDecision.REVIEW: 1, MemeGateDecision.BLOCK: 2}
    gate = max((safety_decision, originality_decision), key=lambda d: ranks[d])
    return MemeSafetyOriginalityGateResult(policy_version="v1", gate_decision=gate, safety=safety, originality=originality)


def test_build_safety_summary_includes_flags_when_present() -> None:
    gate = _safety_gate(safety_decision=MemeGateDecision.BLOCK, sensitivity_categories=["crime_with_victim"])
    summary = build_safety_summary(gate)
    assert "Safety: BLOCK" in summary
    assert "crime_with_victim" in summary


def test_build_quality_summary_lists_failed_checks() -> None:
    checks = MemeQualityChecks(
        factual_alignment=True, punchline_clarity=False, readability=True, originality=True,
        brand_fit=True, meme_safety=True, visual_quality=True, mobile_friendliness=True,
    )
    assessment = MemeQualityAssessment(
        policy_version="v1", decision=MemeQualityDecision.REVIEW, checks=checks,
    )
    summary = build_quality_summary(assessment)
    assert "punchline_clarity" in summary
    assert "REVIEW" in summary


def test_build_quality_summary_all_passed() -> None:
    checks = MemeQualityChecks(
        factual_alignment=True, punchline_clarity=True, readability=True, originality=True,
        brand_fit=True, meme_safety=True, visual_quality=True, mobile_friendliness=True,
    )
    assessment = MemeQualityAssessment(
        policy_version="v1", decision=MemeQualityDecision.READY_FOR_EDITOR, checks=checks,
    )
    assert "all checks passed" in build_quality_summary(assessment)


# ---------------------------------------------------------------------------
# send_meme_preview - dry-run contract
# ---------------------------------------------------------------------------


class _NeverCalledBot:
    """Raises if ANY send/edit method is ever invoked - the strongest possible proof that
    dry_run=True makes zero Telegram API contact."""

    def __getattr__(self, name: str):
        raise AssertionError(f"Bot.{name}() must never be called when dry_run=True")


_MEME_CHAT_ID = -1004297182444
_MEME_TOPIC_ID = 77


@pytest.fixture(autouse=True)
def _meme_destination_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """MEME PRODUCTION PIPELINE: send_meme_preview() now resolves EditorialDestination.MEME via
    services.telegram_routing.resolve_route() instead of taking a raw chat_id parameter - every
    test in this section needs the destination configured exactly like a real deployment would."""
    from core.config import settings

    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _MEME_CHAT_ID)
    monkeypatch.setattr(settings, "meme_topic_id", _MEME_TOPIC_ID)


@pytest.mark.asyncio
async def test_dry_run_never_touches_the_bot(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    outcome = await send_meme_preview(_NeverCalledBot(), storage, _card(), dry_run=True)  # type: ignore[arg-type]
    assert outcome.sent is False
    assert outcome.reason == "dry_run"
    assert outcome.chat_id == _MEME_CHAT_ID
    assert "Nvidia CEO insists AI is not destroying jobs" in outcome.rendered_caption


@pytest.mark.asyncio
async def test_dry_run_reports_has_image_false_when_no_storage_key(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    outcome = await send_meme_preview(
        _NeverCalledBot(), storage, _card(image_storage_key=None), dry_run=True,  # type: ignore[arg-type]
    )
    assert outcome.has_image is False


@pytest.mark.asyncio
async def test_dry_run_with_unconfigured_destination_still_never_sends(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconfigured newsroom_telegram_chat_id must never fall back to sending anywhere else -
    never asserts, never calls the bot, mirrors services.telegram_routing.resolve_route()'s own
    established "no chat id -> None -> unconfigured_destination" contract."""
    from core.config import settings

    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", None)
    storage = LocalImageStorage(tmp_path)
    outcome = await send_meme_preview(_NeverCalledBot(), storage, _card(), dry_run=True)  # type: ignore[arg-type]
    assert outcome.sent is False
    assert outcome.reason == "unconfigured_destination"
    assert outcome.chat_id is None


@pytest.mark.asyncio
async def test_render_failure_in_dry_run_returns_unsent_outcome(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    outcome = await send_meme_preview(
        _NeverCalledBot(), storage, _card(news_title="x" * 2000), dry_run=True,  # type: ignore[arg-type]
    )
    assert outcome.sent is False
    assert outcome.reason == "caption_too_long"
    assert outcome.rendered_caption == ""


@pytest.mark.asyncio
async def test_dry_run_never_sends_to_a_different_destination(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit destination-isolation proof (MEME PRODUCTION PIPELINE §9's own requirement): even
    when OTHER editorial topics are configured, the resolved chat_id/topic_id must be exactly the
    MEME ones, never NEWS/TELEGRAPH/some other topic."""
    from core.config import settings

    monkeypatch.setattr(settings, "news_topic_id", 111)
    monkeypatch.setattr(settings, "telegraph_topic_id", 222)
    storage = LocalImageStorage(tmp_path)
    outcome = await send_meme_preview(_NeverCalledBot(), storage, _card(), dry_run=True)  # type: ignore[arg-type]
    assert outcome.chat_id == _MEME_CHAT_ID


@pytest.mark.asyncio
async def test_live_send_routes_to_meme_chat_and_topic_thread(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real (non-dry-run) send must carry `message_thread_id=meme_topic_id` - the exact gap a
    prior version of this function had (it never passed message_thread_id at all, so a live send
    would have landed in the configured chat's root, never the MEMES forum topic specifically)."""
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import SendMessage, TelegramMethod

    class _FakeSession(BaseSession):
        def __init__(self) -> None:
            super().__init__()
            self.sent: list[TelegramMethod] = []

        async def close(self) -> None:
            pass

        async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
            self.sent.append(method)
            return True

        async def stream_content(self, *args: object, **kwargs: object) -> object:
            raise NotImplementedError

    monkeypatch.setattr("core.config.settings.meme_telegram_preview_mode", "enforce", raising=False)
    session = _FakeSession()
    bot = Bot(token="123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    storage = LocalImageStorage(tmp_path)

    outcome = await send_meme_preview(bot, storage, _card(image_storage_key=None), dry_run=False)

    assert outcome.sent is True
    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert len(sends) == 1
    assert sends[0].chat_id == _MEME_CHAT_ID
    assert sends[0].message_thread_id == _MEME_TOPIC_ID
