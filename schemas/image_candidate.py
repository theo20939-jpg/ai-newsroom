"""Phase 16 M1: Image Intelligence candidate contract (docs/
phase16_image_intelligence_discovery_report.md §11, docs/phase16_m1_native_media_ingestion_report.md).

Zero-download, zero-LLM, metadata-only. Nothing here represents downloaded image bytes, a
decoded/validated MIME type, a content hash, or a perceptual hash - those are later milestones
(discovery report §11 explicitly excludes them from the M1 contract). `NativeMediaHint` is what an
adapter produces the instant it sees a raw message/entry, before any NewsEvent exists.
`ImageCandidate`/`ImageIntelligenceResult` are what services.image_intelligence produces once an
`event_id` is known - the only two places this shape is ever built are
services/collector.py (post-flush, full source-native hints) and capabilities/executor.py's
"copywriting" step hook (best-effort reconstruction from already-persisted NewsEvent fields).

Deliberately unaware of the database, aiogram, Telethon, and feedparser types - mirrors
schemas/raw_news_item.py's own "adapters only know how to produce this shape" discipline.
"""
import enum
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from database.models.news_source import SourceType


class ImageDiscoveryMethod(str, enum.Enum):
    """How a candidate's existence was learned - never how it will be fetched (M1 fetches nothing).

    Bounded per docs/phase16_image_intelligence_discovery_report.md §11/§15 - discovery method
    feeds the (future, M4) relevance-ranking provenance component, so this enum is intentionally
    specific rather than a free-form string.
    """

    TELEGRAM_PHOTO = "telegram_photo"
    TELEGRAM_DOCUMENT = "telegram_document"
    TELEGRAM_THUMBNAIL = "telegram_thumbnail"
    RSS_MEDIA_CONTENT = "rss_media_content"
    RSS_MEDIA_THUMBNAIL = "rss_media_thumbnail"
    RSS_ENCLOSURE = "rss_enclosure"
    RSS_INLINE_IMAGE = "rss_inline_image"
    SOURCE_NATIVE_UNKNOWN = "source_native_unknown"
    # Phase 16 M2 (docs/phase16_m2_secure_fetch_and_validation_report.md §10/§11): article-page
    # metadata discovery methods, in the deterministic priority order services/article_metadata.py
    # extracts them - og:image:secure_url > og:image > JSON-LD > twitter:image > image_src link.
    OPEN_GRAPH_SECURE_IMAGE = "open_graph_secure_image"
    OPEN_GRAPH_IMAGE = "open_graph_image"
    JSONLD_ARTICLE_IMAGE = "jsonld_article_image"
    TWITTER_IMAGE = "twitter_image"
    IMAGE_SRC_LINK = "image_src_link"


class ImageCandidateStatus(str, enum.Enum):
    """M1 states are metadata-only. M2 adds the technical-validation outcome states - a candidate
    moves from `discovered` to exactly one of `validated`/`rejected_technical`/`fetch_failed` only
    if it was actually selected for M2 byte-level validation (bounded by `image_intelligence_max_
    image_downloads_per_event`); candidates beyond that cap simply stay `discovered`, never
    touched by M2. No download/selection/editorial state exists yet (M3/M6)."""

    DISCOVERED = "discovered"
    REJECTED_METADATA = "rejected_metadata"
    UNAVAILABLE = "unavailable"
    VALIDATED = "validated"
    REJECTED_TECHNICAL = "rejected_technical"
    FETCH_FAILED = "fetch_failed"


class TelegramReference(BaseModel):
    """Stable, non-secret Telegram retrieval coordinates only - never a session-bound
    access_hash or file-reference blob (docs/phase16_image_intelligence_discovery_report.md's own
    Telegram security guidance: "prefer stable retrieval coordinates over persisting opaque
    session-bound data"). `media_id` is Telethon's own `Photo.id`/`Document.id` - a stable,
    non-secret per-file identifier, deliberately not paired with its `access_hash` (session/
    context-bound, expires - re-derived by re-fetching the message later, not stored now)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: int
    grouped_id: int | None = None
    media_kind: Literal["photo", "document"]
    media_id: int | None = None
    file_name: str | None = None


class NativeMediaHint(BaseModel):
    """What an adapter produces the instant it sees native media on a raw message/entry - before
    any NewsEvent exists, before any rejection rule or deterministic ID is assigned. Consumed only
    by services.image_intelligence.consolidate_candidates(), never persisted or logged as-is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_method: ImageDiscoveryMethod
    remote_url: str | None = None
    source_url: str | None = None
    declared_width: int | None = None
    declared_height: int | None = None
    declared_mime_type: str | None = None
    alt_text: str | None = None
    caption: str | None = None
    telegram: TelegramReference | None = None
    warnings: list[str] = Field(default_factory=list)


class TechnicalValidation(BaseModel):
    """Phase 16 M2: the outcome of actually fetching and decoding a candidate's image bytes -
    transient only, bytes themselves are never part of this or any persisted shape. `error_code`
    is one of `integrations.http.safe_fetch.FetchErrorCode`'s values, or an image-specific code
    (`signature_mismatch`/`unsupported_format`/`svg_rejected`/`decode_failed`/`pixel_limit_
    exceeded`/`animation_unsupported`), never a raw exception string (docs/phase16_m2_secure_
    fetch_and_validation_report.md §16)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["m2"] = "m2"
    final_url: str | None = None
    http_status: int | None = None
    redirect_count: int = 0
    observed_mime: str | None = None
    format: str | None = None
    byte_size: int | None = None
    width: int | None = None
    height: int | None = None
    pixel_count: int | None = None
    aspect_ratio: float | None = None
    animated: bool | None = None
    frame_count: int | None = None
    sha256: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None


class QualityStatus(str, enum.Enum):
    """Phase 16 M3 (docs/phase16_m3_quality_and_deduplication_report.md §17) - a candidate reaches
    exactly one of these only if it was `VALIDATED` by M2 and selected for M3 analysis. Distinct
    from `ImageCandidateStatus`: that field is M1/M2's own technical/metadata lifecycle status and
    is never overwritten by M3 (docs' own explicit "keep separate concerns" instruction) -
    `QualityValidation.status` here is the M3-only editorial-usability/duplicate verdict."""

    ACCEPTED = "accepted"
    REJECTED_QUALITY = "rejected_quality"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_NEAR = "duplicate_near"
    REVIEW = "review"


class ResolutionBand(str, enum.Enum):
    """Deterministic dimension band - see the M3 report §8 for the calibration evidence behind
    each threshold."""

    TRACKING = "tracking"
    ICON = "icon"
    WEAK = "weak"
    ADEQUATE = "adequate"
    GOOD = "good"


class AspectRatioBand(str, enum.Enum):
    """Deterministic aspect-ratio band - see the M3 report §9."""

    EXTREME_TALL = "extreme_tall"
    PORTRAIT = "portrait"
    SQUARE = "square"
    EDITORIAL_LANDSCAPE = "editorial_landscape"
    WIDE_BANNER = "wide_banner"
    EXTREME_WIDE = "extreme_wide"


class QualitySignals(BaseModel):
    """Conservative, deterministic signals only - every `possible_*` field is exactly that, a
    possibility, never a `confirmed_*` claim (M3 task brief's own explicit requirement, §8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution_band: ResolutionBand
    aspect_ratio_band: AspectRatioBand
    possible_tracking_pixel: bool = False
    possible_icon: bool = False
    possible_logo: bool = False
    possible_avatar: bool = False
    possible_banner: bool = False
    possible_placeholder: bool = False


class DeduplicationInfo(BaseModel):
    """Exact and perceptual duplicate-cluster membership - scoped to one event only (M3 does not
    query across events or persist anything - discovery report §12/§14)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exact_hash: str | None = None
    perceptual_hash: str | None = None
    exact_cluster_id: str | None = None
    perceptual_cluster_id: str | None = None
    duplicate_of: str | None = None  # candidate_id of the cluster representative, if not itself
    hamming_distance: int | None = None
    is_representative: bool = False


class QualityValidation(BaseModel):
    """Phase 16 M3: deterministic editorial-usability and duplicate-cluster verdict. Deliberately
    separate from `TechnicalValidation` (M2) and any future relevance-ranking shape (M4) - a
    candidate can be `TechnicalValidation.error_code is None` (M2: technically decodable) and
    still `QualityStatus.REJECTED_QUALITY` (M3: a 1x1 tracking pixel) or `DUPLICATE_NEAR` (M3: a
    resized copy of a better candidate). Never claims semantic/story relevance - `quality_score`
    reflects technical/editorial usability only (M3 task brief §16's own explicit non-goal list)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["m3"] = "m3"
    status: QualityStatus
    quality_score: int = Field(ge=0, le=100)
    quality_components: dict[str, int] = Field(default_factory=dict)
    quality_penalties: dict[str, int] = Field(default_factory=dict)
    hard_rejection_reasons: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    signals: QualitySignals
    deduplication: DeduplicationInfo
    duration_ms: int | None = None


class RelevanceStatus(str, enum.Enum):
    """Phase 16 M4 (docs/phase16_m4_relevance_ranking_report.md §5) - a candidate reaches exactly
    one of these. `INELIGIBLE` never reached scoring at all (M2/M3 gate failure - see
    `services.image_relevance.evaluate_eligibility`). `INSUFFICIENT_EVIDENCE` passed the M2/M3 gate
    but has too little relevance-specific evidence (no text, weak/unknown provenance and
    relationship) to be confidently ranked - reported, never silently dropped. `RANKED` was scored
    and assigned a position in the deterministic ordering; only the top `image_intelligence_top_
    candidates` of these are `eligible_for_editorial`."""

    RANKED = "ranked"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INELIGIBLE = "ineligible"


class SourceRelationship(str, enum.Enum):
    """Phase 16 M4 (docs/phase16_m4_relevance_ranking_report.md §7) - how a candidate's image URL
    relates to the NewsEvent's own article/source. Ordered here from strongest to weakest
    confidence; the numeric mapping lives in `services.image_relevance`, not on the enum itself."""

    NATIVE_SAME_ITEM = "native_same_item"
    SAME_ARTICLE = "same_article"
    SAME_DOMAIN = "same_domain"
    SOURCE_CDN_OR_RELATED = "source_cdn_or_related"
    THIRD_PARTY_UNKNOWN = "third_party_unknown"
    UNRELATED_OR_CONFLICTING = "unrelated_or_conflicting"


class RelevanceValidation(BaseModel):
    """Phase 16 M4: deterministic, metadata-only relevance-to-story ranking. Deliberately separate
    from `TechnicalValidation` (M2) and `QualityValidation` (M3) - a candidate can be `QualityStatus.
    ACCEPTED` (M3: technically/editorially usable) and still rank last here (M4: weak provenance, no
    textual overlap with the story). Never claims visual/semantic understanding of image content -
    `relevance_score` reflects only lexical/provenance/structural evidence (M4 task brief's own
    explicit non-goal list). `eligibility_reason` is always set; `relevance_score`/`components`/
    `penalties`/`coverage`/`rank`/`reason` are only meaningful once `status != ineligible`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["m4"] = "m4"
    status: RelevanceStatus
    eligibility_reason: str
    relevance_score: int = Field(default=0, ge=0, le=100)
    rank: int | None = Field(default=None, ge=1)
    eligible_for_editorial: bool = False
    source_relationship: SourceRelationship | None = None
    components: dict[str, int] = Field(default_factory=dict)
    penalties: dict[str, int] = Field(default_factory=dict)
    coverage: dict[str, bool] = Field(default_factory=dict)
    reason: str | None = None
    duration_ms: int | None = None


class ImageCandidate(BaseModel):
    """One consolidated, identified candidate - the per-item shape inside `ImageIntelligenceResult.
    candidates`. `remote_url` is None for Telegram-native candidates (nothing HTTP-addressable
    exists pre-download; `telegram` carries the retrieval coordinates instead). `source_url` (M2)
    is the article page a metadata-discovered candidate came from - None for native (Telegram/RSS)
    candidates, which have no separate "source page" beyond the event itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    schema_version: Literal["m1", "m2", "m3", "m4"] = "m1"
    event_id: UUID
    source_type: SourceType
    discovery_method: ImageDiscoveryMethod
    status: ImageCandidateStatus
    remote_url: str | None = None
    source_url: str | None = None
    telegram: TelegramReference | None = None
    declared_width: int | None = None
    declared_height: int | None = None
    declared_mime_type: str | None = None
    alt_text: str | None = None
    caption: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    discovery_order: int = Field(ge=0)
    discovered_at: datetime
    technical_validation: TechnicalValidation | None = None
    quality_validation: QualityValidation | None = None
    relevance_validation: RelevanceValidation | None = None


class ImageIntelligenceResult(BaseModel):
    """The exact shape attached at `structured_output["image_intelligence"]` (CONTENT_GENERATION
    "copywriting" step hook) and logged at Collector time - see docs/phase16_image_intelligence_
    discovery_report.md §11 for why this JSON shape, not a new table, is the correct M1 boundary.
    M2 fields are additive and default to values that are exactly correct when M2 processing never
    ran (mode="off", or an event with no article URL) - backward-compatible with every M1 result
    already logged/recorded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["m1", "m2", "m3", "m4"] = "m1"
    mode: Literal["off", "shadow"]
    event_id: UUID
    candidates_discovered: int = Field(ge=0)
    candidates_accepted: int = Field(ge=0)
    candidates_rejected: int = Field(ge=0)
    candidates: list[ImageCandidate] = Field(default_factory=list)
    generated_at: datetime
    errors: list[str] = Field(default_factory=list)
    # Phase 16 M2 observability (docs/phase16_m2_secure_fetch_and_validation_report.md §17).
    article_fetch_attempted: bool = False
    article_fetch_error: str | None = None
    candidates_validated: int = Field(default=0, ge=0)
    candidates_rejected_technical: int = Field(default=0, ge=0)
    candidates_fetch_failed: int = Field(default=0, ge=0)
    # Phase 16 M3 observability (docs/phase16_m3_quality_and_deduplication_report.md §21).
    candidates_quality_accepted: int = Field(default=0, ge=0)
    candidates_rejected_quality: int = Field(default=0, ge=0)
    candidates_duplicate_exact: int = Field(default=0, ge=0)
    candidates_duplicate_near: int = Field(default=0, ge=0)
    candidates_review: int = Field(default=0, ge=0)
    # Phase 16 M4 observability (docs/phase16_m4_relevance_ranking_report.md §18).
    candidates_quality_eligible: int = Field(default=0, ge=0)
    candidates_ranked: int = Field(default=0, ge=0)
    top_candidate_ids: list[str] = Field(default_factory=list)
