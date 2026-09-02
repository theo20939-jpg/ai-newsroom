"""Phase I.2: services.final_post_review_notifier tests. Mirrors tests/test_event_recap_review_
notifier.py's own established convention exactly: `Bot` is a plain `unittest.mock.AsyncMock` - no
real Postgres for pure-mock tests, no real Telegram API contact of any kind, including a "live"
(`dry_run=False`) send, since the fake bot never leaves the process. Media-resolution tests use the
real `db_session` fixture (genuine ImageCandidateRecord rows), mirroring that same file's own H.2/
H.3C section.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_route import EditorialDestination
from services import image_persistence
from services.final_post_review_notifier import send_final_post_preview, update_final_post_review_message
from services.final_post_review_service import get_final_post_review

_NOTIFIER_SOURCE = Path("services/final_post_review_notifier.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)


def _pending_review() -> FinalPostReview:
    return FinalPostReview(id=uuid.uuid4(), content_draft_id=uuid.uuid4(), status=FinalPostReviewStatus.PENDING)


def _bundle(*, media_plan: dict | None, source_refs: list[str] | None = None) -> dict:
    return {
        "source_event_recap_task_id": str(uuid.uuid4()), "source_event_recap_review_id": str(uuid.uuid4()),
        "story_id": str(uuid.uuid4()), "anchor_event_id": str(uuid.uuid4()),
        "approved_recap": {"recap_title": "t", "recap_summary": "s", "key_takeaways": [], "uncertainty_notes": []},
        "verified_facts": [], "source_refs": source_refs if source_refs is not None else ["https://example.com/a"],
        "selected_media_plan": media_plan, "legacy_snapshot_missing": False, "language": "ru",
        "authoring_prompt_version": "2",
    }


def _attach_call_order(bot: AsyncMock, order: list[str]) -> None:
    async def _photo(*args: object, **kwargs: object) -> AsyncMock:
        order.append("photo")
        return bot.send_photo.return_value

    async def _text(*args: object, **kwargs: object) -> AsyncMock:
        order.append("text")
        return bot.send_message.return_value

    bot.send_photo.side_effect = _photo
    bot.send_message.side_effect = _text


async def _seed_event_with_image(
    db_session: AsyncSession, *, candidate_id: str = "hero-candidate", telegram_file_id: str = "cached-file-id-123",
) -> tuple[NewsEvent, dict]:
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid.uuid4()}.xml", active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(source_id=source.id, title="Test event", content="Body", category=EventCategory.AI, hash=f"hash-{uuid.uuid4()}")
    db_session.add(event)
    await db_session.flush()
    db_session.add(
        ImageCandidateRecord(
            news_event_id=event.id, candidate_id=candidate_id, source_type=SourceType.RSS,
            discovery_method="open_graph_image", quality_score=90, relevance_score=60, rank=1,
            width=1200, height=800, image_format="JPEG", quality_warnings=[],
            source_url="https://example.com/hero.jpg", eligible_for_editorial=True,
            telegram_file_id=telegram_file_id,
        )
    )
    await db_session.flush()
    media_plan = {
        "tier": "story_pool",
        "representative": {
            "candidate_id": candidate_id, "originating_event_id": str(event.id), "media_type": "image",
            "recommended_role": "hero", "storage_key": None, "telegram_file_id": telegram_file_id,
            "sha256": None, "remote_url": "https://example.com/hero.jpg",
        },
    }
    return event, media_plan


def _branded_fallback_media_plan() -> dict:
    data = b"fake-branded-fallback-jpeg-bytes-for-i2-tests"
    sha256 = hashlib.sha256(data).hexdigest()
    stored = image_persistence._get_storage().store_validated_image(
        data, sha256=sha256, image_format="JPEG", max_bytes=10_000_000,
    )
    return {
        "tier": "branded_fallback",
        "representative": {
            "candidate_id": None, "originating_event_id": None, "media_type": "image",
            "recommended_role": "hero", "storage_key": stored.storage_key, "telegram_file_id": None,
            "sha256": stored.sha256, "remote_url": None,
        },
    }


# ---------------------------------------------------------------------------------------------
# Media required (Part C/U Case 1)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_media_resolution_failure_sends_nothing() -> None:
    """Case 1: the plan points at a candidate that cannot be re-resolved (no ImageCandidateRecord
    seeded at all) - no preview, no control message, review not marked delivered."""
    bot = AsyncMock()
    session = AsyncMock()
    review = _pending_review()
    bundle = _bundle(media_plan={
        "tier": "story_pool",
        "representative": {
            "candidate_id": "vanished", "originating_event_id": str(uuid.uuid4()), "media_type": "image",
            "recommended_role": "hero", "storage_key": None, "telegram_file_id": None, "sha256": None, "remote_url": None,
        },
    })

    outcome = await send_final_post_preview(
        bot, session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "media_resolution_failed"
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_none_tier_media_plan_sends_nothing() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    review = _pending_review()
    bundle = _bundle(media_plan={"tier": "none", "representative": None})

    outcome = await send_final_post_preview(
        bot, session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "media_resolution_failed"
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------------------------
# No silent truncation (Part G)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_presentation_too_long_sends_nothing(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()

    outcome = await send_final_post_preview(
        bot, db_session, review, title="Title", body="x" * 2000, final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "presentation_too_long"
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------------------------
# Two-message contract (Part H/I/S)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_message_order_and_content(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan, source_refs=["https://example.com/source-article"])

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502
    call_order: list[str] = []
    _attach_call_order(bot, call_order)

    outcome = await send_final_post_preview(
        bot, db_session, review, title="Final Title", body="Final body.", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert bot.send_photo.call_count == 1
    assert bot.send_message.call_count == 1
    assert call_order == ["photo", "text"]

    photo_kwargs = bot.send_photo.call_args.kwargs
    assert "Final Title" in photo_kwargs["caption"]
    assert "Final body." in photo_kwargs["caption"]

    text_kwargs = bot.send_message.call_args.kwargs
    assert text_kwargs["reply_to_message_id"] == 501

    assert outcome.status == "sent"
    assert outcome.preview_message_id == 501
    assert outcome.control_message_id == 502


@pytest.mark.asyncio
async def test_message_1_keyboard_is_canonical_source_and_meme_never_decision_buttons(db_session: AsyncSession) -> None:
    """PRESENTATION RECOVERY (2026-09-02) supersedes this test's original "source-only" contract:
    WYSIWYG now requires MESSAGE 1's keyboard to be the exact same canonical
    bot.keyboards.image_preview.build_editorial_send_keyboard() result real publication would
    send - source button + meme button - never the internal ✅/✏️ decision keyboard (that stays
    MESSAGE 2-only, unchanged)."""
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan, source_refs=["https://example.com/source-article"])
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    photo_kwargs = bot.send_photo.call_args.kwargs
    keyboard = photo_kwargs["reply_markup"]
    assert keyboard is not None
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "🔗 Open source" in texts
    assert "😂 Сгенерировать мем" in texts
    urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert urls == ["https://example.com/source-article"]
    for forbidden in ("✅", "✏️", "К публикации", "На доработку", "NINJA PULSE", "Подписаться"):
        assert forbidden not in texts


@pytest.mark.asyncio
async def test_message_2_keyboard_is_decision_only(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    text_kwargs = bot.send_message.call_args.kwargs
    keyboard = text_kwargs["reply_markup"]
    assert keyboard is not None
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert texts == ["✅ К публикации", "✏️ На доработку"]


@pytest.mark.asyncio
async def test_no_source_url_yields_meme_only_message_1_keyboard(db_session: AsyncSession) -> None:
    """PRESENTATION RECOVERY (2026-09-02) supersedes this test's original "no keyboard at all"
    contract: the canonical keyboard always includes the meme button regardless of source_url
    (Case 2 of the canonical contract - meme-only), matching real publication's own behavior."""
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan, source_refs=["not-a-url"])
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    keyboard = bot.send_photo.call_args.kwargs["reply_markup"]
    assert keyboard is not None
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert texts == ["😂 Сгенерировать мем"]
    urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert urls == []


@pytest.mark.asyncio
async def test_canonical_metadata_records_message_2_not_message_1(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )
    assert outcome.status == "sent"

    # `review` above is a plain in-memory instance (never persisted) - record_telegram_delivery()
    # would find no row. Repeat against a genuinely persisted review to check the real DB write.
    from database.models.content_draft import ContentDraft, ContentType
    from database.models.editorial_task import TaskPriority
    from schemas.editorial_task import EditorialTaskCreate
    from schemas.workflow import WorkflowType
    from services import workflow_service
    from services.final_post_review_service import create_final_post_review

    task_read = await workflow_service.create_task(
        db_session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.FINAL_POST_AUTHORING, priority=TaskPriority.C),
    )
    draft = ContentDraft(id=uuid.uuid4(), task_id=task_read.id, type=ContentType.POST, title="T", body="B", version=1, status="draft")
    db_session.add(draft)
    await db_session.commit()
    await db_session.refresh(draft)

    persisted_review = await create_final_post_review(db_session, content_draft_id=draft.id)
    bot2 = AsyncMock()
    bot2.send_photo.return_value.message_id = 601
    bot2.send_message.return_value.message_id = 602
    await send_final_post_preview(
        bot2, db_session, persisted_review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )
    reloaded = await get_final_post_review(db_session, persisted_review.id)
    assert reloaded is not None
    assert reloaded.telegram_message_id == 602
    assert reloaded.telegram_message_id != 601
    assert reloaded.telegram_chat_id == -100123456789


# ---------------------------------------------------------------------------------------------
# Send failure semantics (Part U, Cases 2/3)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_1_send_failure_never_sends_message_2(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.side_effect = TelegramBadRequest(method=AsyncMock(), message="Bad Request: PHOTO_INVALID_DIMENSIONS")

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "preview_send_failed"
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_message_1_success_message_2_failure_is_reported_not_hidden(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.side_effect = TelegramBadRequest(method=AsyncMock(), message="Bad Request: chat not found")

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "control_send_failed"
    assert outcome.preview_message_id == 501
    assert outcome.control_message_id is None


@pytest.mark.asyncio
async def test_dry_run_never_calls_telegram(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=True,
    )

    assert outcome.status == "dry_run"
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------------------------
# Media resolution: story_pool / discovered / branded_fallback (Part D)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_story_pool_media_resolves_via_image_candidate_record(db_session: AsyncSession) -> None:
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "sent"
    assert bot.send_photo.call_args.kwargs["photo"] == "cached-file-id-123"


@pytest.mark.asyncio
async def test_discovered_tier_media_resolves_the_same_way_as_story_pool(db_session: AsyncSession) -> None:
    """tier="discovered" uses the SAME candidate_id+originating_event_id resolution path as
    story_pool - the notifier is tier-agnostic by construction."""
    event, media_plan = await _seed_event_with_image(db_session)
    media_plan = {**media_plan, "tier": "discovered"}
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "sent"
    assert bot.send_photo.call_args.kwargs["photo"] == "cached-file-id-123"


@pytest.mark.asyncio
async def test_branded_fallback_resolves_from_local_storage_no_candidate_lookup(db_session: AsyncSession) -> None:
    media_plan = _branded_fallback_media_plan()
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    outcome = await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
    )

    assert outcome.status == "sent"
    from aiogram.types import BufferedInputFile

    assert isinstance(bot.send_photo.call_args.kwargs["photo"], BufferedInputFile)


# ---------------------------------------------------------------------------------------------
# Destination safety (Part T) / no-publication / no-LLM structural assertions
# ---------------------------------------------------------------------------------------------


def test_notifier_only_ever_references_telegraph_destination_by_default():
    for forbidden in ("EditorialDestination.NEWS", "EditorialDestination.MEME", "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS"):
        assert forbidden not in _NOTIFIER_SOURCE, f"unexpected non-default destination reference: {forbidden}"
    assert "EditorialDestination.TELEGRAPH" in _NOTIFIER_SOURCE


def test_notifier_never_references_publication_senders():
    for forbidden in ("send_news_with_image_preview", "send_news_with_rich_media", "send_editorial_card"):
        assert forbidden not in _NOTIFIER_SOURCE, f"unexpected publication-sender reference: {forbidden}"


def test_notifier_never_references_llm_gateway():
    for forbidden in ("LLMGateway", "call_generate", "CapabilityExecutor", "WorkflowRunner"):
        assert forbidden not in _NOTIFIER_SOURCE, f"unexpected LLM/workflow reference: {forbidden}"


@pytest.mark.asyncio
async def test_accepts_an_explicit_alternate_destination(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "news_topic_id", 11)
    event, media_plan = await _seed_event_with_image(db_session)
    review = _pending_review()
    bundle = _bundle(media_plan=media_plan)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    await send_final_post_preview(
        bot, db_session, review, title="T", body="B", final_post_source=bundle,
        authoring_prompt_version="2", fact_safety_status="pass", dry_run=False,
        destination=EditorialDestination.NEWS,
    )

    assert bot.send_message.call_args.kwargs["message_thread_id"] == 11


# ---------------------------------------------------------------------------------------------
# update_final_post_review_message() - MESSAGE 2 edit only
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_message_edits_message_2_only():
    bot = AsyncMock()
    review = FinalPostReview(id=uuid.uuid4(), content_draft_id=uuid.uuid4(), status=FinalPostReviewStatus.APPROVED_FOR_PUBLICATION)

    edited = await update_final_post_review_message(bot, chat_id=-100123456789, message_id=502, review=review)

    assert edited is True
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()
    bot.edit_message_caption.assert_not_called()
    bot.edit_message_media.assert_not_called()
    assert bot.edit_message_text.call_count == 1
    kwargs = bot.edit_message_text.call_args.kwargs
    assert kwargs["message_id"] == 502
    assert "✅ Пост одобрен к публикации" in kwargs["text"]
    assert kwargs["reply_markup"] is None  # terminal state - no keyboard


@pytest.mark.asyncio
async def test_update_message_returns_false_on_telegram_api_error():
    bot = AsyncMock()
    bot.edit_message_text.side_effect = TelegramBadRequest(method=AsyncMock(), message="message to edit not found")
    review = _pending_review()

    edited = await update_final_post_review_message(bot, chat_id=-100123456789, message_id=42, review=review)

    assert edited is False
