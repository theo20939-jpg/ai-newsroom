"""DIRECTOR-CONTROL-PLANE-1 §16/§20-21: DesignSpecRegistry - the ONE place a DesignSpecVersion row
is ever created, activated, or rejected. Mirrors services/visual_designer_brief_service.py's own
established shape (same "at most one ACTIVE row per scope, application-level invariant, history
never deleted" discipline).

AUTO_PROMOTION=false (spec §21) is enforced structurally, not by a flag: `promote_candidate()` is a
plain, callable, mechanical function - nothing in this phase's own code (services/
visual_design_director.py, services/director_editorial_gate.py, or any Director) ever calls it
automatically. The only real callers are a future explicit Founder/console action or an explicit
promotion-policy service, exactly mirroring VisualDesignerBriefVersion's own identical
promote_candidate() precedent."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecStatus, DesignSpecType, DesignSpecVersion
from schemas.declarative_visual_parameters import DeclarativeVisualParameters

logger = logging.getLogger(__name__)


class InvalidDeclarativeParameters(ValueError):
    """Raised when a candidate's own `parameters` dict fails schema validation - spec §52's own
    "invalid values rejected" test requirement. Wraps the real pydantic ValidationError so a
    caller sees exactly which field/value failed, never a bare generic error."""


async def get_active_spec(session: AsyncSession, scope: str) -> DesignSpecVersion | None:
    stmt = (
        select(DesignSpecVersion)
        .where(DesignSpecVersion.scope == scope, DesignSpecVersion.status == DesignSpecStatus.ACTIVE)
        .order_by(DesignSpecVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_frozen_spec(session: AsyncSession, scope: str) -> DesignSpecVersion | None:
    stmt = (
        select(DesignSpecVersion)
        .where(DesignSpecVersion.scope == scope, DesignSpecVersion.status == DesignSpecStatus.FROZEN)
        .order_by(DesignSpecVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_active_or_frozen_spec(session: AsyncSession, scope: str) -> DesignSpecVersion | None:
    active = await get_active_spec(session, scope)
    if active is not None:
        return active
    return await get_frozen_spec(session, scope)


async def list_history(session: AsyncSession, scope: str) -> list[DesignSpecVersion]:
    stmt = select(DesignSpecVersion).where(DesignSpecVersion.scope == scope).order_by(DesignSpecVersion.version.desc())
    return list((await session.execute(stmt)).scalars().all())


def describe_spec_for_creative(spec: DesignSpecVersion | None) -> str:
    """DIRECTOR-CONTROL-PLANE-1A §14: a plain, compact summary string for VisualDirectorContext -
    mirrors services/social_launch_context_service.py::describe_launch_context_for_creative()'s own
    "None -> honest empty string, never a fabricated spec description" contract."""
    if spec is None:
        return ""
    parts = [f"scope={spec.scope}", f"type={spec.spec_type.value}", f"status={spec.status.value}", f"version={spec.version}"]
    if spec.parameters:
        parts.append(f"parameters={spec.parameters}")
    if spec.notes:
        parts.append(f"notes={spec.notes}")
    return "; ".join(parts)


async def _next_version_number(session: AsyncSession, scope: str) -> int:
    history = await list_history(session, scope)
    return (max((v.version for v in history), default=0)) + 1


def _validate_parameters(parameters: dict | None) -> dict | None:
    if parameters is None:
        return None
    try:
        validated = DeclarativeVisualParameters.model_validate(parameters)
    except ValidationError as exc:
        raise InvalidDeclarativeParameters(str(exc)) from exc
    return validated.model_dump(exclude_none=True, mode="json")


async def create_candidate_spec(
    session: AsyncSession, *, scope: str, spec_type: DesignSpecType, platform: str | None = None,
    surface: str | None = None, presentation_type: str | None = None, source_asset_ref: str | None = None,
    parameters: dict | None = None, notes: str | None = None, created_by: int | None = None,
) -> DesignSpecVersion:
    """Spec §21's own required pipeline entry point: ACTIVE SPEC -> Director proposes CANDIDATE.
    `parameters` (when spec_type=declarative_visual_params) is validated against
    DeclarativeVisualParameters BEFORE this ever reaches the database - raises
    InvalidDeclarativeParameters, never silently drops or coerces an invalid value."""
    validated_parameters = _validate_parameters(parameters)
    parent = await get_active_or_frozen_spec(session, scope)
    next_version = await _next_version_number(session, scope)
    candidate = DesignSpecVersion(
        platform=platform, surface=surface, presentation_type=presentation_type, spec_type=spec_type,
        scope=scope, version=next_version, status=DesignSpecStatus.CANDIDATE,
        supersedes=parent.id if parent is not None else None, source_asset_ref=source_asset_ref,
        parameters=validated_parameters, notes=notes, created_by=created_by,
    )
    session.add(candidate)
    await session.flush()
    logger.info(
        "design_spec_candidate_created",
        extra={"scope": scope, "version": candidate.version, "spec_id": str(candidate.id), "spec_type": spec_type.value},
    )
    return candidate


async def promote_candidate(session: AsyncSession, candidate_id: UUID) -> DesignSpecVersion:
    """The ONLY function that ever moves a CANDIDATE to ACTIVE - never called automatically by any
    Director/LLM code path in this phase (module docstring)."""
    candidate = await session.get(DesignSpecVersion, candidate_id)
    if candidate is None:
        raise ValueError(f"no DesignSpecVersion with id={candidate_id}")
    if candidate.status != DesignSpecStatus.CANDIDATE:
        raise ValueError(f"spec {candidate_id} is not a CANDIDATE (status={candidate.status.value})")

    previous_active = await get_active_spec(session, candidate.scope)
    if previous_active is not None:
        previous_active.status = DesignSpecStatus.SUPERSEDED
    candidate.status = DesignSpecStatus.ACTIVE
    candidate.active_from = datetime.now(timezone.utc)
    await session.flush()
    logger.info("design_spec_promoted", extra={"scope": candidate.scope, "version": candidate.version, "spec_id": str(candidate.id)})
    return candidate


async def reject_candidate(session: AsyncSession, candidate_id: UUID, *, reason: str) -> DesignSpecVersion:
    candidate = await session.get(DesignSpecVersion, candidate_id)
    if candidate is None:
        raise ValueError(f"no DesignSpecVersion with id={candidate_id}")
    if candidate.status != DesignSpecStatus.CANDIDATE:
        raise ValueError(f"spec {candidate_id} is not a CANDIDATE (status={candidate.status.value})")
    candidate.status = DesignSpecStatus.REJECTED
    candidate.notes = reason
    await session.flush()
    return candidate


async def freeze_spec(session: AsyncSession, scope: str) -> DesignSpecVersion:
    active = await get_active_spec(session, scope)
    if active is None:
        raise ValueError(f"no ACTIVE spec for scope {scope!r} to freeze")
    active.status = DesignSpecStatus.FROZEN
    await session.flush()
    return active
