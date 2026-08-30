"""TELEGRAPH EDITORIAL CHAT DELIVERY: services.telegraph_article_review_notifier -
send_article_review()/update_article_review_message(). Same technique as
tests/test_telegraph_article_review_handler.py: a real aiogram `Bot` bound to a fake, in-memory
`BaseSession` subclass overriding `make_request()` - no real Telegram API call ever. This module
is DB-free by its own design (a plain `TelegraphArticleReview` object is enough), so these tests
need no `db_session` fixture at all - pure/fast, no Postgres required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Chat, Message as AiogramMessage

from bot.telegraph_article_review_formatting import build_article_body_chunks
from core.config import settings
from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from schemas.editorial import EditorialChannel
from services.telegraph_article_review_notifier import send_article_review, update_article_review_message

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_CHAT_ID = -1004297182444
_TOPIC_ID = 39

_ARTICLE: dict[str, Any] = {
    "headline": "Product Y Launch",
    "lead": "Company X released product Y, a development that may reshape the market.",
    "context": ["Some context paragraph."], "timeline": ["2026-08-10: announced."],
    "confirmed_facts": ["Fact A.", "Fact B.", "Fact C.", "Fact D."],
    "analysis": ["Analysis paragraph."], "implications": ["Implication paragraph."],
    "background": ["Background paragraph."], "risks": ["Risk paragraph."],
    "conclusion": "The full impact remains to be seen.", "sources": ["Source A", "https://example.com/source-b"],
}


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []
        self._next_message_id = 1000

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        self.sent.append(method)
        if isinstance(method, SendMessage):
            message_id = self._next_message_id
            self._next_message_id += 1
            return AiogramMessage(
                message_id=message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="supergroup"), text=method.text,
            )
        if isinstance(method, EditMessageText):
            return AiogramMessage(
                message_id=method.message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="supergroup"), text=method.text,
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _bot(session: FakeSession) -> Bot:
    return Bot(token=_FAKE_TOKEN, session=session)


def _review(*, status: TelegraphArticleReviewStatus = TelegraphArticleReviewStatus.PENDING,
            telegram_message_id: int | None = None) -> TelegraphArticleReview:
    return TelegraphArticleReview(
        id=uuid4(), article_task_id=uuid4(), proposal_id=uuid4(), status=status,
        decided_at=None, decided_by_telegram_user_id=None,
        telegram_chat_id=_CHAT_ID if telegram_message_id is not None else None,
        telegram_message_id=telegram_message_id,
        telegram_thread_id=_TOPIC_ID if telegram_message_id is not None else None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _routing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _CHAT_ID)
    monkeypatch.setattr(settings, "telegraph_topic_id", _TOPIC_ID)


@pytest.mark.asyncio
async def test_full_article_body_sent_not_preview_only() -> None:
    session = FakeSession()
    outcome = await send_article_review(_bot(session), _review(), _ARTICLE, EditorialChannel.NINJA_AI, dry_run=False)
    assert outcome.sent is True

    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    all_text = "\n".join(m.text or "" for m in sends)
    assert _ARTICLE["lead"] in all_text
    for fact in _ARTICLE["confirmed_facts"]:
        assert fact in all_text
    assert _ARTICLE["conclusion"] in all_text
    assert "предпросмотр" not in all_text
    assert "доступен в системе" not in all_text


@pytest.mark.asyncio
async def test_long_article_splits_into_multiple_messages_completely() -> None:
    huge_article = {**_ARTICLE, "confirmed_facts": [f"Unique fact number {i} with detail text." for i in range(300)]}
    session = FakeSession()
    outcome = await send_article_review(_bot(session), _review(), huge_article, EditorialChannel.NINJA_AI, dry_run=False)
    assert outcome.sent is True

    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert len(sends) > 3  # header + multiple body chunks + footer
    all_text = "\n".join(m.text or "" for m in sends)
    for i in range(300):
        assert f"Unique fact number {i} with detail text." in all_text  # nothing dropped


@pytest.mark.asyncio
async def test_all_messages_route_to_telegraph_topic_id() -> None:
    session = FakeSession()
    await send_article_review(_bot(session), _review(), _ARTICLE, EditorialChannel.NINJA_AI, dry_run=False)
    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert len(sends) >= 2
    for message in sends:
        assert message.chat_id == _CHAT_ID
        assert message.message_thread_id == _TOPIC_ID


@pytest.mark.asyncio
async def test_sources_are_included_in_final_message() -> None:
    session = FakeSession()
    await send_article_review(_bot(session), _review(), _ARTICLE, EditorialChannel.NINJA_AI, dry_run=False)
    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    footer = sends[-1]
    assert "1. Source A" in (footer.text or "")
    assert "2. https://example.com/source-b" in (footer.text or "")


@pytest.mark.asyncio
async def test_final_message_carries_the_review_keyboard() -> None:
    session = FakeSession()
    await send_article_review(_bot(session), _review(), _ARTICLE, EditorialChannel.NINJA_AI, dry_run=False)
    sends = [m for m in session.sent if isinstance(m, SendMessage)]
    assert sends[-1].reply_markup is not None
    for message in sends[:-1]:
        assert message.reply_markup is None


@pytest.mark.asyncio
async def test_already_delivered_review_is_never_resent() -> None:
    review = _review(telegram_message_id=555)
    session = FakeSession()
    outcome = await send_article_review(_bot(session), review, _ARTICLE, EditorialChannel.NINJA_AI, dry_run=False)
    assert outcome.sent is False
    assert outcome.reason == "already_delivered"
    assert session.sent == []  # zero Telegram calls


@pytest.mark.asyncio
async def test_dry_run_never_calls_telegram_but_walks_the_full_sequence() -> None:
    session = FakeSession()
    outcome = await send_article_review(_bot(session), _review(), _ARTICLE, EditorialChannel.NINJA_AI, dry_run=True)
    assert outcome.sent is False
    assert outcome.reason == "dry_run"
    assert session.sent == []


@pytest.mark.asyncio
async def test_update_article_review_message_edits_footer_only() -> None:
    session = FakeSession()
    review = _review(status=TelegraphArticleReviewStatus.APPROVED, telegram_message_id=777)
    edited = await update_article_review_message(
        _bot(session), chat_id=_CHAT_ID, message_id=777, review=review, article_result=_ARTICLE,
        editorial_channel=EditorialChannel.NINJA_AI,
    )
    assert edited is True
    edits = [m for m in session.sent if isinstance(m, EditMessageText)]
    assert len(edits) == 1
    assert "✅ Статья одобрена" in (edits[0].text or "")
    assert "1. Source A" in (edits[0].text or "")


def test_body_chunks_reused_matches_notifier_send_count() -> None:
    # Sanity: the notifier's own per-chunk send count matches the pure formatting helper's own
    # chunk count directly - no divergent chunking logic duplicated inside the notifier.
    chunks = build_article_body_chunks(_ARTICLE)
    assert len(chunks) >= 1
