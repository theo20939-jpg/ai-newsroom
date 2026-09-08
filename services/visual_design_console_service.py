"""VISUAL-DESIGN-AUTONOMY-1, spec §52-53/§76: DesignConsoleService - the pure-read assembly for
`/design` and `/design <scope>`. Every function here only ever reads (VisualDesignerBriefVersion,
VisualDesignAttempt, VisualDesignAttempt cost sums) - never computes a creative direction, never
calls the Gateway, never persists a DirectorRun (spec §52's own "do not trigger design generation
merely by opening /design" instruction, mirroring services/director_console_service.py's own
read-purity invariant established in SOCIAL-INTELLIGENCE-OPS-1A)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.design_reference_asset import DesignReferenceRole
from database.models.visual_design_attempt import VisualDesignAttempt, VisualDesignAttemptStatus
from database.models.visual_designer_brief import VisualDesignerBriefStatus, VisualDesignerBriefVersion
from services.design_reference_registry import list_assets
from services.design_spec_registry import describe_spec_for_creative, get_active_or_frozen_spec
from services.visual_budget_service import daily_cost_summary
from services.visual_designer_brief_service import GLOBAL_SCOPE, list_history

_RECENT_ATTEMPT_LOOKBACK = 30


class VisualHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    WATCH = "watch"
    DEGRADED = "degraded"
    FROZEN = "frozen"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class VisualHealthSummary:
    status: VisualHealthStatus
    pass_count: int = 0
    notes_count: int = 0
    rework_count: int = 0
    block_count: int = 0
    dominant_issue_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualScopeSummary:
    scope: str
    active_brief_version: int | None
    active_brief_status: str
    health: VisualHealthSummary


@dataclass(frozen=True)
class DesignSpecRegistrySummary:
    """DIRECTOR-CONTROL-PLANE-1A §25: the exact required `/design` visibility list - editorial gate
    shadow/enforced state, active Design Spec, and approved/rejected/needs-review reference counts.
    Pure reads only (module docstring's own "never trigger design generation" invariant is
    unaffected - this reads DesignSpecVersion/DesignReferenceAsset rows, never calls the Gateway)."""

    editorial_gate_enabled: bool
    active_spec_summary: str
    approved_reference_count: int
    rejected_reference_count: int
    needs_review_reference_count: int


@dataclass(frozen=True)
class VisualDesignView:
    as_of: datetime
    scopes: list[VisualScopeSummary] = field(default_factory=list)
    daily_cost_known: bool = True
    daily_cost_so_far: float | None = None
    daily_cost_limit: float = 0.0
    design_spec_registry: DesignSpecRegistrySummary | None = None


@dataclass(frozen=True)
class VisualDesignScopeDetailView:
    as_of: datetime
    scope: str
    active_brief_version: int | None
    active_brief_status: str
    last_change_reason: str | None
    last_change_at: datetime | None
    health: VisualHealthSummary
    rollback_available: bool
    adaptation_status: str = "insufficient_data"
    latest_candidate_reason: str | None = None
    brief_text: str | None = None  # role-based redaction happens in the formatter, not here


async def _recent_attempts_for_scope(session: AsyncSession, scope: str) -> list[VisualDesignAttempt]:
    stmt = (
        select(VisualDesignAttempt)
        .join(VisualDesignerBriefVersion, VisualDesignAttempt.brief_version_id == VisualDesignerBriefVersion.id)
        .where(VisualDesignerBriefVersion.scope == scope)
        .order_by(VisualDesignAttempt.created_at.desc())
        .limit(_RECENT_ATTEMPT_LOOKBACK)
    )
    return list((await session.execute(stmt)).scalars().all())


def _compute_health(attempts: list[VisualDesignAttempt], *, is_frozen: bool) -> VisualHealthSummary:
    if is_frozen:
        return VisualHealthSummary(status=VisualHealthStatus.FROZEN)
    if not attempts:
        return VisualHealthSummary(status=VisualHealthStatus.INSUFFICIENT_DATA)

    pass_count = sum(1 for a in attempts if a.status == VisualDesignAttemptStatus.PASSED and (a.issue_codes is None or not a.issue_codes))
    notes_count = sum(1 for a in attempts if a.status == VisualDesignAttemptStatus.PASSED and a.issue_codes)
    rework_count = sum(1 for a in attempts if a.status == VisualDesignAttemptStatus.REWORK)
    block_count = sum(1 for a in attempts if a.art_decision == "block")

    issue_counter: dict[str, int] = {}
    for a in attempts:
        for code in a.issue_codes or []:
            issue_counter[code] = issue_counter.get(code, 0) + 1
    dominant = sorted(issue_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]

    total = len(attempts)
    if total < 3:
        status = VisualHealthStatus.INSUFFICIENT_DATA
    elif block_count > 0 or rework_count / total >= 0.5:
        status = VisualHealthStatus.DEGRADED
    elif rework_count / total >= 0.2:
        status = VisualHealthStatus.WATCH
    else:
        status = VisualHealthStatus.HEALTHY

    return VisualHealthSummary(
        status=status, pass_count=pass_count, notes_count=notes_count, rework_count=rework_count,
        block_count=block_count, dominant_issue_codes=[code for code, _ in dominant],
    )


async def _known_scopes(session: AsyncSession) -> list[str]:
    stmt = select(VisualDesignerBriefVersion.scope).distinct()
    return sorted((await session.execute(stmt)).scalars().all())


async def build_design_view(session: AsyncSession, *, now: datetime | None = None) -> VisualDesignView:
    now = now or datetime.now(timezone.utc)
    scopes: list[VisualScopeSummary] = []
    for scope in await _known_scopes(session):
        history = await list_history(session, scope)
        active = next((v for v in history if v.status in (VisualDesignerBriefStatus.ACTIVE, VisualDesignerBriefStatus.FROZEN)), None)
        attempts = await _recent_attempts_for_scope(session, scope)
        health = _compute_health(attempts, is_frozen=(active is not None and active.status == VisualDesignerBriefStatus.FROZEN))
        scopes.append(VisualScopeSummary(
            scope=scope, active_brief_version=active.version if active else None,
            active_brief_status=active.status.value if active else "none", health=health,
        ))

    cost_known, cost_so_far = await daily_cost_summary(session, now=now)

    active_spec = await get_active_or_frozen_spec(session, GLOBAL_SCOPE)
    approved = await list_assets(session, reference_role=DesignReferenceRole.APPROVED_REFERENCE)
    rejected = await list_assets(session, reference_role=DesignReferenceRole.REJECTED_REFERENCE)
    needs_review = await list_assets(session, reference_role=DesignReferenceRole.NEEDS_FOUNDER_REVIEW)
    design_spec_registry = DesignSpecRegistrySummary(
        editorial_gate_enabled=settings.telegram_editorial_gate_enabled,
        active_spec_summary=describe_spec_for_creative(active_spec) or "нет активного Design Spec",
        approved_reference_count=len(approved), rejected_reference_count=len(rejected),
        needs_review_reference_count=len(needs_review),
    )

    return VisualDesignView(
        as_of=now, scopes=scopes, daily_cost_known=cost_known,
        daily_cost_so_far=cost_so_far if cost_known else None, daily_cost_limit=settings.visual_max_cost_per_day,
        design_spec_registry=design_spec_registry,
    )


async def build_design_scope_detail_view(
    session: AsyncSession, scope: str, *, now: datetime | None = None, include_brief_text: bool = True,
) -> VisualDesignScopeDetailView | None:
    """`include_brief_text` always defaults True - role-based redaction of the brief text itself
    happens in ONE place, bot/visual_design_formatting.py::render_design_scope_detail() via
    DirectorConsoleAccessPolicy, mirroring every other console view's "service returns full data,
    formatter redacts by role" convention (never duplicated here)."""
    now = now or datetime.now(timezone.utc)
    history = await list_history(session, scope)
    if not history:
        return None
    active = next((v for v in history if v.status in (VisualDesignerBriefStatus.ACTIVE, VisualDesignerBriefStatus.FROZEN)), None)
    attempts = await _recent_attempts_for_scope(session, scope)
    health = _compute_health(attempts, is_frozen=(active is not None and active.status == VisualDesignerBriefStatus.FROZEN))
    rollback_candidates = [
        v for v in history
        if v.status in (VisualDesignerBriefStatus.SUPERSEDED, VisualDesignerBriefStatus.ROLLED_BACK, VisualDesignerBriefStatus.FROZEN)
        and (active is None or v.id != active.id)
    ]

    from services.visual_brief_revision_service import describe_adaptation_status

    adaptation_status = await describe_adaptation_status(session, scope, now=now)
    latest_candidate = next((v for v in history if v.status == VisualDesignerBriefStatus.CANDIDATE), None)
    if latest_candidate is None:
        latest_candidate = next((v for v in history if v.status == VisualDesignerBriefStatus.REJECTED), None)

    return VisualDesignScopeDetailView(
        as_of=now, scope=scope, active_brief_version=active.version if active else None,
        active_brief_status=active.status.value if active else "none",
        last_change_reason=active.reason if active else None, last_change_at=active.activated_at if active else None,
        health=health, rollback_available=bool(rollback_candidates), adaptation_status=adaptation_status.value,
        latest_candidate_reason=(latest_candidate.reason if latest_candidate is not None else None),
        brief_text=(active.brief_text if (active is not None and include_brief_text) else None),
    )
