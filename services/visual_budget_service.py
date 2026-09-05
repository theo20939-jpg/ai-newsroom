"""VISUAL-DESIGN-AUTONOMY-1, spec §27-30/§60: VisualBudgetService - the hard attempt/cost limits
the design loop (services/visual_design_loop.py) operates inside of. Every check here is a plain
read (row count / cost sum over VisualDesignAttempt) or a config lookup - never a Gateway call.

CRITICAL (spec §28/§60): unknown cost is NEVER silently treated as zero. A cost sum that
encounters any attempt with `total_cost IS NULL` (a real attempt whose cost could not be
determined) reports `cost_known=False` and the budget check fails SAFE (BUDGET_UNKNOWN) rather
than under-counting spend."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.visual_design_attempt import VisualDesignAttempt

_PRESENTATION_MAX_ATTEMPTS: dict[str, str] = {
    "DATA": "visual_max_attempts_data",
    "CAMPAIGN": "visual_max_attempts_campaign",
    "HERO": "visual_max_attempts_campaign",
}


def max_attempts_for(presentation_type: str | None) -> int:
    setting_name = _PRESENTATION_MAX_ATTEMPTS.get((presentation_type or "").upper())
    if setting_name is not None:
        return int(getattr(settings, setting_name))
    return settings.visual_max_attempts_default


class BudgetDecision(str, enum.Enum):
    ALLOWED = "allowed"
    ATTEMPT_LIMIT_REACHED = "attempt_limit_reached"
    POST_BUDGET_EXHAUSTED = "post_budget_exhausted"
    DAILY_BUDGET_EXHAUSTED = "daily_budget_exhausted"
    BUDGET_UNKNOWN = "budget_unknown"


@dataclass(frozen=True)
class BudgetCheckResult:
    decision: BudgetDecision
    attempts_used: int
    max_attempts: int
    post_cost_known: bool
    post_cost_so_far: float | None
    daily_cost_known: bool
    daily_cost_so_far: float | None

    @property
    def allowed(self) -> bool:
        return self.decision == BudgetDecision.ALLOWED


async def _attempts_for_post(session: AsyncSession, *, story_id: UUID, platform: str) -> list[VisualDesignAttempt]:
    stmt = select(VisualDesignAttempt).where(
        VisualDesignAttempt.story_id == story_id, VisualDesignAttempt.platform == platform,
    )
    return list((await session.execute(stmt)).scalars().all())


async def _cost_sum(session: AsyncSession, attempts: list[VisualDesignAttempt]) -> tuple[bool, float]:
    """Returns (cost_known, sum) - cost_known is False the moment ANY attempt in the set has a
    NULL total_cost (spec §28's own "unknown cost must not be silently treated as zero")."""
    if any(a.total_cost is None for a in attempts):
        return False, 0.0
    return True, sum(a.total_cost for a in attempts if a.total_cost is not None)


async def daily_cost_summary(session: AsyncSession, *, now: datetime) -> tuple[bool, float]:
    """Public: (cost_known, sum) of every VisualDesignAttempt cost today - used both by
    check_budget() below and by services/visual_design_console_service.py's own read-only
    budget-today display."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(VisualDesignAttempt).where(VisualDesignAttempt.created_at >= day_start)
    attempts = list((await session.execute(stmt)).scalars().all())
    return await _cost_sum(session, attempts)


async def check_budget(
    session: AsyncSession, *, story_id: UUID, platform: str, presentation_type: str | None = None,
    now: datetime | None = None,
) -> BudgetCheckResult:
    """Called BEFORE every new paid attempt (spec §29) - never after."""
    now = now or datetime.now(timezone.utc)
    max_attempts = max_attempts_for(presentation_type)
    attempts = await _attempts_for_post(session, story_id=story_id, platform=platform)
    attempts_used = len(attempts)

    post_cost_known, post_cost_so_far = await _cost_sum(session, attempts)
    daily_cost_known, daily_cost_so_far = await daily_cost_summary(session, now=now)

    if attempts_used >= max_attempts:
        decision = BudgetDecision.ATTEMPT_LIMIT_REACHED
    elif not post_cost_known or not daily_cost_known:
        decision = BudgetDecision.BUDGET_UNKNOWN
    elif post_cost_so_far >= settings.visual_max_cost_per_post:
        decision = BudgetDecision.POST_BUDGET_EXHAUSTED
    elif daily_cost_so_far >= settings.visual_max_cost_per_day:
        decision = BudgetDecision.DAILY_BUDGET_EXHAUSTED
    else:
        decision = BudgetDecision.ALLOWED

    return BudgetCheckResult(
        decision=decision, attempts_used=attempts_used, max_attempts=max_attempts,
        post_cost_known=post_cost_known, post_cost_so_far=post_cost_so_far if post_cost_known else None,
        daily_cost_known=daily_cost_known, daily_cost_so_far=daily_cost_so_far if daily_cost_known else None,
    )
