"""DIRECTOR-CONTROL-PLANE-1A §29: explicit daily bounded Director gate-call (Stage 2 LLM) budget.
Mirrors services/social_advisory_budget_service.py's own established shape exactly (same "unknown
cost is never silently zero" discipline) - counts real DirectorEditorialDecision rows created today
whose `director_version` marks them as Stage-2-escalated (director_editorial_gate_llm.py's own
future live caller is expected to set `director_version="v1-llm"` when it actually runs Stage 2;
today nothing does, so this bound is real and enforced but always observes 0 real Stage-2 runs -
see services/director_editorial_gate_shadow.py's own module docstring for why Stage 2 is not yet
wired into the live worker/content_cycle.py call site)."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_editorial_decision import DirectorEditorialDecision

STAGE_2_DIRECTOR_VERSION_MARKER = "v1-llm"


class GateLLMBudgetDecision(str, enum.Enum):
    ALLOWED = "allowed"
    DAILY_LIMIT_REACHED = "daily_limit_reached"


@dataclass(frozen=True)
class GateLLMBudgetResult:
    decision: GateLLMBudgetDecision
    reviews_today: int
    max_reviews_per_day: int

    @property
    def allowed(self) -> bool:
        return self.decision == GateLLMBudgetDecision.ALLOWED


async def check_gate_llm_budget(session: AsyncSession, *, now: datetime) -> GateLLMBudgetResult:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.count()).select_from(DirectorEditorialDecision).where(
        DirectorEditorialDecision.created_at >= day_start,
        DirectorEditorialDecision.director_version == STAGE_2_DIRECTOR_VERSION_MARKER,
    )
    reviews_today = (await session.execute(stmt)).scalar_one()
    max_reviews = settings.director_editorial_gate_max_llm_reviews_per_day
    decision = (
        GateLLMBudgetDecision.DAILY_LIMIT_REACHED if reviews_today >= max_reviews
        else GateLLMBudgetDecision.ALLOWED
    )
    return GateLLMBudgetResult(decision=decision, reviews_today=reviews_today, max_reviews_per_day=max_reviews)
