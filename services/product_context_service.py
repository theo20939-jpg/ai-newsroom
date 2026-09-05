"""NINJA Social Intelligence Foundation, Part I §5-§7: Product / ProductContextVersion /
ProductEvent persistence. Plain module-level async functions, no class - mirrors services/
event_recap_review_service.py's own established shape exactly (module docstring's own "A. creation"
stage). Pure persistence only: no LLM Gateway call, no Telegram call anywhere in this module."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.product import Product, ProductStatus
from database.models.product_context_version import ProductContextVersion
from database.models.product_event import ProductEvent, ProductEventType
from database.models.business_context_shared import Visibility

# Fields a ProductContextVersion's `structured_context` payload may set on the canonical `Product`
# row - an explicit allowlist (never `setattr` on an arbitrary key) so a malformed/unexpected LLM
# parse can never write to a column this module did not intend to expose.
_PRODUCT_UPDATABLE_FIELDS = frozenset({
    "name", "status", "current_stage", "description", "target_audience",
    "core_value_propositions", "current_features", "planned_features", "pricing_status",
    "product_url", "waitlist_url", "owner", "priority",
})


async def get_product(session: AsyncSession, product_id: UUID) -> Product | None:
    return await session.get(Product, product_id)


async def get_product_by_slug(session: AsyncSession, slug: str) -> Product | None:
    stmt = select(Product).where(Product.slug == slug)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_products(session: AsyncSession) -> list[Product]:
    stmt = select(Product).order_by(Product.priority.asc(), Product.name.asc())
    return list((await session.execute(stmt)).scalars().all())


async def create_product(
    session: AsyncSession, *, slug: str, name: str, status: ProductStatus = ProductStatus.IDEA,
) -> Product:
    """Idempotent per `slug` - mirrors create_event_recap_review()'s own identical discipline
    (return the existing row rather than raising on a duplicate slug)."""
    existing = await get_product_by_slug(session, slug)
    if existing is not None:
        return existing
    product = Product(slug=slug, name=name, status=status)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def _next_version_number(session: AsyncSession, product_id: UUID) -> int:
    stmt = select(func.max(ProductContextVersion.version)).where(ProductContextVersion.product_id == product_id)
    current_max = (await session.execute(stmt)).scalar_one_or_none()
    return (current_max or 0) + 1


async def _latest_version_for_product(session: AsyncSession, product_id: UUID) -> ProductContextVersion | None:
    stmt = (
        select(ProductContextVersion)
        .where(ProductContextVersion.product_id == product_id)
        .order_by(ProductContextVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_product_context_version(
    session: AsyncSession, *, product_id: UUID, raw_instruction: str, structured_context: dict[str, Any],
    confirmed_by: int, telegram_chat_id: int | None = None, telegram_topic_id: int | None = None,
    telegram_message_id: int | None = None, source: str = "telegram",
) -> ProductContextVersion:
    """Creates exactly one new, immutable version row (auto-incrementing per product, chained via
    `supersedes_id`) AND applies `structured_context`'s allowlisted fields onto the canonical
    `Product` row - both in the same transaction, so the two can never drift out of sync. This is
    the ONLY function in this module (besides `create_product`) that ever mutates a `Product` row
    - services/business_context_proposal_service.py::confirm_proposal() is the only caller, always
    from an already-confirmed human decision, never from the parser directly (spec §32/§102)."""
    product = await session.get(Product, product_id)
    assert product is not None, "product_id must reference an existing Product"

    previous = await _latest_version_for_product(session, product_id)
    version_number = await _next_version_number(session, product_id)

    version = ProductContextVersion(
        product_id=product_id, version=version_number, raw_instruction=raw_instruction,
        structured_context=structured_context, source=source, created_by=confirmed_by,
        telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id,
        telegram_message_id=telegram_message_id,
        confirmed_at=datetime.now(timezone.utc), confirmed_by=confirmed_by,
        supersedes_id=previous.id if previous is not None else None,
    )
    session.add(version)

    for field, value in structured_context.items():
        if field not in _PRODUCT_UPDATABLE_FIELDS:
            continue
        if field == "status" and isinstance(value, str):
            value = ProductStatus(value)
        setattr(product, field, value)

    await session.commit()
    await session.refresh(version)
    return version


async def list_product_context_versions(session: AsyncSession, product_id: UUID) -> list[ProductContextVersion]:
    stmt = (
        select(ProductContextVersion)
        .where(ProductContextVersion.product_id == product_id)
        .order_by(ProductContextVersion.version.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_product_event(
    session: AsyncSession, *, product_id: UUID, event_type: ProductEventType, title: str,
    event_at: datetime, description: str | None = None, importance: int = 100,
    visibility: Visibility = Visibility.INTERNAL_ONLY, raw_instruction: str | None = None,
    structured_payload: dict[str, Any] | None = None, source: str = "telegram",
) -> ProductEvent:
    event = ProductEvent(
        product_id=product_id, event_type=event_type, title=title, description=description,
        event_at=event_at, importance=importance, visibility=visibility,
        raw_instruction=raw_instruction, structured_payload=structured_payload, source=source,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def list_upcoming_product_events(
    session: AsyncSession, *, now: datetime, days: int = 30, product_id: UUID | None = None,
) -> list[ProductEvent]:
    from datetime import timedelta

    stmt = select(ProductEvent).where(
        ProductEvent.event_at >= now, ProductEvent.event_at <= now + timedelta(days=days),
    )
    if product_id is not None:
        stmt = stmt.where(ProductEvent.product_id == product_id)
    stmt = stmt.order_by(ProductEvent.event_at.asc())
    return list((await session.execute(stmt)).scalars().all())
