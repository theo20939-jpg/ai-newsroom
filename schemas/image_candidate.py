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


class ImageCandidateStatus(str, enum.Enum):
    """M1 only has metadata-only states - no download/validation/selection state exists yet
    (those belong to M2/M3/M6 respectively, per the implementation plan's milestone split)."""

    DISCOVERED = "discovered"
    REJECTED_METADATA = "rejected_metadata"
    UNAVAILABLE = "unavailable"


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
    declared_width: int | None = None
    declared_height: int | None = None
    declared_mime_type: str | None = None
    alt_text: str | None = None
    caption: str | None = None
    telegram: TelegramReference | None = None
    warnings: list[str] = Field(default_factory=list)


class ImageCandidate(BaseModel):
    """One consolidated, identified candidate - the per-item shape inside `ImageIntelligenceResult.
    candidates`. `remote_url` is None for Telegram-native candidates (nothing HTTP-addressable
    exists pre-download; `telegram` carries the retrieval coordinates instead)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    schema_version: Literal["m1"] = "m1"
    event_id: UUID
    source_type: SourceType
    discovery_method: ImageDiscoveryMethod
    status: ImageCandidateStatus
    remote_url: str | None = None
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


class ImageIntelligenceResult(BaseModel):
    """The exact shape attached at `structured_output["image_intelligence"]` (CONTENT_GENERATION
    "copywriting" step hook) and logged at Collector time - see docs/phase16_image_intelligence_
    discovery_report.md §11 for why this JSON shape, not a new table, is the correct M1 boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["m1"] = "m1"
    mode: Literal["off", "shadow"]
    event_id: UUID
    candidates_discovered: int = Field(ge=0)
    candidates_accepted: int = Field(ge=0)
    candidates_rejected: int = Field(ge=0)
    candidates: list[ImageCandidate] = Field(default_factory=list)
    generated_at: datetime
    errors: list[str] = Field(default_factory=list)
