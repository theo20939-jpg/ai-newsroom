"""Tests for services.image_persistence's Phase 16 M6 additions (docs/
phase16_m6_telegram_editorial_preview_report.md §7-8/§11): linking candidates to a ContentDraft,
recording the editor's decision, and resolving stored bytes for the Telegram preview. Real
Postgres (tests/conftest.py's db_session fixture, rolled back per test) + a tmp_path-backed
LocalImageStorage - no network, no LLM, no aiogram/Bot type anywhere in this file.
"""
import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.image_candidate_record import ImageCandidateRecord, ImageEditorDecision
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from integrations.storage.image_storage import LocalImageStorage
from services import image_persistence
from services.image_persistence import EditorialImageCandidate

_DATA = b"fake-stored-bytes-for-m6-persistence-tests"
_SHA256 = hashlib.sha256(_DATA).hexdigest()


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


async def _make_task(db_session: AsyncSession, real_news_event: NewsEvent) -> EditorialTask:
    task = EditorialTask(event_id=real_news_event.id, priority=TaskPriority.B)
    db_session.add(task)
    await db_session.flush()
    return task


async def _make_draft(db_session: AsyncSession, task: EditorialTask) -> ContentDraft:
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title="t", body="b", hashtags=[])
    db_session.add(draft)
    await db_session.flush()
    return draft


async def _make_candidate_row(
    db_session: AsyncSession, *, news_event_id, editorial_task_id=None, candidate_id: str = "c1",
    content_draft_id=None, storage_status=None, storage_key: str | None = None,
) -> ImageCandidateRecord:
    from database.models.image_candidate_record import ImageStorageStatus

    row = ImageCandidateRecord(
        candidate_id=candidate_id, news_event_id=news_event_id, editorial_task_id=editorial_task_id,
        content_draft_id=content_draft_id, source_type=SourceType.RSS, discovery_method="open_graph_image",
        eligible_for_editorial=True, rank=1,
        storage_status=storage_status or ImageStorageStatus.NOT_REQUESTED, storage_key=storage_key,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_link_candidates_to_content_draft_updates_matching_rows(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)
    row = await _make_candidate_row(db_session, news_event_id=real_news_event.id, editorial_task_id=task.id)

    count = await image_persistence.link_candidates_to_content_draft(
        db_session, editorial_task_id=task.id, content_draft_id=draft.id
    )

    assert count == 1
    await db_session.refresh(row)
    assert row.content_draft_id == draft.id


@pytest.mark.asyncio
async def test_link_candidates_to_content_draft_is_scoped_to_one_task(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task_a = await _make_task(db_session, real_news_event)
    task_b = await _make_task(db_session, real_news_event)
    draft_a = await _make_draft(db_session, task_a)
    row_a = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task_a.id, candidate_id="a"
    )
    row_b = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task_b.id, candidate_id="b"
    )

    await image_persistence.link_candidates_to_content_draft(
        db_session, editorial_task_id=task_a.id, content_draft_id=draft_a.id
    )

    await db_session.refresh(row_a)
    await db_session.refresh(row_b)
    assert row_a.content_draft_id == draft_a.id
    assert row_b.content_draft_id is None  # a different task's own candidate is never touched


@pytest.mark.asyncio
async def test_link_candidates_returns_zero_when_nothing_matches(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)

    count = await image_persistence.link_candidates_to_content_draft(
        db_session, editorial_task_id=task.id, content_draft_id=draft.id
    )
    assert count == 0


@pytest.mark.asyncio
async def test_set_editor_decision_selects_one_and_rejects_siblings(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)
    row_1 = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id,
        candidate_id="c1", content_draft_id=draft.id,
    )
    row_2 = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id,
        candidate_id="c2", content_draft_id=draft.id,
    )

    ok = await image_persistence.set_editor_decision(
        db_session, content_draft_id=draft.id, candidate_row_id=row_1.id
    )

    assert ok is True
    await db_session.refresh(row_1)
    await db_session.refresh(row_2)
    assert row_1.editor_decision == ImageEditorDecision.SELECTED
    assert row_1.editor_decision_at is not None
    assert row_2.editor_decision == ImageEditorDecision.REJECTED


@pytest.mark.asyncio
async def test_set_editor_decision_is_idempotent(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)
    row = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )

    first = await image_persistence.set_editor_decision(db_session, content_draft_id=draft.id, candidate_row_id=row.id)
    second = await image_persistence.set_editor_decision(db_session, content_draft_id=draft.id, candidate_row_id=row.id)

    assert first is True
    assert second is True
    await db_session.refresh(row)
    assert row.editor_decision == ImageEditorDecision.SELECTED


@pytest.mark.asyncio
async def test_set_editor_decision_rejects_candidate_from_a_different_draft(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """A callback referencing a real row.id that does not belong to the given content_draft_id
    (e.g. tampered/replayed callback_data) must never be silently applied."""
    task = await _make_task(db_session, real_news_event)
    draft_a = await _make_draft(db_session, task)
    draft_b = await _make_draft(db_session, task)
    row = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft_b.id,
    )

    ok = await image_persistence.set_editor_decision(
        db_session, content_draft_id=draft_a.id, candidate_row_id=row.id
    )

    assert ok is False
    await db_session.refresh(row)
    assert row.editor_decision is None


@pytest.mark.asyncio
async def test_set_editor_decision_rejects_nonexistent_row_id(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)

    ok = await image_persistence.set_editor_decision(
        db_session, content_draft_id=draft.id, candidate_row_id=uuid.uuid4()
    )
    assert ok is False


@pytest.mark.asyncio
async def test_reject_all_candidates_marks_every_row_rejected(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)
    row_1 = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id,
        candidate_id="c1", content_draft_id=draft.id,
    )
    row_2 = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id,
        candidate_id="c2", content_draft_id=draft.id,
    )

    count = await image_persistence.reject_all_candidates(db_session, content_draft_id=draft.id)

    assert count == 2
    await db_session.refresh(row_1)
    await db_session.refresh(row_2)
    assert row_1.editor_decision == ImageEditorDecision.REJECTED
    assert row_2.editor_decision == ImageEditorDecision.REJECTED


@pytest.mark.asyncio
async def test_reject_all_candidates_is_idempotent_and_overrides_a_prior_selection(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)
    row = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )
    await image_persistence.set_editor_decision(db_session, content_draft_id=draft.id, candidate_row_id=row.id)

    await image_persistence.reject_all_candidates(db_session, content_draft_id=draft.id)

    await db_session.refresh(row)
    assert row.editor_decision == ImageEditorDecision.REJECTED


def _fake_candidate(**overrides) -> EditorialImageCandidate:
    base = dict(
        id=uuid.uuid4(), candidate_id="c1", rank=1, relevance_score=80, quality_score=80,
        discovery_method="open_graph_image", source_relationship="same_article",
        relevance_reason="strong metadata overlap", width=800, height=600,
        observed_mime="image/jpeg", image_format="JPEG", storage_status="not_requested",
        storage_key=None, telegram_file_id=None, editor_decision=None,
        source_url="https://example.com/a", article_url="https://example.com/article",
        warnings=None, is_expired=False,
    )
    base.update(overrides)
    return EditorialImageCandidate(**base)


def test_read_candidate_bytes_returns_none_when_not_stored() -> None:
    candidate = _fake_candidate(storage_status="not_requested", storage_key=None)
    assert image_persistence.read_candidate_bytes(candidate) is None


def test_read_candidate_bytes_returns_none_when_stored_but_no_key() -> None:
    candidate = _fake_candidate(storage_status="stored", storage_key=None)
    assert image_persistence.read_candidate_bytes(candidate) is None


def test_read_candidate_bytes_reads_real_stored_bytes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)

    candidate = _fake_candidate(storage_status="stored", storage_key=stored.storage_key)
    result = image_persistence.read_candidate_bytes(candidate)

    assert result == _DATA


def test_read_candidate_bytes_returns_none_when_file_is_missing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)

    candidate = _fake_candidate(storage_status="stored", storage_key="images/ab/does-not-exist.jpg")
    result = image_persistence.read_candidate_bytes(candidate)

    assert result is None


def test_read_candidate_bytes_rejects_path_traversal_key(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a malformed/unexpected storage_key (which should never occur given
    build_storage_key()'s own trusted-generation guarantee) can never escape the storage root."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)

    candidate = _fake_candidate(storage_status="stored", storage_key="../../etc/passwd")
    result = image_persistence.read_candidate_bytes(candidate)

    assert result is None


@pytest.mark.asyncio
async def test_record_telegram_file_id_persists_the_value(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    row = await _make_candidate_row(db_session, news_event_id=real_news_event.id, editorial_task_id=task.id)

    await image_persistence.record_telegram_file_id(db_session, candidate_row_id=row.id, file_id="AgACAgIAAx")

    await db_session.refresh(row)
    assert row.telegram_file_id == "AgACAgIAAx"


@pytest.mark.asyncio
async def test_get_editorial_image_candidates_exposes_m6_fields(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _make_task(db_session, real_news_event)
    draft = await _make_draft(db_session, task)
    row = await _make_candidate_row(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
    )
    row.relevance_reason = "strong metadata overlap"
    row.telegram_file_id = "AgACAgIAAx"
    await db_session.flush()
    await image_persistence.set_editor_decision(db_session, content_draft_id=draft.id, candidate_row_id=row.id)

    candidates = await image_persistence.get_editorial_image_candidates(db_session, content_draft_id=draft.id)

    assert len(candidates) == 1
    assert candidates[0].relevance_reason == "strong metadata overlap"
    assert candidates[0].telegram_file_id == "AgACAgIAAx"
    assert candidates[0].editor_decision == "selected"
