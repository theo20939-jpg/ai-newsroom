"""Durable Telegram radar evidence and fail-closed origin resolution for Phase 2B."""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.redis import get_redis_client
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FETCH_FAILED,
    ACQUISITION_STATUS_REDIRECT_UNRESOLVED,
    ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE,
    TRIGGERED_BY_CONTENT_GENERATION_SELECTED,
)
from database.models.news_source import NewsSource, SourceType
from services.article_acquisition import get_or_acquire

ORIGINAL_ARTIFACT_RESOLVED = "ORIGINAL_ARTIFACT_RESOLVED"
OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED = "OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED"
RADAR_ONLY_NO_ORIGIN = "RADAR_ONLY_NO_ORIGIN"
TELEGRAM_POST_IS_ITSELF_THE_PRIMARY_ARTIFACT = "TELEGRAM_POST_IS_ITSELF_THE_PRIMARY_ARTIFACT"
RADAR_SOURCE_CATEGORY = "viral_radar"
_KEY_PREFIX = "ninja:pulse:telegram:evidence:v1"
_UNRESOLVED_STATUSES = frozenset({
    ACQUISITION_STATUS_FETCH_FAILED,
    ACQUISITION_STATUS_REDIRECT_UNRESOLVED,
    ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE,
})


class TelegramRadarEvidenceStore:
    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client if redis_client is not None else get_redis_client()

    @staticmethod
    def key_for(event_id: UUID) -> str:
        return f"{_KEY_PREFIX}:{event_id}"

    async def put(self, event_id: UUID, evidence: dict[str, object]) -> None:
        await self._redis.set(
            self.key_for(event_id),
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    async def get(self, event_id: UUID) -> dict[str, object] | None:
        raw = await self._redis.get(self.key_for(event_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(raw)
        return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class TelegramRadarOriginDecision:
    applies: bool
    allowed: bool
    origin_class: str | None
    reason: str


async def evaluate_origin_before_generation(
    session: AsyncSession,
    event_id: UUID,
    *,
    evidence_store: TelegramRadarEvidenceStore | None = None,
) -> TelegramRadarOriginDecision:
    """Resolve an explicit outbound artifact before paid generation; radar-only fails closed."""
    event = await session.get(NewsEvent, event_id)
    if event is None:
        return TelegramRadarOriginDecision(False, True, None, "event_not_found")
    source = await session.get(NewsSource, event.source_id)
    if source is None or source.type != SourceType.TELEGRAM or source.category != RADAR_SOURCE_CATEGORY:
        return TelegramRadarOriginDecision(False, True, None, "not_a_managed_radar_source")

    store = evidence_store or TelegramRadarEvidenceStore()
    try:
        evidence = await store.get(event_id)
    except Exception:
        return TelegramRadarOriginDecision(True, False, None, "radar_evidence_unavailable")
    if evidence is None:
        return TelegramRadarOriginDecision(True, False, None, "radar_evidence_missing")

    origin_class = evidence.get("origin_class")
    if origin_class == TELEGRAM_POST_IS_ITSELF_THE_PRIMARY_ARTIFACT:
        return TelegramRadarOriginDecision(True, True, str(origin_class), "telegram_primary_artifact")
    if origin_class == ORIGINAL_ARTIFACT_RESOLVED:
        return TelegramRadarOriginDecision(True, True, str(origin_class), "origin_already_resolved")
    if origin_class != OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED:
        return TelegramRadarOriginDecision(True, False, str(origin_class), "radar_only_no_origin")

    acquisition = await get_or_acquire(
        session, event, triggered_by=TRIGGERED_BY_CONTENT_GENERATION_SELECTED
    )
    await session.flush()
    if acquisition.acquisition_status in _UNRESOLVED_STATUSES:
        return TelegramRadarOriginDecision(
            True,
            False,
            OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED,
            f"origin_acquisition_{acquisition.acquisition_status.lower()}",
        )

    # The acquisition row is the durable truth. Commit it before promoting the Redis evidence;
    # a crash can therefore leave B+resolved-row (safely repaired on retry), never A without the
    # corresponding persisted acquisition.
    await session.commit()
    evidence["origin_class"] = ORIGINAL_ARTIFACT_RESOLVED
    evidence["resolved_origin_url"] = acquisition.canonical_url or event.url
    try:
        await store.put(event_id, evidence)
    except Exception:
        return TelegramRadarOriginDecision(
            True, False, OUTBOUND_LINK_PRESENT_BUT_NOT_RESOLVED, "resolved_evidence_persistence_failed"
        )
    return TelegramRadarOriginDecision(True, True, ORIGINAL_ARTIFACT_RESOLVED, "origin_resolved")
