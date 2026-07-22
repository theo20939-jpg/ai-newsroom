"""Tests for bot.handlers.news.handle_news (Phase 11 M3/M4, docs/
phase11_telegram_editorial_inbox_architecture_contract.md §9/§16/§24).

This is this repository's first bot-handler test. Network-free: constructs an aiogram `Message`
bound to a `Bot` whose session is a fake, in-memory `aiogram.client.session.base.BaseSession`
subclass overriding `make_request()` - no real Telegram API call, no live network access, no
production-code change (this technique was independently proven feasible against the real,
installed `aiogram==3.29.1` during the Phase 11 Implementation Plan audit before being used here).

The unit-level tests (top of file) mock the DB session and query-service call at the
`bot.handlers.news` module boundary (`async_session_factory`, `get_latest_editorial_cards`) - they
test the handler's own orchestration logic (which calls it makes, in which order, how it reacts to
each failure mode), not the query/renderer behavior already proven by
tests/test_editorial_inbox_service.py and tests/test_editorial_card_formatting.py.

The M4 integration tests (bottom of file, "--- M4" marker) use none of those mocks except the
Telegram transport itself (still the same FakeSession - only the external network boundary is
faked, per Contract/Plan M4's own scope) - real `db_session`, real
services.editorial_inbox_service.get_latest_editorial_cards, real bot.formatting.render_editorial_card,
real bot.handlers.news.handle_news, proving the whole internal Phase 11 stack together.
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.methods.send_message import SendMessage
from aiogram.types import Chat
from aiogram.types import Message as AiogramMessage
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatting import CardTooLongError, _telegram_utf16_length
from bot.handlers.news import EMPTY_INBOX_TEXT, GENERIC_ERROR_TEXT, handle_news
from database.models.content_draft import ContentDraft
from database.models.editorial_task import TaskStatus
from schemas.editorial_inbox import EditorialInboxCard
from tests.test_editorial_inbox_service import _eligible_draft, _make_draft, _make_event, _make_source, _make_task

_TESTS_ROOT = Path(__file__).resolve().parent
_HANDLER_FILE = _TESTS_ROOT.parent / "bot" / "handlers" / "news.py"

_FORBIDDEN_IMPORTS = (
    "workflows.runner",
    "capabilities.executor",
    "capabilities.research_capability",
    "capabilities.intelligence_capability",
    "capabilities.copywriting_capability",
    "capabilities.quality_capability",
    "capabilities.scoring_capability",
    "scripts.run_content_generation",
)

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class FakeSession(BaseSession):
    """Records every outgoing method, returns canned Message responses - zero network access."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []
        self.fail_on_text: str | None = None

    async def close(self) -> None:
        pass

    async def make_request(
        self, bot: Bot, method: TelegramMethod, timeout: int | None = None
    ) -> object:
        if isinstance(method, SendMessage):
            if self.fail_on_text is not None and method.text == self.fail_on_text:
                raise TelegramBadRequest(method=method, message="Bad Request: message is too long")
            self.sent.append(method)
            return AiogramMessage(
                message_id=len(self.sent),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


class _FakeSessionCM:
    """Mimics `async_session_factory()`'s `async with ... as session:` shape without a real DB
    connection - the handler never touches the yielded object directly when the query-service call
    is itself mocked (as every test below does)."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _fake_session_factory() -> _FakeSessionCM:
    return _FakeSessionCM()


def _make_message(session: FakeSession, *, is_topic_message: bool = False, message_thread_id: int | None = None, chat_type: str = "private") -> AiogramMessage:
    bot = Bot(token=_FAKE_TOKEN, session=session)
    chat = Chat(id=42, type=chat_type)
    message = AiogramMessage(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=chat,
        is_topic_message=is_topic_message,
        message_thread_id=message_thread_id,
    )
    return message.as_(bot)


def _card(**overrides: object) -> EditorialInboxCard:
    defaults: dict[str, object] = dict(
        draft_id=uuid4(),
        draft_title="Title",
        draft_body="Body",
        hashtags=None,
        draft_created_at=datetime.now(timezone.utc),
        news_title="News",
        news_category="TECH",
        news_url=None,
        news_published_at=None,
    )
    defaults.update(overrides)
    return EditorialInboxCard(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_calls_query_service_with_limit_five() -> None:
    session = FakeSession()
    message = _make_message(session)
    mock_get_cards = AsyncMock(return_value=[])

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", mock_get_cards),
    ):
        await handle_news(message)

    mock_get_cards.assert_awaited_once()
    assert mock_get_cards.call_args.kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_empty_inbox_sends_frozen_empty_message() -> None:
    session = FakeSession()
    message = _make_message(session)

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", AsyncMock(return_value=[])),
    ):
        await handle_news(message)

    assert len(session.sent) == 1
    assert session.sent[0].text == EMPTY_INBOX_TEXT


@pytest.mark.asyncio
async def test_sends_one_message_per_card() -> None:
    session = FakeSession()
    message = _make_message(session)
    cards = [_card(), _card(), _card()]

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", AsyncMock(return_value=cards)),
    ):
        await handle_news(message)

    assert len(session.sent) == 3


@pytest.mark.asyncio
async def test_db_service_failure_sends_generic_error_never_raw_exception() -> None:
    session = FakeSession()
    message = _make_message(session)

    async def _raise(*_args: object, **_kwargs: object) -> list[EditorialInboxCard]:
        raise RuntimeError("db exploded - connection refused at secret-internal-host:5432")

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", _raise),
    ):
        await handle_news(message)

    assert len(session.sent) == 1
    assert session.sent[0].text == GENERIC_ERROR_TEXT
    assert "secret-internal-host" not in session.sent[0].text


@pytest.mark.asyncio
async def test_card_render_failure_is_skipped_remaining_cards_still_sent() -> None:
    session = FakeSession()
    message = _make_message(session)
    cards = [_card(draft_title="one"), _card(draft_title="two"), _card(draft_title="three")]

    def _render(card: EditorialInboxCard) -> str:
        if card.draft_title == "two":
            raise CardTooLongError("too long even with empty body")
        return f"rendered:{card.draft_title}"

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", AsyncMock(return_value=cards)),
        patch("bot.handlers.news.render_editorial_card", side_effect=_render),
    ):
        await handle_news(message)

    assert [m.text for m in session.sent] == ["rendered:one", "rendered:three"]


@pytest.mark.asyncio
async def test_telegram_send_failure_is_skipped_remaining_cards_still_sent() -> None:
    session = FakeSession()
    session.fail_on_text = "SECOND"
    message = _make_message(session)
    cards = [_card(draft_title="FIRST"), _card(draft_title="SECOND"), _card(draft_title="THIRD")]

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", AsyncMock(return_value=cards)),
        patch("bot.handlers.news.render_editorial_card", side_effect=lambda c: c.draft_title),
    ):
        await handle_news(message)

    assert [m.text for m in session.sent] == ["FIRST", "THIRD"]


@pytest.mark.asyncio
async def test_forum_topic_message_thread_id_is_preserved_automatically() -> None:
    """Contract §10/finding F-3: message.answer() under the pinned aiogram==3.29.1 already,
    automatically threads message_thread_id - the handler must not override or strip it."""
    session = FakeSession()
    message = _make_message(
        session, is_topic_message=True, message_thread_id=777, chat_type="supergroup"
    )

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", AsyncMock(return_value=[])),
    ):
        await handle_news(message)

    assert session.sent[0].message_thread_id == 777


@pytest.mark.asyncio
async def test_private_chat_reply_lands_in_invocation_chat() -> None:
    session = FakeSession()
    message = _make_message(session, chat_type="private")

    with (
        patch("bot.handlers.news.async_session_factory", _fake_session_factory),
        patch("bot.handlers.news.get_latest_editorial_cards", AsyncMock(return_value=[])),
    ):
        await handle_news(message)

    assert session.sent[0].chat_id == 42


def test_no_ai_or_workflow_import_in_handler() -> None:
    """Mechanical import-boundary check (mirrors tests/test_capability_testing_convention.py's
    AST-based approach)."""
    tree = ast.parse(_HANDLER_FILE.read_text(encoding="utf-8"), filename=str(_HANDLER_FILE))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            imported.add(node.module)

    for forbidden in _FORBIDDEN_IMPORTS:
        matching = {name for name in imported if name == forbidden or name.startswith(forbidden + ".")}
        assert not matching, f"bot/handlers/news.py imports forbidden module(s): {matching}"


# --- M4: integrated real-stack verification (docs/phase11_m4_integrated_verification_report.md) --
#
# Real db_session -> real get_latest_editorial_cards -> real render_editorial_card -> real
# handle_news. Only the external Telegram transport is faked (same FakeSession as above). No
# OpenAI, no WorkflowRunner, no ContentDraft generation - fixture rows are constructed directly at
# the ORM level, exactly as tests/test_editorial_inbox_service.py's own M1 tests already do.


class _RealSessionCM:
    """Mimics `async_session_factory()`'s shape, but yields the real, test-fixture-backed
    `db_session` (SAVEPOINT-rolled-back) instead of opening a second, independent connection."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_integrated_stack_sends_safely_escaped_html_within_utf16_limit(
    db_session: AsyncSession,
) -> None:
    source = await _make_source(db_session)
    event = await _make_event(
        db_session, source, title="<script>alert(1)</script> & Title", url="https://x.com/a?b=1&c=2"
    )
    task = await _make_task(db_session, event, status=TaskStatus.COMPLETED)
    draft = await _make_draft(db_session, task, title="Draft <b>title</b>", body="Body & text")

    session = FakeSession()
    message = _make_message(session)

    with patch("bot.handlers.news.async_session_factory", lambda: _RealSessionCM(db_session)):
        await handle_news(message)

    matches = [m for m in session.sent if "Draft" in (m.text or "")]
    assert len(matches) == 1
    text = matches[0].text
    assert draft.title == "Draft <b>title</b>"  # sanity: this is the row we just created
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text
    assert "b=1&amp;c=2" in text  # news_url's literal '&' is escaped, never raw
    assert _telegram_utf16_length(text) <= 4096


@pytest.mark.asyncio
async def test_integrated_stack_respects_ordering_and_limit(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    created_drafts = []
    for i in range(6):
        draft, _event = await _eligible_draft(
            db_session, created_at=now - timedelta(minutes=(5 - i)), title=f"integrated-{i}"
        )
        created_drafts.append(draft)

    session = FakeSession()
    message = _make_message(session)

    with patch("bot.handlers.news.async_session_factory", lambda: _RealSessionCM(db_session)):
        await handle_news(message)

    assert len(session.sent) == 5  # limit enforced even though 6+ eligible rows exist

    our_titles_in_order = [
        m.text.split("\n\n")[1].removeprefix("<b>").removesuffix("</b>")
        for m in session.sent
        if "integrated-" in (m.text or "")
    ]
    # Newest-first: integrated-5 (created most recently) must precede integrated-4, etc.
    assert our_titles_in_order == sorted(our_titles_in_order, reverse=True)


@pytest.mark.asyncio
async def test_integrated_stack_empty_state(db_session: AsyncSession) -> None:
    # Scoped to this test's own SAVEPOINT-rolled-back transaction only (mirrors
    # tests/test_editorial_inbox_service.py::test_empty_result_returns_empty_list) - never
    # committed, never destructive to any pre-existing row.
    await db_session.execute(delete(ContentDraft))

    session = FakeSession()
    message = _make_message(session)

    with patch("bot.handlers.news.async_session_factory", lambda: _RealSessionCM(db_session)):
        await handle_news(message)

    assert len(session.sent) == 1
    assert session.sent[0].text == EMPTY_INBOX_TEXT


@pytest.mark.asyncio
async def test_integrated_stack_causes_zero_db_mutation(db_session: AsyncSession) -> None:
    draft, _event = await _eligible_draft(db_session, title="mutation-check")

    before = (await db_session.get(ContentDraft, draft.id))
    before_snapshot = (before.title, before.body, before.status, before.updated_at)

    session = FakeSession()
    message = _make_message(session)

    with patch("bot.handlers.news.async_session_factory", lambda: _RealSessionCM(db_session)):
        await handle_news(message)

    after = await db_session.get(ContentDraft, draft.id)
    after_snapshot = (after.title, after.body, after.status, after.updated_at)
    assert after_snapshot == before_snapshot
