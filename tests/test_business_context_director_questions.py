"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: services/business_context_proposal_service.py's new
Director-initiated information-need functions - creation/dedup, the shared reply-to/exactly-one-
pending resolution rule, and the conservative proactive scanner. Real db_session (Postgres),
mirroring tests/test_business_context_proposal_service.py's own conventions exactly."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.business_context_proposal import BusinessContextCommandType, BusinessContextProposalStatus
from services.business_context_proposal_service import (
    DIRECTOR_INITIATED_ORIGIN,
    close_answered_question,
    create_director_information_need,
    create_proposal,
    find_open_director_question,
    list_pending_proposals,
    resolve_target_proposal,
    scan_for_director_information_needs,
)
from services.campaign_service import create_campaign, create_milestone
from services.product_context_service import create_product, create_product_context_version


@pytest.mark.asyncio
async def test_create_director_information_need_is_pending_with_empty_change_set(db_session: AsyncSession) -> None:
    proposal = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT",
        question_text="Какая модель оплаты будет у Production Mode?",
    )
    assert proposal.status == BusinessContextProposalStatus.PENDING
    assert proposal.origin == DIRECTOR_INITIATED_ORIGIN
    assert proposal.proposed_change_set == []
    assert proposal.origin_context == {
        "product_slug": "ai", "missing_fact": "production_mode.billing",
        "opportunity_id": "opp-1", "opportunity_source_type": "PRODUCT",
    }


@pytest.mark.asyncio
async def test_dedup_returns_existing_open_question_never_creates_a_duplicate(db_session: AsyncSession) -> None:
    first = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT", question_text="Q1",
    )
    second = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-2", opportunity_source_type="TREND", question_text="Q2 (different wording)",
    )
    assert first.id == second.id
    assert second.question_text == "Q1"  # the original question wins, never silently replaced


@pytest.mark.asyncio
async def test_find_open_director_question_returns_none_after_it_is_closed(db_session: AsyncSession) -> None:
    proposal = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT", question_text="Q1",
    )
    await close_answered_question(db_session, proposal.id, answered_by=42)
    still_open = await find_open_director_question(db_session, product_slug="ai", missing_fact="production_mode.billing")
    assert still_open is None

    # A new question for the SAME fact may now be raised again (not permanently blocked).
    again = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-3", opportunity_source_type="PRODUCT", question_text="Q3",
    )
    assert again.id != proposal.id


@pytest.mark.asyncio
async def test_resolve_target_proposal_reply_to_message_wins_even_with_multiple_pending(db_session: AsyncSession) -> None:
    p1 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="first",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve1", "name": "R1", "status": None}],
        created_by=1, telegram_chat_id=-100, telegram_topic_id=None,
    )
    p1.telegram_message_id = 501
    p2 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="second",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve2", "name": "R2", "status": None}],
        created_by=1, telegram_chat_id=-100, telegram_topic_id=None,
    )
    p2.telegram_message_id = 502
    await db_session.commit()

    resolved, pending = await resolve_target_proposal(
        db_session, telegram_chat_id=-100, telegram_topic_id=None, reply_to_message_id=501,
    )
    assert resolved is not None
    assert resolved.id == p1.id
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_resolve_target_proposal_ambiguous_with_no_reply_returns_none(db_session: AsyncSession) -> None:
    await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="first",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve3", "name": "R3", "status": None}],
        created_by=1, telegram_chat_id=-200, telegram_topic_id=None,
    )
    await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="second",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve4", "name": "R4", "status": None}],
        created_by=1, telegram_chat_id=-200, telegram_topic_id=None,
    )
    resolved, pending = await resolve_target_proposal(
        db_session, telegram_chat_id=-200, telegram_topic_id=None, reply_to_message_id=None,
    )
    assert resolved is None
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_resolve_target_proposal_exactly_one_pending_is_unambiguous(db_session: AsyncSession) -> None:
    only = await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="only",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve5", "name": "R5", "status": None}],
        created_by=1, telegram_chat_id=-300, telegram_topic_id=None,
    )
    resolved, pending = await resolve_target_proposal(
        db_session, telegram_chat_id=-300, telegram_topic_id=None, reply_to_message_id=None,
    )
    assert resolved is not None
    assert resolved.id == only.id
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_resolve_target_proposal_zero_pending_returns_none_and_empty_list(db_session: AsyncSession) -> None:
    resolved, pending = await resolve_target_proposal(
        db_session, telegram_chat_id=-999999, telegram_topic_id=None, reply_to_message_id=None,
    )
    assert resolved is None
    assert pending == []


@pytest.mark.asyncio
async def test_list_pending_proposals_excludes_confirmed_and_cancelled(db_session: AsyncSession) -> None:
    from services.business_context_proposal_service import confirm_proposal

    p1 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="a",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve6", "name": "R6", "status": None}],
        created_by=1, telegram_chat_id=-400, telegram_topic_id=None,
    )
    await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="b",
        proposed_change_set=[{"entity_type": "product", "slug": "resolve7", "name": "R7", "status": None}],
        created_by=1, telegram_chat_id=-400, telegram_topic_id=None,
    )
    await confirm_proposal(db_session, p1.id, decided_by=1)
    pending = await list_pending_proposals(db_session, telegram_chat_id=-400, telegram_topic_id=None)
    assert len(pending) == 1
    assert pending[0].raw_instruction == "b"


# ---------------------------------------------------------------------------
# Proactive scan (conservative, deterministic, zero-LLM, no Trend Radar dependency)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_reasks_stale_undecided_fact_after_cooldown(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scan1", name="Scan Test 1")
    old_time = datetime.now(timezone.utc) - timedelta(days=30)
    version = await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="undecided a while ago",
        structured_context={"undecided_facts_add": ["production_mode.billing"]}, confirmed_by=1,
    )
    # Backdate the version's created_at directly (server_default sets "now" at insert time).
    version.created_at = old_time
    await db_session.commit()

    created = await scan_for_director_information_needs(
        db_session, now=datetime.now(timezone.utc), undecided_reask_cooldown=timedelta(days=14),
    )
    assert any(p.origin_context.get("missing_fact") == "production_mode.billing" for p in created)


@pytest.mark.asyncio
async def test_scan_does_not_reask_within_cooldown(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scan2", name="Scan Test 2")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="undecided just now",
        structured_context={"undecided_facts_add": ["production_mode.billing"]}, confirmed_by=1,
    )
    created = await scan_for_director_information_needs(
        db_session, now=datetime.now(timezone.utc), undecided_reask_cooldown=timedelta(days=14),
    )
    assert not any(
        p.origin_context.get("product_slug") == "scan2" and p.origin_context.get("missing_fact") == "production_mode.billing"
        for p in created
    )


@pytest.mark.asyncio
async def test_scan_flags_approaching_milestone_with_no_fresh_context(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scan3", name="Scan Test 3")
    campaign = await create_campaign(db_session, product_id=product.id, name="Scan Test 3 Launch")
    now = datetime.now(timezone.utc)
    milestone = await create_milestone(
        db_session, product_id=product.id, campaign_id=campaign.id, title="Public launch",
        milestone_at=now + timedelta(days=3), asset_preparation_allowed=True,
    )
    created = await scan_for_director_information_needs(db_session, now=now, milestone_lookahead=timedelta(days=14))
    assert any(p.origin_context.get("opportunity_id") == f"approaching_milestone:{milestone.id}" for p in created)


@pytest.mark.asyncio
async def test_scan_does_not_flag_milestone_without_asset_preparation_allowed(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scan4", name="Scan Test 4")
    campaign = await create_campaign(db_session, product_id=product.id, name="Scan Test 4 Launch")
    now = datetime.now(timezone.utc)
    milestone = await create_milestone(
        db_session, product_id=product.id, campaign_id=campaign.id, title="Internal only",
        milestone_at=now + timedelta(days=3), asset_preparation_allowed=False,
    )
    created = await scan_for_director_information_needs(db_session, now=now, milestone_lookahead=timedelta(days=14))
    assert not any(p.origin_context.get("opportunity_id") == f"approaching_milestone:{milestone.id}" for p in created)


@pytest.mark.asyncio
async def test_scan_is_deduplicated_across_repeated_calls(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="scan5", name="Scan Test 5")
    old_time = datetime.now(timezone.utc) - timedelta(days=30)
    version = await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="undecided a while ago",
        structured_context={"undecided_facts_add": ["some.fact"]}, confirmed_by=1,
    )
    version.created_at = old_time
    await db_session.commit()

    now = datetime.now(timezone.utc)
    first_run = await scan_for_director_information_needs(db_session, now=now, undecided_reask_cooldown=timedelta(days=14))
    second_run = await scan_for_director_information_needs(db_session, now=now, undecided_reask_cooldown=timedelta(days=14))
    relevant_first = [p for p in first_run if p.origin_context.get("product_slug") == "scan5"]
    relevant_second = [p for p in second_run if p.origin_context.get("product_slug") == "scan5"]
    assert len(relevant_first) == 1
    assert relevant_second[0].id == relevant_first[0].id  # same row returned, never duplicated
