"""VISUAL-DESIGN-AUTONOMY-1, spec §16-18/§50/§71: persistent Designer Brief adaptation - detects
whether recent VisualDesignAttempt evidence has reached REPEATED_PATTERN for a given scope, and
only then (never on a single failure, never on a bare POSSIBLE_SIGNAL) allows a CANDIDATE brief to
be drafted. Mirrors services/telegram_performance_memory.py's own anti-overfit repeatability floor
(`_MIN_REPEATABILITY_FOR_PATTERN = 3`) rather than inventing a second threshold convention.

Gated by `settings.visual_brief_auto_adaptation_enabled` (default False) AND a per-scope cooldown
(spec §50's own "no automatic persistent-brief change more than once per 24h per scope" default) -
both checked BEFORE ever drafting a candidate, never after."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.visual_design_attempt import VisualDesignAttempt
from database.models.visual_designer_brief import VisualDesignerBriefStatus
from services.visual_designer_brief_service import list_history

_MIN_REPEATABILITY_FOR_PATTERN = 3
_LOOKBACK_ATTEMPTS = 20
_DEFAULT_COOLDOWN = timedelta(hours=24)


class EvidenceStage:
    ANOMALY = "anomaly"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN = "repeated_pattern"


@dataclass(frozen=True)
class RepeatedPatternEvidence:
    stage: str
    issue_code: str
    occurrences: int
    sample_size: int


async def recent_attempts_for_scope(session: AsyncSession, scope: str) -> list[VisualDesignAttempt]:
    """Public: also reused by services/visual_brief_revision_service.py to build the successful-
    history/issue-distribution summaries for a candidate-generation call."""
    from database.models.visual_designer_brief import VisualDesignerBriefVersion

    stmt = (
        select(VisualDesignAttempt)
        .join(VisualDesignerBriefVersion, VisualDesignAttempt.brief_version_id == VisualDesignerBriefVersion.id)
        .where(VisualDesignerBriefVersion.scope == scope)
        .order_by(VisualDesignAttempt.created_at.desc())
        .limit(_LOOKBACK_ATTEMPTS)
    )
    return list((await session.execute(stmt)).scalars().all())


def _classify(attempts: list[VisualDesignAttempt]) -> RepeatedPatternEvidence | None:
    """Never promotes a single occurrence past ANOMALY, never a 2-occurrence run past
    POSSIBLE_SIGNAL - only >= _MIN_REPEATABILITY_FOR_PATTERN independent attempts sharing the same
    issue code reach REPEATED_PATTERN, the only stage this module ever allows a candidate for."""
    issue_counts: dict[str, int] = {}
    for attempt in attempts:
        for code in attempt.issue_codes or []:
            issue_counts[code] = issue_counts.get(code, 0) + 1
    if not issue_counts:
        return None
    top_code, top_count = max(issue_counts.items(), key=lambda kv: kv[1])
    if top_count >= _MIN_REPEATABILITY_FOR_PATTERN:
        stage = EvidenceStage.REPEATED_PATTERN
    elif top_count >= 2:
        stage = EvidenceStage.POSSIBLE_SIGNAL
    else:
        stage = EvidenceStage.ANOMALY
    return RepeatedPatternEvidence(stage=stage, issue_code=top_code, occurrences=top_count, sample_size=len(attempts))


async def detect_repeated_pattern(session: AsyncSession, scope: str) -> RepeatedPatternEvidence | None:
    attempts = await recent_attempts_for_scope(session, scope)
    return _classify(attempts)


async def _cooldown_active(session: AsyncSession, scope: str, *, now: datetime, cooldown: timedelta) -> bool:
    """Only a version that was ever CREATED AS A CANDIDATE counts as a "recent adaptation" -
    `parent_version_id is not None` is exactly that set (create_initial_brief() never sets it;
    create_candidate_brief() always does) regardless of the row's CURRENT status (CANDIDATE,
    promoted to ACTIVE, REJECTED, or later ROLLED_BACK). Bootstrapping v1 ACTIVE for a brand-new
    scope has no parent and must never itself trigger a cooldown against the first real candidate."""
    history = await list_history(session, scope)
    ever_candidates = [v for v in history if v.parent_version_id is not None and v.created_at is not None]
    if not ever_candidates:
        return False
    most_recent = max(v.created_at for v in ever_candidates)
    return (now - most_recent) < cooldown


async def may_create_candidate(
    session: AsyncSession, scope: str, *, now: datetime | None = None, cooldown: timedelta = _DEFAULT_COOLDOWN,
) -> tuple[bool, str]:
    """The ONE gate services/visual_design_loop.py or a future scheduled job must consult before
    ever drafting a candidate brief. Returns (allowed, reason) - reason is always populated, even
    when allowed=True, so a caller can log/display why."""
    now = now or datetime.now(timezone.utc)
    if not settings.visual_brief_auto_adaptation_enabled:
        return False, "visual_brief_auto_adaptation_enabled is False"

    history = await list_history(session, scope)
    active = next((v for v in history if v.status == VisualDesignerBriefStatus.FROZEN), None)
    if active is not None:
        return False, "brief is FROZEN - per-post prompts may still vary, but the persistent brief cannot auto-change"

    if await _cooldown_active(session, scope, now=now, cooldown=cooldown):
        return False, f"cooldown active - a brief version was created/activated within the last {cooldown}"

    evidence = await detect_repeated_pattern(session, scope)
    if evidence is None:
        return False, "no evidence available yet"
    if evidence.stage != EvidenceStage.REPEATED_PATTERN:
        return False, f"evidence stage is {evidence.stage}, not REPEATED_PATTERN - a single failure never triggers adaptation"

    return True, f"REPEATED_PATTERN: {evidence.issue_code!r} occurred {evidence.occurrences}/{evidence.sample_size} times"
