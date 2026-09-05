"""NINJA Social Intelligence Foundation, Part I §12/§14: StrategicDirective persistence. Plain
module-level async functions, no class. Pure persistence only."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.strategic_directive import DirectiveStatus, StrategicDirective


async def get_directive(session: AsyncSession, directive_id: UUID) -> StrategicDirective | None:
    return await session.get(StrategicDirective, directive_id)


async def create_directive(
    session: AsyncSession, *, instruction: str, valid_from: datetime, created_by: int,
    valid_until: datetime | None = None, priority: int = 100, scope: str | None = None,
    products: list[str] | None = None, platforms: list[str] | None = None, source: str = "telegram",
) -> StrategicDirective:
    directive = StrategicDirective(
        instruction=instruction, valid_from=valid_from, valid_until=valid_until, priority=priority,
        scope=scope, products=products, platforms=platforms, source=source, created_by=created_by,
    )
    session.add(directive)
    await session.commit()
    await session.refresh(directive)
    return directive


async def list_active_directives(session: AsyncSession, *, now: datetime) -> list[StrategicDirective]:
    """"Active" = `status == ACTIVE` AND `now` falls within `[valid_from, valid_until)` (an unset
    `valid_until` means open-ended). Ordered by `priority` ascending (lower number = higher
    priority) so callers naturally see founder-critical directives first."""
    stmt = select(StrategicDirective).where(
        StrategicDirective.status == DirectiveStatus.ACTIVE,
        StrategicDirective.valid_from <= now,
    ).order_by(StrategicDirective.priority.asc())
    directives = list((await session.execute(stmt)).scalars().all())
    return [d for d in directives if d.valid_until is None or d.valid_until > now]


async def cancel_directive(session: AsyncSession, directive_id: UUID) -> StrategicDirective | None:
    directive = await session.get(StrategicDirective, directive_id)
    if directive is None:
        return None
    directive.status = DirectiveStatus.CANCELLED
    await session.commit()
    await session.refresh(directive)
    return directive
