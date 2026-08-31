"""MEME-PROD-1: bot.keyboards.meme_generate + bot.handlers.meme_generate - the manual
"😂 Сгенерировать мем" NEWS-button callback/decode and its handler. First dedicated test file for
either module - neither had any test coverage before this phase.

Handler tests monkeypatch `bot.handlers.meme_generate.trigger_meme_generation` and
`bot.handlers.meme_generate._build_capability_context()` (both module-level names, easily
patchable) rather than exercising the real orchestrator/AI-integration-layer assembly - this file
proves the HANDLER's own logic (auth, event lookup, callback_data binding, never mutating the
originating NEWS message) in isolation, exactly mirroring
tests/test_telegraph_article_review_handler.py's own established fake-session/fake-service
technique. Real Postgres (db_session fixture) only for the one real `NewsEvent` row each test
needs; no LLM/image/Telegram call anywhere in this file.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage
from aiogram.types import Message as AiogramMessage
from aiogram.types import User
from sqlalchemy.ext.asyncio import AsyncSession

import bot.handlers.meme_generate as meme_generate_handler
from bot.keyboards.image_preview import build_source_only_keyboard
from bot.keyboards.meme_generate import (
    MEME_GENERATE_BUTTON_LABEL,
    append_meme_generate_button,
    build_meme_generate_button,
    encode_callback_data,
    parse_callback_data,
)
from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.meme_generation_orchestrator import MemeGenerationOutcome

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_AUTHORIZED_CHAT_ID = -1004297182444
_AUTHORIZED_USER_ID = 99


# ---------------------------------------------------------------------------------------------
# bot/keyboards/meme_generate.py - pure, no DB, no Bot
# ---------------------------------------------------------------------------------------------


def test_encode_decode_round_trip() -> None:
    event_id = uuid.uuid4()
    assert parse_callback_data(encode_callback_data(event_id)) == event_id


def test_parse_rejects_malformed_or_foreign_payloads() -> None:
    assert parse_callback_data("not-a-valid-payload") is None
    assert parse_callback_data("memegen:not-a-uuid") is None
    assert parse_callback_data("imgprev:use:" + str(uuid.uuid4()) + ":0") is None  # a different namespace


def test_build_meme_generate_button_shape() -> None:
    event_id = uuid.uuid4()
    button = build_meme_generate_button(event_id)
    assert button.text == MEME_GENERATE_BUTTON_LABEL
    assert button.callback_data == encode_callback_data(event_id)
    assert button.url is None


def test_append_meme_generate_button_adds_a_new_row_alongside_source() -> None:
    """Required test: 'keyboard contains Source + Generate Meme together'."""
    event_id = uuid.uuid4()
    source_keyboard = build_source_only_keyboard("https://example.com/article", label="🔗 Источник")
    combined = append_meme_generate_button(source_keyboard, event_id)

    buttons = [b for row in combined.inline_keyboard for b in row]
    assert len(buttons) == 2
    assert buttons[0].text == "🔗 Источник"
    assert buttons[0].url == "https://example.com/article"
    assert buttons[1].text == MEME_GENERATE_BUTTON_LABEL
    assert buttons[1].callback_data == encode_callback_data(event_id)
    # Additive only - the Source row itself is untouched, never merged/replaced.
    assert len(combined.inline_keyboard) == 2


def test_append_meme_generate_button_builds_a_fresh_keyboard_when_none() -> None:
    event_id = uuid.uuid4()
    combined = append_meme_generate_button(None, event_id)
    buttons = [b for row in combined.inline_keyboard for b in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data == encode_callback_data(event_id)


# ---------------------------------------------------------------------------------------------
# bot/handlers/meme_generate.py - handler logic, DB + fake Telegram session, orchestrator faked
# ---------------------------------------------------------------------------------------------


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        self.sent.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise NotImplementedError(f"FakeSession cannot handle {type(method)} - the handler must never send/edit/delete anything on the originating NEWS message itself")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _make_callback(
    session: FakeSession, *, data: str, chat_id: int = _AUTHORIZED_CHAT_ID,
    message_id: int = 500, inaccessible: bool = False, user_id: int = _AUTHORIZED_USER_ID,
) -> CallbackQuery:
    bot = Bot(token=_FAKE_TOKEN, session=session)
    chat = Chat(id=chat_id, type="supergroup")
    if inaccessible:
        message: object = InaccessibleMessage(chat=chat, message_id=message_id, date=0)
    else:
        message = AiogramMessage(
            message_id=message_id, date=datetime.now(timezone.utc), chat=chat, text="a NEWS post",
        ).as_(bot)
    return CallbackQuery(
        id="cbq1", from_user=User(id=user_id, is_bot=False, first_name="Editor"), chat_instance="ci", data=data,
        message=message,
    ).as_(bot)


def _fake_session_factory(db_session: AsyncSession):
    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _CM()


class _RecordingOrchestrator:
    """Fakes services.meme_generation_orchestrator.trigger_meme_generation() - records every call's
    kwargs and returns a caller-controlled outcome, without ever touching a real LLM/image
    gateway/Telegram bot."""

    def __init__(self, outcome: MemeGenerationOutcome) -> None:
        self.calls: list[dict[str, Any]] = []
        self._outcome = outcome

    async def __call__(self, session: AsyncSession, **kwargs: Any) -> MemeGenerationOutcome:
        self.calls.append(kwargs)
        return self._outcome


@pytest.fixture(autouse=True)
def _authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _AUTHORIZED_CHAT_ID)
    monkeypatch.setattr(settings, "meme_manual_approver_user_ids", [_AUTHORIZED_USER_ID])
    monkeypatch.setattr(meme_generate_handler, "_build_capability_context", lambda: (None, None, None))


async def _seed_event(db_session: AsyncSession) -> NewsEvent:
    source = NewsSource(name=f"Meme handler test source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="A meme-worthy headline", content="Body.",
        category=EventCategory.AI, hash=f"memehandler-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


def _install_fake_orchestrator(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, outcome: MemeGenerationOutcome) -> _RecordingOrchestrator:
    monkeypatch.setattr(meme_generate_handler, "async_session_factory", _fake_session_factory(db_session))
    fake = _RecordingOrchestrator(outcome)
    monkeypatch.setattr(meme_generate_handler, "trigger_meme_generation", fake)
    return fake


@pytest.mark.asyncio
async def test_malformed_callback_data_fails_safely_no_orchestration_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_orchestrator(monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=uuid.uuid4()))
    session = FakeSession()
    callback = _make_callback(session, data="not-a-valid-payload")

    await meme_generate_handler.handle_meme_generate_callback(callback)

    assert len(session.sent) == 1
    assert isinstance(session.sent[0], AnswerCallbackQuery)
    assert fake.calls == []


@pytest.mark.asyncio
async def test_inaccessible_message_fails_safely(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_orchestrator(monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=uuid.uuid4()))
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(uuid.uuid4()), inaccessible=True)

    await meme_generate_handler.handle_meme_generate_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert fake.calls == []


@pytest.mark.asyncio
async def test_unauthorized_chat_fails_closed_no_orchestration_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_orchestrator(monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=uuid.uuid4()))
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(uuid.uuid4()), chat_id=_AUTHORIZED_CHAT_ID + 1)

    await meme_generate_handler.handle_meme_generate_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert fake.calls == []


@pytest.mark.asyncio
async def test_unauthorized_user_fails_closed_no_orchestration_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_orchestrator(monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=uuid.uuid4()))
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(uuid.uuid4()), user_id=_AUTHORIZED_USER_ID + 1)

    await meme_generate_handler.handle_meme_generate_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert fake.calls == []


@pytest.mark.asyncio
async def test_empty_approver_allowlist_fails_closed_by_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The allowlist's own fail-closed default (core/config.py: empty by default, nobody
    authorized until an operator explicitly populates it)."""
    monkeypatch.setattr(settings, "meme_manual_approver_user_ids", [])
    fake = _install_fake_orchestrator(monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=uuid.uuid4()))
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(uuid.uuid4()))

    await meme_generate_handler.handle_meme_generate_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert fake.calls == []


@pytest.mark.asyncio
async def test_missing_event_fails_closed_no_orchestration_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_orchestrator(monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=uuid.uuid4()))
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(uuid.uuid4()))  # a real UUID, no such row

    await meme_generate_handler.handle_meme_generate_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert fake.calls == []


@pytest.mark.asyncio
async def test_authorized_valid_callback_triggers_manual_generation_for_the_exact_event(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story/news identity preservation: the orchestrator call receives byte-identical
    `news_event_id` to the one encoded in callback_data - never inferred from message text."""
    event = await _seed_event(db_session)
    fake = _install_fake_orchestrator(
        monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=event.id, task_id=uuid.uuid4(), candidate_id=uuid.uuid4()),
    )
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(event.id))

    await meme_generate_handler.handle_meme_generate_callback(callback)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["news_event_id"] == event.id
    assert call["trigger_source"] == "manual"
    # Never leaks a value only the internal default-resolution seam should choose.
    assert "image_gateway" not in call


@pytest.mark.asyncio
async def test_generation_failure_never_mutates_or_deletes_the_originating_news_message(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Required behavior: 'A generation failure must not damage the NEWS message or existing meme
    variants.' The handler never edits/deletes the message this callback came from, regardless of
    the orchestrator's own outcome - FakeSession.make_request() itself raises NotImplementedError
    for anything other than AnswerCallbackQuery, so any such attempt would fail this test loudly."""
    event = await _seed_event(db_session)
    _install_fake_orchestrator(
        monkeypatch, db_session, MemeGenerationOutcome(status="image_generation_failed", news_event_id=event.id, error="boom"),
    )
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data(event.id))

    await meme_generate_handler.handle_meme_generate_callback(callback)

    assert all(isinstance(m, AnswerCallbackQuery) for m in session.sent)
    assert len(session.sent) == 1  # only the initial "sent to generation" ack - nothing else


@pytest.mark.asyncio
async def test_repeated_click_calls_orchestration_again_each_time(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handler itself never debounces - repeated-click/new-variant semantics live entirely in
    services/meme_generation_orchestrator.py (already tested there); this only proves the handler
    calls through every time, never short-circuiting a second click on its own."""
    event = await _seed_event(db_session)
    fake = _install_fake_orchestrator(
        monkeypatch, db_session, MemeGenerationOutcome(status="delivered", news_event_id=event.id, task_id=uuid.uuid4()),
    )
    session = FakeSession()

    await meme_generate_handler.handle_meme_generate_callback(_make_callback(session, data=encode_callback_data(event.id)))
    await meme_generate_handler.handle_meme_generate_callback(_make_callback(session, data=encode_callback_data(event.id)))

    assert len(fake.calls) == 2
    assert all(c["news_event_id"] == event.id for c in fake.calls)
