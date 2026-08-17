"""TELEGRAPH Checkpoint 6: bot.handlers.telegraph_article_review callback handler tests. Same
technique as tests/test_telegraph_shortlist_handler.py: a real aiogram `Bot` bound to a fake,
in-memory `BaseSession` subclass overriding `make_request()` - no real Telegram API call ever.
Real Postgres (db_session fixture) for review rows, fed by a real, fully-completed CP3+CP5 flow
(via _DualGateway) so the linked EditorialTask has a genuine "generate_article" step result.
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
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.telegraph_article_review import handle_article_review_callback
from bot.keyboards.telegraph_article_review import encode_callback_data
from core.config import settings
from database.models.telegraph_article_review import TelegraphArticleReviewStatus
from services.telegraph_article_processor import generate_article_for_researched_proposal
from services.telegraph_article_review_service import TelegraphArticleReviewService, create_article_review
from tests.test_telegraph_article_processor import _DualGateway, _researched_proposal

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_AUTHORIZED_CHAT_ID = -1004297182444
_AUTHORIZED_USER_ID = 99
_HANDLER_SOURCE = Path("bot/handlers/telegraph_article_review.py").read_text(encoding="utf-8")
_NOTIFIER_SOURCE = Path("services/telegraph_article_review_notifier.py").read_text(encoding="utf-8")


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
        if isinstance(method, EditMessageText):
            return AiogramMessage(
                message_id=method.message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="supergroup"), text=method.text,
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

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
            message_id=message_id, date=datetime.now(timezone.utc), chat=chat, text="old review text",
        ).as_(bot)
    callback = CallbackQuery(
        id="cbq1", from_user=User(id=user_id, is_bot=False, first_name="Editor"), chat_instance="ci", data=data,
        message=message,
    ).as_(bot)
    return callback


def _fake_session_factory(db_session: AsyncSession):
    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _CM()


@pytest.fixture(autouse=True)
def _authorized_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _AUTHORIZED_CHAT_ID)


@pytest.fixture(autouse=True)
def _authorized_approver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegraph_approver_user_ids", [_AUTHORIZED_USER_ID])


async def _seed_pending_review(db_session: AsyncSession):
    gateway = _DualGateway()
    proposal, registry = await _researched_proposal(db_session, gateway)
    outcome = await generate_article_for_researched_proposal(db_session, proposal.id, capability_registry=registry)
    assert outcome.status == "generated" and outcome.task_id is not None
    review = await create_article_review(db_session, article_task_id=outcome.task_id, proposal_id=proposal.id)
    return review


@pytest.mark.asyncio
async def test_malformed_callback_data_fails_safely(db_session: AsyncSession) -> None:
    session = FakeSession()
    callback = _make_callback(session, data="not-a-valid-payload")
    await handle_article_review_callback(callback)
    assert len(session.sent) == 1
    assert isinstance(session.sent[0], AnswerCallbackQuery)


@pytest.mark.asyncio
async def test_inaccessible_message_fails_safely(db_session: AsyncSession) -> None:
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()), inaccessible=True)
    await handle_article_review_callback(callback)
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_nonexistent_review_fails_safely(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()))
    await handle_article_review_callback(callback)
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert not any(isinstance(m, EditMessageText) for m in session.sent)


@pytest.mark.asyncio
async def test_unauthorized_chat_cannot_approve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)
    session = FakeSession()
    callback = _make_callback(
        session, data=encode_callback_data("approve", review.id), chat_id=_AUTHORIZED_CHAT_ID + 1,
    )
    await handle_article_review_callback(callback)

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.PENDING


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_approve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)
    session = FakeSession()
    callback = _make_callback(
        session, data=encode_callback_data("approve", review.id), user_id=_AUTHORIZED_USER_ID + 1,
    )
    await handle_article_review_callback(callback)

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.PENDING


@pytest.mark.asyncio
async def test_empty_approver_allowlist_fails_closed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegraph_approver_user_ids", [])
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", review.id))
    await handle_article_review_callback(callback)

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.PENDING


@pytest.mark.asyncio
async def test_authorized_approve_mutates_and_edits_message(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", review.id), message_id=777)
    await handle_article_review_callback(callback)

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.APPROVED
    assert reloaded.decided_by_telegram_user_id == _AUTHORIZED_USER_ID

    edits = [m for m in session.sent if isinstance(m, EditMessageText)]
    assert len(edits) == 1
    assert edits[0].message_id == 777
    assert "✅ Статья одобрена" in (edits[0].text or "")


@pytest.mark.asyncio
async def test_authorized_revise_mutates_status(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("revise", review.id))
    await handle_article_review_callback(callback)

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.NEEDS_REVISION


@pytest.mark.asyncio
async def test_double_tap_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)

    await handle_article_review_callback(
        _make_callback(FakeSession(), data=encode_callback_data("approve", review.id))
    )
    session2 = FakeSession()
    await handle_article_review_callback(
        _make_callback(session2, data=encode_callback_data("approve", review.id))
    )

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.APPROVED
    assert not any(isinstance(m, EditMessageText) for m in session2.sent)


@pytest.mark.asyncio
async def test_opposite_decision_after_final_does_not_flip(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)

    await handle_article_review_callback(
        _make_callback(FakeSession(), data=encode_callback_data("approve", review.id))
    )
    await handle_article_review_callback(
        _make_callback(FakeSession(), data=encode_callback_data("revise", review.id))
    )

    service = TelegraphArticleReviewService(db_session)
    reloaded = await service.get_review(review.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphArticleReviewStatus.APPROVED


@pytest.mark.asyncio
async def test_no_real_telegram_send_beyond_answer_and_edit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_article_review.async_session_factory", _fake_session_factory(db_session),
    )
    review = await _seed_pending_review(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", review.id))
    await handle_article_review_callback(callback)  # would raise if an unrecognized method fired
    assert len(session.sent) == 2


def test_notifier_only_ever_references_telegraph_destination() -> None:
    for forbidden in (
        "EditorialDestination.NEWS", "EditorialDestination.MEME",
        "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS",
    ):
        assert forbidden not in _NOTIFIER_SOURCE, f"unexpected non-TELEGRAPH destination reference: {forbidden}"
    assert "EditorialDestination.TELEGRAPH" in _NOTIFIER_SOURCE


def test_handler_never_references_other_destinations_or_publishing() -> None:
    for forbidden in (
        "EditorialDestination.NEWS", "EditorialDestination.MEME",
        "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS",
        "telegra.ph", "createPage", "createAccount",
    ):
        assert forbidden not in _HANDLER_SOURCE, f"unexpected reference: {forbidden}"


def test_handler_creates_no_next_stage_side_effect() -> None:
    for forbidden in (
        "CapabilityExecutor", "WorkflowRunner", "call_generate", "LLMGateway",
    ):
        assert forbidden not in _HANDLER_SOURCE, f"unexpected next-stage reference: {forbidden}"
