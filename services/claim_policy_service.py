"""NINJA Social Intelligence Foundation, Part I §13: ClaimPolicy persistence + the "is this claim
currently approved AS OF `now`" resolution query. Never conflates "true internally" with "approved
for public communication" - `get_claim_policy()` is the one place that answers the real question a
content-generation caller needs, not a raw status field read."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.claim_policy import ClaimPolicy, ClaimStatus


async def create_claim_policy(
    session: AsyncSession, *, product_id: UUID, claim_text: str, status: ClaimStatus,
    campaign_id: UUID | None = None, embargoed_until: datetime | None = None, notes: str | None = None,
) -> ClaimPolicy:
    claim = ClaimPolicy(
        product_id=product_id, campaign_id=campaign_id, claim_text=claim_text, status=status,
        embargoed_until=embargoed_until, notes=notes,
    )
    session.add(claim)
    await session.commit()
    await session.refresh(claim)
    return claim


async def get_claim_policy(
    session: AsyncSession, product_id: UUID, *, now: datetime, campaign_id: UUID | None = None,
) -> list[ClaimPolicy]:
    """Returns every claim policy row for a product (optionally scoped to one campaign),
    resolved AS OF `now`: an EMBARGOED claim whose `embargoed_until` has already passed is
    returned with its EFFECTIVE status recomputed to APPROVED (via a fresh, non-persisted
    `ClaimPolicy` copy - the stored row's own `status` column is never silently rewritten by a
    read-only query; only a future explicit confirmation flow would ever do that)."""
    stmt = select(ClaimPolicy).where(ClaimPolicy.product_id == product_id)
    if campaign_id is not None:
        stmt = stmt.where(ClaimPolicy.campaign_id == campaign_id)
    rows = list((await session.execute(stmt)).scalars().all())

    resolved: list[ClaimPolicy] = []
    for row in rows:
        if row.status == ClaimStatus.EMBARGOED and row.embargoed_until is not None and row.embargoed_until <= now:
            effective = ClaimPolicy(
                id=row.id, product_id=row.product_id, campaign_id=row.campaign_id,
                claim_text=row.claim_text, status=ClaimStatus.APPROVED,
                embargoed_until=row.embargoed_until, notes=row.notes,
            )
            resolved.append(effective)
        else:
            resolved.append(row)
    return resolved
