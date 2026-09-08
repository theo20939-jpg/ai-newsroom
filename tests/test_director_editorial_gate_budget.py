"""DIRECTOR-CONTROL-PLANE-1A §29: gate budget tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_editorial_decision import DirectorEditorialDecision, EditorialGateDecision
from services.director_editorial_gate_budget import (
    STAGE_2_DIRECTOR_VERSION_MARKER,
    GateLLMBudgetDecision,
    check_gate_llm_budget,
)

_NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_budget_allows_when_under_the_daily_limit(db_session: AsyncSession) -> None:
    result = await check_gate_llm_budget(db_session, now=_NOW)
    assert result.allowed is True
    assert result.decision == GateLLMBudgetDecision.ALLOWED


@pytest.mark.asyncio
async def test_budget_blocks_once_the_daily_limit_is_reached(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "director_editorial_gate_max_llm_reviews_per_day", 2)
    for _ in range(2):
        db_session.add(DirectorEditorialDecision(
            story_id=None, event_id=None, platform="telegram", decision=EditorialGateDecision.SEND_TO_EDITOR,
            priority=50, reason_codes=[], short_reason="test", director="channel_director",
            director_version=STAGE_2_DIRECTOR_VERSION_MARKER, context_fingerprint="x", created_at=_NOW,
        ))
    await db_session.flush()

    result = await check_gate_llm_budget(db_session, now=_NOW)
    assert result.allowed is False
    assert result.decision == GateLLMBudgetDecision.DAILY_LIMIT_REACHED
    assert result.reviews_today == 2


@pytest.mark.asyncio
async def test_budget_only_counts_stage_2_marked_decisions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "director_editorial_gate_max_llm_reviews_per_day", 1)
    db_session.add(DirectorEditorialDecision(
        story_id=None, event_id=None, platform="telegram", decision=EditorialGateDecision.SEND_TO_EDITOR,
        priority=50, reason_codes=[], short_reason="test", director="channel_director",
        director_version="v1", context_fingerprint="x", created_at=_NOW,  # NOT the Stage-2 marker
    ))
    await db_session.flush()

    result = await check_gate_llm_budget(db_session, now=_NOW)
    assert result.allowed is True
    assert result.reviews_today == 0


def test_default_budget_is_a_real_positive_bound() -> None:
    assert settings.director_editorial_gate_max_llm_reviews_per_day > 0
