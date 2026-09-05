"""INSTAGRAM GROWTH ENGINE v2, spec §39/§40/§41: Dynamic Content Calendar persistence + context
invalidation. `invalidate_items_for_campaign_change()` is the mandatory function spec §40 describes:
when business truth changes (delay/cancel/embargo/directive/phase change), every future calendar
item that DEPENDED on the now-stale assumption becomes STALE/INVALIDATED - generic, phase-
independent content is never touched, and no per-post manual cleanup is required (spec §41's own
"no manual per-post cleanup should be required" instruction)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import CampaignStatus
from database.models.instagram_calendar_item import CalendarItemStatus, InstagramContentCalendarItem

# Only these campaign statuses represent a business-truth change serious enough to invalidate
# phase-dependent future content (spec §41's own delay/cancel examples) - LAUNCHED/COMPLETED are
# forward progress, not invalidation triggers.
_STATUS_CHANGES_TRIGGERING_INVALIDATION = {CampaignStatus.DELAYED, CampaignStatus.CANCELLED}

# Spec §70's own required test: "TENTATIVE launch blocks hard countdown assumptions" - a calendar
# item may never be PLANNED against one of these exact-date-dependent phases while the campaign
# producing it is not yet CONFIRMED (mirrors services/campaign_planner.py::derive_phase()'s own
# TENTATIVE-never-resolves-to-an-exact-date-phase safety contract, enforced here at the point a
# calendar item is created rather than only at read time).
_EXACT_DATE_DEPENDENT_PHASES = {"COUNTDOWN", "LAUNCH", "FEATURE_REVEAL"}
_STATUSES_ALLOWING_EXACT_DATE_DEPENDENT_ITEMS = {CampaignStatus.CONFIRMED.value, CampaignStatus.LAUNCHED.value}


class UnsafeCalendarAssumptionError(ValueError):
    """Raised when a calendar item is planned against an exact-date-dependent phase while its
    campaign is not yet CONFIRMED/LAUNCHED - never silently allowed through."""


async def create_calendar_item(
    session: AsyncSession, *, planned_at: datetime, objective: str, format: str,
    campaign_id: UUID | None = None, product_id: UUID | None = None, opportunity_id: str | None = None,
    creative_concept_id: str | None = None, creative_plan_id: UUID | None = None,
    depends_on_campaign_phase: str | None = None, planned_against_campaign_status: str | None = None,
    planned_against_campaign_phase: str | None = None,
) -> InstagramContentCalendarItem:
    if (
        depends_on_campaign_phase in _EXACT_DATE_DEPENDENT_PHASES
        and planned_against_campaign_status not in _STATUSES_ALLOWING_EXACT_DATE_DEPENDENT_ITEMS
    ):
        raise UnsafeCalendarAssumptionError(
            f"cannot plan a {depends_on_campaign_phase!r}-dependent item against campaign "
            f"status={planned_against_campaign_status!r} - only CONFIRMED/LAUNCHED campaigns may carry "
            "exact-date-dependent content (spec §41)"
        )
    item = InstagramContentCalendarItem(
        planned_at=planned_at, objective=objective, format=format, campaign_id=campaign_id, product_id=product_id,
        opportunity_id=opportunity_id, creative_concept_id=creative_concept_id, creative_plan_id=creative_plan_id,
        depends_on_campaign_phase=depends_on_campaign_phase,
        planned_against_campaign_status=planned_against_campaign_status,
        planned_against_campaign_phase=planned_against_campaign_phase,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def reschedule_calendar_item(
    session: AsyncSession, item_id: UUID, *, new_planned_at: datetime, reason: str,
) -> InstagramContentCalendarItem:
    """Spec item 8's own third required outcome (alongside STALE/INVALIDATED): a calendar item
    whose underlying idea is still good but whose timing no longer fits (e.g. a launch delay with
    a NEW confirmed date, rather than an open-ended delay) moves to RESCHEDULED with a new
    `planned_at`, distinct from an INVALIDATED item that has no good timing to move to."""
    item = await session.get(InstagramContentCalendarItem, item_id)
    if item is None:
        raise ValueError(f"no InstagramContentCalendarItem with id={item_id}")
    item.status = CalendarItemStatus.RESCHEDULED
    item.planned_at = new_planned_at
    item.invalidation_reason = reason
    await session.commit()
    await session.refresh(item)
    return item


async def list_calendar_items(
    session: AsyncSession, *, campaign_id: UUID | None = None, status: CalendarItemStatus | None = None,
) -> list[InstagramContentCalendarItem]:
    stmt = select(InstagramContentCalendarItem)
    if campaign_id is not None:
        stmt = stmt.where(InstagramContentCalendarItem.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(InstagramContentCalendarItem.status == status)
    return list((await session.execute(stmt)).scalars().all())


async def invalidate_items_for_campaign_change(
    session: AsyncSession, *, campaign_id: UUID, new_status: CampaignStatus, new_phase: str | None, reason: str,
) -> list[InstagramContentCalendarItem]:
    """Idempotent (spec §70's own required test): an item already INVALIDATED/CANCELLED is left
    untouched rather than re-invalidated with a duplicate/overwritten reason. Only ACTIVE/STALE
    items that declared a `depends_on_campaign_phase` are affected - a `None` there (generic
    awareness content) is a structural guarantee it survives every invalidation pass."""
    items = await list_calendar_items(session, campaign_id=campaign_id)
    changed: list[InstagramContentCalendarItem] = []

    should_invalidate_phase_dependent = (
        new_status in _STATUS_CHANGES_TRIGGERING_INVALIDATION
        or new_phase is None
    )

    for item in items:
        if item.status not in (CalendarItemStatus.ACTIVE, CalendarItemStatus.STALE):
            continue
        if item.depends_on_campaign_phase is None:
            continue  # generic awareness content - never invalidated by a campaign change alone
        phase_no_longer_matches = new_phase is not None and item.depends_on_campaign_phase != new_phase
        if should_invalidate_phase_dependent or phase_no_longer_matches:
            item.status = CalendarItemStatus.INVALIDATED
            item.invalidation_reason = reason
            changed.append(item)

    if changed:
        await session.commit()
        for item in changed:
            await session.refresh(item)
    return changed


async def invalidate_items_for_claim_change(
    session: AsyncSession, *, product_id: UUID, reason: str,
) -> list[InstagramContentCalendarItem]:
    """Spec §70's own required test: "claim-policy change marks affected content stale/invalid".
    A newly restricted/embargoed claim marks that product's future ACTIVE items STALE (not
    INVALIDATED outright) - the underlying idea may still be usable once the copy is reworked
    around the new restriction, unlike a campaign delay/cancel which invalidates the assumption
    itself. Idempotent - an item already STALE/INVALIDATED is left untouched."""
    items = await list_calendar_items(session)
    changed: list[InstagramContentCalendarItem] = []
    for item in items:
        if item.product_id != product_id or item.status != CalendarItemStatus.ACTIVE:
            continue
        item.status = CalendarItemStatus.STALE
        item.invalidation_reason = reason
        changed.append(item)

    if changed:
        await session.commit()
        for item in changed:
            await session.refresh(item)
    return changed
