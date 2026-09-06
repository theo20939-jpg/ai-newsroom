"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §45: SocialAdvisoryBudgetService - daily run count/cost limits,
unknown cost never treated as zero."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRun, DirectorRunStatus, DirectorType
from core.config import settings
from services.social_advisory_budget_service import (
    SocialAdvisoryBudgetDecision,
    check_social_advisory_budget,
    daily_advisory_summary,
)

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


async def _seed_advisory_run(session: AsyncSession, *, cost_usd: float | None, created_at=None) -> DirectorRun:
    run = DirectorRun(
        director_type=DirectorType.TELEGRAM_PRELAUNCH, platform="telegram", input_fingerprint="fp",
        generated_at=_NOW, status=DirectorRunStatus.OK, result_payload={}, model_provider="fake-provider",
        model_name="fake-model", cost_usd=cost_usd,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    if created_at is not None:
        run.created_at = created_at
        await session.commit()
    return run


async def test_zero_runs_today_allows_a_refresh(db_session: AsyncSession) -> None:
    result = await check_social_advisory_budget(db_session, now=_NOW)
    assert result.decision == SocialAdvisoryBudgetDecision.ALLOWED
    assert result.runs_today == 0


async def test_daily_run_count_is_enforced(db_session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(settings, "social_advisory_max_runs_per_day", 2)
    await _seed_advisory_run(db_session, cost_usd=0.10)
    await _seed_advisory_run(db_session, cost_usd=0.10)
    result = await check_social_advisory_budget(db_session, now=_NOW)
    assert result.decision == SocialAdvisoryBudgetDecision.DAILY_RUN_LIMIT_REACHED
    assert result.runs_today == 2


async def test_unknown_cost_is_not_treated_as_zero(db_session: AsyncSession) -> None:
    """spec §45's own explicit requirement."""
    await _seed_advisory_run(db_session, cost_usd=None)
    runs_today, cost_known, cost_sum = await daily_advisory_summary(db_session, now=_NOW)
    assert runs_today == 1
    assert cost_known is False
    # cost_sum is a real 0.0 placeholder (never meaningfully used when cost_known is False) -
    # the caller must check cost_known, never treat this number as "spend was actually zero".
    assert cost_sum == 0.0


async def test_unknown_cost_blocks_further_gateway_calls(db_session: AsyncSession) -> None:
    """spec §45: budget exhaustion (here: unverifiable budget) prevents the next Gateway call."""
    await _seed_advisory_run(db_session, cost_usd=None)
    result = await check_social_advisory_budget(db_session, now=_NOW)
    assert result.decision == SocialAdvisoryBudgetDecision.BUDGET_UNKNOWN
    assert result.allowed is False


async def test_daily_cost_budget_is_enforced_when_cost_is_known(db_session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(settings, "social_advisory_max_cost_per_day", 1.0)
    await _seed_advisory_run(db_session, cost_usd=0.60)
    await _seed_advisory_run(db_session, cost_usd=0.60)
    result = await check_social_advisory_budget(db_session, now=_NOW)
    assert result.decision == SocialAdvisoryBudgetDecision.DAILY_BUDGET_EXHAUSTED
    assert result.cost_known is True
    assert result.cost_today == pytest.approx(1.20)


async def test_deterministic_director_runs_never_count_toward_the_advisory_budget(db_session: AsyncSession) -> None:
    """The existing free, deterministic Telegram Strategy/Growth/Instagram Growth runs never set
    model_provider - they must never be mistaken for a paid advisory run."""
    run = DirectorRun(
        director_type=DirectorType.TELEGRAM_STRATEGY, platform="telegram", input_fingerprint="fp",
        generated_at=_NOW, status=DirectorRunStatus.OK, result_payload={}, model_provider=None,
    )
    db_session.add(run)
    await db_session.commit()
    runs_today, cost_known, _cost_sum = await daily_advisory_summary(db_session, now=_NOW)
    assert runs_today == 0
    assert cost_known is True


async def test_read_commands_never_touch_the_budget_service() -> None:
    """spec §24/§45: read commands remain cost-free - confirmed structurally, since
    bot/handlers/director_console.py's pure read handlers never import this module at all
    (only _handle_refresh_request/handle_refresh_callback do)."""
    import inspect

    import bot.handlers.director_console as module

    source = inspect.getsource(module.handle_directors)
    assert "check_social_advisory_budget" not in source
    assert "daily_advisory_summary" not in source
