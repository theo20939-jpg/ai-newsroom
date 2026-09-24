"""NewsEventArticleAcquisition ORM model (Phase 19 M1/M2).

A deliberately standalone table, PK = news_event_id - same hot-path-dependency reasoning as
database/models/story_link.py/content_draft_quote.py: NewsEvent.content is never overwritten and
NewsEvent itself never gains a column, so the always-run NewsEvent insert (services/collector.py)
never depends on this migration being applied.

One row per acquisition *attempt* (not per NewsEvent that merely exists) - only ever created for
an event that has already passed the existing selection pipeline (scripts/run_content_generation.
py::run_content_generation_for_event(), never for the mass NEWS_ANALYSIS population - see
services/article_acquisition.py).

Reuse design (Phase 19 plan Correction 3): `reused_from_news_event_id` is non-null only on a
lightweight "reuse" row - such a row's own raw_extracted_text/cleaned_text/hash columns stay NULL
by construction; readers resolve the effective text via services.article_acquisition.
get_effective_acquisition(), which follows this pointer at most one hop (a reuse row is never
itself a valid reuse target - enforced before write, not just by convention).

Persisted-text/provenance design (Correction 4): raw_extracted_text and cleaned_text are both
stored directly on this row (never reconstructed on a later read), plus a
selected_editorial_text_hash so any ContentDraft can be traced, via its own event_id FK alone,
back to the exact text a model saw and the cleaning-rule version that produced it.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base

# Required acquisition statuses (Phase 19 plan, exact) - a deterministic char-count/extraction-
# ratio classification, never a judgment call. PAYWALLED is a disclosed, approximate heuristic
# (services/article_cleaning.py), not a guarantee.
ACQUISITION_STATUS_FULL_TEXT = "FULL_TEXT"
ACQUISITION_STATUS_SUBSTANTIAL_TEXT = "SUBSTANTIAL_TEXT"
ACQUISITION_STATUS_PARTIAL_TEXT = "PARTIAL_TEXT"
ACQUISITION_STATUS_HEADLINE_ONLY = "HEADLINE_ONLY"
ACQUISITION_STATUS_PAYWALLED = "PAYWALLED"
ACQUISITION_STATUS_FETCH_FAILED = "FETCH_FAILED"
ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
ACQUISITION_STATUS_REDIRECT_UNRESOLVED = "REDIRECT_UNRESOLVED"

TRIGGERED_BY_CONTENT_GENERATION_SELECTED = "content_generation_selected"
TRIGGERED_BY_STORY_UPDATE_REUSE = "story_update_reuse"
TRIGGERED_BY_INSTAGRAM_SELECTED = "instagram_selected"  # a KAGE Instagram post already selected (services/instagram_evidence_package.py)


class NewsEventArticleAcquisition(Base):
    __tablename__ = "news_event_article_acquisitions"

    news_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), primary_key=True
    )
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Self-referential FK, one hop only by construction (see module docstring).
    reused_from_news_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=True
    )
    acquisition_status: Mapped[str] = mapped_column(String, nullable=False)
    # Verbatim extraction, pre-cleaning. NULL on a reuse row and on any non-text status.
    raw_extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # services/article_cleaning.py's output - persisted, never reconstructed on read.
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # May be downgraded from acquisition_status by article_cleaning.py's own confidence check
    # (e.g. a raw FULL_TEXT-sized extraction that cleaned down to very little becomes PARTIAL_TEXT
    # here) - this is the value every downstream reader should trust.
    effective_completeness_status: Mapped[str] = mapped_column(String, nullable=False)
    # SHA-256 of whichever text was actually handed to Research/Copywriting (cleaned_text, or the
    # RSS-excerpt fallback) - the exact provenance field a ContentDraft traces back to.
    selected_editorial_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cleaned_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    removed_block_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cleaning_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cleaning_version: Mapped[str] = mapped_column(String, nullable=False, default="unset")
    source_html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetch_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
