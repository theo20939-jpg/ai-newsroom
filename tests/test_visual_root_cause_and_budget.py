"""VISUAL-DESIGN-AUTONOMY-1, spec §69/§70: root-cause classification and attempt/cost budget
enforcement tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_design_attempt import VisualDesignAttempt, VisualFailureRootCause
from services.telegram_art_director import ArtDirectorIssueCode
from services.visual_budget_service import BudgetDecision, check_budget, max_attempts_for
from services.visual_root_cause import classify_root_cause


def test_factual_issue_always_wins_priority() -> None:
    assert classify_root_cause([ArtDirectorIssueCode.NUMBER_MISMATCH, ArtDirectorIssueCode.VISUAL_TOO_BUSY]) == VisualFailureRootCause.FACTUAL


def test_source_media_issue_routes_away_from_generation() -> None:
    assert classify_root_cause([ArtDirectorIssueCode.MEDIA_LOW_QUALITY]) == VisualFailureRootCause.SOURCE_MEDIA
    assert classify_root_cause([ArtDirectorIssueCode.SUBJECT_CROP_BAD]) == VisualFailureRootCause.SOURCE_MEDIA


def test_design_direction_issue_allows_creative_redesign() -> None:
    assert classify_root_cause([ArtDirectorIssueCode.VISUAL_TOO_BUSY]) == VisualFailureRootCause.DESIGN_DIRECTION


def test_unknown_when_no_code_matches() -> None:
    assert classify_root_cause([]) == VisualFailureRootCause.UNKNOWN
    assert classify_root_cause([ArtDirectorIssueCode.UNKNOWN_VISUAL_FAILURE]) == VisualFailureRootCause.UNKNOWN


def test_max_attempts_uses_presentation_override() -> None:
    assert max_attempts_for("DATA") == 3
    assert max_attempts_for("NEWS") == 2
    assert max_attempts_for(None) == 2


@pytest.mark.asyncio
async def test_budget_allows_first_attempt(db_session: AsyncSession) -> None:
    result = await check_budget(db_session, story_id=uuid4(), platform="telegram")
    assert result.decision == BudgetDecision.ALLOWED
    assert result.attempts_used == 0


@pytest.mark.asyncio
async def test_budget_stops_at_attempt_limit(db_session: AsyncSession) -> None:
    story_id = uuid4()
    for i in range(2):
        db_session.add(VisualDesignAttempt(
            story_id=story_id, platform="telegram", attempt_number=i + 1, total_cost=0.01,
        ))
    await db_session.commit()
    result = await check_budget(db_session, story_id=story_id, platform="telegram", presentation_type="NEWS")
    assert result.decision == BudgetDecision.ATTEMPT_LIMIT_REACHED


@pytest.mark.asyncio
async def test_budget_unknown_when_a_prior_attempt_has_no_cost_recorded(db_session: AsyncSession) -> None:
    story_id = uuid4()
    db_session.add(VisualDesignAttempt(story_id=story_id, platform="telegram", attempt_number=1, total_cost=None))
    await db_session.commit()
    result = await check_budget(db_session, story_id=story_id, platform="telegram")
    assert result.decision == BudgetDecision.BUDGET_UNKNOWN
    assert result.post_cost_known is False
    assert result.post_cost_so_far is None  # never a fabricated 0.0


@pytest.mark.asyncio
async def test_budget_exhausted_per_post(db_session: AsyncSession) -> None:
    story_id = uuid4()
    db_session.add(VisualDesignAttempt(story_id=story_id, platform="telegram", attempt_number=1, total_cost=999.0))
    await db_session.commit()
    result = await check_budget(db_session, story_id=story_id, platform="telegram", presentation_type="DATA")
    assert result.decision == BudgetDecision.POST_BUDGET_EXHAUSTED


@pytest.mark.asyncio
async def test_budget_exhausted_daily(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(VisualDesignAttempt(
            story_id=uuid4(), platform="telegram", attempt_number=1, total_cost=10.0,
            created_at=now - timedelta(hours=i),
        ))
    await db_session.commit()
    result = await check_budget(db_session, story_id=uuid4(), platform="telegram", now=now)
    assert result.decision == BudgetDecision.DAILY_BUDGET_EXHAUSTED
