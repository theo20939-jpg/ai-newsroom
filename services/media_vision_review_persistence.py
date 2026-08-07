"""Phase 19 M13: the sole place that constructs/persists a MediaVisionReview row.

Exists specifically so no capabilities/-layer or executor code needs to import
database.models.media_vision_review directly - mirrors services/editorial_plan_persistence.py's
own exact rationale and shape. In this milestone the only real caller is
scripts/phase19_m13_vision_review_manual.py.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.media_vision_review import MediaVisionReview


async def persist_media_vision_review(
    session: AsyncSession, *, image_candidate_id: UUID, structured_output: dict,
) -> None:
    """Adds one MediaVisionReview row to `session` (does not commit - the caller's own
    SAVEPOINT/commit discipline governs that, exactly as every other Phase 19 write does).
    `structured_output` is the capability's own already-floor-validated response - every key
    required by the output schema is guaranteed present by that validation, never re-checked here."""
    row = MediaVisionReview(
        image_candidate_id=image_candidate_id,
        relevant_to_story=structured_output["relevant_to_story"],
        source_logo_present=structured_output["source_logo_present"],
        watermark_present=structured_output["watermark_present"],
        website_or_social_ui_present=structured_output["website_or_social_ui_present"],
        advertisement_or_banner_present=structured_output["advertisement_or_banner_present"],
        readable_quality=structured_output["readable_quality"],
        recommended_role=structured_output["recommended_role"],
    )
    session.add(row)
