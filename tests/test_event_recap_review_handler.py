"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: bot.handlers.event_recap_review callback
handler tests. Same technique as tests/test_telegraph_article_review_handler.py: a real aiogram
`Bot` bound to a fake, in-memory `BaseSession` subclass overriding `make_request()` - no real
Telegram API call ever, no database of any kind (this handler never touches one - see its own
docstring for why).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage
from aiogram.types import Message as AiogramMessage
from aiogram.types import User

from bot.handlers.event_recap_review import handle_event_recap_review_callback
from bot.keyboards.event_recap_review import encode_callback_data
from core.config import settings

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_AUTHORIZED_CHAT_ID = -1004297182444
_AUTHORIZED_USER_ID = 99
_HANDLER_SOURCE = Path("bot/handlers/event_recap_review.py").read_text(encoding="utf-8")
_NOTIFIER_SOURCE = Path("services/event_recap_review_notifier.py").read_text(encoding="utf-8")


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
        raise NotImplementedError(f"FakeSession cannot handle {type(method)} - this handler must never send it")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _make_callback(
    session: FakeSession, *, data: str, chat_id: int = _AUTHORIZED_CHAT_ID,
    inaccessible: bool = False, user_id: int = _AUTHORIZED_USER_ID,
) -> CallbackQuery:
    bot = Bot(token=_FAKE_TOKEN, session=session)
    chat = Chat(id=chat_id, type="supergroup")
    if inaccessible:
        message: object = InaccessibleMessage(chat=chat, message_id=500, date=0)
    else:
        message = AiogramMessage(
            message_id=500, date=datetime.now(timezone.utc), chat=chat, text="recap preview",
        ).as_(bot)
    return CallbackQuery(
        id="cbq1", from_user=User(id=user_id, is_bot=False, first_name="Editor"), chat_instance="ci", data=data,
        message=message,
    ).as_(bot)


@pytest.fixture(autouse=True)
def _authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _AUTHORIZED_CHAT_ID)
    monkeypatch.setattr(settings, "telegraph_approver_user_ids", [_AUTHORIZED_USER_ID])


@pytest.mark.asyncio
async def test_malformed_callback_data_fails_safely() -> None:
    session = FakeSession()
    callback = _make_callback(session, data="not-a-valid-payload")
    await handle_event_recap_review_callback(callback)
    assert len(session.sent) == 1
    assert isinstance(session.sent[0], AnswerCallbackQuery)


@pytest.mark.asyncio
async def test_inaccessible_message_fails_safely() -> None:
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()), inaccessible=True)
    await handle_event_recap_review_callback(callback)
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_unauthorized_chat_rejected() -> None:
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()), chat_id=-999)
    await handle_event_recap_review_callback(callback)
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_unauthorized_user_rejected() -> None:
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()), user_id=1)
    await handle_event_recap_review_callback(callback)
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_authorized_click_only_acknowledges_never_edits_the_message() -> None:
    """The core Phase C.1 contract: a valid, authorized click gets ONE AnswerCallbackQuery and
    nothing else - no EditMessageText (there is no persisted decision to re-render), no DB write
    (this handler holds no session at all)."""
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()))

    await handle_event_recap_review_callback(callback)  # would raise if an unrecognized method fired

    assert len(session.sent) == 1
    answer = session.sent[0]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is not True
    assert not any(isinstance(m, EditMessageText) for m in session.sent)


@pytest.mark.asyncio
async def test_authorized_reject_click_also_only_acknowledges() -> None:
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("reject", uuid.uuid4()))
    await handle_event_recap_review_callback(callback)
    assert len(session.sent) == 1
    assert isinstance(session.sent[0], AnswerCallbackQuery)


def test_handler_never_references_publishing_or_other_destinations() -> None:
    """The module's own docstring legitimately DISCUSSES "publishable" in prose (explaining it is
    never touched, and never reachable, since this handler never loads a candidate object at all
    - see test_handler_creates_no_next_stage_or_persistence_side_effect below, which structurally
    proves no candidate/session ever enters this module) - so that word is deliberately not
    checked here; these checks target unambiguous code-level references instead."""
    for forbidden in (
        "EditorialDestination.NEWS", "EditorialDestination.MEME",
        "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS",
        "ContentDraft",
    ):
        assert forbidden not in _HANDLER_SOURCE, f"unexpected reference: {forbidden}"


def test_handler_creates_no_next_stage_or_persistence_side_effect() -> None:
    """No DB session, no ORM model, no workflow/capability machinery - matches the module's own
    explicit "no persistence" contract (see its own docstring for why)."""
    for forbidden in (
        "CapabilityExecutor", "WorkflowRunner", "call_generate", "LLMGateway",
        "AsyncSession", "session.add", "session.commit", "async_session_factory",
    ):
        assert forbidden not in _HANDLER_SOURCE, f"unexpected reference: {forbidden}"


def test_notifier_only_ever_references_telegraph_destination_by_default() -> None:
    for forbidden in ("EditorialDestination.NEWS", "EditorialDestination.MEME", "EditorialDestination.INSTAGRAM"):
        assert forbidden not in _NOTIFIER_SOURCE, f"unexpected non-default destination reference: {forbidden}"
    assert "EditorialDestination.TELEGRAPH" in _NOTIFIER_SOURCE
