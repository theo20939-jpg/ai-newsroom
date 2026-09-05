"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §14/§15/§16: TelegramSurface registry - CRUD plus the
one mandatory safety gate (`list_public_analytics_surfaces`) every performance/strategy consumer
must call instead of re-deriving "is this a public audience surface" itself.

No row is ever created with a guessed chat_id - every `create_surface()` call requires an explicit
`chat_id` the caller already knows (a future configuration command's job, out of scope here)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_surface import PUBLIC_SURFACE_ROLES, TelegramSurface, TelegramSurfaceRole
from services.telegram_own_channel import owned_chat_id


async def create_surface(
    session: AsyncSession, *, chat_id: int, role: TelegramSurfaceRole, name: str, username: str | None = None,
    active: bool = True, analytics_enabled: bool = False,
) -> TelegramSurface:
    surface = TelegramSurface(
        chat_id=chat_id, username=username, role=role, name=name, active=active, analytics_enabled=analytics_enabled,
    )
    session.add(surface)
    await session.commit()
    await session.refresh(surface)
    return surface


async def upsert_surface(
    session: AsyncSession, *, chat_id: int, role: TelegramSurfaceRole, name: str, username: str | None = None,
    active: bool = True, analytics_enabled: bool = False,
) -> TelegramSurface:
    """SOCIAL-INTELLIGENCE-OPS-1, spec §4's own "repeated confirmation must be idempotent"
    instruction: confirming the same /surface proposal (or a later one for the same chat_id) twice
    must never create a duplicate row - updates the existing surface for that chat_id in place if
    one exists, creates one otherwise."""
    existing = await get_surface_by_chat_id(session, chat_id)
    if existing is not None:
        existing.role = role
        existing.name = name
        existing.username = username
        existing.active = active
        existing.analytics_enabled = analytics_enabled
        await session.commit()
        await session.refresh(existing)
        return existing
    return await create_surface(
        session, chat_id=chat_id, role=role, name=name, username=username, active=active,
        analytics_enabled=analytics_enabled,
    )


async def get_surface(session: AsyncSession, surface_id: UUID) -> TelegramSurface | None:
    return await session.get(TelegramSurface, surface_id)


async def get_surface_by_chat_id(session: AsyncSession, chat_id: int) -> TelegramSurface | None:
    stmt = select(TelegramSurface).where(TelegramSurface.chat_id == chat_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_surfaces(session: AsyncSession, *, active_only: bool = False) -> list[TelegramSurface]:
    stmt = select(TelegramSurface)
    if active_only:
        stmt = stmt.where(TelegramSurface.active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def list_public_analytics_surfaces(session: AsyncSession) -> list[TelegramSurface]:
    """Spec §15's own mandatory gate: a surface counts as feeding audience performance/strategy
    learning ONLY when it is active, ANALYTICS-enabled, AND has a PUBLIC_* role - INTERNAL_EDITORIAL
    is structurally excluded regardless of any other field (never a caller-supplied override)."""
    stmt = select(TelegramSurface).where(
        TelegramSurface.active.is_(True), TelegramSurface.analytics_enabled.is_(True),
        TelegramSurface.role.in_(PUBLIC_SURFACE_ROLES),
    )
    return list((await session.execute(stmt)).scalars().all())


async def resolve_owned_surface(session: AsyncSession) -> TelegramSurface | None:
    """The registry row (if any) matching whatever `services/telegram_own_channel.py::
    owned_chat_id()` currently resolves to - lets a caller ask "is our real publication target
    actually a classified, analytics-enabled PUBLIC surface, or is it silently just the internal
    editorial chat" without duplicating that resolution logic."""
    chat_id = owned_chat_id()
    if chat_id is None:
        return None
    return await get_surface_by_chat_id(session, chat_id)


async def owned_surface_is_public_and_analytics_enabled(session: AsyncSession) -> bool:
    """Spec §16's own required gate for the console: True only when the real owned-channel target
    is BOTH classified as a PUBLIC_* surface AND explicitly analytics_enabled. False (never a
    fabricated True) when unconfigured, internal, inactive, or analytics-disabled - the console
    must render PUBLIC_CHANNEL_NOT_CONFIGURED (or equivalent) in every False case."""
    surface = await resolve_owned_surface(session)
    if surface is None:
        return False
    return surface.active and surface.analytics_enabled and surface.role in PUBLIC_SURFACE_ROLES
