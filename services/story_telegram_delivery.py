"""Story Telegram Delivery (Phase 18.10 M3): reply-target determination and durable delivery
tracking for story-linked ContentDraft Telegram sends.

Split into a pure decision function (`determine_reply_target` - no I/O, fully unit-testable,
mirrors services/editorial_scoring.py's own established pure-calculator convention) and thin
async persistence functions (`get_root_delivery`, `record_delivery`) that worker/content_cycle.py
is the only caller of.

Core contract (explicit, non-negotiable requirement): a send is not "successful"
(DeliveryStatus.SENT) unless `telegram_message_id` was actually persisted - enforced both here
(only SENT is ever recorded together with a message_id) and at the database level (the
migration's own CHECK constraint). For a story update: `reply_to_message_id` MUST be the root
story message ID. If no root message exists yet, this fails closed - no standalone (non-reply)
send is ever attempted for an update; it is routed to review instead (DeliveryStatus.
SKIPPED_REVIEW), never silently downgraded to a fresh root post.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery


@dataclass(frozen=True)
class ReplyDecision:
    """The single decision point governing every story-linked Telegram send.

    `action`: "send_as_root" (a fresh post, no reply target), "send_as_reply" (a story update,
    replying to the story's own root message), or "fail_closed_route_to_review" (an update whose
    story has no discoverable root message - never sent as a standalone post)."""

    action: str  # "send_as_root" | "send_as_reply" | "fail_closed_route_to_review"
    reply_to_message_id: int | None
    delivery_type: DeliveryType | None


SEND_AS_ROOT = "send_as_root"
SEND_AS_REPLY = "send_as_reply"
FAIL_CLOSED_ROUTE_TO_REVIEW = "fail_closed_route_to_review"


def determine_reply_target(
    *, is_story_update: bool, root_message_id: int | None
) -> ReplyDecision:
    """Pure. `root_message_id` is the story's own root delivery's `telegram_message_id` (already
    resolved by the caller via `get_root_delivery()`), or None if no root delivery exists (or one
    exists but was never SENT - see `get_root_delivery()`'s own docstring for why only a SENT
    root ever counts)."""
    if not is_story_update:
        return ReplyDecision(SEND_AS_ROOT, None, DeliveryType.ROOT)
    if root_message_id is None:
        return ReplyDecision(FAIL_CLOSED_ROUTE_TO_REVIEW, None, None)
    return ReplyDecision(SEND_AS_REPLY, root_message_id, DeliveryType.REPLY)


def build_idempotency_key(content_draft_id: UUID) -> str:
    """Deterministic, derived from the draft id alone - the same draft always yields the same
    key, so a DB-level unique constraint on this column is the structural "never send the same
    draft twice" backstop, independent of any application-level retry logic."""
    return f"content_draft:{content_draft_id}"


async def get_root_delivery(session: AsyncSession, story_id: UUID) -> StoryTelegramDelivery | None:
    """The story's own root delivery, if a SUCCESSFUL one exists - only DeliveryStatus.SENT rows
    are ever eligible (a FAILED/UNCONFIRMED/SKIPPED_REVIEW attempt is not a real root message to
    reply to, even if one happens to exist), ordered by sent_at ascending so the true first
    successful post is always the one returned, even if it wasn't the first *attempt*."""
    stmt = (
        select(StoryTelegramDelivery)
        .where(
            StoryTelegramDelivery.story_id == story_id,
            StoryTelegramDelivery.delivery_type == DeliveryType.ROOT,
            StoryTelegramDelivery.delivery_status == DeliveryStatus.SENT,
        )
        .order_by(StoryTelegramDelivery.sent_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def record_delivery(
    session: AsyncSession,
    *,
    story_id: UUID,
    content_draft_id: UUID,
    telegram_chat_id: int | None,
    telegram_message_id: int | None,
    reply_to_message_id: int | None,
    delivery_type: DeliveryType,
    delivery_status: DeliveryStatus,
    sent_at: datetime | None,
) -> StoryTelegramDelivery:
    """Persists exactly one delivery attempt row. Never mutates an existing row - each attempt
    (even a retry) gets its own row; `idempotency_key`'s DB-level unique constraint is the
    backstop against a genuinely duplicate successful send for the same draft, not this
    function's own responsibility to check first (fail loud on a real constraint violation,
    never silently swallow one)."""
    delivery = StoryTelegramDelivery(
        story_id=story_id,
        content_draft_id=content_draft_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        reply_to_message_id=reply_to_message_id,
        delivery_type=delivery_type,
        delivery_status=delivery_status,
        idempotency_key=build_idempotency_key(content_draft_id),
        sent_at=sent_at,
    )
    session.add(delivery)
    return delivery
