"""SOCIAL-INTELLIGENCE-OPS-1, spec §21-§27: Telegram Content Calendar persistence + context
invalidation. Mirrors services/instagram_calendar_service.py's own semantics exactly (same
STALE/INVALIDATED/RESCHEDULED discipline, same idempotency, same TENTATIVE-blocks-exact-date-items
safety contract) against the SEPARATE telegram_content_calendar_items table (spec §21's own
"do not reuse InstagramContentCalendarItem" instruction) - deliberately duplicated logic, not a
cross-platform import, per the established "shared business truth, separate platform execution"
architectural boundary."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import CampaignStatus
from database.models.telegram_content_calendar_item import (
    TelegramCalendarItemStatus,
    TelegramContentCalendarItem,
    TelegramContentRole,
)

_STATUS_CHANGES_TRIGGERING_INVALIDATION = {CampaignStatus.DELAYED, CampaignStatus.CANCELLED}
_EXACT_DATE_DEPENDENT_PHASES = {"COUNTDOWN", "LAUNCH", "FEATURE_REVEAL"}
_STATUSES_ALLOWING_EXACT_DATE_DEPENDENT_ITEMS = {CampaignStatus.CONFIRMED.value, CampaignStatus.LAUNCHED.value}


class UnsafeCalendarAssumptionError(ValueError):
    """Raised when a calendar item is planned against an exact-date-dependent phase while its
    campaign is not yet CONFIRMED/LAUNCHED - never silently allowed through."""


async def create_calendar_item(
    session: AsyncSession, *, planned_at: datetime, objective: str, content_role: TelegramContentRole,
    story_id: UUID | None = None, campaign_id: UUID | None = None, product_id: UUID | None = None,
    surface_id: UUID | None = None, presentation_hint: str | None = None, source_opportunity_id: str | None = None,
    business_context_version: str | None = None, depends_on_campaign_phase: str | None = None,
    planned_against_campaign_status: str | None = None, planned_against_campaign_phase: str | None = None,
    director_run_id: UUID | None = None,
) -> TelegramContentCalendarItem:
    if (
        depends_on_campaign_phase in _EXACT_DATE_DEPENDENT_PHASES
        and planned_against_campaign_status not in _STATUSES_ALLOWING_EXACT_DATE_DEPENDENT_ITEMS
    ):
        raise UnsafeCalendarAssumptionError(
            f"cannot plan a {depends_on_campaign_phase!r}-dependent item against campaign "
            f"status={planned_against_campaign_status!r} - only CONFIRMED/LAUNCHED campaigns may carry "
            "exact-date-dependent content"
        )
    item = TelegramContentCalendarItem(
        planned_at=planned_at, objective=objective, content_role=content_role, story_id=story_id,
        campaign_id=campaign_id, product_id=product_id, surface_id=surface_id, presentation_hint=presentation_hint,
        source_opportunity_id=source_opportunity_id, business_context_version=business_context_version,
        depends_on_campaign_phase=depends_on_campaign_phase,
        planned_against_campaign_status=planned_against_campaign_status,
        planned_against_campaign_phase=planned_against_campaign_phase, director_run_id=director_run_id,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def reschedule_calendar_item(
    session: AsyncSession, item_id: UUID, *, new_planned_at: datetime, reason: str,
) -> TelegramContentCalendarItem:
    item = await session.get(TelegramContentCalendarItem, item_id)
    if item is None:
        raise ValueError(f"no TelegramContentCalendarItem with id={item_id}")
    item.status = TelegramCalendarItemStatus.RESCHEDULED
    item.planned_at = new_planned_at
    item.invalidation_reason = reason
    await session.commit()
    await session.refresh(item)
    return item


async def list_calendar_items(
    session: AsyncSession, *, campaign_id: UUID | None = None, status: TelegramCalendarItemStatus | None = None,
) -> list[TelegramContentCalendarItem]:
    stmt = select(TelegramContentCalendarItem)
    if campaign_id is not None:
        stmt = stmt.where(TelegramContentCalendarItem.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(TelegramContentCalendarItem.status == status)
    return list((await session.execute(stmt)).scalars().all())


async def invalidate_items_for_campaign_change(
    session: AsyncSession, *, campaign_id: UUID, new_status: CampaignStatus, new_phase: str | None, reason: str,
) -> list[TelegramContentCalendarItem]:
    """Idempotent: an item already INVALIDATED/CANCELLED is left untouched. Only ACTIVE/STALE items
    that declared a `depends_on_campaign_phase` are affected - a `None` there (generic category
    awareness content, spec §27's own "generic category awareness may remain active" instruction)
    is a structural guarantee it survives every invalidation pass."""
    items = await list_calendar_items(session, campaign_id=campaign_id)
    changed: list[TelegramContentCalendarItem] = []

    should_invalidate_phase_dependent = new_status in _STATUS_CHANGES_TRIGGERING_INVALIDATION or new_phase is None

    for item in items:
        if item.status not in (TelegramCalendarItemStatus.ACTIVE, TelegramCalendarItemStatus.STALE):
            continue
        if item.depends_on_campaign_phase is None:
            continue
        phase_no_longer_matches = new_phase is not None and item.depends_on_campaign_phase != new_phase
        if should_invalidate_phase_dependent or phase_no_longer_matches:
            item.status = TelegramCalendarItemStatus.INVALIDATED
            item.invalidation_reason = reason
            changed.append(item)

    if changed:
        await session.commit()
        for item in changed:
            await session.refresh(item)
    return changed


async def invalidate_items_for_claim_change(
    session: AsyncSession, *, product_id: UUID, reason: str,
) -> list[TelegramContentCalendarItem]:
    """A newly restricted/embargoed claim marks that product's future ACTIVE items STALE (not
    INVALIDATED outright) - idempotent, mirrors services/instagram_calendar_service.py's own
    identical rule exactly."""
    items = await list_calendar_items(session)
    changed: list[TelegramContentCalendarItem] = []
    for item in items:
        if item.product_id != product_id or item.status != TelegramCalendarItemStatus.ACTIVE:
            continue
        item.status = TelegramCalendarItemStatus.STALE
        item.invalidation_reason = reason
        changed.append(item)

    if changed:
        await session.commit()
        for item in changed:
            await session.refresh(item)
    return changed
