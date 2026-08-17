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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.story import Story
from database.models.telegraph_shortlist import (
    TelegraphProposalStatus,
    TelegraphShortlistBatch,
    TelegraphTopicProposal,
)
from services.editorial_channel_classifier import classify_editorial_channel
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
    persistence into its own `already_proposed_story_ids` parameter, classifying each candidate's
    editorial channel (services.editorial_channel_classifier.py - deterministic, zero-LLM), and
    persisting the result.

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

        # Editorial channel split: classified here, BEFORE the proposal is ever persisted (never
        # a live-recomputed value later) - deterministic, zero-LLM, zero-new-query (reuses
        # candidate.summary, the same StoryEvidenceSummary already computed by services.
        # telegraph_topic_candidates.py for THIS candidate). See services.
        # editorial_channel_classifier.py's own docstring for the full scoring rubric.
        channel_decision = classify_editorial_channel(candidate.summary)

        proposal = TelegraphTopicProposal(
            batch_id=batch.id,
            story_id=candidate.story_id,
            rank=rank,
            topic_score=candidate.topic_score,
            topic_title=_derive_topic_title(candidate),
            rationale_snapshot=f"{candidate.rationale} | {channel_decision.rationale}",
            signals_snapshot=_build_signals_snapshot(candidate),
            editorial_channel=channel_decision.channel,
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


async def claim_approved_telegraph_proposal(
    session: AsyncSession, proposal_id: UUID, *, now: datetime | None = None, commit: bool = True,
) -> TelegraphTopicProposal | None:
    """TELEGRAPH Checkpoint 3: the exactly-once claim primitive. Mirrors this codebase's own
    established atomic-conditional-claim idiom byte-for-byte (the same pattern the Workflow
    Engine's own task-claim step already uses elsewhere in this codebase) - a single-statement
    conditional UPDATE (`WHERE status == APPROVED AND consumed_at IS NULL`) followed by a
    `rowcount` check, never a `SELECT ... FOR UPDATE` and never a new distributed-lock mechanism.
    Postgres's own row-level locking on the UPDATE statement is what makes two concurrent callers
    racing this same `proposal_id` safe: only one transaction's WHERE clause can still match once
    the other has (atomically) set `consumed_at` - the second sees `rowcount == 0` and returns
    `None`, exactly like a second concurrent claim of the same CREATED task elsewhere in this
    codebase already does.

    Deliberately does NOT create or link an `EditorialTask`, and never imports anything from the
    Workflow Engine or Capability layer - that orchestration is services.
    telegraph_research_processor.process_approved_telegraph_proposal()'s job, immediately after a
    successful claim, in the same overall transaction. This function's only job is the claim
    itself, so it stays independently testable (a claim can succeed with zero task-creation
    machinery involved at all) and so "no paid call happens before successful claim" is
    structurally true: nothing past this function's own single UPDATE can run until it returns
    a non-None proposal.

    Returns the claimed proposal (its own in-memory `status` stays APPROVED; `consumed_at` is now
    set) on success. Returns `None` for every non-claimable case, never raising: PENDING,
    REJECTED, already-consumed (`consumed_at` already set, regardless of status), or a
    nonexistent `proposal_id` - the caller cannot and must not distinguish between these from the
    return value alone (mirrors `TelegraphShortlistService.set_decision()`'s own "return a
    signal, never raise" convention for a missing row); the pre-claim `status`/`consumed_at`
    values are already durable and inspectable via a normal read if a caller needs to know why.

    `commit` (Checkpoint 3 correctness fix, additive/backward-compatible - defaults to `True`,
    byte-identical to every pre-existing caller/test's behavior): pass `commit=False` so this
    claim participates in the caller's own larger atomic transaction (services.
    telegraph_research_processor.process_approved_telegraph_proposal()'s claim+create-task+link
    sequence) instead of committing independently. The returned proposal always reflects the real
    post-UPDATE state either way - a session always sees its own uncommitted writes within the
    same transaction, so `session.get()` below never needs a commit to be accurate.
    """
    claim_at = now if now is not None else datetime.now(timezone.utc)
    result = await session.execute(
        update(TelegraphTopicProposal)
        .where(
            TelegraphTopicProposal.id == proposal_id,
            TelegraphTopicProposal.status == TelegraphProposalStatus.APPROVED,
            TelegraphTopicProposal.consumed_at.is_(None),
        )
        .values(consumed_at=claim_at)
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return None
    return await session.get(TelegraphTopicProposal, proposal_id)


async def link_research_task(
    session: AsyncSession, proposal_id: UUID, task_id: UUID, *, commit: bool = True,
) -> TelegraphTopicProposal | None:
    """Sets `research_task_id` on an already-claimed proposal - called exactly once, immediately
    after `claim_approved_telegraph_proposal()` succeeds and the new `EditorialTask` row has been
    flushed (services.telegraph_research_processor.process_approved_telegraph_proposal()).
    Unconditional (no WHERE-clause race guard): by the time this is called, the claim UPDATE
    above has already made this proposal exclusively "ours" for this call - a second concurrent
    processing attempt for the same `proposal_id` could not have reached this point (its own
    claim would have returned `None` first). Returns `None` only if `proposal_id` does not exist
    (should not happen immediately after a successful claim; handled safely regardless, never
    raising).

    `commit` (Checkpoint 3 correctness fix, additive/backward-compatible - defaults to `True`):
    pass `commit=False` to make this UPDATE participate in the caller's own larger atomic
    transaction, exactly like `claim_approved_telegraph_proposal()`'s identical parameter."""
    proposal = await session.get(TelegraphTopicProposal, proposal_id)
    if proposal is None:
        return None
    proposal.research_task_id = task_id
    if commit:
        await session.commit()
    else:
        await session.flush()
    await session.refresh(proposal)
    return proposal


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
