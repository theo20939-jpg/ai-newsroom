"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §11/§12/§21: durable, idempotent Instagram-package-to-
Telegram-editorial-topic delivery state - mirrors `services.instagram_publication_state`'s own
shape and concurrency-safety pattern exactly (SAVEPOINT + `IntegrityError` recovery), applied to a
completely separate lifecycle (editorial review inside Telegram, never a real Instagram write).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_editorial_delivery import InstagramEditorialDelivery, InstagramEditorialDeliveryState

logger = logging.getLogger(__name__)

_CURRENT_STATES = (
    InstagramEditorialDeliveryState.PENDING, InstagramEditorialDeliveryState.DELIVERED,
    InstagramEditorialDeliveryState.APPROVED, InstagramEditorialDeliveryState.REGENERATING_FULL,
    InstagramEditorialDeliveryState.REGENERATING_TEXT, InstagramEditorialDeliveryState.REGENERATING_VISUAL,
    InstagramEditorialDeliveryState.HOLD, InstagramEditorialDeliveryState.BLOCK,
)
_REGENERATING_STATES = (
    InstagramEditorialDeliveryState.REGENERATING_FULL, InstagramEditorialDeliveryState.REGENERATING_TEXT,
    InstagramEditorialDeliveryState.REGENERATING_VISUAL,
)
_ACTIONABLE_STATES = (InstagramEditorialDeliveryState.DELIVERED,)
"""§13/§N "stale callback fails safely": a button press is honored only while the delivery is
sitting in this exact state - not yet approved, not already mid-regeneration (double-tap guard),
not superseded by a newer version, not HOLD/BLOCK (never presented with action buttons at all -
see the presenter)."""


def compute_package_identity(*, source_key: str, content_format: str) -> str:
    """Stable across every regeneration of "the same story/opportunity as the same format" -
    deliberately never derived from a package's own random `package_id` (same reasoning as
    `instagram_publication_state.py::compute_idempotency_key()`). `source_key` is whatever stable
    upstream identity the caller has (`opportunity.id`/`story_id`) - this function only combines it
    with the format, it invents no new authority over what counts as "the same story."""
    payload = f"instagram_editorial:{source_key}:{content_format}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class InstagramEditorialDeliveryService:
    """Stateless - safe to construct fresh per call, exactly like `InstagramPublicationStateService`."""

    async def find_current(self, session: AsyncSession, *, package_identity: str) -> InstagramEditorialDelivery | None:
        stmt = (
            select(InstagramEditorialDelivery)
            .where(InstagramEditorialDelivery.package_identity == package_identity)
            .where(InstagramEditorialDelivery.state.in_(_CURRENT_STATES))
            .order_by(InstagramEditorialDelivery.version.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, session: AsyncSession, delivery_id: Any) -> InstagramEditorialDelivery | None:
        return await session.get(InstagramEditorialDelivery, delivery_id)

    async def get_or_create_first_version(
        self, session: AsyncSession, *, package_identity: str, source_story_id: str | None,
        content_format: str, package_snapshot: dict,
    ) -> tuple[InstagramEditorialDelivery, bool]:
        """§21 duplicate prevention: if a CURRENT row already exists for this identity (any
        version), it is returned unchanged and `created=False` - a worker cycle re-considering the
        same story never creates a second row nor re-sends. `created=True` only for a genuinely
        first-ever delivery of this identity. Concurrency-safe via the same SAVEPOINT +
        `IntegrityError` pattern `InstagramPublicationStateService.get_or_create()` established."""
        existing = await self.find_current(session, package_identity=package_identity)
        if existing is not None:
            return existing, False

        delivery = InstagramEditorialDelivery(
            package_identity=package_identity, version=1, source_story_id=source_story_id,
            content_format=content_format, state=InstagramEditorialDeliveryState.PENDING,
            package_snapshot=package_snapshot,
        )
        try:
            async with session.begin_nested():
                session.add(delivery)
                await session.flush()
        except IntegrityError:
            winner = await self.find_current(session, package_identity=package_identity)
            if winner is None:  # pragma: no cover - the violation proves a row exists
                raise
            return winner, False
        logger.info(
            "instagram_editorial_delivery_created",
            extra={"delivery_id": str(delivery.id), "package_identity": package_identity, "version": 1},
        )
        return delivery, True

    async def mark_delivered(
        self, session: AsyncSession, delivery: InstagramEditorialDelivery, *, chat_id: int, topic_id: int | None,
        media_message_ids: list[int], control_message_id: int | None,
    ) -> InstagramEditorialDelivery:
        delivery.telegram_chat_id = chat_id
        delivery.telegram_topic_id = topic_id
        delivery.media_message_ids = media_message_ids
        delivery.control_message_id = control_message_id
        if delivery.state == InstagramEditorialDeliveryState.PENDING:
            delivery.state = InstagramEditorialDeliveryState.DELIVERED
        await session.flush()
        return delivery

    async def mark_hold_or_block(
        self, session: AsyncSession, delivery: InstagramEditorialDelivery, *, state: InstagramEditorialDeliveryState,
    ) -> InstagramEditorialDelivery:
        assert state in (InstagramEditorialDeliveryState.HOLD, InstagramEditorialDeliveryState.BLOCK)
        delivery.state = state
        await session.flush()
        return delivery

    def is_actionable(self, delivery: InstagramEditorialDelivery, *, expected_version: int) -> bool:
        """§11/§N: the single stale-callback guard every button handler must call before doing
        anything - `False` for a version mismatch (a newer version already superseded this one) or
        a state that no longer accepts an action (already approved, mid-regeneration, HOLD/BLOCK)."""
        return delivery.version == expected_version and delivery.state in _ACTIONABLE_STATES

    async def set_approved(
        self, session: AsyncSession, delivery: InstagramEditorialDelivery, *, telegram_user_id: int,
    ) -> InstagramEditorialDelivery:
        """§10 "Принять": idempotent and immutable-once-final, byte-for-byte the same policy
        `TelegramArticleReviewService.set_decision()` already established (§H/§I: this ONLY changes
        `state`, it never calls any Instagram API and never can - no such call exists on this code
        path at all)."""
        if delivery.state != InstagramEditorialDeliveryState.DELIVERED:
            return delivery  # already final/regenerating/stale - no mutation, no side effect
        delivery.state = InstagramEditorialDeliveryState.APPROVED
        delivery.decided_by_telegram_user_id = telegram_user_id
        await session.flush()
        logger.info("instagram_editorial_delivery_approved", extra={"delivery_id": str(delivery.id)})
        return delivery

    async def begin_regeneration(
        self, session: AsyncSession, delivery: InstagramEditorialDelivery, *, kind: InstagramEditorialDeliveryState,
        expected_version: int,
    ) -> InstagramEditorialDelivery | None:
        """§11/§K double-regeneration guard: returns `None` (no mutation) if the delivery is not
        currently actionable (already regenerating from an earlier tap, already approved, stale
        version, or HOLD/BLOCK) - the caller must treat `None` as "do nothing, tell the editor this
        was already handled or is out of date", never retry silently."""
        assert kind in _REGENERATING_STATES
        if not self.is_actionable(delivery, expected_version=expected_version):
            return None
        delivery.state = kind
        await session.flush()
        logger.info("instagram_editorial_delivery_regeneration_started", extra={"delivery_id": str(delivery.id), "kind": kind.value})
        return delivery

    async def create_new_version(
        self, session: AsyncSession, *, previous: InstagramEditorialDelivery, package_snapshot: dict,
    ) -> InstagramEditorialDelivery:
        """Supersedes `previous` and creates version+1 in the SAME transaction - the partial unique
        index on `package_identity` (states other than SUPERSEDED) guarantees these two writes can
        never leave two simultaneously-current rows for the same identity, even under a race."""
        previous.state = InstagramEditorialDeliveryState.SUPERSEDED
        new_version = InstagramEditorialDelivery(
            package_identity=previous.package_identity, version=previous.version + 1,
            source_story_id=previous.source_story_id, content_format=previous.content_format,
            state=InstagramEditorialDeliveryState.PENDING, package_snapshot=package_snapshot,
        )
        session.add(new_version)
        await session.flush()
        logger.info(
            "instagram_editorial_delivery_new_version",
            extra={"package_identity": previous.package_identity, "version": new_version.version},
        )
        return new_version

    async def fail_regeneration_back_to_delivered(
        self, session: AsyncSession, delivery: InstagramEditorialDelivery,
    ) -> InstagramEditorialDelivery:
        """A regeneration attempt failed (pipeline error) - restore the editor's ability to act on
        the STILL-CURRENT, still-valid prior version rather than leaving it stuck in a
        REGENERATING_* state forever."""
        if delivery.state in _REGENERATING_STATES:
            delivery.state = InstagramEditorialDeliveryState.DELIVERED
            await session.flush()
        return delivery
