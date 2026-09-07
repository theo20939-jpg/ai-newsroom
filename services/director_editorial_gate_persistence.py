"""DIRECTOR-CONTROL-PLANE-1 §10/§47: persistence for DirectorEditorialDecision, plus the Founder
override mechanics. Plain module-level async functions (no class), mirroring services/
event_recap_review_service.py's own established idempotent-mutation shape."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_editorial_decision import DirectorEditorialDecision, EditorialGateDecision
from services.director_editorial_gate import EditorialGateInput, GateOutcome, context_fingerprint, default_hold_expiry


async def persist_gate_decision(
    session: AsyncSession, *, gate_input: EditorialGateInput, outcome: GateOutcome, director: str = "channel_director",
    director_version: str = "v1", launch_context_fingerprint: str | None = None,
    campaign_context_fingerprint: str | None = None, now: datetime | None = None,
) -> DirectorEditorialDecision:
    now = now or datetime.now(timezone.utc)
    row = DirectorEditorialDecision(
        id=uuid.uuid4(),
        story_id=UUID(gate_input.story_id) if _looks_like_uuid(gate_input.story_id) else None,
        event_id=UUID(gate_input.event_id) if _looks_like_uuid(gate_input.event_id) else None,
        platform=gate_input.platform,
        decision=outcome.decision, priority=outcome.priority,
        reason_codes=[code.value for code in outcome.reason_codes], short_reason=outcome.short_reason,
        director=director, director_version=director_version,
        context_fingerprint=context_fingerprint(gate_input),
        launch_context_fingerprint=launch_context_fingerprint, campaign_context_fingerprint=campaign_context_fingerprint,
        expires_at=default_hold_expiry(now) if outcome.decision == EditorialGateDecision.HOLD else None,
    )
    session.add(row)
    return row


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


async def list_hold_queue(session: AsyncSession, *, now: datetime | None = None) -> list[DirectorEditorialDecision]:
    """Spec §13: the bounded, still-live HOLD queue - excludes expired holds, never a full history
    scan a console command would have to paginate through manually."""
    now = now or datetime.now(timezone.utc)
    stmt = select(DirectorEditorialDecision).where(
        DirectorEditorialDecision.decision == EditorialGateDecision.HOLD,
        DirectorEditorialDecision.founder_overridden.is_(False),
    ).order_by(DirectorEditorialDecision.created_at.desc())
    rows = list((await session.execute(stmt)).scalars().all())
    return [r for r in rows if r.expires_at is None or r.expires_at > now]


async def apply_founder_override(
    session: AsyncSession, decision_id: UUID, *, new_decision: EditorialGateDecision, overridden_by: int,
    now: datetime | None = None,
) -> DirectorEditorialDecision | None:
    """Spec §47: DROP -> SEND_TO_EDITOR or HOLD -> SEND_TO_EDITOR (or any other explicit Founder
    choice). Idempotent once applied - a second override attempt on an already-overridden row
    returns it unchanged rather than silently re-mutating (mirrors this codebase's own established
    confirm/cancel idempotency convention) - a Director may never supersede a Founder override."""
    row = await session.get(DirectorEditorialDecision, decision_id)
    if row is None:
        return None
    if row.founder_overridden:
        return row
    row.founder_overridden = True
    row.founder_override_decision = new_decision
    row.founder_override_by = overridden_by
    row.founder_override_at = now or datetime.now(timezone.utc)
    return row


def effective_decision(row: DirectorEditorialDecision) -> EditorialGateDecision:
    """The decision a caller should actually ACT on - the Founder override when present, the
    Director's own original decision otherwise. Never re-derives from scratch."""
    if row.founder_overridden and row.founder_override_decision is not None:
        return row.founder_override_decision
    return row.decision
