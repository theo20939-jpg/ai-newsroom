"""Phase 18.10 M3: pure, tier-1 unit tests for services.story_telegram_delivery.
determine_reply_target() - the single decision point governing every story-linked Telegram send.
No DB, no Telegram, no aiogram import.
"""
from uuid import uuid4

from database.models.story_telegram_delivery import DeliveryType
from services.story_telegram_delivery import (
    FAIL_CLOSED_ROUTE_TO_REVIEW,
    SEND_AS_REPLY,
    SEND_AS_ROOT,
    build_idempotency_key,
    determine_reply_target,
)


def test_non_update_always_sends_as_root_with_no_reply_target() -> None:
    decision = determine_reply_target(is_story_update=False, root_message_id=None)
    assert decision.action == SEND_AS_ROOT
    assert decision.reply_to_message_id is None
    assert decision.delivery_type == DeliveryType.ROOT


def test_non_update_sends_as_root_even_if_a_root_message_id_is_somehow_present() -> None:
    """A non-update draft is always a fresh post - root_message_id is irrelevant to this branch."""
    decision = determine_reply_target(is_story_update=False, root_message_id=999)
    assert decision.action == SEND_AS_ROOT
    assert decision.reply_to_message_id is None


def test_update_with_root_message_replies_to_it() -> None:
    decision = determine_reply_target(is_story_update=True, root_message_id=12345)
    assert decision.action == SEND_AS_REPLY
    assert decision.reply_to_message_id == 12345
    assert decision.delivery_type == DeliveryType.REPLY


def test_update_with_no_root_message_fails_closed() -> None:
    """The explicit, non-negotiable requirement: no root message ID exists -> fail closed, do
    not send a standalone update, route to review instead."""
    decision = determine_reply_target(is_story_update=True, root_message_id=None)
    assert decision.action == FAIL_CLOSED_ROUTE_TO_REVIEW
    assert decision.reply_to_message_id is None
    assert decision.delivery_type is None


def test_idempotency_key_is_deterministic_per_draft() -> None:
    draft_id = uuid4()
    assert build_idempotency_key(draft_id) == build_idempotency_key(draft_id)


def test_idempotency_key_differs_across_drafts() -> None:
    assert build_idempotency_key(uuid4()) != build_idempotency_key(uuid4())
