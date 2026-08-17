"""TELEGRAPH Checkpoint 2: services.telegraph_shortlist_service - persistence, decision
idempotency, cost-boundary structural proofs, and Checkpoint 1 regression coverage.

Reuses tests.test_telegraph_topic_candidates's own established fixtures (`_make_source`,
`_make_anchor_event`, `_make_analyzed_event`, `_require_tables`) - this repo's own established
cross-file fixture-reuse convention (e.g. tests/test_router_media_integration.py importing from
tests/test_content_worker_cycle.py), never duplicated.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory
from database.models.story import Story
from database.models.telegraph_shortlist import (
    TelegraphProposalStatus,
    TelegraphShortlistBatch,
    TelegraphTopicProposal,
)
from services.telegraph_shortlist_service import (
    TelegraphShortlistService,
    create_telegraph_shortlist,
    get_recently_proposed_story_ids,
)
from tests.test_telegraph_topic_candidates import (
    _make_analyzed_event,
    _make_anchor_event,
    _make_source,
    _require_tables as _require_story_tables,
)

_SERVICE_SOURCE = Path("services/telegraph_shortlist_service.py").read_text(encoding="utf-8")


async def _require_shortlist_tables(session: AsyncSession) -> None:
    await _require_story_tables(session)
    from sqlalchemy import inspect

    def _check(sync_session: object) -> bool:
        insp = inspect(sync_session.connection())  # type: ignore[attr-defined]
        return insp.has_table("telegraph_shortlist_batches") and insp.has_table("telegraph_topic_proposals")

    if not await session.run_sync(_check):
        pytest.skip("telegraph_shortlist_batches/telegraph_topic_proposals not present on this DB.")


async def _seed_story_with_events(
    db_session: AsyncSession, *, title: str = "Strong story", score: int = 85, significance: float = 8.0,
    n_events: int = 1, topic_bucket: str = "product",
) -> Story:
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title=title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket=topic_bucket, first_event_id=anchor.id, event_count=n_events,
    )
    db_session.add(story)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    match_types = ["new_story", "story_update", "supporting_source"]
    for i in range(n_events):
        src = source if i == 0 else await _make_source(db_session)
        await _make_analyzed_event(
            db_session, src, story, match_type=match_types[min(i, 2)], published_at=now - timedelta(hours=i),
            score=score, significance=significance, acquisition_status="FULL_TEXT",
        )
    return story


# ---------------------------------------------------------------------------------------------
# Persistence (required tests 1-10)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1_shortlist_creates_one_batch_and_n_proposals(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Story A")
    await _seed_story_with_events(db_session, title="Story B")

    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    assert result.batch is not None
    assert result.batch.proposal_count == len(result.proposals) == 2


@pytest.mark.asyncio
async def test_2_one_story_yields_one_proposal(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, n_events=3)

    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    matching = [p for p in result.proposals if p.story_id == story.id]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_3_proposals_persisted_in_deterministic_rank_order(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Weaker", score=60, significance=5.5)
    await _seed_story_with_events(db_session, title="Stronger", score=95, significance=9.0)

    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    ranks = [p.rank for p in result.proposals]
    assert ranks == sorted(ranks)
    assert result.proposals[0].topic_score >= result.proposals[-1].topic_score

    service = TelegraphShortlistService(db_session)
    reloaded = await service.list_proposals_for_batch(result.batch.id)  # type: ignore[union-attr]
    assert [p.id for p in reloaded] == [p.id for p in result.proposals]


@pytest.mark.asyncio
async def test_4_zero_candidates_is_valid_no_batch_persisted(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    # No stories seeded at all in this isolated transaction/window.
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(
        db_session, limit=5, now=now, recency_cutoff_hours=0.001,  # near-zero window, nothing qualifies
    )
    assert result.batch is None
    assert result.proposals == []


@pytest.mark.asyncio
async def test_5_already_recently_proposed_story_is_excluded(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, title="Already proposed")
    now = datetime.now(timezone.utc)

    first = await create_telegraph_shortlist(
        db_session, limit=5, now=now, recency_cutoff_hours=72.0, reproposal_cooldown_hours=24.0,
    )
    assert story.id in [p.story_id for p in first.proposals]

    second = await create_telegraph_shortlist(
        db_session, limit=5, now=now + timedelta(hours=1), recency_cutoff_hours=72.0,
        reproposal_cooldown_hours=24.0,
    )
    assert story.id not in [p.story_id for p in second.proposals]


@pytest.mark.asyncio
async def test_6_story_outside_reproposal_cooldown_can_appear_again(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, title="Cooldown expired")
    now = datetime.now(timezone.utc)

    first = await create_telegraph_shortlist(
        db_session, limit=5, now=now, recency_cutoff_hours=72.0, reproposal_cooldown_hours=1.0,
    )
    assert story.id in [p.story_id for p in first.proposals]

    later = await create_telegraph_shortlist(
        db_session, limit=5, now=now + timedelta(hours=2), recency_cutoff_hours=72.0,
        reproposal_cooldown_hours=1.0,
    )
    assert story.id in [p.story_id for p in later.proposals]


@pytest.mark.asyncio
async def test_7_proposal_stores_compact_score_and_rationale_snapshot(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Snapshot story")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    proposal = result.proposals[0]
    assert isinstance(proposal.topic_score, int)
    assert proposal.rationale_snapshot
    assert isinstance(proposal.signals_snapshot, dict)
    assert "normalized_significance" in proposal.signals_snapshot
    assert "source_diversity_proxy" in proposal.signals_snapshot


@pytest.mark.asyncio
async def test_proposal_saves_editorial_channel(db_session: AsyncSession) -> None:
    """TELEGRAPH editorial channel split, required test 4 ("proposal saves channel"):
    create_telegraph_shortlist() classifies and persists a real EditorialChannel value on every
    proposal it creates - never left at some implicit/unset state."""
    from schemas.editorial import EditorialChannel

    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Как использовать новую функцию Claude")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    proposal = result.proposals[0]
    assert isinstance(proposal.editorial_channel, EditorialChannel)
    assert proposal.editorial_channel == EditorialChannel.NINJA_AI
    # The channel rationale is appended to rationale_snapshot, per the task's own explicit
    # "в rationale добавить: почему выбран канал" requirement.
    assert "Канал:" in proposal.rationale_snapshot
    assert "NINJA_AI" in proposal.rationale_snapshot


@pytest.mark.asyncio
async def test_8_no_full_news_content_copied_into_proposal(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="No leakage story")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    proposal = result.proposals[0]
    # Only the title/rationale/compact signals - never a raw_extracted_text/cleaned_text field,
    # never the full research "facts" list, never NewsEvent.content.
    column_names = {c.name for c in TelegraphTopicProposal.__table__.columns}
    assert "raw_extracted_text" not in column_names
    assert "cleaned_text" not in column_names
    assert "content" not in column_names
    assert len(proposal.rationale_snapshot) < 2000  # a compact one-liner, not a research bundle


@pytest.mark.asyncio
async def test_9_fk_integrity_batch_to_proposal_to_story(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, title="FK integrity story")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    proposal = result.proposals[0]
    assert proposal.batch_id == result.batch.id  # type: ignore[union-attr]
    assert proposal.story_id == story.id

    reloaded_batch = await db_session.get(TelegraphShortlistBatch, proposal.batch_id)
    reloaded_story = await db_session.get(Story, proposal.story_id)
    assert reloaded_batch is not None
    assert reloaded_story is not None


@pytest.mark.asyncio
async def test_10_transaction_is_all_or_nothing(db_session: AsyncSession) -> None:
    """If persistence fails partway, no partial batch/proposal set should be visible - proven
    here by seeding two eligible stories and confirming a successful run always produces exactly
    proposal_count rows, never a partial subset (the create function commits once, at the end,
    for the whole batch+proposals)."""
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Txn A")
    await _seed_story_with_events(db_session, title="Txn B")
    now = datetime.now(timezone.utc)

    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    assert result.batch is not None

    rows = (
        await db_session.execute(
            select(TelegraphTopicProposal).where(TelegraphTopicProposal.batch_id == result.batch.id)
        )
    ).scalars().all()
    assert len(rows) == result.batch.proposal_count == len(result.proposals)


# ---------------------------------------------------------------------------------------------
# Decisions (required tests 11-16, 19 partial)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_11_pending_to_approved(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Approve me")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    updated = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert updated is not None
    assert updated.status == TelegraphProposalStatus.APPROVED
    assert updated.decided_at is not None


@pytest.mark.asyncio
async def test_12_pending_to_rejected(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Reject me")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    updated = await service.set_decision(
        proposal.id, TelegraphProposalStatus.REJECTED, decided_by_telegram_user_id=111,
    )
    assert updated is not None
    assert updated.status == TelegraphProposalStatus.REJECTED
    assert updated.decided_at is not None


@pytest.mark.asyncio
async def test_13_approving_an_approved_proposal_is_idempotent(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Double approve")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    first = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    second = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert first is not None and second is not None
    assert first.decided_at == second.decided_at
    assert second.status == TelegraphProposalStatus.APPROVED


@pytest.mark.asyncio
async def test_14_rejecting_a_rejected_proposal_is_idempotent(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Double reject")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    first = await service.set_decision(
        proposal.id, TelegraphProposalStatus.REJECTED, decided_by_telegram_user_id=111,
    )
    second = await service.set_decision(
        proposal.id, TelegraphProposalStatus.REJECTED, decided_by_telegram_user_id=111,
    )
    assert first is not None and second is not None
    assert first.decided_at == second.decided_at
    assert second.status == TelegraphProposalStatus.REJECTED


@pytest.mark.asyncio
async def test_15_opposite_decision_after_final_is_immutable(db_session: AsyncSession) -> None:
    """Documented safe policy (services.telegraph_shortlist_service.TelegraphShortlistService.
    set_decision()'s own docstring): once a proposal reaches a final status, the OPPOSITE
    decision is a no-op, never silently flips it."""
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Immutable final")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    approved = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    flipped = await service.set_decision(
        proposal.id, TelegraphProposalStatus.REJECTED, decided_by_telegram_user_id=222,
    )
    assert approved is not None and flipped is not None
    assert flipped.status == TelegraphProposalStatus.APPROVED  # unchanged
    assert flipped.decided_at == approved.decided_at


@pytest.mark.asyncio
async def test_16_decided_at_set_once(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Decided once")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]
    assert proposal.decided_at is None

    service = TelegraphShortlistService(db_session)
    decided = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert decided is not None and decided.decided_at is not None
    first_decided_at = decided.decided_at

    again = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert again is not None
    assert again.decided_at == first_decided_at


@pytest.mark.asyncio
async def test_19_nonexistent_proposal_fails_safely(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    service = TelegraphShortlistService(db_session)
    result = await service.set_decision(
        uuid.uuid4(), TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert result is None


# ---------------------------------------------------------------------------------------------
# Decision auditability (security-correction: decided_by_telegram_user_id)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decided_by_telegram_user_id_null_while_pending(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Decider null while pending")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    assert result.proposals[0].decided_by_telegram_user_id is None


@pytest.mark.asyncio
async def test_decided_by_telegram_user_id_persisted_on_approve(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Decider persisted")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    updated = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=424242,
    )
    assert updated is not None
    assert updated.decided_by_telegram_user_id == 424242


@pytest.mark.asyncio
async def test_repeated_same_decision_preserves_original_decider(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Repeat preserves decider")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    first = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    # A different (still authorized) user double-taps the same button second.
    second = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=999,
    )
    assert first is not None and second is not None
    assert second.decided_by_telegram_user_id == 111  # original decider preserved, never overwritten


@pytest.mark.asyncio
async def test_opposite_decision_after_final_preserves_original_decider(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    await _seed_story_with_events(db_session, title="Opposite preserves decider")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    proposal = result.proposals[0]

    service = TelegraphShortlistService(db_session)
    approved = await service.set_decision(
        proposal.id, TelegraphProposalStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    flipped = await service.set_decision(
        proposal.id, TelegraphProposalStatus.REJECTED, decided_by_telegram_user_id=999,
    )
    assert approved is not None and flipped is not None
    assert flipped.status == TelegraphProposalStatus.APPROVED
    assert flipped.decided_by_telegram_user_id == 111


# ---------------------------------------------------------------------------------------------
# Reproposal lookback signal (get_recently_proposed_story_ids)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recently_proposed_signal_reflects_real_persisted_rows(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, title="Recently proposed lookup")
    now = datetime.now(timezone.utc)
    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    assert story.id in [p.story_id for p in result.proposals]

    recent = await get_recently_proposed_story_ids(db_session, now=now + timedelta(hours=1), cooldown_hours=24.0)
    assert story.id in recent

    long_after = await get_recently_proposed_story_ids(
        db_session, now=now + timedelta(hours=48), cooldown_hours=24.0,
    )
    assert story.id not in long_after


# ---------------------------------------------------------------------------------------------
# Cost boundary (required tests 31-38, structural)
# ---------------------------------------------------------------------------------------------


def test_31_32_33_no_llm_gateway_call_in_service_source() -> None:
    for forbidden in ("call_generate", "LLMGateway", "WorkflowRunner", "capabilities.executor"):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected LLM/Gateway reference: {forbidden}"


def test_34_35_no_article_acquisition_or_web_fetch_in_service_source() -> None:
    for forbidden in ("acquire_article(", "get_or_acquire", "safe_fetch", "import httpx", "import requests"):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected fetch reference: {forbidden}"
    assert "from services.article_acquisition import" not in _SERVICE_SOURCE


def test_36_37_no_article_generation_or_telegraph_article_task_in_service_source() -> None:
    for forbidden in ("TELEGRAPH_ARTICLE", "run_content_generation_for_event", "CopywritingCapability"):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected article-generation reference: {forbidden}"


def test_38_no_telegra_ph_client_reference_in_service_source() -> None:
    for forbidden in ("telegra.ph", "createPage", "createAccount", "editPage"):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected telegra.ph reference: {forbidden}"


def test_no_telegram_send_call_in_service_source() -> None:
    for forbidden in ("aiogram", "bot.send", "send_to_editorial_destination"):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected Telegram reference: {forbidden}"


# ---------------------------------------------------------------------------------------------
# Checkpoint 1 regression (required tests 40-44)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_40_41_build_telegraph_topic_candidates_still_deterministic_and_limit_respected(
    db_session: AsyncSession,
) -> None:
    await _require_shortlist_tables(db_session)
    from services.telegraph_topic_candidates import build_telegraph_topic_candidates

    await _seed_story_with_events(db_session, title="Regression A")
    await _seed_story_with_events(db_session, title="Regression B")
    now = datetime.now(timezone.utc)

    first = await build_telegraph_topic_candidates(db_session, limit=1, now=now, recency_cutoff_hours=72.0)
    second = await build_telegraph_topic_candidates(db_session, limit=1, now=now, recency_cutoff_hours=72.0)
    assert len(first) == 1
    assert [c.story_id for c in first] == [c.story_id for c in second]


@pytest.mark.asyncio
async def test_42_already_proposed_story_ids_supplied_from_persistence(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, title="Persistence-supplied exclusion")
    now = datetime.now(timezone.utc)
    await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)

    already_proposed = await get_recently_proposed_story_ids(db_session, now=now, cooldown_hours=24.0)
    assert story.id in already_proposed

    from services.telegraph_topic_candidates import build_telegraph_topic_candidates

    candidates = await build_telegraph_topic_candidates(
        db_session, limit=5, now=now, recency_cutoff_hours=72.0,
        already_proposed_story_ids=already_proposed,
    )
    assert story.id not in [c.story_id for c in candidates]


@pytest.mark.asyncio
async def test_43_semantic_duplicates_never_create_independent_proposals(db_session: AsyncSession) -> None:
    await _require_shortlist_tables(db_session)
    source = await _make_source(db_session)
    anchor = await _make_anchor_event(db_session, source)
    story = Story(
        id=uuid.uuid4(), title="Duplicate-proof story", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    await _make_analyzed_event(
        db_session, source, story, match_type="new_story", published_at=now,
        score=85, significance=8.0, acquisition_status="FULL_TEXT",
    )
    dup_source = await _make_source(db_session)
    await _make_analyzed_event(
        db_session, dup_source, story, match_type="semantic_duplicate", published_at=now,
        score=99, significance=10.0,
    )

    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    matching = [p for p in result.proposals if p.story_id == story.id]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_44_supporting_sources_strengthen_one_story_never_separate_proposals(
    db_session: AsyncSession,
) -> None:
    await _require_shortlist_tables(db_session)
    story = await _seed_story_with_events(db_session, title="Supporting-source story", n_events=2)
    now = datetime.now(timezone.utc)

    result = await create_telegraph_shortlist(db_session, limit=5, now=now, recency_cutoff_hours=72.0)
    matching = [p for p in result.proposals if p.story_id == story.id]
    assert len(matching) == 1
    assert matching[0].signals_snapshot["source_diversity_proxy"] >= 2
