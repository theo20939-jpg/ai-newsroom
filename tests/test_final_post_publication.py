"""PRESENTATION RECOVERY (2026-09-02), Phase I.3: services.final_post_publication tests.

Reuses tests/test_final_post_review_eligibility.py::_seed_setup() (the established, realistic
ContentDraft+EditorialTask+step_results fixture) and tests/test_final_post_review_notifier.py's
own `_branded_fallback_media_plan()` (real storage-backed media, no candidate-row dependency) -
never a third, divergent fixture set for the same eligible-draft shape.
"""
from __future__ import annotations

import uuid

import pytest
from unittest.mock import AsyncMock

from core.config import settings
from database.models.final_post_review import FinalPostReviewStatus
from services import image_persistence
from services.final_post_publication import publish_approved_final_post
from services.final_post_review_notifier import resolve_final_post_photo_input, send_final_post_preview
from services.final_post_review_service import create_final_post_review, get_final_post_review, set_decision
from tests.test_final_post_review_eligibility import _seed_setup
from tests.test_final_post_review_notifier import _branded_fallback_media_plan


@pytest.fixture(autouse=True)
def _isolated_image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_route() is called unconditionally before the dry_run short-circuit (services/
    telegram_routing.py), so even a dry-run publish needs a resolvable NEWS/TELEGRAPH destination."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "news_topic_id", 2)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)


async def _seed_approved(db_session, *, media_plan=None):
    draft, _task = await _seed_setup(db_session, media_plan=media_plan if media_plan is not None else _branded_fallback_media_plan())
    review = await create_final_post_review(db_session, content_draft_id=draft.id)
    review = await set_decision(
        db_session, review.id, FinalPostReviewStatus.APPROVED_FOR_PUBLICATION, decided_by_user_id=1,
    )
    return draft, review


@pytest.mark.asyncio
async def test_review_not_found_is_not_approved():
    bot = AsyncMock()
    session = AsyncMock()
    session.get.return_value = None
    outcome = await publish_approved_final_post(session, bot, uuid.uuid4(), live=False)
    assert outcome.status == "not_approved"
    bot.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_pending_review_is_not_approved(db_session):
    draft, _task = await _seed_setup(db_session, media_plan=_branded_fallback_media_plan())
    review = await create_final_post_review(db_session, content_draft_id=draft.id)  # stays PENDING
    bot = AsyncMock()

    outcome = await publish_approved_final_post(db_session, bot, review.id, live=True)

    assert outcome.status == "not_approved"
    bot.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_is_the_default_and_makes_no_real_send(db_session):
    _draft, review = await _seed_approved(db_session)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 999

    outcome = await publish_approved_final_post(db_session, bot, review.id, live=False)

    assert outcome.status == "dry_run"
    refreshed = await get_final_post_review(db_session, review.id)
    assert refreshed.published_at is None  # dry-run never records a delivery


@pytest.mark.asyncio
async def test_live_send_without_the_enable_flag_is_still_a_dry_run(db_session, monkeypatch: pytest.MonkeyPatch):
    """Two-factor confirmation: `live=True` alone is not enough - `settings.final_post_publication_
    enabled` (default False, never flipped by this phase) must also be True."""
    monkeypatch.setattr(settings, "final_post_publication_enabled", False)
    _draft, review = await _seed_approved(db_session)
    bot = AsyncMock()

    outcome = await publish_approved_final_post(db_session, bot, review.id, live=True)

    assert outcome.status == "dry_run"


@pytest.mark.asyncio
async def test_live_send_with_flag_enabled_publishes_and_records_delivery(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "final_post_publication_enabled", True)
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    _draft, review = await _seed_approved(db_session)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 777

    outcome = await publish_approved_final_post(db_session, bot, review.id, live=True)

    assert outcome.status == "published"
    assert outcome.telegram_message_id == 777
    bot.send_photo.assert_called_once()

    refreshed = await get_final_post_review(db_session, review.id)
    assert refreshed.published_at is not None
    assert refreshed.published_telegram_message_id == 777
    assert refreshed.published_telegram_chat_id == -100123456789
    # status/decided_* stay owned exclusively by the human-decision gate - never touched here.
    assert refreshed.status == FinalPostReviewStatus.APPROVED_FOR_PUBLICATION


@pytest.mark.asyncio
async def test_already_published_is_idempotent_never_sends_twice(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "final_post_publication_enabled", True)
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    _draft, review = await _seed_approved(db_session)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 888

    first = await publish_approved_final_post(db_session, bot, review.id, live=True)
    assert first.status == "published"

    second = await publish_approved_final_post(db_session, bot, review.id, live=True)
    assert second.status == "already_published"
    assert second.telegram_message_id == 888
    bot.send_photo.assert_called_once()  # never a second real send


@pytest.mark.asyncio
async def test_media_resolution_failure_never_publishes(db_session):
    broken_plan = {
        "tier": "story_pool",
        "representative": {
            "candidate_id": "vanished", "originating_event_id": str(uuid.uuid4()), "media_type": "image",
            "recommended_role": "hero", "storage_key": None, "telegram_file_id": None, "sha256": None, "remote_url": None,
        },
    }
    _draft, review = await _seed_approved(db_session, media_plan=broken_plan)
    bot = AsyncMock()

    outcome = await publish_approved_final_post(db_session, bot, review.id, live=True)

    assert outcome.status == "media_resolution_failed"
    bot.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_publication_payload_is_byte_identical_to_the_preview_payload(db_session, monkeypatch: pytest.MonkeyPatch):
    """WYSIWYG equivalence proof (plan review correction 2): the preview send and the real publish
    resolve the exact same media bytes, caption, and keyboard from the exact same underlying
    ContentDraft/final_post_source - proving one shared implementation, not two independently
    re-derived presentations, for identical input."""
    monkeypatch.setattr(settings, "final_post_publication_enabled", True)
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)
    draft, review = await _seed_approved(db_session)

    from database.models.editorial_task import EditorialTask
    from services.final_post_review_eligibility import check_final_post_preview_eligibility

    eligibility = await check_final_post_preview_eligibility(db_session, draft.id)
    assert eligibility.eligible

    preview_bot = AsyncMock()
    preview_bot.send_photo.return_value.message_id = 111
    preview_bot.send_message.return_value.message_id = 112
    preview_outcome = await send_final_post_preview(
        preview_bot, db_session, review, title=draft.title, body=draft.body,
        final_post_source=eligibility.final_post_source, authoring_prompt_version="2",
        fact_safety_status="pass", dry_run=False,
    )
    assert preview_outcome.status == "sent"
    preview_photo_kwargs = preview_bot.send_photo.call_args.kwargs

    publish_bot = AsyncMock()
    publish_bot.send_photo.return_value.message_id = 222
    publish_outcome = await publish_approved_final_post(db_session, publish_bot, review.id, live=True)
    assert publish_outcome.status == "published"
    publish_photo_kwargs = publish_bot.send_photo.call_args.kwargs

    assert preview_photo_kwargs["caption"] == publish_photo_kwargs["caption"]

    preview_keyboard, publish_keyboard = preview_photo_kwargs["reply_markup"], publish_photo_kwargs["reply_markup"]
    preview_texts = [b.text for row in preview_keyboard.inline_keyboard for b in row]
    publish_texts = [b.text for row in publish_keyboard.inline_keyboard for b in row]
    assert preview_texts == publish_texts

    preview_photo, publish_photo = preview_photo_kwargs["photo"], publish_photo_kwargs["photo"]
    assert preview_photo.data == publish_photo.data  # byte-identical branded media
