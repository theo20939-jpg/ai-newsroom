"""MemeCandidateService: the only component authorized to create a MemeCandidate row (Phase 18
M2, mirrors `services/content_draft_service.py::ContentDraftService`'s own established shape -
class-based, constructor-injected with the caller's own already-open `AsyncSession`).

Only `create_from_concept()` exists as of M2 - later milestones (M3 safety/originality, M4 copy,
M5 image, M6 render, M7 quality, M9 human decision) each add their own single, narrow update
method here when that milestone actually lands, never speculative stub methods ahead of the
milestone that needs them (docs/phase18_m2_meme_concept_report.md).
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from schemas.meme_concept import MemeConcept


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
