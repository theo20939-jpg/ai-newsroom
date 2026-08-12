"""Tests for bot.handlers.whereami.handle_whereami (Phase 23.0).

Written test-first, mirroring tests/test_news_handler.py's own established, already-proven-
feasible technique exactly: a real aiogram `Message` bound to a real `Bot` whose session is a
fake, in-memory `FakeSession` overriding `make_request()` - zero real network access, zero
Docker/Telegram API contact, no production-code change needed to make this testable.

Five required cases (phase brief §3):
- A: a plain, non-forum chat -> `message_thread_id: none` reported safely.
- B: a forum topic -> the real integer `message_thread_id` is reported.
- C: no secret (bot token, or any other settings value) ever appears in the outgoing reply text.
- D: the diagnostic command has no outbound Telegram effect beyond its own single reply.
- E: existing handlers/routers remain registered and unaffected by adding this one.
"""
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.send_message import SendMessage
from aiogram.types import Chat
from aiogram.types import Message as AiogramMessage

from bot.handlers.whereami import handle_whereami

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class FakeSession(BaseSession):
    """Records every outgoing method, returns a canned Message response - zero network access.
    Byte-for-byte the same shape as tests/test_news_handler.py::FakeSession (not imported from
    there to keep this diagnostic test file fully standalone/removable alongside the handler
    itself, matching bot/handlers/whereami.py's own "temporary by design" scope)."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        if isinstance(method, SendMessage):
            self.sent.append(method)
            return AiogramMessage(
                message_id=len(self.sent), date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"), text=method.text,
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _make_message(
    session: FakeSession, *, chat_id: int, chat_type: str = "private", is_forum: bool = False,
    is_topic_message: bool = False, message_thread_id: int | None = None,
) -> AiogramMessage:
    bot = Bot(token=_FAKE_TOKEN, session=session)
    chat = Chat(id=chat_id, type=chat_type, is_forum=is_forum)
    message = AiogramMessage(
        message_id=1, date=datetime.now(timezone.utc), chat=chat,
        is_topic_message=is_topic_message, message_thread_id=message_thread_id,
    )
    return message.as_(bot)


# ---------------------------------------------------------------------------
# CASE A - plain, non-forum chat -> message_thread_id: none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_a_non_forum_chat_reports_message_thread_id_none() -> None:
    session = FakeSession()
    message = _make_message(session, chat_id=42, chat_type="private", is_forum=False, message_thread_id=None)

    await handle_whereami(message)

    assert len(session.sent) == 1
    reply_text = session.sent[0].text
    assert "chat_id: 42" in reply_text
    assert "is_forum: false" in reply_text
    assert "message_thread_id: none" in reply_text


# ---------------------------------------------------------------------------
# CASE B - forum topic -> the real integer message_thread_id is reported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_b_forum_topic_reports_real_message_thread_id() -> None:
    session = FakeSession()
    message = _make_message(
        session, chat_id=-1001234567890, chat_type="supergroup", is_forum=True,
        is_topic_message=True, message_thread_id=987,
    )

    await handle_whereami(message)

    reply_text = session.sent[0].text
    assert "chat_id: -1001234567890" in reply_text
    assert "is_forum: true" in reply_text
    assert "message_thread_id: 987" in reply_text


@pytest.mark.asyncio
async def test_case_b_different_topics_report_different_thread_ids() -> None:
    """Sanity check for the manual ID-collection workflow itself: two distinct topics in the same
    chat must be distinguishable by their reported message_thread_id alone."""
    session = FakeSession()
    news_message = _make_message(
        session, chat_id=-100999, chat_type="supergroup", is_forum=True, is_topic_message=True, message_thread_id=11,
    )
    meme_message = _make_message(
        session, chat_id=-100999, chat_type="supergroup", is_forum=True, is_topic_message=True, message_thread_id=22,
    )

    await handle_whereami(news_message)
    await handle_whereami(meme_message)

    assert "message_thread_id: 11" in session.sent[0].text
    assert "message_thread_id: 22" in session.sent[1].text


# ---------------------------------------------------------------------------
# CASE C - no secret ever appears in the outgoing reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_c_no_bot_token_or_settings_secret_in_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from core.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("real-secret-token-value"))
    monkeypatch.setattr(settings, "postgres_password", SecretStr("real-db-password"))

    session = FakeSession()
    message = _make_message(session, chat_id=-100999, chat_type="supergroup", is_forum=True, message_thread_id=11)

    await handle_whereami(message)

    reply_text = session.sent[0].text
    assert _FAKE_TOKEN not in reply_text
    assert "real-secret-token-value" not in reply_text
    assert "real-db-password" not in reply_text
    assert "token" not in reply_text.lower()


@pytest.mark.asyncio
async def test_case_c_reply_contains_only_the_four_documented_lines() -> None:
    """No raw Update/Message dump, no extra fields beyond the module docstring's documented
    scope - the reply is exactly the header, a blank line, and three labeled fields."""
    session = FakeSession()
    message = _make_message(session, chat_id=7, chat_type="private", is_forum=False, message_thread_id=None)

    await handle_whereami(message)

    lines = session.sent[0].text.split("\n")
    assert lines == ["TELEGRAM ROUTE DEBUG", "", "chat_id: 7", "is_forum: false", "message_thread_id: none"]


# ---------------------------------------------------------------------------
# CASE D - no outbound effect beyond the single reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_d_exactly_one_outbound_call_and_it_is_send_message() -> None:
    session = FakeSession()
    message = _make_message(session, chat_id=42, message_thread_id=None)

    await handle_whereami(message)

    assert len(session.sent) == 1
    assert isinstance(session.sent[0], SendMessage)


# ---------------------------------------------------------------------------
# CASE E - existing handlers/routers remain unaffected
# ---------------------------------------------------------------------------


def test_case_e_root_router_includes_whereami_router_alongside_every_existing_router() -> None:
    from bot.handlers import router as root_router
    from bot.handlers.digest import router as digest_router
    from bot.handlers.image_preview import router as image_preview_router
    from bot.handlers.meme_preview import router as meme_preview_router
    from bot.handlers.news import router as news_router
    from bot.handlers.settings import router as settings_router
    from bot.handlers.start import router as start_router
    from bot.handlers.status import router as status_router
    from bot.handlers.whereami import router as whereami_router

    names = [sub.name for sub in root_router.sub_routers]
    for existing_router in (
        start_router, news_router, digest_router, status_router, settings_router,
        image_preview_router, meme_preview_router,
    ):
        assert existing_router in root_router.sub_routers
    assert whereami_router in root_router.sub_routers
    assert "whereami" in names


def test_case_e_bot_main_still_registers_root_router_and_polls() -> None:
    import ast
    import inspect

    import bot.main as bot_main

    source = inspect.getsource(bot_main.main)
    tree = ast.parse(source)
    calls = [
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "include_router" in calls
    assert "start_polling" in calls
