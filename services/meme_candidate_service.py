"""MemeCandidateService: the only component authorized to create or update a MemeCandidate row
(Phase 18 M2, mirrors `services/content_draft_service.py::ContentDraftService`'s own established
shape - class-based, constructor-injected with the caller's own already-open `AsyncSession`).

`create_from_concept()` (M2), `record_editor_decision()` (M8, extended M9 with the reason
taxonomy/notes), `add_cost()` and `build_feedback_summary()` (M9), plus `attach_safety_assessment`/
`attach_copy`/`attach_image_result`/`attach_render_result`/`attach_quality_assessment` (added at
Phase 18 final acceptance, docs/phase18_final_acceptance_db_integration_report.md - closing the
disclosed "no persistence method yet" gap each of M3-M7's own reports flagged, using exactly the
columns M2's migration already reserved for them) - no orchestrator calls these in a live run yet
(same disclosed deferral as ever), but they are now real, tested, and ready for one.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from schemas.meme_concept import MemeConcept
from schemas.meme_copy import MemeCopy
from schemas.meme_feedback import MemeFeedbackSummary, MemeRejectionReason
from schemas.meme_image import MemeImageGenerationResult, MemeImageStatus
from schemas.meme_quality import MemeQualityAssessment, MemeQualityDecision
from schemas.meme_render import MemeRenderResult, MemeRenderStatus
from schemas.meme_safety import MemeGateDecision, MemeSafetyOriginalityGateResult

_DECISION_TO_STATUS: dict[str, MemeCandidateStatus] = {
    "approved": MemeCandidateStatus.APPROVED,
    "rejected": MemeCandidateStatus.REJECTED,
}

# MemeQualityDecision (M7) has 5 values; MemeCandidateStatus (M2, designed before M7 existed) has
# only 3 quality-stage values plus PENDING_EDITOR - there is no dedicated status for "needs a new
# concept" or "needs a new image." This documented mapping (found and resolved during Phase 18
# final acceptance, docs/phase18_final_acceptance_db_integration_report.md) sends a regenerate
# recommendation back to the status of the stage that must actually be redone, rather than
# inventing a new enum value/migration for a distinction the status column was never meant to
# carry in this much granularity.
_QUALITY_DECISION_TO_STATUS: dict[MemeQualityDecision, MemeCandidateStatus] = {
    MemeQualityDecision.READY_FOR_EDITOR: MemeCandidateStatus.PENDING_EDITOR,
    MemeQualityDecision.REVIEW: MemeCandidateStatus.QUALITY_REVIEW,
    MemeQualityDecision.REJECT: MemeCandidateStatus.QUALITY_REJECTED,
    MemeQualityDecision.REGENERATE_CONCEPT: MemeCandidateStatus.CONCEPT_GENERATED,
    MemeQualityDecision.REGENERATE_IMAGE: MemeCandidateStatus.COPY_GENERATED,
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

    async def attach_safety_assessment(
        self, candidate_id: UUID, result: MemeSafetyOriginalityGateResult,
    ) -> MemeCandidate | None:
        """Persists M3's `MemeSafetyOriginalityGateResult` onto its owning row. Only advances
        `status` for the two outcomes that actually warrant a distinct milestone
        (`SAFETY_BLOCKED`/`SAFETY_REVIEW`) - a clean `PASS` leaves `status` at
        `CONCEPT_GENERATED`, since `MemeCandidateStatus` (M2) has no dedicated "safety passed"
        value of its own; processing simply continues to whatever `attach_copy()` sets next.
        Returns `None` if `candidate_id` does not exist, never raises."""
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.safety_status = result.safety.decision.value
        candidate.safety_reason_codes = result.safety.reason_codes
        candidate.originality_status = result.originality.decision.value
        candidate.originality_reason_codes = result.originality.reason_codes
        if result.gate_decision == MemeGateDecision.BLOCK:
            candidate.status = MemeCandidateStatus.SAFETY_BLOCKED
        elif result.gate_decision == MemeGateDecision.REVIEW:
            candidate.status = MemeCandidateStatus.SAFETY_REVIEW
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def attach_copy(self, candidate_id: UUID, copy: MemeCopy) -> MemeCandidate | None:
        """Persists M4's `MemeCopy` onto its owning row and advances `status` to
        `COPY_GENERATED`. Does not itself check `safety_status` first - records what the caller
        supplies, mirroring `record_editor_decision()`'s identical "record, don't second-guess
        call order" convention."""
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.copy_schema_version = copy.schema_version
        candidate.copy_data = copy.model_dump(mode="json")
        candidate.status = MemeCandidateStatus.COPY_GENERATED
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def attach_image_result(
        self, candidate_id: UUID, result: MemeImageGenerationResult,
    ) -> MemeCandidate | None:
        """Persists M5's `MemeImageGenerationResult` onto its owning row - never the raw image
        bytes, only the storage reference already inside `result` (mirrors every Phase 18 result
        schema's own "storage_key is an internal reference only" discipline). `mode="off"`
        results (`MemeImageStatus.OFF`) are recorded but do not advance `status` - nothing was
        actually attempted."""
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.image_status = result.status.value
        candidate.image_storage_key = result.storage_key
        candidate.image_provider = result.provider
        candidate.image_model = result.model_used
        if result.status == MemeImageStatus.GENERATED:
            candidate.status = MemeCandidateStatus.IMAGE_GENERATED
        elif result.status == MemeImageStatus.FAILED:
            candidate.status = MemeCandidateStatus.IMAGE_FAILED
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def attach_render_result(self, candidate_id: UUID, result: MemeRenderResult) -> MemeCandidate | None:
        """Persists M6's `MemeRenderResult` onto its owning row. Only advances `status` to
        `RENDERED` on success - a render failure leaves `status` at whatever M5's own
        `attach_image_result()` last set (typically `IMAGE_GENERATED`), since the underlying
        image itself was fine; only rendering needs to be retried."""
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.render_storage_key = result.storage_key
        if result.status == MemeRenderStatus.RENDERED:
            candidate.status = MemeCandidateStatus.RENDERED
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def attach_quality_assessment(
        self, candidate_id: UUID, assessment: MemeQualityAssessment,
    ) -> MemeCandidate | None:
        """Persists M7's `MemeQualityAssessment` onto its owning row. `quality_score` (a column
        reserved since M2) is never set here - `services.meme_quality.assess_meme_quality()` does
        not compute a numeric score, only the `MemeQualityChecks` boolean breakdown already
        captured in `quality_reason_codes`' sibling `reason_codes` list; the column remains
        genuinely unpopulated by this phase's own logic, not a bug. See this module's own
        `_QUALITY_DECISION_TO_STATUS` docstring for the status-mapping rationale."""
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.quality_decision = assessment.decision.value
        candidate.quality_reason_codes = assessment.reason_codes
        candidate.status = _QUALITY_DECISION_TO_STATUS[assessment.decision]
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
