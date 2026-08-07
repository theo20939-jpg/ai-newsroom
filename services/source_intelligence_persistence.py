"""Phase 19 M8: the sole place that constructs/persists a NewsEventSourceIntelligence row.

Exists specifically so capabilities/executor.py never imports database.models.
news_event_source_intelligence directly - mirrors services/editorial_plan_persistence.py's own
exact rationale and shape.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event_source_intelligence import NewsEventSourceIntelligence


async def persist_source_intelligence(
    session: AsyncSession,
    *,
    news_event_id: UUID,
    role: str,
    is_first_in_story: bool,
    match_type: str | None,
    reliability_score: float | None,
) -> None:
    """Adds one NewsEventSourceIntelligence row to `session` (does not commit - the caller's own
    SAVEPOINT/commit discipline governs that, exactly as every other Phase 19 shadow write does)."""
    row = NewsEventSourceIntelligence(
        news_event_id=news_event_id, role=role, is_first_in_story=is_first_in_story,
        match_type=match_type, reliability_score=reliability_score,
    )
    session.add(row)
