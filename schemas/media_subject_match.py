"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 sections 7/8/10/12/14: the contracts for one
discovered/considered media candidate, its provenance, its usage-rights classification, and its
subject-identity classification. Deliberately separate from `schemas/image_candidate.py` (Phase 16
M1-M4) rather than a migration of it (section 14: "avoid unnecessary schema migration if an
existing model supports this truthfully" - it does not: that contract has no field anywhere for
"does this depict the exact claimed subject" or "what is this image's usage-rights status", and
extending its live, migrated `image_candidates` table is a real production-schema decision this
phase does not make unilaterally - see the report's own disclosed-scope section). A
`ResolvedMediaCandidate` MAY wrap an existing `ImageCandidate`/`ImageCandidateRecord` (Tier 1 - see
`services/media_research_selection.py`) as well as a newly web-discovered asset (Tier 2-5) - one
shape for both, everything downstream (scoring, selection) never needs to know which tier a
candidate came from except as one of many scoring inputs."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoveryTier(str, enum.Enum):
    """Section 5's own explicit preference order - purely descriptive of WHERE a candidate was
    found; never itself the final usage/rights verdict (that is `MediaUsageClassification`, kept
    separate on purpose, section 8)."""

    TIER1_CURRENT_SOURCE = "tier1_current_source"  # already attached to / scraped from the
    # NewsEvent's own article - reuses the real Phase 16 `image_candidates` pool, read-only.
    TIER2_OFFICIAL_PRIMARY = "tier2_official_primary"  # manufacturer/brand/official press/event asset
    TIER3_CORROBORATING_EDITORIAL = "tier3_corroborating_editorial"  # a reputable publication
    # covering the same exact product/event, found via Tier 4 discovery then classified up
    TIER4_WEB_IMAGE_DISCOVERY = "tier4_web_image_discovery"  # a generic/unclassified web result
    TIER5_SAFE_FALLBACK = "tier5_safe_fallback"  # contextual/graphic/local-brand-asset - never a
    # claimed depiction of the exact subject


class MediaUsageClassification(str, enum.Enum):
    """Section 8 - NOT a copyright detector (no claim of legal certainty is ever made here); a
    conservative, disclosed, source-based heuristic only. `NOT_USABLE` and anything below
    `APPROVED_SOURCE_MEDIA`/`OFFICIAL_PRESS_ASSET` must never be auto-selected for publication -
    `EDITORIAL_REVIEW_REQUIRED` is the safe default for anything not clearly first-party."""

    APPROVED_SOURCE_MEDIA = "approved_source_media"  # from the NewsEvent's own source, already
    # covered by this codebase's existing editorial media-sourcing policy (Tier 1 candidates)
    OFFICIAL_PRESS_ASSET = "official_press_asset"  # from the subject's own manufacturer/brand
    # newsroom/press domain - the entity being depicted is also the publisher
    EDITORIAL_REVIEW_REQUIRED = "editorial_review_required"  # a third-party publication's own
    # photo - plausibly usable under fair-use/editorial-commentary norms, but rights are not
    # verified here; a human editor must decide before this ever becomes a publication asset
    NOT_USABLE = "not_usable"  # explicitly disqualified (e.g. a stock-photo watermark, a platform
    # that forbids automated reuse) - never selected under any circumstance


class SubjectMatchClassification(str, enum.Enum):
    """Section 10 - visual entity-identity classification, entirely orthogonal to
    `services/image_relevance.py`'s own provenance/lexical relevance score. That module answers
    "how confidently is this image tied to the original publication"; this answers "does this
    image's actual visual content depict the intent's claimed subject." A candidate can score
    highly on one and MISMATCH on the other (the exact "ordinary iPhone reused for the specific
    new foldable iPhone" failure section 0 names)."""

    EXACT_SUBJECT = "exact_subject"  # genuinely depicts the specific named subject (this model,
    # this event, this person) - the only classification allowed to be PRESENTED as the subject.
    STRONG_CONTEXT = "strong_context"  # same brand/family/category/venue, clearly not the exact
    # named subject - usable ONLY with treatment that does not imply it is the exact subject.
    GENERIC_CONTEXT = "generic_context"  # topically related but visually generic (e.g. a plain
    # smartphone stock photo for any phone story) - weak, safe-fallback-adjacent.
    MISMATCH = "mismatch"  # wrong subject, wrong brand, or actively misleading - never selectable.


class SubjectMatchValidation(BaseModel):
    """The real, vision-LLM-backed verdict for one (candidate, intent) pair - produced by
    `capabilities/media_subject_match_capability.py`. Mirrors `schemas/image_candidate.py::
    RelevanceValidation`'s own discipline (a `version` tag, an always-set reason, bounded fields)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["v1"] = "v1"
    depicted_subject_description: str = Field(min_length=1, max_length=500)
    subject_match: SubjectMatchClassification
    must_not_imply_violated: bool
    violated_statements: list[str] = Field(default_factory=list, max_length=10)
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str = Field(min_length=1, max_length=500)


class MediaProvenance(BaseModel):
    """Section 7 - every externally-discovered candidate must carry this; never dropped once a
    candidate is downloaded/cached (section 7's own explicit instruction)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin_url: str = Field(max_length=2000)  # the page the asset was found on/via
    asset_url: str = Field(max_length=2000)  # the resolved, directly-fetchable image URL
    publisher_domain: str | None = Field(default=None, max_length=255)
    discovery_query: str | None = Field(default=None, max_length=300)
    discovered_at: datetime
    discovery_tier: DiscoveryTier
    caption_or_alt: str | None = Field(default=None, max_length=500)
    content_identity_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    licensing_note: str | None = Field(default=None, max_length=500)


class ResolvedMediaCandidate(BaseModel):
    """One candidate ready for scoring - section 14's `MediaCandidate` contract. `local_path` is
    set only after a real, safety-bounded download (`services/media_download_cache.py`); a
    candidate may be fully classified/scored before that (subject-match and usage classification
    both only need the image bytes transiently, not permanent local storage)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    provenance: MediaProvenance
    media_type: Literal["image"] = "image"
    width: int | None = None
    height: int | None = None
    orientation: Literal["portrait", "landscape", "square"] | None = None
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    perceptual_hash: str | None = Field(default=None, min_length=1, max_length=32)
    local_path: str | None = None

    usage_classification: MediaUsageClassification
    subject_match: SubjectMatchValidation | None = None  # None until the vision capability ran

    # Existing Tier-1 pipeline linkage, when this candidate wraps an already-persisted Phase 16
    # image_candidates row - None for every Tier 2-5 (web-discovered/fallback) candidate.
    image_candidate_record_id: str | None = None
    existing_relevance_score: int | None = Field(default=None, ge=0, le=100)
    existing_quality_score: int | None = Field(default=None, ge=0, le=100)


class MediaSelectionResult(BaseModel):
    """Section 11/12 - the final, disclosed outcome for one `MediaIntent`. `exact_subject_media_
    not_found` is always set truthfully (section 11's own explicit requirement), independent of
    whether a candidate was selected at all (a STRONG_CONTEXT selection still sets this True)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_primary_entity: str
    selected: ResolvedMediaCandidate | None
    selected_score: float | None = None
    exact_subject_media_not_found: bool
    fallback_used: bool
    candidates_considered: int
    candidates_by_classification: dict[str, int] = Field(default_factory=dict)
    rejection_reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
