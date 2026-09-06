"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §25/§28: SocialAdvisoryBudgetService - the hard run/cost limits
`/directors refresh` operates inside of. Mirrors services/visual_budget_service.py's own
"unknown cost is NEVER silently treated as zero" discipline exactly.

A "social advisory" run is identified as any persisted DirectorRun with `model_provider IS NOT
NULL` - the one real, checkable signal that a run actually spent a Gateway call (the existing
deterministic Telegram Strategy/Growth and Instagram Growth directors never set model_provider at
all, per services/director_execution_service.py's own "no Gateway call" invariant) - never a new,
separate counting table duplicating what DirectorRun already records."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_run import DirectorRun


class SocialAdvisoryBudgetDecision(str, enum.Enum):
    ALLOWED = "allowed"
    DAILY_RUN_LIMIT_REACHED = "daily_run_limit_reached"
    DAILY_BUDGET_EXHAUSTED = "daily_budget_exhausted"
    BUDGET_UNKNOWN = "budget_unknown"


@dataclass(frozen=True)
class SocialAdvisoryBudgetResult:
    decision: SocialAdvisoryBudgetDecision
    runs_today: int
    max_runs_per_day: int
    cost_known: bool
    cost_today: float | None

    @property
    def allowed(self) -> bool:
        return self.decision == SocialAdvisoryBudgetDecision.ALLOWED


async def _advisory_runs_today(session: AsyncSession, *, now: datetime) -> list[DirectorRun]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(DirectorRun).where(DirectorRun.created_at >= day_start, DirectorRun.model_provider.is_not(None))
    return list((await session.execute(stmt)).scalars().all())


async def daily_advisory_summary(session: AsyncSession, *, now: datetime) -> tuple[int, bool, float]:
    """Public: (runs_today, cost_known, cost_sum) - reused by the /directors refresh confirmation
    preview so a founder sees today's spend BEFORE confirming another run. `cost_sum` is a real
    0.0 (never meaningfully used) whenever `cost_known` is False - mirrors services/
    visual_budget_service.py::_cost_sum()'s own exact "always return a real float, let the bool
    carry validity" shape, never an Optional the caller must re-null-check at every comparison."""
    runs = await _advisory_runs_today(session, now=now)
    if any(r.cost_usd is None for r in runs):
        return len(runs), False, 0.0
    return len(runs), True, sum(r.cost_usd for r in runs if r.cost_usd is not None)


async def check_social_advisory_budget(
    session: AsyncSession, *, now: datetime,
) -> SocialAdvisoryBudgetResult:
    """Called BEFORE every new /directors refresh Gateway call - never after."""
    runs_today, cost_known, cost_today = await daily_advisory_summary(session, now=now)

    if runs_today >= settings.social_advisory_max_runs_per_day:
        decision = SocialAdvisoryBudgetDecision.DAILY_RUN_LIMIT_REACHED
    elif not cost_known:
        # Fail-safe, mirrors services/visual_budget_service.py's own identical policy: a real
        # advisory run persisted earlier today with cost_usd unknown (no PricingCatalog
        # integration in this phase's scope - see services/social_prelaunch_advisory.py's own
        # docstring) means today's spend can no longer be verified against the cost budget below,
        # so further runs are blocked rather than silently assumed cost-free. A day with zero
        # prior runs has nothing to be unknown about (cost_known=True, sum=0.0) and is unaffected.
        decision = SocialAdvisoryBudgetDecision.BUDGET_UNKNOWN
    elif cost_today >= settings.social_advisory_max_cost_per_day:
        decision = SocialAdvisoryBudgetDecision.DAILY_BUDGET_EXHAUSTED
    else:
        decision = SocialAdvisoryBudgetDecision.ALLOWED

    return SocialAdvisoryBudgetResult(
        decision=decision, runs_today=runs_today, max_runs_per_day=settings.social_advisory_max_runs_per_day,
        cost_known=cost_known, cost_today=cost_today if cost_known else None,
    )
