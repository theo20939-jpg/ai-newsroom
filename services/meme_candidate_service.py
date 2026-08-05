"""MemeCandidateService: the only component authorized to create or update a MemeCandidate row
(Phase 18 M2, mirrors `services/content_draft_service.py::ContentDraftService`'s own established
shape - class-based, constructor-injected with the caller's own already-open `AsyncSession`).

`create_from_concept()` (M2), `record_editor_decision()` (M8, extended M9 with the reason
taxonomy/notes), `add_cost()` and `build_feedback_summary()` (M9) exist so far - later milestones
(M3 safety/originality persistence, M4 copy persistence, M5/M6 image/render persistence) each add
their own single, narrow method here when that milestone actually lands, never speculative stub
methods ahead of the milestone that needs them (docs/phase18_m2_meme_concept_report.md).
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from schemas.meme_concept import MemeConcept
from schemas.meme_feedback import MemeFeedbackSummary, MemeRejectionReason

_DECISION_TO_STATUS: dict[str, MemeCandidateStatus] = {
    "approved": MemeCandidateStatus.APPROVED,
    "rejected": MemeCandidateStatus.REJECTED,
}


class MemeCandidateService:
    """Constructed with the same AsyncSession the caller already used for
    WorkflowRunner.run() - never opens a new session or connection (mirrors
    ContentDraftService's identical constraint)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_concept(
        self, *, news_event_id: UUID, editorial_task_id: UUID, concept: MemeConcept,
    ) -> MemeCandidate:
        """Create exactly one new MemeCandidate row from a freshly-generated MemeConcept.

        Always creates a NEW row - never updates an existing one (a regenerated concept is a
        distinct attempt, mirroring `MemeConcept`'s own frozen/immutable discipline). Owns its
        own, single, deterministic commit - a separate transaction from WorkflowRunner.run()'s
        own already-closed final commit, exactly like ContentDraftService's own precedent.
        """
        candidate = MemeCandidate(
            news_event_id=news_event_id,
            editorial_task_id=editorial_task_id,
            status=MemeCandidateStatus.CONCEPT_GENERATED,
            concept_schema_version=concept.schema_version,
            concept_data=concept.model_dump(mode="json"),
            concept_regeneration_count=0,
        )
        self._session.add(candidate)
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def get_by_id(self, candidate_id: UUID) -> MemeCandidate | None:
        """Read-only lookup - `bot/handlers/meme_preview.py` re-queries fresh on every callback,
        never trusting state from an earlier render (mirrors `services.image_persistence.
        get_editorial_image_candidates()`'s own "always re-query" discipline)."""
        return await self._session.get(MemeCandidate, candidate_id)

    async def record_editor_decision(
        self,
        candidate_id: UUID,
        decision: Literal["approved", "rejected"],
        *,
        reasons: list[MemeRejectionReason] | None = None,
        notes: str | None = None,
    ) -> MemeCandidate | None:
        """Terminal approve/reject only - a "regenerate" action is recognized and acknowledged by
        the bot handler but does not yet re-run any generation step (no live orchestrator exists
        for that; `docs/phase18_m8_telegram_editorial_preview_report.md` §6 discloses this
        explicitly). `reasons`/`notes` (Phase 18 M9, docs/phase18_m9_human_feedback_report.md) are
        additive, optional keyword-only parameters - the M8 call site (plain approve, no reason
        prompt) keeps working unchanged with both `None`. `reasons` is accepted regardless of
        `decision` (never validated against it) - this method records what the caller supplies,
        it does not police *when* a reason makes editorial sense.

        Returns `None` if `candidate_id` does not exist (a stale/tampered callback) rather than
        raising - the caller (the bot handler) treats that as "no longer available," mirroring
        `services.image_persistence.set_editor_decision()`'s own "return a signal, never raise on
        a missing row" convention. Idempotent: recording a decision twice (a double-tap, or a
        reason arriving after an initial approve/reject) just overwrites the prior decision fields
        - never a duplicate row, never an error.
        """
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.editor_decision = decision
        candidate.editor_decision_reasons = [r.value for r in reasons] if reasons else None
        candidate.editor_decision_notes = notes
        candidate.editor_decision_at = datetime.now(timezone.utc)
        candidate.status = _DECISION_TO_STATUS[decision]
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def add_cost(self, candidate_id: UUID, amount: Decimal) -> MemeCandidate | None:
        """Adds `amount` to `cumulative_cost_usd` (Phase 18 M9) - never overwrites, always
        accumulates, so repeated calls across concept/copy/image generation attempts (including
        regenerations) correctly sum the real total spend for this candidate. `amount` must be
        non-negative (a real cost can never be negative) - raises `ValueError` otherwise, never
        silently clamped. No live call site exists yet (no orchestrator wires the individual
        capability-cost outputs through to this method as of M9 - same disclosed deferral pattern
        as every prior milestone's persistence wiring); this method is real and tested in
        isolation, ready for that orchestrator once it exists."""
        if amount < 0:
            raise ValueError("cost amount must be non-negative")
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.cumulative_cost_usd = candidate.cumulative_cost_usd + amount
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def build_feedback_summary(self, candidate_id: UUID) -> MemeFeedbackSummary | None:
        """Read-only report view (Phase 18 M9) - `schemas.meme_feedback.MemeFeedbackSummary`'s
        own docstring. `None` if the candidate does not exist."""
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        return MemeFeedbackSummary(
            candidate_id=str(candidate.id),
            status=candidate.status.value,
            editor_decision=candidate.editor_decision,
            editor_decision_reasons=candidate.editor_decision_reasons or [],
            editor_decision_notes=candidate.editor_decision_notes,
            concept_regeneration_count=candidate.concept_regeneration_count,
            copy_regeneration_count=candidate.copy_regeneration_count,
            image_regeneration_count=candidate.image_regeneration_count,
            cumulative_cost_usd=str(candidate.cumulative_cost_usd),
            published=candidate.published,
        )
