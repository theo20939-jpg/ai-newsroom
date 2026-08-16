"""TELEGRAPH Checkpoint 2: durable shortlist creation + human-decision persistence.

Split, mirroring `services/meme_candidate_service.py`'s own established shape (constructor-
injected with the caller's already-open `AsyncSession`, one class owning every read/write against
its own tables) plus the checkpoint's own explicit A/B/C/D separation:

- A. deterministic batch/proposal creation - `create_telegraph_shortlist()` (this module)
- B. Telegram formatting - bot/telegraph_shortlist_formatting.py
- C. Telegram send - services/telegraph_shortlist_notifier.py
- D. callback decision mutation - `TelegraphShortlistService.set_decision()` (this module),
  called only from bot/handlers/telegraph_shortlist.py

No LLM Gateway call, no web/article-fetch call, no Telegram call anywhere in this module - see
tests/test_telegraph_shortlist_service.py's own structural source-scan tests.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.story import Story
from database.models.telegraph_shortlist import (
    TelegraphProposalStatus,
    TelegraphShortlistBatch,
    TelegraphTopicProposal,
)
from services.telegraph_topic_candidates import TelegraphTopicCandidate, build_telegraph_topic_candidates

logger = logging.getLogger(__name__)

_RECENT_PROPOSAL_SCAN_SAFETY_CAP = 2_000


def _derive_topic_title(candidate: TelegraphTopicCandidate) -> str:
    """Deterministic, no LLM. `Story.title` is a non-nullable column ("title of the first event
    that started this story" - database/models/story.py's own docstring), so
    `candidate.story_title` (== `Story.title`, per services/telegraph_topic_candidates.py::
    build_story_evidence_summary()) is always the correct, already-preferred title - this is the
    "Story canonical title if one exists" branch the phase brief asks for. The blank-string guard
    below is defensive only (structurally unreachable today, since the column is NOT NULL), kept
    so this function has a real, documented fallback rather than silently returning an empty
    string if that invariant is ever weakened."""
    title = candidate.story_title.strip()
    return title if title else "Тема без названия"


def _build_signals_snapshot(candidate: TelegraphTopicCandidate) -> dict[str, object]:
    """Compact only - never the full research/evidence text. Every value here already exists on
    `candidate.summary`/`candidate.signals`; this just selects the small subset a shortlist
    render/review actually needs."""
    return {
        "normalized_significance": candidate.signals.normalized_significance,
        "news_score": candidate.summary.max_score,
        "evidence_tier": candidate.signals.evidence_tier,
        "source_diversity_proxy": candidate.summary.source_diversity_proxy,
        "event_count": candidate.summary.event_count,
        "max_engagement_potential_score": candidate.summary.max_engagement_potential_score,
    }


@dataclass(frozen=True)
class TelegraphShortlistResult:
    """The clean domain result `create_telegraph_shortlist()` returns for the Telegram-
    presentation layer to consume - `batch` is `None` exactly when `proposals` is empty (a valid,
    real, quality-over-quota outcome, never an error)."""

    batch: TelegraphShortlistBatch | None
    proposals: list[TelegraphTopicProposal]


async def get_recently_proposed_story_ids(
    session: AsyncSession, *, now: datetime, cooldown_hours: float,
) -> set[UUID]:
    """Every distinct `story_id` proposed (in ANY status - pending, approved, or rejected) within
    the last `cooldown_hours` - the phase brief's own explicit "Same Story inside cooldown:
    excluded" rule, regardless of what the operator ultimately decided (an already-rejected
    proposal being re-shown immediately is exactly the "replacement spam" the brief forbids just
    as much as re-showing an undecided one). Bounded, indexed-adjacent query
    (`TelegraphTopicProposal.created_at`, plus the existing `batch_id`/`story_id` indexes) - never
    an unbounded scan, mirrors every other lookback query in this codebase (e.g.
    services/story_memory.py::_fetch_candidate_stories())."""
    cutoff = now - timedelta(hours=cooldown_hours)
    stmt = (
        select(TelegraphTopicProposal.story_id)
        .where(TelegraphTopicProposal.created_at >= cutoff)
        .distinct()
        .limit(_RECENT_PROPOSAL_SCAN_SAFETY_CAP)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return set(rows)


async def create_telegraph_shortlist(
    session: AsyncSession,
    *,
    limit: int = 5,
    now: datetime | None = None,
    recency_cutoff_hours: float | None = None,
    reproposal_cooldown_hours: float | None = None,
) -> TelegraphShortlistResult:
    """The one callable API this checkpoint's Telegram-delivery layer consumes. Read-only against
    Checkpoint 1's own tables, one write transaction against this module's own two tables only.

    Zero LLM/Gateway calls, zero web/fetch calls, zero Telegram calls - reuses `services.
    telegraph_topic_candidates.build_telegraph_topic_candidates()` (Checkpoint 1, unmodified)
    verbatim for candidate formation; the only new work here is wiring real reproposal-cooldown
    persistence into its own `already_proposed_story_ids` parameter and persisting the result.

    Zero-candidate outcome (the phase brief's own explicit "zero topics is valid... do NOT create
    fake candidates"): no `TelegraphShortlistBatch` row is created at all - a batch's only real
    purpose is to anchor proposals and track a delivered Telegram message, and there is nothing
    to anchor or deliver when nothing qualified. This is logged at INFO (mirroring services/
    collector.py::run_collection_cycle()'s own "the cycle outcome is always logged, even when
    nothing was created" auditability convention) rather than persisted as an empty row - the
    justified choice, not merely the simplest one: a `status` column distinguishing "nothing to
    do" from "created, pending delivery" would be exactly the kind of speculative-workflow-state
    complexity the phase brief asks this checkpoint to avoid.
    """
    reference_now = now if now is not None else datetime.now(timezone.utc)
    cooldown_hours = (
        reproposal_cooldown_hours if reproposal_cooldown_hours is not None
        else settings.telegraph_reproposal_cooldown_hours
    )
    already_proposed = await get_recently_proposed_story_ids(
        session, now=reference_now, cooldown_hours=cooldown_hours,
    )

    candidates = await build_telegraph_topic_candidates(
        session, limit=limit, now=reference_now, recency_cutoff_hours=recency_cutoff_hours,
        already_proposed_story_ids=already_proposed,
    )

    if not candidates:
        logger.info(
            "telegraph_shortlist_zero_candidates",
            extra={"limit": limit, "recently_proposed_count": len(already_proposed)},
        )
        return TelegraphShortlistResult(batch=None, proposals=[])

    batch = TelegraphShortlistBatch(proposal_count=len(candidates))
    session.add(batch)
    await session.flush()  # assigns batch.id, without committing yet - one transaction below

    proposals: list[TelegraphTopicProposal] = []
    for rank, candidate in enumerate(candidates, start=1):
        story = await session.get(Story, candidate.story_id)
        assert story is not None  # candidate.story_id was just resolved from a real Story row
        proposal = TelegraphTopicProposal(
            batch_id=batch.id,
            story_id=candidate.story_id,
            rank=rank,
            topic_score=candidate.topic_score,
            topic_title=_derive_topic_title(candidate),
            rationale_snapshot=candidate.rationale,
            signals_snapshot=_build_signals_snapshot(candidate),
        )
        session.add(proposal)
        proposals.append(proposal)

    await session.commit()  # one transaction: batch + every proposal, or none of them
    for proposal in proposals:
        await session.refresh(proposal)

    logger.info(
        "telegraph_shortlist_created",
        extra={"batch_id": str(batch.id), "proposal_count": len(proposals)},
    )
    return TelegraphShortlistResult(batch=batch, proposals=proposals)


class TelegraphShortlistService:
    """Owns every read/write against `TelegraphTopicProposal`/`TelegraphShortlistBatch` past
    creation time - the callback-decision mutation path (D), plus the read paths bot/handlers/
    telegraph_shortlist.py needs to re-render a batch fresh on every callback (never trusting
    state from an earlier render, mirrors bot/handlers/meme_preview.py's identical discipline)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_proposal(self, proposal_id: UUID) -> TelegraphTopicProposal | None:
        return await self._session.get(TelegraphTopicProposal, proposal_id)

    async def get_batch(self, batch_id: UUID) -> TelegraphShortlistBatch | None:
        return await self._session.get(TelegraphShortlistBatch, batch_id)

    async def list_proposals_for_batch(self, batch_id: UUID) -> list[TelegraphTopicProposal]:
        """Always ordered by the snapshotted `rank` - the same deterministic order the batch was
        created and first rendered in, on every re-query."""
        stmt = (
            select(TelegraphTopicProposal)
            .where(TelegraphTopicProposal.batch_id == batch_id)
            .order_by(TelegraphTopicProposal.rank.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def record_telegram_delivery(
        self, batch_id: UUID, *, chat_id: int, message_id: int, thread_id: int | None,
    ) -> TelegraphShortlistBatch | None:
        batch = await self._session.get(TelegraphShortlistBatch, batch_id)
        if batch is None:
            return None
        batch.telegram_chat_id = chat_id
        batch.telegram_message_id = message_id
        batch.telegram_thread_id = thread_id
        await self._session.commit()
        await self._session.refresh(batch)
        return batch

    async def set_decision(
        self, proposal_id: UUID, decision: TelegraphProposalStatus, *, decided_by_telegram_user_id: int,
    ) -> TelegraphTopicProposal | None:
        """Approve/reject a proposal. Idempotent and immutable-once-final by design (the phase
        brief's own "Prefer immutable final decisions unless an existing review mechanism
        explicitly supports changing decisions" - no existing mechanism does, so this is the
        conservative choice):

        - `PENDING -> APPROVED` / `PENDING -> REJECTED`: sets `status`, `decided_at`, and
          `decided_by_telegram_user_id` (all once, atomically, in the same transaction).
        - Same decision repeated (`APPROVED -> APPROVED`, `REJECTED -> REJECTED`): a true no-op -
          returns the unchanged row, `decided_at`/`decided_by_telegram_user_id` are never touched
          again, even if a DIFFERENT authorized user repeats the tap - the original decider is
          preserved, not overwritten by whoever double-taps second.
        - The OPPOSITE decision after a final one (`APPROVED -> REJECTED` or vice versa): also a
          no-op - the row, including its original decider, is returned exactly as it already was.
          This is deliberately STRICTER than services/meme_candidate_service.py::
          record_editor_decision()'s own documented "recording a decision twice just overwrites
          the prior decision" precedent: that function's own real callers never actually exercise
          a second, opposite decision in practice either (bot/handlers/meme_preview.py always
          swaps to a decided-only keyboard with no more decision buttons once terminal - the same
          discipline bot/handlers/telegraph_shortlist.py follows here), and article-topic approval
          is a higher-stakes, less-frequently-retried decision than a meme regenerate/reject loop
          - immutability (of the decision AND of who made it) is the safer, disclosed choice for
          this domain, not an oversight.

        `decided_by_telegram_user_id` is a required keyword-only argument (never a mutable default
        or an inferred value) - the caller (bot/handlers/telegraph_shortlist.py) must have already
        authorized this exact user before calling; this method persists that identity, it does not
        decide authorization itself.

        Returns `None` only if `proposal_id` does not exist (a stale/tampered callback) - never
        raises, mirrors `MemeCandidateService`'s identical "return a signal, never raise on a
        missing row" convention."""
        proposal = await self._session.get(TelegraphTopicProposal, proposal_id)
        if proposal is None:
            return None
        if proposal.status != TelegraphProposalStatus.PENDING:
            return proposal  # already final (same or opposite decision) - immutable, no mutation
        proposal.status = decision
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decided_by_telegram_user_id = decided_by_telegram_user_id
        await self._session.commit()
        await self._session.refresh(proposal)
        return proposal
