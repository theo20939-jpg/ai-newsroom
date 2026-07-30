"""Tests for bot.handlers.image_preview's Phase 16 M6 callback handler (docs/
phase16_m6_telegram_editorial_preview_report.md §6/§8/§9). Same technique as
tests/test_news_handler.py: a `Bot` bound to a fake, in-memory `BaseSession` subclass overriding
`make_request()` - no real Telegram API call, no live network access. Real Postgres (db_session
fixture, rolled back per test) for candidate rows + a tmp_path-backed LocalImageStorage for
resolvable bytes - no test in this file sends a real Telegram message or calls any external API.
"""
import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageCaption,
    EditMessageMedia,
    EditMessageText,
    SendMessage,
    SendPhoto,
)
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage
from aiogram.types import Message as AiogramMessage
from aiogram.types import PhotoSize, User
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.image_candidate_record import ImageCandidateRecord, ImageEditorDecision, ImageStorageStatus
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from bot.handlers.image_preview import handle_image_preview_callback
from bot.keyboards.image_preview import encode_callback_data
from integrations.storage.image_storage import LocalImageStorage
from services import image_persistence

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_DATA = b"fake-stored-bytes-for-handler-tests"
_SHA256 = hashlib.sha256(_DATA).hexdigest()


class FakeSession(BaseSession):
    """Records every outgoing method, returns canned responses - zero network access."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []
        self._next_message_id = 100

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        self.sent.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, DeleteMessage):
            return True
        if isinstance(method, SendPhoto):
            self._next_message_id += 1
            return AiogramMessage(
                message_id=self._next_message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"), caption=method.caption,
                photo=[PhotoSize(file_id=f"fake-file-id-{self._next_message_id}", file_unique_id="u", width=10, height=10)],
            )
        if isinstance(method, SendMessage):
            self._next_message_id += 1
            return AiogramMessage(
                message_id=self._next_message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"), text=method.text,
            )
        if isinstance(method, EditMessageMedia):
            file_id = method.media.media if isinstance(method.media.media, str) else "fake-file-id-uploaded"
            return AiogramMessage(
                message_id=method.message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"), caption=method.media.caption,
                photo=[PhotoSize(file_id=file_id, file_unique_id="u", width=10, height=10)],
            )
        if isinstance(method, EditMessageCaption):
            return AiogramMessage(
                message_id=method.message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"), caption=method.caption,
            )
        if isinstance(method, EditMessageText):
            return AiogramMessage(
                message_id=method.message_id, date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"), text=method.text,
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _make_callback(
    session: FakeSession, *, data: str, has_photo: bool = False, message_id: int = 1, inaccessible: bool = False,
) -> CallbackQuery:
    bot = Bot(token=_FAKE_TOKEN, session=session)
    chat = Chat(id=42, type="private")
    if inaccessible:
        message: object = InaccessibleMessage(chat=chat, message_id=message_id, date=0)
    else:
        photo = [PhotoSize(file_id="original-file-id", file_unique_id="u", width=10, height=10)] if has_photo else None
        message = AiogramMessage(
            message_id=message_id, date=datetime.now(timezone.utc), chat=chat,
            caption="old caption" if has_photo else None, text=None if has_photo else "old text",
            photo=photo,
        ).as_(bot)
    callback = CallbackQuery(
        id="cbq1", from_user=User(id=99, is_bot=False, first_name="Editor"), chat_instance="ci", data=data,
        message=message,
    ).as_(bot)
    return callback


async def _make_task_draft_and_candidates(
    db_session: AsyncSession, real_news_event: NewsEvent, *, n: int = 2, storage_root=None,
) -> tuple[ContentDraft, list[ImageCandidateRecord]]:
    task = EditorialTask(event_id=real_news_event.id, priority=TaskPriority.B)
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title="Draft Title", body="b", hashtags=[])
    db_session.add(draft)
    await db_session.flush()

    rows = []
    for i in range(n):
        row = ImageCandidateRecord(
            candidate_id=f"c{i}", news_event_id=real_news_event.id, editorial_task_id=task.id,
            content_draft_id=draft.id, source_type=SourceType.RSS, discovery_method="open_graph_image",
            eligible_for_editorial=True, rank=i + 1, relevance_score=90 - i, quality_score=80,
            source_url=f"https://example.com/{i}", article_url=f"https://example.com/{i}",
        )
        db_session.add(row)
        rows.append(row)
    await db_session.flush()
    return draft, rows


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


def _fake_session_factory(db_session: AsyncSession):
    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _CM()


@pytest.mark.asyncio
async def test_malformed_callback_data_is_answered_and_ignored(db_session: AsyncSession) -> None:
    session = FakeSession()
    callback = _make_callback(session, data="not-a-valid-payload")

    await handle_image_preview_callback(callback)

    assert len(session.sent) == 1
    assert isinstance(session.sent[0], AnswerCallbackQuery)


@pytest.mark.asyncio
async def test_inaccessible_message_is_answered_with_alert(db_session: AsyncSession) -> None:
    session = FakeSession()
    draft_id = uuid.uuid4()
    callback = _make_callback(session, data=encode_callback_data("next", draft_id, 0), inaccessible=True)

    await handle_image_preview_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_no_candidates_answers_with_alert(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    session = FakeSession()
    draft_id = uuid.uuid4()  # no rows exist for this draft
    callback = _make_callback(session, data=encode_callback_data("next", draft_id, 0))

    await handle_image_preview_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_next_navigation_edits_text_message_when_no_bytes_available(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft, rows = await _make_task_draft_and_candidates(db_session, real_news_event, n=2)

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("next", draft.id, 1), has_photo=False)

    await handle_image_preview_callback(callback)

    edits = [m for m in session.sent if isinstance(m, EditMessageText)]
    assert len(edits) == 1
    assert "Image 2/2" in edits[0].text
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is not True


@pytest.mark.asyncio
async def test_next_navigation_switches_to_photo_and_deletes_old_text_message(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft, rows = await _make_task_draft_and_candidates(db_session, real_news_event, n=2)

    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    rows[1].storage_status = ImageStorageStatus.STORED
    rows[1].storage_key = stored.storage_key
    await db_session.flush()

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("next", draft.id, 1), has_photo=False)

    await handle_image_preview_callback(callback)

    assert any(isinstance(m, DeleteMessage) for m in session.sent)
    photo_sends = [m for m in session.sent if isinstance(m, SendPhoto)]
    assert len(photo_sends) == 1

    await db_session.refresh(rows[1])
    assert rows[1].telegram_file_id is not None  # newly-uploaded file_id cached


@pytest.mark.asyncio
async def test_expired_candidate_blocks_navigation_with_alert(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft, rows = await _make_task_draft_and_candidates(db_session, real_news_event, n=2)
    rows[1].expires_at = datetime.now(timezone.utc).replace(year=2000)
    await db_session.flush()

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("next", draft.id, 1), has_photo=False)

    await handle_image_preview_callback(callback)

    assert not any(isinstance(m, (EditMessageText, SendPhoto, SendMessage, DeleteMessage)) for m in session.sent)
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_use_image_selects_candidate_and_confirms(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft, rows = await _make_task_draft_and_candidates(db_session, real_news_event, n=2)

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("use", draft.id, 0), has_photo=False)

    await handle_image_preview_callback(callback)

    await db_session.refresh(rows[0])
    await db_session.refresh(rows[1])
    assert rows[0].editor_decision == ImageEditorDecision.SELECTED
    assert rows[1].editor_decision == ImageEditorDecision.REJECTED

    edits = [m for m in session.sent if isinstance(m, EditMessageText)]
    assert len(edits) == 1
    assert "selected" in edits[0].text.lower()
    assert edits[0].reply_markup is None  # keyboard removed


@pytest.mark.asyncio
async def test_use_image_on_expired_candidate_is_rejected(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft, rows = await _make_task_draft_and_candidates(db_session, real_news_event, n=1)
    rows[0].expires_at = datetime.now(timezone.utc).replace(year=2000)
    await db_session.flush()

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("use", draft.id, 0), has_photo=False)

    await handle_image_preview_callback(callback)

    await db_session.refresh(rows[0])
    assert rows[0].editor_decision is None
    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_no_image_rejects_every_candidate_and_confirms(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft, rows = await _make_task_draft_and_candidates(db_session, real_news_event, n=2)

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("none", draft.id, 0), has_photo=False)

    await handle_image_preview_callback(callback)

    await db_session.refresh(rows[0])
    await db_session.refresh(rows[1])
    assert rows[0].editor_decision == ImageEditorDecision.REJECTED
    assert rows[1].editor_decision == ImageEditorDecision.REJECTED

    edits = [m for m in session.sent if isinstance(m, EditMessageText)]
    assert len(edits) == 1
    assert "no image" in edits[0].text.lower()


@pytest.mark.asyncio
async def test_use_image_callback_referencing_row_from_different_draft_is_rejected(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates a tampered/stale callback_data pointing at a valid index but for the wrong draft
    context (the row at that index for the given content_draft_id simply won't exist)."""
    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    draft_a, _ = await _make_task_draft_and_candidates(db_session, real_news_event, n=1)

    session = FakeSession()
    other_draft_id = uuid.uuid4()  # a content_draft_id with zero candidates
    callback = _make_callback(session, data=encode_callback_data("use", other_draft_id, 0), has_photo=False)

    await handle_image_preview_callback(callback)

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True


@pytest.mark.asyncio
async def test_query_failure_answers_with_generic_alert_never_raises(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr("bot.handlers.image_preview.async_session_factory", _fake_session_factory(db_session))
    monkeypatch.setattr("bot.handlers.image_preview.get_editorial_image_candidates", _broken)

    session = FakeSession()
    callback = _make_callback(session, data=encode_callback_data("next", uuid.uuid4(), 0))

    await handle_image_preview_callback(callback)  # must not raise

    answer = session.sent[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
