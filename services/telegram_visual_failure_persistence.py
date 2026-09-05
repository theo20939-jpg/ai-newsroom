"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §19-20: promotes
services/telegram_performance_memory.py::VisualFailureRecord from contract-only to a real
persisted `TelegramVisualFailure` row, and records `route_revision()`'s output as a PROPOSED
ACTION only - never executes a rerender/media replacement/generation/block (spec §20's own hard
constraint: "DO NOT execute actions"). A clean PASS (no issues) is never persisted here - this
table is operational evidence of failures/notes, not a log of every evaluation."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_visual_failure import ArtDirectorDecisionEnum, TelegramVisualFailure
from services.telegram_art_director import ArtDirectorDecision, ArtDirectorResult
from services.telegram_revision_router import RevisionAction, route_revision

_DECISION_MAP = {
    ArtDirectorDecision.PASS: ArtDirectorDecisionEnum.PASS,
    ArtDirectorDecision.PASS_WITH_NOTES: ArtDirectorDecisionEnum.PASS_WITH_NOTES,
    ArtDirectorDecision.REWORK: ArtDirectorDecisionEnum.REWORK,
    ArtDirectorDecision.BLOCK: ArtDirectorDecisionEnum.BLOCK,
}


async def persist_visual_failure_shadow(
    session: AsyncSession, *, result: ArtDirectorResult, final_post_review_id: uuid.UUID | None = None,
    story_id: uuid.UUID | None = None, presentation_type: str | None = None,
    renderer_version: str | None = None, template: str | None = None, media_type: str | None = None,
    revision_round: int = 0,
) -> TelegramVisualFailure | None:
    """Persists only when the Art Director found something worth recording (PASS with zero issues
    is not persisted - spec module docstring). Computes a PROPOSED revision action via
    `route_revision()` but never acts on it - `revision_action` is purely advisory metadata on the
    row, `resolved` always starts False."""
    if result.decision == ArtDirectorDecision.PASS and not result.issue_codes:
        return None

    proposed_action: RevisionAction | None = None
    if result.decision != ArtDirectorDecision.PASS:
        proposed_action = route_revision(result, attempt_count=revision_round)

    row = TelegramVisualFailure(
        id=uuid.uuid4(),
        final_post_review_id=final_post_review_id,
        story_id=story_id,
        presentation_type=presentation_type,
        renderer_version=renderer_version,
        template=template,
        media_type=media_type,
        issue_codes=[code.value for code in result.issue_codes],
        severity=result.severity,
        art_director_decision=_DECISION_MAP[result.decision],
        confidence=result.confidence,
        revision_action=proposed_action.value if proposed_action is not None else None,
        revision_round=revision_round,
        resolved=False,
        resolution_result=None,
    )
    session.add(row)
    return row
