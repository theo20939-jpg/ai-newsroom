"""Phase 19 M13: services.media_vision_review_persistence - fake-session unit tests, mirrors
tests/test_editorial_plan_persistence.py's own established pattern.

MEDIA-PROD-1: real-Postgres tests for get_media_vision_review_calibration_summary() below (a
fake session can't exercise a real select() aggregation) - mirrors tests/
test_image_persistence_m6.py's own db_session/real_news_event/ImageCandidateRecord setup.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from services.media_vision_review_persistence import (
    get_media_vision_review_calibration_summary,
    persist_media_vision_review,
)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


@pytest.mark.asyncio
async def test_persists_one_row_with_expected_fields() -> None:
    session = _FakeSession()
    candidate_id = uuid.uuid4()
    structured_output = {
        "relevant_to_story": True, "source_logo_present": False, "watermark_present": True,
        "website_or_social_ui_present": False, "advertisement_or_banner_present": False,
        "readable_quality": "acceptable", "recommended_role": "supporting",
    }

    await persist_media_vision_review(session, image_candidate_id=candidate_id, structured_output=structured_output)

    assert len(session.added) == 1
    row = session.added[0]
    assert row.image_candidate_id == candidate_id
    assert row.relevant_to_story is True
    assert row.watermark_present is True
    assert row.readable_quality == "acceptable"
    assert row.recommended_role == "supporting"


async def _make_candidate_row(db_session: AsyncSession, *, news_event_id, candidate_id: str) -> ImageCandidateRecord:
    row = ImageCandidateRecord(
        candidate_id=candidate_id, news_event_id=news_event_id, editorial_task_id=None,
        content_draft_id=None, source_type=SourceType.RSS, discovery_method="open_graph_image",
        eligible_for_editorial=True, rank=1, storage_status=ImageStorageStatus.NOT_REQUESTED, storage_key=None,
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _output(**overrides) -> dict:
    base = {
        "relevant_to_story": True, "source_logo_present": False, "watermark_present": False,
        "website_or_social_ui_present": False, "advertisement_or_banner_present": False,
        "readable_quality": "good", "recommended_role": "hero",
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_calibration_summary_is_empty_when_no_reviews_exist(db_session: AsyncSession) -> None:
    summary = await get_media_vision_review_calibration_summary(db_session)
    assert summary.total_reviews == 0
    assert summary.would_flag_count == 0
    assert summary.recommended_role_counts == {}


@pytest.mark.asyncio
async def test_calibration_summary_tallies_flags_and_role_breakdown(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    watermarked = await _make_candidate_row(db_session, news_event_id=real_news_event.id, candidate_id="c1")
    clean_hero = await _make_candidate_row(db_session, news_event_id=real_news_event.id, candidate_id="c2")
    rejected = await _make_candidate_row(db_session, news_event_id=real_news_event.id, candidate_id="c3")

    await persist_media_vision_review(
        db_session, image_candidate_id=watermarked.id,
        structured_output=_output(watermark_present=True, recommended_role="supporting"),
    )
    await persist_media_vision_review(
        db_session, image_candidate_id=clean_hero.id, structured_output=_output(recommended_role="hero"),
    )
    await persist_media_vision_review(
        db_session, image_candidate_id=rejected.id,
        structured_output=_output(recommended_role="reject", readable_quality="poor"),
    )
    await db_session.flush()

    summary = await get_media_vision_review_calibration_summary(db_session)

    assert summary.total_reviews == 3
    assert summary.watermark_present_count == 1
    assert summary.would_flag_count == 2  # the watermarked one + the rejected one, not the clean hero
    assert summary.recommended_role_counts == {"supporting": 1, "hero": 1, "reject": 1}
    assert summary.readable_quality_counts == {"good": 2, "poor": 1}


@pytest.mark.asyncio
async def test_calibration_summary_since_filter_excludes_old_reviews(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    from datetime import datetime, timedelta, timezone

    candidate = await _make_candidate_row(db_session, news_event_id=real_news_event.id, candidate_id="c1")
    await persist_media_vision_review(db_session, image_candidate_id=candidate.id, structured_output=_output())
    await db_session.flush()

    future_cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    summary = await get_media_vision_review_calibration_summary(db_session, since=future_cutoff)
    assert summary.total_reviews == 0  # the just-created row is older than a future cutoff
