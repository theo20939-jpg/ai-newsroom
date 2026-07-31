"""Tests for services.image_preview_notifier's Phase 16 UX-fixed combined news+image send (docs/
phase16_ux_combined_preview_fix_report.md, phase16_m6_telegram_editorial_preview_report.md §7).
Same FakeSession technique as tests/test_news_handler.py - no real Telegram API call. Real
Postgres (db_session fixture) + tmp_path-backed LocalImageStorage for resolvable bytes.

Unlike the pre-fix `send_image_preview()`, `send_news_with_image_preview()` is now the *sole*
delivery function whenever the image-preview flow is active - it always sends exactly one message
(text-only when there is no eligible candidate at all, a photo otherwise), never zero and never
two.
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
from schemas.content_draft import ContentDraftRead
from services import image_persistence
from services.image_preview_notifier import send_news_with_image_preview

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


async def _make_task_and_draft(db_session: AsyncSession, real_news_event: NewsEvent) -> tuple[EditorialTask, ContentDraftRead]:
    task = EditorialTask(event_id=real_news_event.id, priority=TaskPriority.B)
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(
        task_id=task.id, type=ContentType.POST, title="Draft Title",
        body="Draft body text for the combined preview.", hashtags=["#news"],
    )
    db_session.add(draft)
    await db_session.flush()
    draft_read = ContentDraftRead(
        id=draft.id, task_id=draft.task_id, type=draft.type, title=draft.title, body=draft.body,
        hashtags=draft.hashtags, version=draft.version, status=draft.status,
        created_at=draft.created_at, updated_at=draft.updated_at,
    )
    return task, draft_read


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
async def test_no_candidates_still_sends_a_text_only_news_message(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    """Unlike the pre-fix send_image_preview(), the absence of any candidate is never silent -
    exactly one text message (the real news content) is still sent."""
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False)

    assert outcome.sent is True
    assert outcome.has_image is False
    assert outcome.candidate_count == 0
    assert len(fake_session.sent) == 1
    assert isinstance(fake_session.sent[0], SendMessage)
    assert "Draft body text" in fake_session.sent[0].text


@pytest.mark.asyncio
async def test_no_candidates_message_has_no_url_in_body_but_has_source_button(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    real_news_event.url = "https://example.com/source-article"
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False)

    sent = fake_session.sent[0]
    assert isinstance(sent, SendMessage)
    assert "https://example.com/source-article" not in sent.text
    assert sent.reply_markup is not None
    buttons = [b for row in sent.reply_markup.inline_keyboard for b in row]
    assert len(buttons) == 1
    assert buttons[0].url == "https://example.com/source-article"


@pytest.mark.asyncio
async def test_exactly_one_message_is_sent_end_to_end_never_two(
    db_session: AsyncSession, real_news_event: NewsEvent, tmp_path,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
    )
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False)

    assert len(fake_session.sent) == 1  # never a second "Image selected"/preview message


@pytest.mark.asyncio
async def test_sends_photo_with_real_news_caption_when_bytes_are_stored_and_caches_file_id(
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

    outcome = await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False)

    assert outcome.sent is True
    assert outcome.has_image is True
    assert outcome.candidate_count == 1
    photo_sends = [m for m in fake_session.sent if isinstance(m, SendPhoto)]
    assert len(photo_sends) == 1
    assert "Draft body text" in (photo_sends[0].caption or "")
    assert "Draft Title" in (photo_sends[0].caption or "")

    await db_session.refresh(row)
    assert row.telegram_file_id == "fake-file-id-1"


@pytest.mark.asyncio
async def test_sends_text_only_when_candidates_exist_but_no_bytes_available(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )

    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False)

    assert outcome.sent is True
    assert outcome.has_image is False
    text_sends = [m for m in fake_session.sent if isinstance(m, SendMessage)]
    assert len(text_sends) == 1
    assert not any(isinstance(m, SendPhoto) for m in fake_session.sent)


@pytest.mark.asyncio
async def test_dry_run_never_calls_telegram(db_session: AsyncSession, real_news_event: NewsEvent, tmp_path) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    await _make_candidate(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
    )
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=True)

    assert outcome.sent is False
    assert fake_session.sent == []


@pytest.mark.asyncio
async def test_requires_chat_id_for_a_live_send(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    with pytest.raises(AssertionError):
        await send_news_with_image_preview(bot, None, db_session, draft=draft, event=real_news_event, dry_run=False)


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

    outcome = await send_news_with_image_preview(bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False)

    assert outcome.sent is False


@pytest.mark.asyncio
async def test_never_calls_openai_or_any_llm_provider(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    """Static proof: this module's own source imports nothing from integrations.llm_gateway or
    openai anywhere."""
    import services.image_preview_notifier as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "openai" not in source.lower()
    assert "llm_gateway" not in source
