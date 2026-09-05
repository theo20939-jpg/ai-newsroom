"""VISUAL-DESIGN-AUTONOMY-1, spec §43/§76: DesignConsoleService tests - health status transitions,
budget display, and read-purity (opening /design never writes/mutates/calls a Gateway)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRun
from database.models.visual_design_attempt import VisualDesignAttempt, VisualDesignAttemptStatus
from database.models.visual_designer_brief import VisualDesignerBriefVersion
from services.visual_design_console_service import (
    VisualHealthStatus,
    build_design_scope_detail_view,
    build_design_view,
)
from services.visual_designer_brief_service import create_initial_brief, freeze_brief


async def _attempt(db_session: AsyncSession, brief: VisualDesignerBriefVersion, *, status: VisualDesignAttemptStatus, art_decision: str | None = None, issue_codes: list[str] | None = None) -> None:
    db_session.add(VisualDesignAttempt(
        platform="telegram", presentation_type="NEWS", brief_version_id=brief.id, attempt_number=1,
        status=status, art_decision=art_decision, issue_codes=issue_codes,
    ))
    await db_session.flush()


@pytest.mark.asyncio
async def test_view_is_empty_with_no_briefs_at_all(db_session: AsyncSession) -> None:
    view = await build_design_view(db_session, now=datetime.now(timezone.utc))
    assert view.scopes == []


@pytest.mark.asyncio
async def test_new_scope_with_no_attempts_is_insufficient_data(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="quote", brief_text="v1")
    view = await build_design_view(db_session, now=datetime.now(timezone.utc))
    quote = next(s for s in view.scopes if s.scope == "quote")
    assert quote.active_brief_version == 1
    assert quote.health.status == VisualHealthStatus.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_mostly_passing_attempts_are_healthy(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="news", brief_text="v1")
    for _ in range(5):
        await _attempt(db_session, brief, status=VisualDesignAttemptStatus.PASSED, art_decision="pass")
    view = await build_design_view(db_session, now=datetime.now(timezone.utc))
    news = next(s for s in view.scopes if s.scope == "news")
    assert news.health.status == VisualHealthStatus.HEALTHY
    assert news.health.pass_count == 5


@pytest.mark.asyncio
async def test_high_rework_rate_is_degraded(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(3):
        await _attempt(db_session, brief, status=VisualDesignAttemptStatus.REWORK, art_decision="rework", issue_codes=["visual_too_busy"])
    for _ in range(2):
        await _attempt(db_session, brief, status=VisualDesignAttemptStatus.PASSED, art_decision="pass")
    view = await build_design_view(db_session, now=datetime.now(timezone.utc))
    data = next(s for s in view.scopes if s.scope == "data")
    assert data.health.status == VisualHealthStatus.DEGRADED
    assert "visual_too_busy" in data.health.dominant_issue_codes


@pytest.mark.asyncio
async def test_frozen_scope_reports_frozen_health(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="breaking", brief_text="v1")
    await freeze_brief(db_session, "breaking", reason="founder request")
    view = await build_design_view(db_session, now=datetime.now(timezone.utc))
    breaking = next(s for s in view.scopes if s.scope == "breaking")
    assert breaking.health.status == VisualHealthStatus.FROZEN
    assert breaking.active_brief_status == "frozen"


@pytest.mark.asyncio
async def test_scope_detail_view_includes_brief_text_and_rollback_availability(db_session: AsyncSession) -> None:
    from services.visual_designer_brief_service import create_candidate_brief, promote_candidate

    await create_initial_brief(db_session, scope="carousel", brief_text="v1 text")
    candidate = await create_candidate_brief(db_session, scope="carousel", brief_text="v2 text", reason="test")
    await promote_candidate(db_session, candidate.id)

    detail = await build_design_scope_detail_view(db_session, "carousel", now=datetime.now(timezone.utc))
    assert detail is not None
    assert detail.active_brief_version == 2
    assert detail.brief_text == "v2 text"
    assert detail.rollback_available is True


@pytest.mark.asyncio
async def test_unknown_scope_returns_none(db_session: AsyncSession) -> None:
    detail = await build_design_scope_detail_view(db_session, "does-not-exist", now=datetime.now(timezone.utc))
    assert detail is None


@pytest.mark.asyncio
async def test_design_view_is_fully_read_pure(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="reel", brief_text="v1")
    await _attempt(db_session, brief, status=VisualDesignAttemptStatus.PASSED, art_decision="pass")

    async def _counts() -> dict[str, int]:
        return {
            "brief": (await db_session.execute(select(func.count()).select_from(VisualDesignerBriefVersion))).scalar_one(),
            "attempt": (await db_session.execute(select(func.count()).select_from(VisualDesignAttempt))).scalar_one(),
            "director_run": (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one(),
        }

    before = await _counts()
    await build_design_view(db_session, now=datetime.now(timezone.utc))
    await build_design_scope_detail_view(db_session, "reel", now=datetime.now(timezone.utc))
    after = await _counts()
    assert before == after


@pytest.mark.asyncio
async def test_scope_detail_shows_stable_adaptation_status_with_no_evidence(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="stable-scope", brief_text="v1")
    detail = await build_design_scope_detail_view(db_session, "stable-scope", now=datetime.now(timezone.utc))
    assert detail is not None
    assert detail.adaptation_status == "insufficient_data"
    assert detail.latest_candidate_reason is None


@pytest.mark.asyncio
async def test_scope_detail_shows_repeated_pattern_detected(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="rp-scope", brief_text="v1")
    for _ in range(3):
        await _attempt(db_session, brief, status=VisualDesignAttemptStatus.REWORK, art_decision="rework", issue_codes=["visual_too_busy"])
    detail = await build_design_scope_detail_view(db_session, "rp-scope", now=datetime.now(timezone.utc))
    assert detail is not None
    assert detail.adaptation_status == "repeated_pattern_detected"


@pytest.mark.asyncio
async def test_scope_detail_shows_candidate_ready_and_reason(db_session: AsyncSession) -> None:
    from services.visual_designer_brief_service import create_candidate_brief

    await create_initial_brief(db_session, scope="cand-scope", brief_text="v1")
    await create_candidate_brief(db_session, scope="cand-scope", brief_text="v2", reason="repeated VISUAL_TOO_BUSY on DATA")
    detail = await build_design_scope_detail_view(db_session, "cand-scope", now=datetime.now(timezone.utc))
    assert detail is not None
    assert detail.adaptation_status == "candidate_ready"
    assert detail.latest_candidate_reason == "repeated VISUAL_TOO_BUSY on DATA"


@pytest.mark.asyncio
async def test_scope_detail_shows_frozen_adaptation_status(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="frozen-scope", brief_text="v1")
    await freeze_brief(db_session, "frozen-scope", reason="founder request")
    detail = await build_design_scope_detail_view(db_session, "frozen-scope", now=datetime.now(timezone.utc))
    assert detail is not None
    assert detail.adaptation_status == "frozen"
