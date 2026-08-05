"""MemeCandidateService: the only component authorized to create or update a MemeCandidate row
(Phase 18 M2, mirrors `services/content_draft_service.py::ContentDraftService`'s own established
shape - class-based, constructor-injected with the caller's own already-open `AsyncSession`).

`create_from_concept()` (M2) and `record_editor_decision()` (M8, terminal approve/reject only)
exist so far - later milestones (M3 safety/originality persistence, M4 copy persistence, M5/M6
image/render persistence, M9's reason-taxonomy/cost/regeneration-count extension of the decision
row) each add their own single, narrow method here when that milestone actually lands, never
speculative stub methods ahead of the milestone that needs them (docs/
phase18_m2_meme_concept_report.md).
"""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from schemas.meme_concept import MemeConcept

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
        self, candidate_id: UUID, decision: Literal["approved", "rejected"],
    ) -> MemeCandidate | None:
        """Terminal approve/reject only, as of M8 - a "regenerate" action is recognized and
        acknowledged by the bot handler but does not yet re-run any generation step (no live
        orchestrator exists for that as of M8; `docs/phase18_m8_telegram_editorial_preview_
        report.md` §6 discloses this explicitly). Returns `None` if `candidate_id` does not exist
        (a stale/tampered callback) rather than raising - the caller (the bot handler) treats that
        as "no longer available," mirroring `services.image_persistence.set_editor_decision()`'s
        own "return a signal, never raise on a missing row" convention. Idempotent: recording the
        same decision twice (a double-tap) just overwrites `editor_decision_at` with the newer
        timestamp - never a duplicate row, never an error.
        """
        candidate = await self._session.get(MemeCandidate, candidate_id)
        if candidate is None:
            return None
        candidate.editor_decision = decision
        candidate.editor_decision_at = datetime.now(timezone.utc)
        candidate.status = _DECISION_TO_STATUS[decision]
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate
