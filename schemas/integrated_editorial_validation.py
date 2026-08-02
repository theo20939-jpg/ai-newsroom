"""IntegratedEditorialValidation - Phase 17 M6 (docs/
phase17_m6_integrated_editorial_validation_report.md).

A versioned, read-only validation-metadata record combining Channel/Topic Relevance (M2),
Editorial Completeness (M5), calibrated Fact Safety (M5), and deterministic Telegram delivery
feasibility (reusing `bot/formatting.py` unmodified) into one explainable `overall_decision`.
Never enforced - `services/integrated_editorial_validation.py::build_integrated_editorial_
validation()` only assesses and returns this schema; nothing reads it to change delivery.
"""
from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.article_relevance import FitDecision
from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment
from schemas.editorial_brief import SourceSufficiency
from schemas.editorial_completeness import EditorialCompletenessAssessment

INTEGRATED_EDITORIAL_VALIDATION_SCHEMA_VERSION = "v1"
INTEGRATED_VALIDATION_POLICY_VERSION = "v1"


class CandidateKind(str, Enum):
    PRODUCTION_BASELINE = "production_baseline"
    M3_CANDIDATE = "m3_candidate"
    M4_CANDIDATE = "m4_candidate"
    UNKNOWN = "unknown"


class DeliveryModeRecommendation(str, Enum):
    PHOTO_CAPTION = "photo_caption"
    TEXT_MESSAGE = "text_message"
    UNKNOWN = "unknown"


class DeliveryValidation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plain_char_count: int = Field(ge=0)
    formatted_utf16_length: int = Field(ge=0)
    fits_text_message: bool
    fits_photo_caption: bool | None  # None = image state unknown, never invented
    url_exposed_in_body: bool
    silently_truncated: bool
    recommended_delivery_mode: DeliveryModeRecommendation
    reason_codes: list[str] = Field(default_factory=list)


class ImageContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    has_image_candidate: bool | None  # None = unknown, never invented
    source: str  # "known" | "unknown"


class OverallDecision(str, Enum):
    READY_FOR_EDITOR = "READY_FOR_EDITOR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECT_RECOMMENDED = "REJECT_RECOMMENDED"
    INSUFFICIENT_SOURCE = "INSUFFICIENT_SOURCE"
    TECHNICAL_BLOCKER = "TECHNICAL_BLOCKER"


class ValidationConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IntegratedEditorialValidation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = INTEGRATED_EDITORIAL_VALIDATION_SCHEMA_VERSION
    validation_version: str = INTEGRATED_VALIDATION_POLICY_VERSION

    event_id: UUID
    candidate_kind: CandidateKind

    channel_fit_decision: FitDecision | None  # None = channel relevance unavailable
    source_sufficiency: SourceSufficiency

    completeness: EditorialCompletenessAssessment | None
    fact_safety: CalibratedFactSafetyAssessment | None
    delivery: DeliveryValidation | None
    image_context: ImageContext

    overall_decision: OverallDecision
    blocking_reasons: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: ValidationConfidence
