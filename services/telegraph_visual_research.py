"""TELEGRAPH Checkpoint 4: Visual Research - assembles a bounded, deterministic set of images
for an approved TELEGRAPH proposal's Story, entirely from the EXISTING Image Intelligence
pipeline (Phase 16 M1-M6) + Phase 19 M11 media ranking. No second pipeline: this module discovers
nothing itself, downloads nothing, computes no new quality/relevance signal - it only aggregates
already-persisted `ImageCandidateRecord` rows across a Story's contributing events and calls the
existing, unmodified `services.media_ranking.rank_media_candidates()`.

Images only in this checkpoint (never video) - the Checkpoint 4 brief's own explicit "bad images
forbidden" list (avatars/icons/logos/screenshots/low-resolution/duplicates) is entirely image-
specific, and `services/video_discovery.py`'s candidates live in a differently-shaped table
(`ContentDraftMediaItem`, content-draft-scoped, not event-scoped the way `ImageCandidateRecord`
is) - wiring video in is a disclosed, straightforward future extension (`rank_media_candidates()`
is already media-type-agnostic), not attempted here to keep this checkpoint's own scope narrow.

Base eligibility reuses `eligible_for_editorial` - the EXISTING M4 relevance-stage gate, which
already excludes every hard-rejected candidate (favicon-sized images, etc. - services/
image_quality.py's own `quality_hard_rejection_reasons`). `rank_media_candidates()` (M11,
unmodified) then applies the additional quality floor / branding-risk / role-assignment logic on
top. Cross-event exact/near-duplicate suppression within the aggregated pool reuses services.
image_quality.hamming_distance and services.media_ranking's own calibrated near-duplicate
threshold - never a new, divergent one.

`story_reuse_match` (M11's own "already discovered for an EARLIER, separate NEWS post about this
evolving story" signal) is deliberately NOT applied here and always passed as `False`: that
signal's purpose doesn't transfer cleanly to a single aggregate deep-dive article that is
explicitly ABOUT the whole story (unlike a fresh standalone NEWS post for one new development,
this bundle is meant to draw from the story's whole visual history) - only within-bundle
duplication (the same photo discovered from two different events of this batch) is deduplicated
here, which is a different, narrower concern this module handles directly.

No new persistence table (mirrors services/media_ranking.py's own explicit scope decision) - a
future Copywriting-adjacent step can attach a `ArticleVisualResearchBundle`'s result to
`EditorialTask.workflow["step_results"]` if it ever needs to be durable, exactly like TELEGRAPH
Checkpoint 3's deep-research output already does; this checkpoint does not do that itself.
"""
from __future__ import annotations

from typing import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.image_candidate_record import ImageCandidateRecord
from database.models.story_link import NewsEventStoryLink
from schemas.image_candidate import AspectRatioBand
from schemas.media_ranking import MediaRankingInput, RecommendedRole
from schemas.telegraph_visual_research import (
    ArticleVisualImage,
    ArticleVisualResearchBundle,
    ImageProvenance,
    VisualRole,
)
from services.image_quality import aspect_ratio_band as compute_aspect_ratio_band
from services.image_quality import hamming_distance
from services.media_ranking import rank_media_candidates
from services.story_memory import NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE

# Mirrors services/telegraph_research_context.py's own _CONTRIBUTING_MATCH_TYPES exactly -
# Checkpoint 1's established semantics, kept in sync deliberately (module docstring there).
_CONTRIBUTING_MATCH_TYPES = frozenset({NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE})

# Reused, unmodified value - services/media_ranking.py's own calibrated threshold.
_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE = 4

# Reasoned starting caps (this checkpoint's own first calibration, no real usage data exists yet
# to fit against - matches this codebase's own disclosed-reasoning convention). One hero, a
# handful of supporting, a couple of context/explanatory images - never unbounded.
_MAX_HERO = 1
_MAX_SUPPORTING = 4
_MAX_CONTEXT = 3

_VISUAL_ROLE_BY_RECOMMENDED_ROLE: dict[RecommendedRole, VisualRole] = {
    RecommendedRole.HERO: VisualRole.HERO,
    RecommendedRole.SUPPORTING: VisualRole.SUPPORTING,
    RecommendedRole.TECHNICAL_DETAIL: VisualRole.CONTEXT,
    RecommendedRole.CHART_OR_DIAGRAM: VisualRole.CONTEXT,
    # DEMO_VIDEO / CONTEXT_VIDEO never appear - this module never emits media_type="video".
    # REJECT never appears - filtered by eligible_for_delivery before role mapping.
}

_ROLE_CAPS: dict[VisualRole, int] = {
    VisualRole.HERO: _MAX_HERO, VisualRole.SUPPORTING: _MAX_SUPPORTING, VisualRole.CONTEXT: _MAX_CONTEXT,
}


async def _fetch_contributing_event_ids(session: AsyncSession, story_id: UUID) -> list[UUID]:
    stmt = select(NewsEventStoryLink.news_event_id).where(
        NewsEventStoryLink.story_id == story_id,
        NewsEventStoryLink.match_type.in_(_CONTRIBUTING_MATCH_TYPES),
    )
    return list((await session.execute(stmt)).scalars().all())


async def _fetch_eligible_candidates(
    session: AsyncSession, event_ids: Collection[UUID],
) -> list[ImageCandidateRecord]:
    if not event_ids:
        return []
    stmt = select(ImageCandidateRecord).where(
        ImageCandidateRecord.news_event_id.in_(event_ids),
        ImageCandidateRecord.eligible_for_editorial.is_(True),
    )
    return list((await session.execute(stmt)).scalars().all())


def _record_aspect_ratio_band(record: ImageCandidateRecord) -> str | None:
    if record.aspect_ratio is None:
        return None
    band: AspectRatioBand = compute_aspect_ratio_band(record.aspect_ratio)
    return band.value


def _suppress_cross_event_duplicates(
    records: list[ImageCandidateRecord],
) -> list[ImageCandidateRecord]:
    """Pure. Within THIS bundle's own aggregated pool only (never a DB query) - the same photo
    discovered from two different contributing events keeps only its highest-quality-scored
    occurrence. Exact match (sha256) first, then near-duplicate (perceptual hash, reused
    threshold) - mirrors services/image_deduplication.py's own exact-then-near ordering."""
    ordered = sorted(records, key=lambda r: -(r.quality_score or 0))
    kept: list[ImageCandidateRecord] = []
    kept_sha256: set[str] = set()
    kept_phashes: list[str] = []
    for record in ordered:
        if record.sha256 and record.sha256 in kept_sha256:
            continue
        if record.perceptual_hash and any(
            hamming_distance(record.perceptual_hash, known) <= _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE
            for known in kept_phashes
        ):
            continue
        kept.append(record)
        if record.sha256:
            kept_sha256.add(record.sha256)
        if record.perceptual_hash:
            kept_phashes.append(record.perceptual_hash)
    return kept


def _to_ranking_input(record: ImageCandidateRecord) -> MediaRankingInput:
    warnings = record.quality_warnings or []
    return MediaRankingInput(
        media_item_id=record.id,
        media_type="image",
        quality_score=record.quality_score or 0,
        # services/image_quality.py's own discovery-confidence scale (0-20) is not persisted as a
        # separate column on ImageCandidateRecord - provenance_confidence (0-100, M4) is the
        # closest already-persisted analogue; rescaled to the 0-20 band rank_media_candidates()
        # expects, never left at a mismatched raw value.
        source_priority=round((record.provenance_confidence or 0) / 100 * 20),
        relevance_score=record.relevance_score,
        is_duplicate_within_event=record.is_representative is False,
        story_reuse_match=False,  # see module docstring for why this signal is not applied here
        possible_logo="possible_logo" in warnings,
        possible_banner="possible_banner" in warnings,
        possible_watermark="possible_watermark" in warnings,
        possible_tv_lower_third="possible_tv_lower_third" in warnings,
        possible_branded_screenshot="possible_branded_screenshot" in warnings,
        aspect_ratio_band=_record_aspect_ratio_band(record),
    )


def _explanation_for(record: ImageCandidateRecord, role: VisualRole) -> str:
    parts = [f"role={role.value}", f"quality={record.quality_score}"]
    if record.relevance_score is not None:
        parts.append(f"relevance={record.relevance_score}")
    if record.source_name:
        parts.append(f"source={record.source_name}")
    return ", ".join(parts)


async def build_visual_research_bundle(
    session: AsyncSession, *, proposal_id: UUID, story_id: UUID,
) -> ArticleVisualResearchBundle:
    """The one callable API this checkpoint exposes. Bounded, read-only, zero LLM/Gateway/network
    calls anywhere in this call graph (see tests/test_telegraph_visual_research.py's own
    structural source-scan tests) - never downloads an image, never discovers a new candidate.

    Returns 0..N images, role-capped and eligibility-filtered - never padded to reach a cap with
    a sub-threshold candidate (mirrors services/telegraph_topic_candidates.py's own "quality over
    quota" discipline exactly)."""
    event_ids = await _fetch_contributing_event_ids(session, story_id)
    candidates = await _fetch_eligible_candidates(session, event_ids)
    deduplicated = _suppress_cross_event_duplicates(candidates)

    ranking_inputs = [_to_ranking_input(record) for record in deduplicated]
    ranked = rank_media_candidates(ranking_inputs)
    by_id = {record.id: record for record in deduplicated}

    role_counts: dict[VisualRole, int] = {role: 0 for role in VisualRole}
    images: list[ArticleVisualImage] = []
    rejected_count = 0
    for result in ranked:
        if not result.eligible_for_delivery:
            rejected_count += 1
            continue
        visual_role = _VISUAL_ROLE_BY_RECOMMENDED_ROLE.get(result.recommended_role)
        if visual_role is None:
            continue  # a video-only recommended role - structurally unreachable (images only)
        if role_counts[visual_role] >= _ROLE_CAPS[visual_role]:
            continue
        record = by_id[result.media_item_id]
        images.append(
            ArticleVisualImage(
                image_candidate_record_id=record.id,
                source_url=record.source_url,
                final_url=record.final_url,
                provenance=ImageProvenance(
                    source_name=record.source_name, article_url=record.article_url,
                    discovery_method=record.discovery_method,
                    source_relationship=record.source_relationship,
                    news_event_id=record.news_event_id,
                ),
                quality_score=record.quality_score or 0,
                relevance_score=record.relevance_score or 0,
                role=visual_role,
                width=record.width, height=record.height,
                explanation=_explanation_for(record, visual_role),
            )
        )
        role_counts[visual_role] += 1

    return ArticleVisualResearchBundle(
        proposal_id=proposal_id, story_id=story_id, images=images,
        total_candidates_considered=len(candidates), total_rejected=rejected_count,
    )


def render_visual_bundle_summary(bundle: ArticleVisualResearchBundle) -> str:
    """Deterministic, bounded plain-text summary - TELEGRAPH Checkpoint 5's own
    ArticleGenerationCapability reads this as informational context only (its prompt explicitly
    instructs the model never to describe or embed these images as article text). Never image
    bytes, never a data: URI - counts and roles only."""
    if not bundle.images:
        return "No visual research images available for this story."
    by_role: dict[VisualRole, int] = {}
    for image in bundle.images:
        by_role[image.role] = by_role.get(image.role, 0) + 1
    parts = [f"{count} {role.value} image(s)" for role, count in by_role.items()]
    return f"{len(bundle.images)} image(s) selected: " + ", ".join(parts) + "."
