"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: services.event_recap_review_notifier -
send_event_recap_review() + update_event_recap_review_message(). Pure unit tier, mirrors tests/
test_telegram_editorial_routing.py's own established convention exactly: `Bot` is a plain
`unittest.mock.AsyncMock` - no real Postgres, no real Telegram API contact of any kind, including
a "live" (`dry_run=False`) send, since the fake bot never leaves the process.

Phase D.0 change from Phase C.1: both functions now take an `EventRecapReview` ORM instance (for
status/id) plus the recap's own persisted result dict, never a live `EventRecapCandidate` - see
services/event_recap_review_notifier.py's own module docstring.

Phase H.2 change: `send_event_recap_review()` now also takes a session and an optional
`selected_media` dict, and returns `EventRecapReviewSendOutcome` (`.text_outcome`/`.media_outcome`)
instead of a bare `RoutingOutcome` - the pre-existing tests above that don't pass `selected_media`
use a plain `AsyncMock()` session, since `_resolve_selected_media_photo_input()` short-circuits on
`selected_media is None` before any DB call. The dedicated media-path tests further below use the
real `db_session` fixture instead, since they need genuine `ImageCandidateRecord` rows.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_route import EditorialDestination
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FULL_TEXT,
    TRIGGERED_BY_CONTENT_GENERATION_SELECTED,
    NewsEventArticleAcquisition,
)
from services import image_persistence, workflow_service
from services.event_recap_review_notifier import send_event_recap_review, update_event_recap_review_message
from services.event_recap_review_service import create_event_recap_review, get_event_recap_review


@pytest.fixture(autouse=True)
def _isolated_image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Phase H.3C: the branded_fallback resolution tests below write/read real bytes through
    `services.image_persistence._get_storage()` - isolated per test, singleton reset, mirrors
    tests/test_image_persistence.py's own established `_isolated_storage` fixture exactly."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)

_RECAP_RESULT = {
    "recap_title": "Apple Watch Ultra Unveiled",
    "recap_summary": "Apple introduced a new Watch Ultra model.",
    "key_takeaways": ["Priced at $999.", "Positioned as the flagship Watch tier."],
    "uncertainty_notes": ["Availability date not yet confirmed."],
}


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated topic ids for every test in this file - mirrors tests/test_telegram_editorial_
    routing.py's own identical fixture, never the real environment's values."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)


def _pending_review() -> EventRecapReview:
    """An unpersisted, in-memory EventRecapReview - exactly the ORM shape the caller would hold
    right after services.event_recap_review_service.create_event_recap_review() returns."""
    return EventRecapReview(id=uuid.uuid4(), recap_task_id=uuid.uuid4(), status=EventRecapReviewStatus.PENDING)


@pytest.mark.asyncio
async def test_dry_run_is_true_by_default_and_never_calls_send_message() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    review = _pending_review()

    outcome = await send_event_recap_review(bot, session, review, _RECAP_RESULT)

    bot.send_message.assert_not_called()
    assert outcome.text_outcome.sent is False
    assert outcome.text_outcome.reason == "dry_run"
    assert outcome.media_outcome is None  # no selected_media passed - never even attempted


@pytest.mark.asyncio
async def test_live_send_builds_a_correct_preview_message() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 777
    session = AsyncMock()
    review = _pending_review()

    outcome = await send_event_recap_review(bot, session, review, _RECAP_RESULT, dry_run=False)

    assert bot.send_message.call_count == 1
    args, kwargs = bot.send_message.call_args
    sent_chat_id, sent_text = args[0], args[1]
    assert sent_chat_id == -100123456789
    assert kwargs["message_thread_id"] == 33  # EditorialDestination.TELEGRAPH's own topic id

    assert _RECAP_RESULT["recap_title"] in sent_text
    assert _RECAP_RESULT["recap_summary"] in sent_text
    for takeaway in _RECAP_RESULT["key_takeaways"]:
        assert takeaway in sent_text
    for note in _RECAP_RESULT["uncertainty_notes"]:
        assert note in sent_text
    assert "shadow" in sent_text.lower()  # never rendered as a finished, publishable post
    assert "⏳" in sent_text  # PENDING status line

    assert outcome.text_outcome.sent is True
    assert outcome.text_outcome.destination is EditorialDestination.TELEGRAPH
    assert outcome.text_outcome.message_id == 777

    # Real reply_markup wired through - a keyboard, not None, while PENDING.
    assert kwargs["reply_markup"] is not None
    # No media was selected - never a reply-to relationship.
    assert kwargs["reply_to_message_id"] is None


@pytest.mark.asyncio
async def test_uses_the_real_send_to_editorial_destination_routing() -> None:
    """Proves this notifier routes through the existing, unmodified send_to_editorial_destination()
    - never a parallel/duplicated Telegram call - by checking the real routing side effects
    (parse_mode, message_thread_id resolved from settings, link_preview_options) that only that
    function applies."""
    from aiogram.types import LinkPreviewOptions

    bot = AsyncMock()
    session = AsyncMock()
    review = _pending_review()

    await send_event_recap_review(bot, session, review, _RECAP_RESULT, dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert kwargs["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


@pytest.mark.asyncio
async def test_accepts_an_explicit_alternate_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller may pass a different EditorialDestination explicitly - this module makes no
    destination decision of its own beyond the TELEGRAPH default (module docstring)."""
    monkeypatch.setattr(settings, "news_topic_id", 11)
    bot = AsyncMock()
    session = AsyncMock()
    review = _pending_review()

    await send_event_recap_review(
        bot, session, review, _RECAP_RESULT, dry_run=False, destination=EditorialDestination.NEWS,
    )

    _, kwargs = bot.send_message.call_args
    assert kwargs["message_thread_id"] == 11


@pytest.mark.asyncio
async def test_update_message_edits_in_place_never_sends_new() -> None:
    bot = AsyncMock()
    review = EventRecapReview(id=uuid.uuid4(), recap_task_id=uuid.uuid4(), status=EventRecapReviewStatus.APPROVED)

    edited = await update_event_recap_review_message(
        bot, chat_id=-100123456789, message_id=42, review=review, recap_result=_RECAP_RESULT,
    )

    assert edited is True
    bot.send_message.assert_not_called()
    assert bot.edit_message_text.call_count == 1
    _, kwargs = bot.edit_message_text.call_args
    assert kwargs["chat_id"] == -100123456789
    assert kwargs["message_id"] == 42
    assert "✅ Recap одобрен" in kwargs["text"]
    # APPROVED is a final state - no keyboard on the re-rendered message.
    assert kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_update_message_returns_false_on_telegram_api_error() -> None:
    from aiogram.exceptions import TelegramBadRequest

    bot = AsyncMock()
    bot.edit_message_text.side_effect = TelegramBadRequest(method=AsyncMock(), message="message to edit not found")
    review = _pending_review()

    edited = await update_event_recap_review_message(
        bot, chat_id=-100123456789, message_id=42, review=review, recap_result=_RECAP_RESULT,
    )

    assert edited is False


@pytest.mark.asyncio
async def test_publishable_is_never_read_or_touched_by_the_notifier() -> None:
    """EventRecapCandidate.publishable stays exactly what services/event_recap.py already
    returned - this notifier never imports EventRecapCandidate at all any more (Phase D.0
    change), only the recap's own persisted result dict and the durable EventRecapReview row."""
    bot = AsyncMock()
    session = AsyncMock()
    review = _pending_review()

    outcome = await send_event_recap_review(bot, session, review, _RECAP_RESULT, dry_run=False)

    assert not hasattr(outcome, "publishable")
    assert not hasattr(outcome.text_outcome, "publishable")


# ---------------------------------------------------------------------------------------------
# Phase H.2 - two-message media contract (real db_session - genuine ImageCandidateRecord rows)
# ---------------------------------------------------------------------------------------------


async def _seed_event(db_session: AsyncSession, *, title: str = "Test event") -> NewsEvent:
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid.uuid4()}.xml", active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, content="Body", category=EventCategory.AI, hash=f"hash-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    return event


async def _seed_review(db_session: AsyncSession, event: NewsEvent) -> EventRecapReview:
    """A real EventRecapReview backed by a real EditorialTask row (EventRecapReview.recap_task_id
    is a genuine FK - create_event_recap_review() with a bare uuid4() would violate it)."""
    task_read = await workflow_service.create_task(
        db_session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.EVENT_RECAP, priority=TaskPriority.C),
    )
    return await create_event_recap_review(db_session, recap_task_id=task_read.id)


async def _seed_event_with_image(
    db_session: AsyncSession, *, candidate_id: str = "hero-candidate", telegram_file_id: str = "cached-file-id-123",
) -> tuple[NewsEvent, dict]:
    """A real NewsEvent + one eligible, telegram_file_id-cached ImageCandidateRecord - the
    file_id path means resolve_photo_input() never touches local storage/ImageStorage at all,
    keeping this test file's own established zero-network/zero-filesystem discipline. Returns the
    event plus the exact `selected_media` dict shape `services.event_recap.
    serialize_selected_media_plan()` already produces (Phase H.1, unmodified)."""
    event = await _seed_event(db_session)
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

    selected_media = {
        "tier": "story_pool",
        "representative": {
            "candidate_id": candidate_id, "originating_event_id": str(event.id), "media_type": "image",
            "recommended_role": "hero", "storage_key": None, "telegram_file_id": telegram_file_id,
            "sha256": None, "remote_url": "https://example.com/hero.jpg",
        },
    }
    return event, selected_media


def _attach_call_order(bot: AsyncMock, order: list[str]) -> None:
    async def _photo(*args: object, **kwargs: object) -> AsyncMock:
        order.append("photo")
        return bot.send_photo.return_value

    async def _text(*args: object, **kwargs: object) -> AsyncMock:
        order.append("text")
        return bot.send_message.return_value

    bot.send_photo.side_effect = _photo
    bot.send_message.side_effect = _text


@pytest.mark.asyncio
async def test_media_then_text_two_message_contract(db_session: AsyncSession) -> None:
    """Phase H.2 §12: photo sent exactly once, text sent exactly once, photo before text,
    keyboard ONLY on the text message, full recap never used as photo caption, reply association
    to the photo message, canonical message_id is the TEXT message's id."""
    event, selected_media = await _seed_event_with_image(db_session)
    review = await _seed_review(db_session, event)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502
    call_order: list[str] = []
    _attach_call_order(bot, call_order)

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert bot.send_photo.call_count == 1
    assert bot.send_message.call_count == 1
    assert call_order == ["photo", "text"]

    photo_kwargs = bot.send_photo.call_args.kwargs
    assert photo_kwargs["caption"] == ""  # never the full recap
    assert photo_kwargs.get("reply_markup") is None  # keyboard never on the media message

    text_kwargs = bot.send_message.call_args.kwargs
    assert text_kwargs["reply_markup"] is not None  # keyboard only on the text message
    assert text_kwargs["reply_to_message_id"] == 501  # reply association to the photo message

    assert outcome.media_outcome is not None and outcome.media_outcome.sent is True
    assert outcome.text_outcome.sent is True
    assert outcome.text_outcome.message_id == 502  # canonical = text message


@pytest.mark.asyncio
async def test_delivery_metadata_records_the_text_message_not_the_photo(db_session: AsyncSession) -> None:
    """Phase H.2 §13: EventRecapReview.telegram_* must match the canonical TEXT message, never
    the photo message - machine-checked, not just asserted in prose."""
    event, selected_media = await _seed_event_with_image(db_session)
    review = await _seed_review(db_session, event)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    persisted = await get_event_recap_review(db_session, review.id)
    assert persisted is not None
    assert persisted.telegram_message_id == 502
    assert persisted.telegram_message_id != 501
    assert persisted.telegram_chat_id == -100123456789


@pytest.mark.asyncio
async def test_callback_after_media_review_only_edits_the_text_message() -> None:
    """Phase H.2 §14: update_event_recap_review_message() is completely unchanged - proves it
    never touches edit_message_caption/edit_message_media/send_photo, regardless of whether the
    review it is re-rendering happened to have media attached at send time (this function has no
    way to know either way, by design - module docstring)."""
    bot = AsyncMock()
    review = EventRecapReview(id=uuid.uuid4(), recap_task_id=uuid.uuid4(), status=EventRecapReviewStatus.APPROVED)

    edited = await update_event_recap_review_message(
        bot, chat_id=-100123456789, message_id=502, review=review, recap_result=_RECAP_RESULT,
    )

    assert edited is True
    assert bot.edit_message_text.call_count == 1
    assert bot.edit_message_caption.call_count == 0
    assert bot.edit_message_media.call_count == 0
    assert bot.send_photo.call_count == 0
    kwargs = bot.edit_message_text.call_args.kwargs
    assert kwargs["message_id"] == 502
    assert kwargs["reply_markup"] is None  # APPROVED is final - no keyboard


@pytest.mark.asyncio
async def test_zero_media_sends_text_only_and_records_metadata(db_session: AsyncSession) -> None:
    """Phase H.2 §15: tier="none" (or selected_media=None) - existing text-only behavior
    preserved exactly: zero photo sends, one text send, keyboard present, metadata recorded."""
    event = await _seed_event(db_session)
    review = await _seed_review(db_session, event)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 502

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT,
        selected_media={"tier": "none", "representative": None}, dry_run=False,
    )

    assert bot.send_photo.call_count == 0
    assert bot.send_message.call_count == 1
    assert outcome.media_outcome is None
    assert outcome.text_outcome.sent is True
    assert outcome.text_outcome.message_id == 502
    assert bot.send_message.call_args.kwargs["reply_markup"] is not None

    persisted = await get_event_recap_review(db_session, review.id)
    assert persisted is not None and persisted.telegram_message_id == 502


@pytest.mark.asyncio
async def test_photo_resolution_failure_falls_back_to_text_only(db_session: AsyncSession) -> None:
    """Phase H.2 §16: the persisted plan references a candidate that no longer resolves (here:
    no ImageCandidateRecord at all for that event/candidate_id combination) - fail-soft: zero
    photo sends, canonical text send still happens, keyboard present, review remains actionable."""
    event = await _seed_event(db_session, title="No image event")
    # Deliberately NO ImageCandidateRecord seeded - the plan points at a candidate that cannot
    # be re-resolved (mirrors "missing storage file"/"candidate record deleted" in production).
    selected_media = {
        "tier": "story_pool",
        "representative": {
            "candidate_id": "vanished-candidate", "originating_event_id": str(event.id),
            "media_type": "image", "recommended_role": "hero", "storage_key": None,
            "telegram_file_id": None, "sha256": None, "remote_url": None,
        },
    }
    review = await _seed_review(db_session, event)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 502

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert bot.send_photo.call_count == 0
    assert bot.send_message.call_count == 1
    assert outcome.media_outcome is None  # never even attempted - resolution failed first
    assert outcome.text_outcome.sent is True
    assert bot.send_message.call_args.kwargs["reply_markup"] is not None

    persisted = await get_event_recap_review(db_session, review.id)
    assert persisted is not None and persisted.telegram_message_id == 502


@pytest.mark.asyncio
async def test_photo_send_failure_still_delivers_the_text_review(db_session: AsyncSession) -> None:
    """Phase H.2 §17: photo resolves fine, but the live bot.send_photo() call itself fails - the
    canonical text review must still be sent (never "media failure -> zero review")."""
    event, selected_media = await _seed_event_with_image(db_session)
    review = await _seed_review(db_session, event)

    bot = AsyncMock()
    bot.send_photo.side_effect = TelegramBadRequest(method=AsyncMock(), message="Bad Request: PHOTO_INVALID_DIMENSIONS")
    bot.send_message.return_value.message_id = 502

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert bot.send_photo.call_count == 1  # attempted
    assert outcome.media_outcome is not None and outcome.media_outcome.sent is False
    assert bot.send_message.call_count == 1  # still sent
    assert outcome.text_outcome.sent is True
    assert bot.send_message.call_args.kwargs["reply_to_message_id"] is None  # no successful photo to reply to

    persisted = await get_event_recap_review(db_session, review.id)
    assert persisted is not None and persisted.telegram_message_id == 502


@pytest.mark.asyncio
async def test_canonical_text_send_failure_is_not_recorded_as_success(db_session: AsyncSession) -> None:
    """Phase H.2 §18: media send succeeds, but the canonical TEXT review send fails - the overall
    delivery must be reported as a failure, and telegram_* metadata must NOT be written (the
    review has no keyboard message an operator could ever act on)."""
    event, selected_media = await _seed_event_with_image(db_session)
    review = await _seed_review(db_session, event)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.side_effect = TelegramBadRequest(method=AsyncMock(), message="Bad Request: chat not found")

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert outcome.media_outcome is not None and outcome.media_outcome.sent is True
    assert outcome.text_outcome.sent is False  # not hidden as success

    persisted = await get_event_recap_review(db_session, review.id)
    assert persisted is not None
    assert persisted.telegram_message_id is None
    assert persisted.telegram_chat_id is None
    assert persisted.status == EventRecapReviewStatus.PENDING  # no keyboard message exists to act on


# ---------------------------------------------------------------------------------------------
# Phase H.3C - tier-agnostic media resolution (branded_fallback + old-plan compatibility)
# ---------------------------------------------------------------------------------------------


def _seed_branded_fallback_bytes() -> dict:
    """Writes real bytes through the SAME `services.image_persistence._get_storage()` abstraction
    `render_branded_fallback_media()` uses, and returns the exact `selected_media` dict shape
    `services.event_recap.serialize_selected_media_plan()` produces for `tier="branded_fallback"`
    - `candidate_id`/`originating_event_id` both `None`, by design (no `ImageCandidateRecord` row
    exists for a rendered card)."""
    import hashlib

    data = b"fake-branded-fallback-jpeg-bytes-for-h3c-tests"
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


@pytest.mark.asyncio
async def test_branded_fallback_resolves_from_local_storage_no_candidate_lookup(db_session: AsyncSession) -> None:
    """Phase H.3C §20: a persisted `tier="branded_fallback"` plan (no `candidate_id`/`originating_
    event_id` - no `ImageCandidateRecord` row exists at all, deliberately unseeded here) resolves
    via direct local-storage bytes, never an `ImageCandidateRecord` lookup, never a network call.
    The two-message contract (§21) is unaffected: the notifier does not know or care that this
    visual came from Tier 3 rather than Tier 1/2B."""
    selected_media = _seed_branded_fallback_bytes()
    review = _pending_review()

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502
    call_order: list[str] = []
    _attach_call_order(bot, call_order)

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert call_order == ["photo", "text"]
    assert outcome.media_outcome is not None and outcome.media_outcome.sent is True
    assert outcome.text_outcome.sent is True

    photo_kwargs = bot.send_photo.call_args.kwargs
    assert photo_kwargs["caption"] == ""
    assert photo_kwargs.get("reply_markup") is None
    # The actual photo payload is a freshly-read BufferedInputFile (from local storage), never a
    # bare candidate_id/event_id lookup.
    from aiogram.types import BufferedInputFile

    assert isinstance(bot.send_photo.call_args.kwargs["photo"], BufferedInputFile)

    text_kwargs = bot.send_message.call_args.kwargs
    assert text_kwargs["reply_to_message_id"] == 501
    assert text_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_old_story_pool_plan_still_resolves_via_image_candidate_record(db_session: AsyncSession) -> None:
    """Phase H.3C §22 (regression guard): an H.1-shaped `tier="story_pool"` plan (`candidate_id` +
    `originating_event_id` both present, exactly as every pre-H.3C persisted task still has) must
    keep resolving through the existing `get_editorial_image_candidates()` path - no branded-
    fallback/storage-key-only branch ever intercepts it. This is already exercised implicitly by
    every other `story_pool` test in this file; this test names the guarantee explicitly."""
    event, selected_media = await _seed_event_with_image(db_session)
    assert selected_media["tier"] == "story_pool"
    assert selected_media["representative"]["candidate_id"] is not None
    assert selected_media["representative"]["originating_event_id"] is not None
    review = _pending_review()

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 501
    bot.send_message.return_value.message_id = 502

    outcome = await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert outcome.media_outcome is not None and outcome.media_outcome.sent is True
    # The seeded candidate has a real telegram_file_id (see _seed_event_with_image) - resolved via
    # resolve_photo_input()'s existing file_id-first path, a plain string, never BufferedInputFile.
    assert bot.send_photo.call_args.kwargs["photo"] == "cached-file-id-123"


# ---------------------------------------------------------------------------------------------
# Phase I.2.2L - source-verification button: URL resolution priority + keyboard wiring
# ---------------------------------------------------------------------------------------------


async def _seed_review_with_source_snapshot(
    db_session: AsyncSession, *, anchor_event: NewsEvent, canonical_url: str | None = None,
) -> EventRecapReview:
    """A real EventRecapReview whose EditorialTask.workflow already carries a persisted
    `event_recap_source_snapshot` step result naming `anchor_event` as the anchor - exactly the
    shape `services/event_recap_processor.py::_persist_source_snapshot()` writes before synthesis
    ever runs (see that function's own `result={"story_id": ..., "anchor_event_id": ...}` shape).
    Optionally also seeds a `NewsEventArticleAcquisition.canonical_url` row for that same event."""
    task_read = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=anchor_event.id, workflow_type=WorkflowType.EVENT_RECAP, priority=TaskPriority.C),
    )
    task = await db_session.get(EditorialTask, task_read.id)
    workflow = dict(task.workflow or {})
    workflow["step_results"] = [
        {
            "step_name": "event_recap_source_snapshot", "status": "SUCCESS", "attempt": 1,
            "started_at": None, "finished_at": None, "error": None,
            "result": {
                "story_id": str(uuid.uuid4()), "anchor_event_id": str(anchor_event.id),
                "verified_facts": [], "source_refs": [],
            },
        },
        *workflow.get("step_results", []),
    ]
    task.workflow = workflow
    await db_session.flush()

    if canonical_url is not None:
        db_session.add(
            NewsEventArticleAcquisition(
                news_event_id=anchor_event.id, canonical_url=canonical_url,
                acquisition_status=ACQUISITION_STATUS_FULL_TEXT,
                effective_completeness_status=ACQUISITION_STATUS_FULL_TEXT,
                cleaning_version="test", triggered_by=TRIGGERED_BY_CONTENT_GENERATION_SELECTED,
            )
        )
        await db_session.flush()

    return await create_event_recap_review(db_session, recap_task_id=task_read.id)


@pytest.mark.asyncio
async def test_source_url_prefers_canonical_over_raw_anchor_url(db_session: AsyncSession) -> None:
    """Section 10.C: when article acquisition has already resolved a canonical URL for the
    anchor event, the review keyboard's source button must point to THAT URL, never the raw
    (possibly aggregator-wrapper) `NewsEvent.url`."""
    event = await _seed_event(db_session, title="Anchor event")
    event.url = "https://news.google.com/rss/articles/wrapper-link"
    await db_session.flush()
    review = await _seed_review_with_source_snapshot(
        db_session, anchor_event=event, canonical_url="https://real-publisher.example.com/article",
    )
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 900

    await send_event_recap_review(bot, db_session, review, _RECAP_RESULT, dry_run=False)

    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert urls == ["https://real-publisher.example.com/article"]


@pytest.mark.asyncio
async def test_source_url_falls_back_to_raw_anchor_url_without_canonical(db_session: AsyncSession) -> None:
    """Section 10.C fallback leg: no canonical URL has been resolved yet - the anchor event's own
    stored `NewsEvent.url` is used (always populated, a required collector field)."""
    event = await _seed_event(db_session, title="Anchor event, no acquisition yet")
    event.url = "https://www.techmeme.com/260826/p14#a260826p14"
    await db_session.flush()
    review = await _seed_review_with_source_snapshot(db_session, anchor_event=event)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 901

    await send_event_recap_review(bot, db_session, review, _RECAP_RESULT, dry_run=False)

    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert urls == ["https://www.techmeme.com/260826/p14#a260826p14"]


@pytest.mark.asyncio
async def test_source_url_absent_without_source_snapshot_omits_button_safely(db_session: AsyncSession) -> None:
    """Section 10.F: no `event_recap_source_snapshot` step result exists at all (e.g. a review
    seeded like every pre-I.2.2L test in this file) - the keyboard must still deliver safely, with
    only the two decision buttons, never a crash and never a placeholder URL."""
    event = await _seed_event(db_session)
    review = await _seed_review(db_session, event)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 902

    outcome = await send_event_recap_review(bot, db_session, review, _RECAP_RESULT, dry_run=False)

    assert outcome.text_outcome.sent is True
    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 2


@pytest.mark.asyncio
async def test_source_button_survives_the_two_message_media_contract(db_session: AsyncSession) -> None:
    """Section 10.G: photo+text delivery still produces the correct keyboard placement - the
    source button lands on MESSAGE 2 (the text message) only, exactly like the decision buttons,
    never on MESSAGE 1 (the photo)."""
    event, selected_media = await _seed_event_with_image(db_session)
    event.url = "https://example.com/original-anchor-article"
    await db_session.flush()
    review = await _seed_review_with_source_snapshot(db_session, anchor_event=event)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 903
    bot.send_message.return_value.message_id = 904

    await send_event_recap_review(
        bot, db_session, review, _RECAP_RESULT, selected_media=selected_media, dry_run=False,
    )

    assert bot.send_photo.call_args.kwargs.get("reply_markup") is None
    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
    assert urls == ["https://example.com/original-anchor-article"]
