"""DIRECTOR-CONTROL-PLANE-1 §4/§6: InstagramAccount registry - mirrors services/
telegram_surface_registry.py's own shape exactly (same CRUD/upsert idempotency discipline). No row
is ever created with a guessed ig_user_id."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_account import InstagramAccount, InstagramAccountRole, InstagramConnectionState


async def create_account(
    session: AsyncSession, *, display_name: str, role: InstagramAccountRole = InstagramAccountRole.OWNED_BRAND_ACCOUNT,
    ig_user_id: str | None = None, username: str | None = None, active: bool = True,
) -> InstagramAccount:
    account = InstagramAccount(
        ig_user_id=ig_user_id, username=username, role=role, display_name=display_name, active=active,
        connection_state=InstagramConnectionState.CONNECTED if ig_user_id else InstagramConnectionState.NOT_CONNECTED,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def get_account(session: AsyncSession, account_id: UUID) -> InstagramAccount | None:
    return await session.get(InstagramAccount, account_id)


async def get_owned_brand_account(session: AsyncSession) -> InstagramAccount | None:
    """The one row (if any) representing the real NINJA PULSE Instagram account - never a guess
    among several rows; returns None (not a fabricated placeholder) when no row has ever been
    registered, which is this table's own honest default state (module docstring)."""
    stmt = select(InstagramAccount).where(
        InstagramAccount.role == InstagramAccountRole.OWNED_BRAND_ACCOUNT, InstagramAccount.active.is_(True),
    )
    return (await session.execute(stmt)).scalars().first()


async def list_accounts(session: AsyncSession, *, active_only: bool = False) -> list[InstagramAccount]:
    stmt = select(InstagramAccount)
    if active_only:
        stmt = stmt.where(InstagramAccount.active.is_(True))
    return list((await session.execute(stmt)).scalars().all())
