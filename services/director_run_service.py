"""SOCIAL-INTELLIGENCE-OPS-1, spec §29-§34: DirectorRun persistence + staleness detection.

CRITICAL (spec §32): nothing in this module is ever called from a read-only console command to
GENERATE a new run - `create_director_run()` is only ever invoked as a byproduct of a director
already computing its (free, deterministic) advisory for `/plan`/`/performance` display, exactly
the same computation that already happens on every call today; `get_latest_run()` is the ONLY
function `/directors` itself calls, and it never computes or persists anything.

Staleness follows the same TARGETED comparison services/telegram_calendar_service.py /
services/instagram_calendar_service.py already use for calendar items (compare the specific
campaign status/phase captured at run time against the live campaign), plus one coarser
`business_context_fingerprint` catch-all for a run that concerned no specific campaign (e.g. a
directive newly appearing should be able to mark even a campaign-less run stale)."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import (
    DirectorRun,
    DirectorRunEvidenceStage,
    DirectorRunStatus,
    DirectorType,
)
from services.business_context_snapshot_service import BusinessContextSnapshot, get_business_context_snapshot
from services.campaign_planner import build_campaign_plan
from services.campaign_service import get_campaign

logger = logging.getLogger(__name__)


def compute_input_fingerprint(*parts: object) -> str:
    """A stable sha256 over the canonical string form of whatever concrete inputs a director's
    decision was actually computed from (e.g. story ids, feed-state counters) - never a random
    UUID, so an identical input set always reproduces the identical fingerprint."""
    canonical = "|".join(repr(p) for p in parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_business_context_fingerprint(snapshot: BusinessContextSnapshot) -> str:
    """A coarse fingerprint of the whole BusinessContextSnapshot - any real change to an active
    campaign's status/phase, an active directive, or the approved/restricted claim sets changes
    this value; a snapshot with identical content always reproduces the identical fingerprint."""
    parts: list[str] = []
    for plan in sorted(snapshot.active_campaigns, key=lambda p: p.campaign_id):
        parts.append(f"campaign:{plan.campaign_id}:{plan.status}:{plan.phase}")
    for directive in sorted(snapshot.active_directives, key=lambda d: str(d.id)):
        parts.append(f"directive:{directive.id}")
    for claim in sorted(snapshot.approved_claims, key=lambda c: str(c.id)):
        parts.append(f"approved_claim:{claim.id}:{claim.status.value}")
    for claim in sorted(snapshot.restricted_claims, key=lambda c: str(c.id)):
        parts.append(f"restricted_claim:{claim.id}:{claim.status.value}")
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def create_director_run(
    session: AsyncSession, *, director_type: DirectorType, platform: str, generated_at: datetime,
    input_fingerprint: str, result_payload: dict, status: DirectorRunStatus = DirectorRunStatus.OK,
    subject_type: str | None = None, subject_id: UUID | None = None, campaign_id: UUID | None = None,
    campaign_status_at_run: str | None = None, campaign_phase_at_run: str | None = None,
    business_context_fingerprint: str | None = None, decision: str | None = None,
    confidence: float | None = None, evidence_stage: DirectorRunEvidenceStage | None = None,
    model_provider: str | None = None, model_name: str | None = None, cost_usd: float | None = None,
) -> DirectorRun:
    run = DirectorRun(
        director_type=director_type, platform=platform, subject_type=subject_type, subject_id=subject_id,
        campaign_id=campaign_id, campaign_status_at_run=campaign_status_at_run,
        campaign_phase_at_run=campaign_phase_at_run, business_context_fingerprint=business_context_fingerprint,
        input_fingerprint=input_fingerprint, generated_at=generated_at, status=status, decision=decision,
        confidence=confidence, evidence_stage=evidence_stage, result_payload=result_payload,
        model_provider=model_provider, model_name=model_name, cost_usd=cost_usd,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    logger.info(
        "director_run_persisted",
        extra={"run_id": str(run.id), "director_type": director_type.value, "platform": platform, "status": status.value},
    )
    return run


async def get_latest_run(
    session: AsyncSession, director_type: DirectorType, *, subject_type: str | None = None,
    subject_id: UUID | None = None,
) -> DirectorRun | None:
    """The ONE function `/directors` may call - a plain read, never a computation, never a write."""
    stmt = select(DirectorRun).where(DirectorRun.director_type == director_type)
    if subject_type is not None:
        stmt = stmt.where(DirectorRun.subject_type == subject_type)
    if subject_id is not None:
        stmt = stmt.where(DirectorRun.subject_id == subject_id)
    stmt = stmt.order_by(DirectorRun.generated_at.desc()).limit(1)
    return (await session.execute(stmt)).scalars().first()


async def is_run_context_stale(
    session: AsyncSession, run: DirectorRun, *, now: datetime, current_business_context_fingerprint: str | None = None,
) -> bool:
    """Display-time freshness check, independent of `run.stale_at` itself - mirrors
    services/director_console_service.py::_is_context_stale()'s own targeted comparison."""
    if run.campaign_id is not None:
        campaign = await get_campaign(session, run.campaign_id)
        if campaign is None:
            return True  # the campaign this run concerned no longer exists at all
        live_plan = build_campaign_plan(campaign, now=now)
        if run.campaign_status_at_run is not None and run.campaign_status_at_run != live_plan.status:
            return True
        if run.campaign_phase_at_run is not None and run.campaign_phase_at_run != live_plan.phase:
            return True
    if (
        current_business_context_fingerprint is not None
        and run.business_context_fingerprint is not None
        and run.business_context_fingerprint != current_business_context_fingerprint
    ):
        return True
    return False


async def describe_latest_run(session: AsyncSession, director_type: DirectorType, *, now: datetime) -> str | None:
    """SOCIAL-INTELLIGENCE-OPS-1A, spec §5: a plain, read-only, Russian-text summary of the
    latest persisted run for console display - shared by `/directors`
    (services/director_status_service.py) and `/performance`
    (services/director_console_service.py) so the "last real run" summary never drifts between the
    two surfaces. Never computes or persists anything itself; returns None (never a fabricated
    message) when no run has ever been persisted for this director type."""
    run = await get_latest_run(session, director_type)
    if run is None:
        return None
    snapshot = await get_business_context_snapshot(session, now=now)
    current_fingerprint = compute_business_context_fingerprint(snapshot)
    stale = await is_run_context_stale(session, run, now=now, current_business_context_fingerprint=current_fingerprint)
    decision = run.decision or "решение не зафиксировано"
    confidence_text = f", уверенность {run.confidence:.2f}" if run.confidence is not None else ""
    stale_text = " [STALE_CONTEXT]" if stale else ""
    return f"последний запуск {run.generated_at.strftime('%Y-%m-%d %H:%M UTC')}: {decision}{confidence_text}{stale_text}"


async def mark_stale(session: AsyncSession, run_id: UUID, *, reason: str) -> DirectorRun:
    """Idempotent - a run already marked stale is left untouched (its original `stale_at`/reason
    is preserved, never overwritten by a later, redundant staleness pass)."""
    run = await session.get(DirectorRun, run_id)
    if run is None:
        raise ValueError(f"no DirectorRun with id={run_id}")
    if run.stale_at is None:
        run.stale_at = datetime.now(timezone.utc)
        run.stale_reason = reason
        await session.commit()
        await session.refresh(run)
        logger.info(
            "director_run_stale", extra={"run_id": str(run.id), "director_type": run.director_type.value, "reason": reason},
        )
    return run
