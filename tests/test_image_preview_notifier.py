"""Tests for services.image_preview_notifier's Phase 16 M6 initial preview send (docs/
phase16_m6_telegram_editorial_preview_report.md §7). Same FakeSession technique as
tests/test_news_handler.py - no real Telegram API call. Real Postgres (db_session fixture) +
tmp_path-backed LocalImageStorage for resolvable bytes.
"""
import hashlib
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SendPhoto, TelegramMethod
from aiogram.types import Chat
from aiogram.types import Message as AiogramMessage
from aiogram.types import PhotoSize
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from integrations.storage.image_storage import LocalImageStorage
from services import image_persistence
from services.image_preview_notifier import send_image_preview

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_DATA = b"fake-stored-bytes-for-notifier-tests"
_SHA256 = hashlib.sha256(_DATA).hexdigest()


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []
        self.fail = False

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        if self.fail:
            raise TelegramBadRequest(method=method, message="Bad Request: simulated failure")
        self.sent.append(method)
        if isinstance(method, SendPhoto):
            return AiogramMessage(
                message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=method.chat_id, type="private"),
                caption=method.caption,
                photo=[PhotoSize(file_id="fake-file-id-1", file_unique_id="u", width=10, height=10)],
            )
        if isinstance(method, SendMessage):
            return AiogramMessage(
                message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


async def _make_task_and_draft(db_session: AsyncSession, real_news_event: NewsEvent) -> tuple[EditorialTask, ContentDraft]:
    task = EditorialTask(event_id=real_news_event.id, priority=TaskPriority.B)
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title="Draft Title", body="b", hashtags=[])
    db_session.add(draft)
    await db_session.flush()
    return task, draft


async def _make_candidate(
    db_session: AsyncSession, *, news_event_id, editorial_task_id, content_draft_id, rank: int = 1,
    storage_status=ImageStorageStatus.NOT_REQUESTED, storage_key: str | None = None,
) -> ImageCandidateRecord:
    row = ImageCandidateRecord(
        candidate_id=f"c{rank}", news_event_id=news_event_id, editorial_task_id=editorial_task_id,
        content_draft_id=content_draft_id, source_type=SourceType.RSS, discovery_method="open_graph_image",
        eligible_for_editorial=True, rank=rank, relevance_score=80, quality_score=80,
        source_url="https://example.com/a", article_url="https://example.com/a",
        storage_status=storage_status, storage_key=storage_key,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_no_candidates_sends_nothing(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_image_preview(bot, 42, db_session, content_draft_id=draft.id, draft_title=draft.title)

    assert outcome.attempted is False
    assert outcome.sent is False
    assert outcome.candidate_count == 0
    assert fake_session.sent == []


@pytest.mark.asyncio
async def test_sends_photo_when_bytes_are_stored_and_caches_file_id(
    db_session: AsyncSession, real_news_event: NewsEvent, tmp_path,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    row = await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
    )

    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_image_preview(bot, 42, db_session, content_draft_id=draft.id, draft_title=draft.title)

    assert outcome.attempted is True
    assert outcome.sent is True
    assert outcome.candidate_count == 1
    photo_sends = [m for m in fake_session.sent if isinstance(m, SendPhoto)]
    assert len(photo_sends) == 1
    assert "Draft Title" in (photo_sends[0].caption or "")

    await db_session.refresh(row)
    assert row.telegram_file_id == "fake-file-id-1"


@pytest.mark.asyncio
async def test_sends_text_only_when_no_bytes_available(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )

    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_image_preview(bot, 42, db_session, content_draft_id=draft.id, draft_title=draft.title)

    assert outcome.attempted is True
    assert outcome.sent is True
    text_sends = [m for m in fake_session.sent if isinstance(m, SendMessage)]
    assert len(text_sends) == 1
    assert not any(isinstance(m, SendPhoto) for m in fake_session.sent)


@pytest.mark.asyncio
async def test_requires_chat_id_when_candidates_exist(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    with pytest.raises(AssertionError):
        await send_image_preview(bot, None, db_session, content_draft_id=draft.id, draft_title=draft.title)


@pytest.mark.asyncio
async def test_send_failure_is_caught_and_reported_not_sent(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )
    fake_session = FakeSession()
    fake_session.fail = True
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_image_preview(bot, 42, db_session, content_draft_id=draft.id, draft_title=draft.title)

    assert outcome.attempted is True
    assert outcome.sent is False


@pytest.mark.asyncio
async def test_never_calls_openai_or_any_llm_provider(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    """Static proof: this module's own source imports nothing from integrations.llm_gateway or
    openai anywhere."""
    import services.image_preview_notifier as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "openai" not in source.lower()
    assert "llm_gateway" not in source
