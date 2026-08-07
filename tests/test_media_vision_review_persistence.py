"""Phase 19 M13: services.media_vision_review_persistence - fake-session unit tests, mirrors
tests/test_editorial_plan_persistence.py's own established pattern.
"""
from __future__ import annotations

import uuid

import pytest

from services.media_vision_review_persistence import persist_media_vision_review


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
