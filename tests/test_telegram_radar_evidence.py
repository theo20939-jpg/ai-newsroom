from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import ACQUISITION_STATUS_FULL_TEXT
from database.models.news_source import NewsSource, SourceType
from services.telegram_radar_evidence import (
    ORIGINAL_ARTIFACT_RESOLVED,
    OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED,
    RADAR_ONLY_NO_ORIGIN,
    TelegramRadarEvidenceStore,
    evaluate_origin_before_generation,
)


class _Store:
    def __init__(self, value):
        self.value = value

    async def get(self, _event_id):
        return self.value

    async def put(self, _event_id, value):
        self.value = value


def _session(event, source):
    session = AsyncMock()

    async def get(model, _identity):
        if model is NewsEvent:
            return event
        if model is NewsSource:
            return source
        raise AssertionError(model)

    session.get.side_effect = get
    return session


@pytest.mark.asyncio
async def test_radar_only_message_fails_closed_before_generation() -> None:
    event_id = uuid4()
    source_id = uuid4()
    session = _session(SimpleNamespace(id=event_id, source_id=source_id), SimpleNamespace(
        id=source_id, type=SourceType.TELEGRAM, category="viral_radar"
    ))
    decision = await evaluate_origin_before_generation(
        session, event_id, evidence_store=_Store({"origin_class": RADAR_ONLY_NO_ORIGIN})
    )
    assert decision.applies is True
    assert decision.allowed is False
    assert decision.reason == "radar_only_no_origin"


@pytest.mark.asyncio
async def test_outbound_origin_uses_existing_acquisition_and_becomes_resolved() -> None:
    event_id = uuid4()
    source_id = uuid4()
    event = SimpleNamespace(id=event_id, source_id=source_id, url="https://example.org/story")
    session = _session(event, SimpleNamespace(
        id=source_id, type=SourceType.TELEGRAM, category="viral_radar"
    ))
    store = _Store({"origin_class": OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED})
    acquisition = SimpleNamespace(
        acquisition_status=ACQUISITION_STATUS_FULL_TEXT,
        canonical_url="https://example.org/canonical",
    )
    with patch("services.telegram_radar_evidence.get_or_acquire", new=AsyncMock(return_value=acquisition)):
        decision = await evaluate_origin_before_generation(session, event_id, evidence_store=store)
    assert decision.allowed is True
    assert decision.origin_class == ORIGINAL_ARTIFACT_RESOLVED
    assert store.value["origin_class"] == ORIGINAL_ARTIFACT_RESOLVED
    assert store.value["resolved_origin_url"] == "https://example.org/canonical"


@pytest.mark.asyncio
async def test_non_radar_source_is_unchanged() -> None:
    event_id = uuid4()
    source_id = uuid4()
    session = _session(SimpleNamespace(id=event_id, source_id=source_id), SimpleNamespace(
        id=source_id, type=SourceType.RSS, category="ai"
    ))
    decision = await evaluate_origin_before_generation(session, event_id, evidence_store=_Store(None))
    assert decision.applies is False
    assert decision.allowed is True
