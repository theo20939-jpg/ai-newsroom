"""TELEGRAPH Checkpoint 2: bot.handlers.telegraph_shortlist callback handler tests. Same
technique as tests/test_image_preview_handler.py: a real aiogram `Bot` bound to a fake, in-memory
`BaseSession` subclass overriding `make_request()` - no real Telegram API call, no live network
access, ever. Real Postgres (db_session fixture, rolled back per test) for proposal rows.
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

from bot.handlers.telegraph_shortlist import handle_telegraph_shortlist_callback
from bot.keyboards.telegraph_shortlist import encode_callback_data
from core.config import settings
from database.models.telegraph_shortlist import TelegraphProposalStatus
from services.telegraph_shortlist_service import TelegraphShortlistService, create_telegraph_shortlist
from tests.test_telegraph_shortlist_service import _require_shortlist_tables, _seed_story_with_events

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_AUTHORIZED_CHAT_ID = -1004297182444
_HANDLER_SOURCE = Path("bot/handlers/telegraph_shortlist.py").read_text(encoding="utf-8")
_NOTIFIER_SOURCE = Path("services/telegraph_shortlist_notifier.py").read_text(encoding="utf-8")


class FakeSession(BaseSession):
    """Records every outgoing method, returns canned responses - zero network access (mirrors
    tests/test_image_preview_handler.py::FakeSession exactly)."""

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
    message_id: int = 500, inaccessible: bool = False, user_id: int = 99,
) -> CallbackQuery:
    bot = Bot(token=_FAKE_TOKEN, session=session)
    chat = Chat(id=chat_id, type="supergroup")
    if inaccessible:
        message: object = InaccessibleMessage(chat=chat, message_id=message_id, date=0)
    else:
        message = AiogramMessage(
            message_id=message_id, date=datetime.now(timezone.utc), chat=chat, text="old shortlist text",
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


_AUTHORIZED_USER_ID = 99  # matches _make_callback()'s default from_user=User(id=99, ...)


@pytest.fixture(autouse=True)
def _authorized_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _AUTHORIZED_CHAT_ID)


@pytest.fixture(autouse=True)
def _authorized_approver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default allowlist for every test in this file - matches _make_callback()'s default
    from_user id (99). Individual tests override this (to [] or to a list excluding 99) to prove
    the fail-closed/unauthorized-user paths."""
    monkeypatch.setattr(settings, "telegraph_approver_user_ids", [_AUTHORIZED_USER_ID])


async def _seed_pending_proposal(db_session: AsyncSession):
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Handler test story")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    return result.proposals[0]


# ---------------------------------------------------------------------------------------------
# Malformed / missing (required test 20, plus nonexistent-proposal at handler level, test 19)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_20_malformed_callback_data_fails_safely(db_session: AsyncSession) -> None:
    session = FakeSession()
    callback = _make_callback(session, data="not-a-valid-payload")

    await handle_telegraph_shortlist_callback(callback)

    assert len(session.sent) == 1
    assert isinstance(session.sent[0], AnswerCallbackQuery)


@pytest.mark.asyncio
async def test_inaccessible_message_fails_safely(db_session: AsyncSession) -> None:
    session = FakeSession()
    callback = _make_callback(
        session, data=encode_callback_data("approve", uuid.uuid4()), inaccessible=True,
    )

    await handle_telegraph_shortlist_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_19_nonexistent_proposal_fails_safely_at_handler_level(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    await _require_shortlist_tables(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", uuid.uuid4()))

    await handle_telegraph_shortlist_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    # Crucially: no EditMessageText call - nothing was mutated or re-rendered.
    assert not any(isinstance(m, EditMessageText) for m in session.sent)


# ---------------------------------------------------------------------------------------------
# Authorization (required tests 17-18)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_17_unauthorized_chat_cannot_approve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    wrong_chat_id = _AUTHORIZED_CHAT_ID + 1
    callback = _make_callback(
        session, data=encode_callback_data("approve", proposal.id), chat_id=wrong_chat_id,
    )

    await handle_telegraph_shortlist_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert not any(isinstance(m, EditMessageText) for m in session.sent)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.PENDING  # never mutated


@pytest.mark.asyncio
async def test_18_unauthorized_chat_cannot_reject(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    wrong_chat_id = _AUTHORIZED_CHAT_ID + 1
    callback = _make_callback(
        session, data=encode_callback_data("reject", proposal.id), chat_id=wrong_chat_id,
    )

    await handle_telegraph_shortlist_callback(callback)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.PENDING  # never mutated


@pytest.mark.asyncio
async def test_unconfigured_chat_id_authorizes_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", None)
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", proposal.id))

    await handle_telegraph_shortlist_callback(callback)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.PENDING


# ---------------------------------------------------------------------------------------------
# Per-user approver allowlist (security-correction: correct chat is no longer sufficient)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_chat_but_unauthorized_user_cannot_approve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    # Correct chat, but this user id is not in the (autouse-fixture) allowlist [_AUTHORIZED_USER_ID].
    callback = _make_callback(
        session, data=encode_callback_data("approve", proposal.id), user_id=_AUTHORIZED_USER_ID + 1,
    )

    await handle_telegraph_shortlist_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert not any(isinstance(m, EditMessageText) for m in session.sent)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.PENDING  # never mutated
    assert reloaded.decided_by_telegram_user_id is None


@pytest.mark.asyncio
async def test_correct_chat_but_unauthorized_user_cannot_reject(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    callback = _make_callback(
        session, data=encode_callback_data("reject", proposal.id), user_id=_AUTHORIZED_USER_ID + 1,
    )

    await handle_telegraph_shortlist_callback(callback)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.PENDING  # never mutated


@pytest.mark.asyncio
async def test_empty_approver_allowlist_fails_closed_even_in_correct_chat(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The checkpoint's own explicit requirement: an empty/unconfigured approver list must NOT
    mean "everyone in the newsroom chat" - it must mean nobody, even the (correctly chat-scoped)
    default test user."""
    monkeypatch.setattr(settings, "telegraph_approver_user_ids", [])
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", proposal.id))

    await handle_telegraph_shortlist_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    assert not any(isinstance(m, EditMessageText) for m in session.sent)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.PENDING


# ---------------------------------------------------------------------------------------------
# Authorized decision + message edit (required test 29), idempotency at handler level
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_approve_mutates_and_edits_the_existing_message(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", proposal.id), message_id=777)

    await handle_telegraph_shortlist_callback(callback)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.APPROVED

    edits = [m for m in session.sent if isinstance(m, EditMessageText)]
    assert len(edits) == 1  # required test 29: edits the SAME message, never sends a new one
    assert edits[0].message_id == 777
    assert "✅ Одобрено" in (edits[0].text or "")

    answers = [m for m in session.sent if isinstance(m, AnswerCallbackQuery)]
    assert len(answers) == 1  # exactly one callback acknowledgement, no extra chat spam


@pytest.mark.asyncio
async def test_authorized_approve_persists_decided_by_telegram_user_id(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    callback = _make_callback(
        session, data=encode_callback_data("approve", proposal.id), user_id=_AUTHORIZED_USER_ID,
    )

    await handle_telegraph_shortlist_callback(callback)

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.decided_by_telegram_user_id == _AUTHORIZED_USER_ID


@pytest.mark.asyncio
async def test_double_tap_by_different_authorized_users_preserves_original_decider(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegraph_approver_user_ids", [_AUTHORIZED_USER_ID, 200])
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)

    await handle_telegraph_shortlist_callback(
        _make_callback(
            FakeSession(), data=encode_callback_data("approve", proposal.id), user_id=_AUTHORIZED_USER_ID,
        )
    )
    await handle_telegraph_shortlist_callback(
        _make_callback(FakeSession(), data=encode_callback_data("approve", proposal.id), user_id=200)
    )

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.decided_by_telegram_user_id == _AUTHORIZED_USER_ID  # first decider preserved


@pytest.mark.asyncio
async def test_double_tap_approve_is_idempotent_at_handler_level(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)

    session1 = FakeSession()
    await handle_telegraph_shortlist_callback(
        _make_callback(session1, data=encode_callback_data("approve", proposal.id))
    )
    session2 = FakeSession()
    await handle_telegraph_shortlist_callback(
        _make_callback(session2, data=encode_callback_data("approve", proposal.id))
    )

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.APPROVED
    # Second tap acknowledges but does not re-edit the message (nothing changed to render).
    assert not any(isinstance(m, EditMessageText) for m in session2.sent)


@pytest.mark.asyncio
async def test_opposite_decision_after_final_does_not_flip_status(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)

    await handle_telegraph_shortlist_callback(
        _make_callback(FakeSession(), data=encode_callback_data("approve", proposal.id))
    )
    await handle_telegraph_shortlist_callback(
        _make_callback(FakeSession(), data=encode_callback_data("reject", proposal.id))
    )

    service = TelegraphShortlistService(db_session)
    reloaded = await service.get_proposal(proposal.id)
    assert reloaded is not None
    assert reloaded.status == TelegraphProposalStatus.APPROVED  # unchanged, per documented policy


# ---------------------------------------------------------------------------------------------
# No real Telegram send anywhere (required test 39), destination safety (required test 30)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_39_no_real_telegram_send_occurs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FakeSession.make_request() raises NotImplementedError for any method it doesn't
    explicitly recognize (AnswerCallbackQuery/EditMessageText only) - if this handler ever called
    a real send method (SendMessage, etc.) instead of editing in place, this test would fail
    loudly rather than silently passing."""
    monkeypatch.setattr(
        "bot.handlers.telegraph_shortlist.async_session_factory", _fake_session_factory(db_session),
    )
    proposal = await _seed_pending_proposal(db_session)
    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("approve", proposal.id))

    await handle_telegraph_shortlist_callback(callback)  # would raise if an unrecognized method fired

    assert len(session.sent) == 2  # exactly EditMessageText + AnswerCallbackQuery, nothing else


def test_30_notifier_only_ever_references_the_telegraph_destination() -> None:
    for forbidden in (
        "EditorialDestination.NEWS", "EditorialDestination.MEME",
        "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS",
    ):
        assert forbidden not in _NOTIFIER_SOURCE, f"unexpected non-TELEGRAPH destination reference: {forbidden}"
    assert "EditorialDestination.TELEGRAPH" in _NOTIFIER_SOURCE


def test_handler_never_references_other_destinations_either() -> None:
    for forbidden in (
        "EditorialDestination.NEWS", "EditorialDestination.MEME",
        "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS",
    ):
        assert forbidden not in _HANDLER_SOURCE, f"unexpected non-TELEGRAPH destination reference: {forbidden}"


# ---------------------------------------------------------------------------------------------
# No-next-stage-side-effect boundary (structural, complements test_telegraph_shortlist_service.py)
# ---------------------------------------------------------------------------------------------


def test_approve_creates_no_article_workflow_reference_in_handler_source() -> None:
    for forbidden in (
        "TELEGRAPH_ARTICLE", "WorkflowRunner", "call_generate", "run_content_generation_for_event",
        "acquire_article(", "safe_fetch",
    ):
        assert forbidden not in _HANDLER_SOURCE, f"unexpected next-stage reference: {forbidden}"
