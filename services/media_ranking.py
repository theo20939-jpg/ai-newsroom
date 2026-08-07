"""Phase 19 M11: deterministic media ranking + story-aware reuse prevention.

Split into a pure calculator (`rank_media_candidates` - no I/O, fully unit-testable) and thin
async cross-event query functions (`find_story_reused_image_signatures`,
`find_story_reused_video_urls` - the caller resolves these into each candidate's
`story_reuse_match` flag before calling the calculator) - mirrors services/story_memory.py's own
established split exactly.

Scope decision: no new persistence table in this milestone. `rank_media_candidates()` is a pure
computation over already-available signals (services/image_quality.py's QualitySignals,
services/video_discovery.py's VideoValidation, this module's own cross-event reuse queries) -
callers (a future M12 delivery-selection step, or a manual review script) decide whether/how to
persist a specific ranking run's output. This keeps M11 a narrow, safe extension rather than a
new hot-path write path, consistent with "don't add a new table unless the milestone's own data
genuinely needs to be durably reviewable" - unlike M7/M8/M10, nothing here is lost if a ranking
is simply recomputed on demand (it is 100% deterministic given the same inputs).

Story-aware reuse prevention extends services/image_deduplication.py's own explicitly-disclosed
gap ("exact and perceptual near-duplicate clustering, scoped to one event only") to compare across
every event already linked to the same Story - the first cross-event duplicate-awareness in this
codebase. Reuses image_deduplication.py's own calibrated Hamming-distance threshold, never a new,
divergent one.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_media_item import ContentDraftMediaItem
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.story_link import NewsEventStoryLink
from schemas.media_ranking import MediaRankingInput, MediaRankingResult, RecommendedRole
from services.image_quality import hamming_distance

# Reused verbatim from services/image_deduplication.py - never a new, divergent threshold for the
# same underlying "is this the same photo" question.
_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE = 4

_ELIGIBILITY_MIN_QUALITY_SCORE = 30
_STORY_REUSE_PENALTY = 40
_DUPLICATE_WITHIN_EVENT_PENALTY = 25

_BRANDING_RISK_WEIGHTS: dict[str, int] = {
    "possible_logo": 25,
    "possible_banner": 20,
    "possible_watermark": 20,
    "possible_tv_lower_third": 15,
    "possible_branded_screenshot": 25,
}

_TV_LIKE_ASPECT_BANDS = ("editorial_landscape", "wide_banner")


def _compute_branding_risk(inp: MediaRankingInput) -> int:
    risk = 0
    if inp.possible_logo:
        risk += _BRANDING_RISK_WEIGHTS["possible_logo"]
    if inp.possible_banner:
        risk += _BRANDING_RISK_WEIGHTS["possible_banner"]
    if inp.possible_watermark:
        risk += _BRANDING_RISK_WEIGHTS["possible_watermark"]
    if inp.possible_tv_lower_third:
        risk += _BRANDING_RISK_WEIGHTS["possible_tv_lower_third"]
    if inp.possible_branded_screenshot:
        risk += _BRANDING_RISK_WEIGHTS["possible_branded_screenshot"]
    return min(100, risk)


def _compute_recommended_role(inp: MediaRankingInput, *, branding_risk: int, eligible: bool) -> RecommendedRole:
    if not eligible:
        return RecommendedRole.REJECT
    if inp.media_type == "video":
        if inp.aspect_ratio_band in _TV_LIKE_ASPECT_BANDS:
            return RecommendedRole.DEMO_VIDEO
        return RecommendedRole.CONTEXT_VIDEO
    # image
    if branding_risk >= 40:
        return RecommendedRole.SUPPORTING  # visible branding risk - never HERO, still usable
    if inp.aspect_ratio_band == "editorial_landscape" and inp.quality_score >= 60:
        return RecommendedRole.HERO
    return RecommendedRole.SUPPORTING


def _explain(
    inp: MediaRankingInput, *, story_reuse_penalty: int, branding_risk: int, eligible: bool,
) -> str:
    parts = [f"quality={inp.quality_score}", f"source_priority={inp.source_priority}"]
    if inp.relevance_score is not None:
        parts.append(f"relevance={inp.relevance_score}")
    if inp.is_duplicate_within_event:
        parts.append("duplicate_within_event")
    if story_reuse_penalty:
        parts.append("already_used_elsewhere_in_story")
    if branding_risk:
        parts.append(f"branding_risk={branding_risk}")
    if inp.video_validation_status == "rejected":
        parts.append("video_validation_rejected")
    if not eligible:
        parts.append("ineligible_for_delivery")
    return ", ".join(parts)


def rank_media_candidates(inputs: list[MediaRankingInput]) -> list[MediaRankingResult]:
    """Pure. Deterministic given the same inputs - never depends on wall-clock time or ordering
    beyond `inputs`' own order (ties broken by input order, never randomized)."""
    scored: list[tuple[int, MediaRankingInput, int, int, int, bool]] = []
    for inp in inputs:
        branding_risk = _compute_branding_risk(inp)
        story_reuse_penalty = _STORY_REUSE_PENALTY if inp.story_reuse_match else 0
        duplicate_penalty = _DUPLICATE_WITHIN_EVENT_PENALTY if inp.is_duplicate_within_event else 0
        video_rejected = inp.media_type == "video" and inp.video_validation_status == "rejected"

        eligible = (
            not video_rejected
            and not inp.story_reuse_match
            and inp.quality_score >= _ELIGIBILITY_MIN_QUALITY_SCORE
        )

        relevance_component = inp.relevance_score if inp.relevance_score is not None else 50
        composite = (
            inp.quality_score + inp.source_priority + relevance_component
            - story_reuse_penalty - duplicate_penalty - branding_risk
        )
        scored.append((composite, inp, branding_risk, story_reuse_penalty, duplicate_penalty, eligible))

    # Stable sort: highest composite first; ties preserve original input order (Python's sort is
    # stable, and enumerate-based negation keeps that guarantee explicit rather than incidental).
    ordered = sorted(enumerate(scored), key=lambda pair: (-pair[1][0], pair[0]))

    results: list[MediaRankingResult] = []
    for order, (_, (_, inp, branding_risk, story_reuse_penalty, _duplicate_penalty, eligible)) in enumerate(ordered):
        role = _compute_recommended_role(inp, branding_risk=branding_risk, eligible=eligible)
        results.append(
            MediaRankingResult(
                media_item_id=inp.media_item_id, media_type=inp.media_type,
                relevance_score=inp.relevance_score if inp.relevance_score is not None else 50,
                source_priority=inp.source_priority, quality_score=inp.quality_score,
                novelty_score=max(0, 100 - story_reuse_penalty - branding_risk),
                story_reuse_penalty=story_reuse_penalty, branding_risk=branding_risk,
                recommended_role=role, recommended_order=order,
                explanation=_explain(inp, story_reuse_penalty=story_reuse_penalty, branding_risk=branding_risk, eligible=eligible),
                eligible_for_delivery=eligible,
            )
        )
    return results


async def find_story_reused_image_signatures(
    session: AsyncSession, *, story_id: UUID, exclude_event_id: UUID
) -> tuple[set[str], list[str]]:
    """Returns (exact_sha256_hashes, perceptual_hashes) already present among every OTHER event
    linked to this Story - the caller compares a new candidate's own sha256 (exact) and
    perceptual_hash (via hamming_distance, reusing image_deduplication.py's own calibrated
    threshold) against these. Bounded to this one story's own linked events only, never a
    cross-story or table-wide scan."""
    event_ids_stmt = select(NewsEventStoryLink.news_event_id).where(
        NewsEventStoryLink.story_id == story_id, NewsEventStoryLink.news_event_id != exclude_event_id,
    )
    event_ids = [row for row in (await session.execute(event_ids_stmt)).scalars().all()]
    if not event_ids:
        return set(), []

    rows = (
        await session.execute(
            select(ImageCandidateRecord.sha256, ImageCandidateRecord.perceptual_hash).where(
                ImageCandidateRecord.news_event_id.in_(event_ids)
            )
        )
    ).all()
    exact = {sha for sha, _ in rows if sha}
    perceptual = [phash for _, phash in rows if phash]
    return exact, perceptual


def is_perceptually_reused(candidate_hash: str | None, known_hashes: list[str]) -> bool:
    """Pure. True if `candidate_hash` is within the calibrated near-duplicate distance of any
    hash already used elsewhere in the story."""
    if not candidate_hash:
        return False
    return any(
        hamming_distance(candidate_hash, known) <= _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE
        for known in known_hashes
    )


async def find_story_reused_video_urls(
    session: AsyncSession, *, story_id: UUID, exclude_event_id: UUID
) -> set[str]:
    """Returns every `remote_url` already discovered for video among every OTHER event linked to
    this Story - an exact-URL match is the only video reuse signal available (no perceptual video
    hashing exists in this codebase, and M10's own scope explicitly excludes building one)."""
    event_ids_stmt = select(NewsEventStoryLink.news_event_id).where(
        NewsEventStoryLink.story_id == story_id, NewsEventStoryLink.news_event_id != exclude_event_id,
    )
    event_ids = [row for row in (await session.execute(event_ids_stmt)).scalars().all()]
    if not event_ids:
        return set()

    rows = (
        await session.execute(
            select(ContentDraftMediaItem.remote_url).where(ContentDraftMediaItem.event_id.in_(event_ids))
        )
    ).scalars().all()
    return set(rows)
