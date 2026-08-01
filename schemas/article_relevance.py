"""ArticleTopicAssessment / ChannelFitAssessment / ShadowEditorialDecision - Phase 17 M2 (docs/
phase17_m2_channel_topic_relevance_shadow_report.md).

Three versioned, strict Pydantic schemas produced by `services/channel_relevance.py`'s
deterministic classifier - never mutated after construction, no mutable defaults.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from database.models.news_event import EventCategory
from schemas.topic_taxonomy import ArticleTopic

ARTICLE_RELEVANCE_SCHEMA_VERSION = "v1"


class FitDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class RelevanceConfidence(str, Enum):
    """Decision confidence - distinct from `schemas.editorial_brief.FieldConfidence` (which
    tags per-field *evidence provenance*, not an overall classification confidence)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ArticleTopicAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = ARTICLE_RELEVANCE_SCHEMA_VERSION
    primary_topic: ArticleTopic
    secondary_topics: list[ArticleTopic] = Field(default_factory=list)
    normalized_category: EventCategory | None
    detected_entities: list[str] = Field(default_factory=list)
    # topic name (str, ArticleTopic.value) -> matched keyword/evidence fragments for that topic.
    topic_evidence: dict[str, list[str]] = Field(default_factory=dict)
    source_category: EventCategory
    category_match: bool
    confidence: RelevanceConfidence
    reason_codes: list[str] = Field(default_factory=list)


class ChannelFitAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = ARTICLE_RELEVANCE_SCHEMA_VERSION
    channel_profile_id: str
    fit_decision: FitDecision
    fit_score: float = Field(ge=0.0, le=1.0)
    confidence: RelevanceConfidence
    matched_topics: list[ArticleTopic] = Field(default_factory=list)
    excluded_topics: list[ArticleTopic] = Field(default_factory=list)
    conditional_matches: list[ArticleTopic] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    human_review_required: bool


class ShadowEditorialDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = ARTICLE_RELEVANCE_SCHEMA_VERSION
    decision: FitDecision
    reason_codes: list[str] = Field(default_factory=list)
    confidence: RelevanceConfidence
    classifier_version: str
