"""Phase 19 M11: media-ranking result shapes. Pure computation output only - no persistence
shape defined here (see services/media_ranking.py's own module docstring for the scope decision
not to add a new table in this milestone).
"""
from __future__ import annotations

import enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecommendedRole(str, enum.Enum):
    HERO = "hero"
    SUPPORTING = "supporting"
    TECHNICAL_DETAIL = "technical_detail"
    CHART_OR_DIAGRAM = "chart_or_diagram"
    DEMO_VIDEO = "demo_video"
    CONTEXT_VIDEO = "context_video"
    REJECT = "reject"


class MediaRankingInput(BaseModel):
    """Everything the ranker needs about one candidate - assembled by the caller from whatever
    combination of services/image_quality.py (QualitySignals), services/image_relevance.py, and
    services/video_discovery.py (VideoValidation) already computed for it. This module never
    fetches or computes any of these itself - pure aggregation/scoring only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    media_item_id: UUID
    media_type: str  # "image" | "video"
    quality_score: int  # 0-100
    source_priority: int  # 0-20, mirrors services/image_quality.py's own discovery-confidence scale
    relevance_score: int | None = None  # 0-100, None if no relevance signal exists for this media_type yet
    is_duplicate_within_event: bool = False
    story_reuse_match: bool = False  # already used elsewhere in the same Story (M11's own cross-event check)
    possible_logo: bool = False
    possible_banner: bool = False
    possible_watermark: bool = False
    possible_tv_lower_third: bool = False
    possible_branded_screenshot: bool = False
    aspect_ratio_band: str | None = None
    video_validation_status: str | None = None  # "valid" | "rejected" | "unvalidated_hosted_platform" | None


class MediaRankingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    media_item_id: UUID
    media_type: str
    relevance_score: int
    source_priority: int
    quality_score: int
    novelty_score: int
    story_reuse_penalty: int
    branding_risk: int
    recommended_role: RecommendedRole
    recommended_order: int
    explanation: str
    eligible_for_delivery: bool
