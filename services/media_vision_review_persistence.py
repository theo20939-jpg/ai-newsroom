"""Phase 19 M13: the sole place that constructs/persists a MediaVisionReview row.

Exists specifically so no capabilities/-layer or executor code needs to import
database.models.media_vision_review directly - mirrors services/editorial_plan_persistence.py's
own exact rationale and shape. In this milestone the only real caller is
scripts/phase19_m13_vision_review_manual.py.

MEDIA-PROD-1 (recovered PRODUCTION-SOURCE-RECONCILIATION-1): also the sole place that READS
MediaVisionReview rows back (`get_media_vision_review_calibration_summary()` below) - a plain,
read-only diagnostics query over whatever the manual harness has already accumulated, for a human
operator to calibrate a FUTURE enforcement mode's thresholds against real reviewer verdicts rather
than guessing. This is explicitly NOT wired into any automatic/scheduled path (worker/
content_cycle.py is untouched by this phase) and has no side effects of any kind - it cannot
reject, filter, or otherwise affect any delivery decision. `media_vision_review_mode` stays exactly
the two-state `off`/`shadow` it already was (core/config.py's own documented "regardless of this
setting's value, always requires the manually-invoked harness script" fence is preserved, not
removed)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
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


@dataclass(frozen=True)
class MediaVisionReviewCalibrationSummary:
    """Aggregate counts over some window of already-persisted `MediaVisionReview` rows - diagnostic
    only, never a decision. `would_flag_count` is a single illustrative heuristic (recommended_role
    == "reject" OR any of the four presence flags True) a human operator can use as a starting point
    when eventually designing a real enforcement rule - NOT a rule this codebase applies anywhere
    itself."""

    total_reviews: int
    watermark_present_count: int
    source_logo_present_count: int
    website_or_social_ui_present_count: int
    advertisement_or_banner_present_count: int
    recommended_role_counts: dict[str, int]
    readable_quality_counts: dict[str, int]
    would_flag_count: int


def _is_flagged(row: MediaVisionReview) -> bool:
    return (
        row.recommended_role == "reject" or row.watermark_present or row.source_logo_present
        or row.website_or_social_ui_present or row.advertisement_or_banner_present
    )


async def get_media_vision_review_calibration_summary(
    session: AsyncSession, *, since: datetime | None = None,
) -> MediaVisionReviewCalibrationSummary:
    """Read-only. `since` (optional) restricts to reviews created on/after that timestamp - omit
    for an all-time summary. Every count here is a plain tally over real rows this codebase already
    wrote via `persist_media_vision_review()` (from the manual harness only, per this module's own
    docstring) - no new table, no schema change, no write of any kind."""
    stmt = select(MediaVisionReview)
    if since is not None:
        stmt = stmt.where(MediaVisionReview.created_at >= since)
    rows = (await session.execute(stmt)).scalars().all()

    role_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    watermark = logo = website_ui = ad_banner = flagged = 0
    for row in rows:
        role_counts[row.recommended_role] = role_counts.get(row.recommended_role, 0) + 1
        quality_counts[row.readable_quality] = quality_counts.get(row.readable_quality, 0) + 1
        watermark += int(row.watermark_present)
        logo += int(row.source_logo_present)
        website_ui += int(row.website_or_social_ui_present)
        ad_banner += int(row.advertisement_or_banner_present)
        flagged += int(_is_flagged(row))

    return MediaVisionReviewCalibrationSummary(
        total_reviews=len(rows), watermark_present_count=watermark, source_logo_present_count=logo,
        website_or_social_ui_present_count=website_ui, advertisement_or_banner_present_count=ad_banner,
        recommended_role_counts=role_counts, readable_quality_counts=quality_counts,
        would_flag_count=flagged,
    )
