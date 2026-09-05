"""VISUAL-DESIGN-AUTONOMY-1, spec §6-8/§16-20/§55-56: VisualDesignerBriefService - the ONE place a
VisualDesignerBriefVersion row is ever created, activated, frozen, rejected, or rolled back.

Invariant this module owns and enforces (not a DB constraint - mirrors
database/models/business_context_proposal.py's own application-level precedent): at most one
ACTIVE row per scope at any time. Every state-changing function here first resolves the current
ACTIVE row for the scope (if any) and moves it to a terminal/inactive status before activating a
new one - never two simultaneously ACTIVE rows for the same scope.

History is NEVER deleted (spec §20/§56) - every prior version stays queryable forever under its
own terminal status (SUPERSEDED/ROLLED_BACK/REJECTED)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_designer_brief import VisualDesignerBriefStatus, VisualDesignerBriefVersion

GLOBAL_SCOPE = "global"


async def get_active_brief(session: AsyncSession, scope: str) -> VisualDesignerBriefVersion | None:
    stmt = (
        select(VisualDesignerBriefVersion)
        .where(VisualDesignerBriefVersion.scope == scope, VisualDesignerBriefVersion.status == VisualDesignerBriefStatus.ACTIVE)
        .order_by(VisualDesignerBriefVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_frozen_brief(session: AsyncSession, scope: str) -> VisualDesignerBriefVersion | None:
    stmt = (
        select(VisualDesignerBriefVersion)
        .where(VisualDesignerBriefVersion.scope == scope, VisualDesignerBriefVersion.status == VisualDesignerBriefStatus.FROZEN)
        .order_by(VisualDesignerBriefVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_active_or_frozen_brief(session: AsyncSession, scope: str) -> VisualDesignerBriefVersion | None:
    """The one function a design run should call for "what brief governs this scope right now" -
    ACTIVE and FROZEN are both currently-governing states (spec §20: "Frozen: ... per-post prompts
    may still vary" - a frozen brief still supplies the persistent creative direction, it simply
    cannot auto-change)."""
    active = await get_active_brief(session, scope)
    if active is not None:
        return active
    return await get_frozen_brief(session, scope)


async def list_history(session: AsyncSession, scope: str) -> list[VisualDesignerBriefVersion]:
    stmt = select(VisualDesignerBriefVersion).where(VisualDesignerBriefVersion.scope == scope).order_by(
        VisualDesignerBriefVersion.version.desc()
    )
    return list((await session.execute(stmt)).scalars().all())


async def _next_version_number(session: AsyncSession, scope: str) -> int:
    history = await list_history(session, scope)
    return (max((v.version for v in history), default=0)) + 1


async def create_initial_brief(
    session: AsyncSession, *, scope: str, brief_text: str, created_by: int | None = None,
) -> VisualDesignerBriefVersion:
    """Bootstraps v1 ACTIVE for a scope that has no history yet. Raises if a version already
    exists for this scope - never silently overwrites existing history."""
    existing = await list_history(session, scope)
    if existing:
        raise ValueError(f"scope {scope!r} already has {len(existing)} brief version(s) - use create_candidate_brief() instead")
    version = VisualDesignerBriefVersion(
        scope=scope, version=1, status=VisualDesignerBriefStatus.ACTIVE, brief_text=brief_text,
        created_by=created_by, activated_at=datetime.now(timezone.utc),
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return version


async def create_candidate_brief(
    session: AsyncSession, *, scope: str, brief_text: str, reason: str, evidence: dict | None = None,
    created_by: int | None = None,
) -> VisualDesignerBriefVersion:
    """Spec §18: broad textual freedom for WHAT the candidate says - this function only handles
    versioning bookkeeping, never validates or constrains brief_text content itself."""
    parent = await get_active_or_frozen_brief(session, scope)
    next_version = await _next_version_number(session, scope)
    candidate = VisualDesignerBriefVersion(
        scope=scope, version=next_version, status=VisualDesignerBriefStatus.CANDIDATE, brief_text=brief_text,
        parent_version_id=parent.id if parent is not None else None, reason=reason, evidence=evidence,
        created_by=created_by,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def promote_candidate(session: AsyncSession, candidate_id: UUID) -> VisualDesignerBriefVersion:
    """Spec §19: the ONLY function that ever moves a CANDIDATE to ACTIVE. Callers
    (services/visual_brief_promotion_service.py) are responsible for having already verified every
    promotion precondition (regression validation, budget, Brand Core compliance) BEFORE calling
    this - this function itself only performs the mechanical, safe state transition."""
    candidate = await session.get(VisualDesignerBriefVersion, candidate_id)
    if candidate is None:
        raise ValueError(f"no VisualDesignerBriefVersion with id={candidate_id}")
    if candidate.status != VisualDesignerBriefStatus.CANDIDATE:
        raise ValueError(f"version {candidate_id} is not a CANDIDATE (status={candidate.status.value})")

    previous_active = await get_active_brief(session, candidate.scope)
    if previous_active is not None:
        previous_active.status = VisualDesignerBriefStatus.SUPERSEDED
    candidate.status = VisualDesignerBriefStatus.ACTIVE
    candidate.activated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def reject_candidate(session: AsyncSession, candidate_id: UUID, *, reason: str) -> VisualDesignerBriefVersion:
    candidate = await session.get(VisualDesignerBriefVersion, candidate_id)
    if candidate is None:
        raise ValueError(f"no VisualDesignerBriefVersion with id={candidate_id}")
    if candidate.status != VisualDesignerBriefStatus.CANDIDATE:
        raise ValueError(f"version {candidate_id} is not a CANDIDATE (status={candidate.status.value})")
    candidate.status = VisualDesignerBriefStatus.REJECTED
    candidate.reason = reason
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def freeze_brief(session: AsyncSession, scope: str, *, reason: str) -> VisualDesignerBriefVersion:
    """Spec §20/§55: the ACTIVE brief (if any) becomes FROZEN in place - it keeps governing
    per-post creative direction, it simply can no longer auto-promote a future candidate."""
    active = await get_active_brief(session, scope)
    if active is None:
        raise ValueError(f"no ACTIVE brief for scope {scope!r} to freeze")
    active.status = VisualDesignerBriefStatus.FROZEN
    active.reason = reason
    await session.commit()
    await session.refresh(active)
    return active


async def unfreeze_brief(session: AsyncSession, scope: str, *, reason: str) -> VisualDesignerBriefVersion:
    frozen = await get_frozen_brief(session, scope)
    if frozen is None:
        raise ValueError(f"no FROZEN brief for scope {scope!r} to unfreeze")
    frozen.status = VisualDesignerBriefStatus.ACTIVE
    frozen.reason = reason
    await session.commit()
    await session.refresh(frozen)
    return frozen


async def find_rollback_candidate(session: AsyncSession, scope: str) -> VisualDesignerBriefVersion | None:
    """The most recent prior validated version other than whatever currently governs the scope -
    used by the /design rollback confirmation flow so a founder does not need to name an exact
    version number."""
    current = await get_active_or_frozen_brief(session, scope)
    history = await list_history(session, scope)  # already ordered newest-version-first
    for version in history:
        if current is not None and version.id == current.id:
            continue
        if version.status in (VisualDesignerBriefStatus.SUPERSEDED, VisualDesignerBriefStatus.ROLLED_BACK, VisualDesignerBriefStatus.FROZEN):
            return version
    return None


async def rollback_to(session: AsyncSession, scope: str, *, target_version_id: UUID, reason: str) -> VisualDesignerBriefVersion:
    """Spec §56: restores a PRIOR VALIDATED version - never deletes anything, the version being
    rolled back FROM moves to ROLLED_BACK (a distinct terminal status from SUPERSEDED, so a reader
    can tell "replaced by a newer promotion" apart from "reverted due to a problem"), and the
    target's own history row is reactivated in place rather than duplicated."""
    target = await session.get(VisualDesignerBriefVersion, target_version_id)
    if target is None or target.scope != scope:
        raise ValueError(f"no VisualDesignerBriefVersion with id={target_version_id} in scope {scope!r}")
    if target.status not in (VisualDesignerBriefStatus.SUPERSEDED, VisualDesignerBriefStatus.ROLLED_BACK, VisualDesignerBriefStatus.FROZEN):
        raise ValueError(f"version {target_version_id} is not a prior validated version (status={target.status.value})")

    current_active = await get_active_brief(session, scope)
    if current_active is not None and current_active.id != target.id:
        current_active.status = VisualDesignerBriefStatus.ROLLED_BACK
    current_frozen = await get_frozen_brief(session, scope)
    if current_frozen is not None and current_frozen.id != target.id:
        current_frozen.status = VisualDesignerBriefStatus.ROLLED_BACK

    target.status = VisualDesignerBriefStatus.ACTIVE
    target.reason = reason
    target.activated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(target)
    return target
