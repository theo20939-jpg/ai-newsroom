"""VISUAL-DESIGN-AUTONOMY-1, spec §71: brief adaptation evidence gate - single failure never
triggers adaptation, POSSIBLE_SIGNAL never auto-promotes, REPEATED_PATTERN can create a candidate,
freeze prevents auto-promotion, cooldown prevents oscillation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_design_attempt import VisualDesignAttempt
from services.visual_brief_adaptation_service import EvidenceStage, detect_repeated_pattern, may_create_candidate
from services.visual_designer_brief_service import create_initial_brief, freeze_brief


async def _attempt_with_issue(db_session: AsyncSession, brief, issue_code: str) -> None:
    db_session.add(VisualDesignAttempt(
        platform="telegram", presentation_type="NEWS", brief_version_id=brief.id, attempt_number=1,
        issue_codes=[issue_code],
    ))
    await db_session.flush()


@pytest.mark.asyncio
async def test_single_failure_is_anomaly_not_repeated_pattern(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="news", brief_text="v1")
    await _attempt_with_issue(db_session, brief, "visual_too_busy")
    evidence = await detect_repeated_pattern(db_session, "news")
    assert evidence is not None
    assert evidence.stage == EvidenceStage.ANOMALY


@pytest.mark.asyncio
async def test_two_occurrences_is_possible_signal_not_repeated_pattern(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(2):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    evidence = await detect_repeated_pattern(db_session, "data")
    assert evidence is not None
    assert evidence.stage == EvidenceStage.POSSIBLE_SIGNAL


@pytest.mark.asyncio
async def test_three_occurrences_reaches_repeated_pattern(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="quote", brief_text="v1")
    for _ in range(3):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    evidence = await detect_repeated_pattern(db_session, "quote")
    assert evidence is not None
    assert evidence.stage == EvidenceStage.REPEATED_PATTERN
    assert evidence.occurrences == 3


@pytest.mark.asyncio
async def test_may_create_candidate_false_when_flag_disabled(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "visual_brief_auto_adaptation_enabled", False)
    brief = await create_initial_brief(db_session, scope="breaking", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    allowed, reason = await may_create_candidate(db_session, "breaking")
    assert allowed is False
    assert "auto_adaptation_enabled" in reason


@pytest.mark.asyncio
async def test_may_create_candidate_requires_repeated_pattern(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "visual_brief_auto_adaptation_enabled", True)
    brief = await create_initial_brief(db_session, scope="carousel", brief_text="v1")
    await _attempt_with_issue(db_session, brief, "visual_too_busy")  # only 1 - ANOMALY
    allowed, reason = await may_create_candidate(db_session, "carousel")
    assert allowed is False
    assert "REPEATED_PATTERN" in reason

    for _ in range(2):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")  # now 3 total - REPEATED_PATTERN
    allowed, reason = await may_create_candidate(db_session, "carousel")
    assert allowed is True


@pytest.mark.asyncio
async def test_frozen_brief_never_auto_adapts(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "visual_brief_auto_adaptation_enabled", True)
    brief = await create_initial_brief(db_session, scope="reel", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    await freeze_brief(db_session, "reel", reason="founder request")
    allowed, reason = await may_create_candidate(db_session, "reel")
    assert allowed is False
    assert "FROZEN" in reason


@pytest.mark.asyncio
async def test_cooldown_blocks_repeated_adaptation_within_window(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    from services.visual_designer_brief_service import create_candidate_brief

    monkeypatch.setattr(settings, "visual_brief_auto_adaptation_enabled", True)
    brief = await create_initial_brief(db_session, scope="single", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    await create_candidate_brief(db_session, scope="single", brief_text="v2", reason="repeated busy")

    allowed, reason = await may_create_candidate(db_session, "single", now=datetime.now(timezone.utc))
    assert allowed is False
    assert "cooldown" in reason

    later = datetime.now(timezone.utc) + timedelta(hours=25)
    allowed, _ = await may_create_candidate(db_session, "single", now=later)
    assert allowed is True
