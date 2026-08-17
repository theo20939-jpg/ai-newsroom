"""TELEGRAPH Checkpoint 4: Visual Research result shapes.

Pure result contracts only - no persistence shape defined here. Mirrors services/
media_ranking.py's own explicit "no new persistence table in this milestone" scope decision
(schemas/media_ranking.py's own module docstring) for the identical reason: `ArticleVisualImage`
is a deterministic recomputation over already-durable `ImageCandidateRecord` rows plus the
existing, unmodified `rank_media_candidates()` - nothing here is lost if recomputed on demand.
"""
from __future__ import annotations

import enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VisualRole(str, enum.Enum):
    """Deliberately only three values (the Checkpoint 4 brief's own explicit vocabulary) -
    narrower than services.media_ranking.RecommendedRole's six. See services/
    telegraph_visual_research.py::_VISUAL_ROLE_BY_RECOMMENDED_ROLE for the exact mapping."""

    HERO = "hero"
    SUPPORTING = "supporting"
    CONTEXT = "context"


class ImageProvenance(BaseModel):
    """Where this image actually came from - never fabricated, always traceable back to the
    NewsEvent/NewsSource it was discovered from (services/image_intelligence.py's own M1-M4
    discovery, unmodified)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_name: str | None
    article_url: str | None
    discovery_method: str
    source_relationship: str | None
    news_event_id: UUID


class ArticleVisualImage(BaseModel):
    """One image selected for a TELEGRAPH article - references and small metadata only, never
    image bytes (mirrors services/telegraph_topic_candidates.py's own StoryEvidenceSummary /
    services/telegraph_research_context.py's own ArticleResearchBundle "references + compact
    deterministic metadata" convention)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    image_candidate_record_id: UUID
    source_url: str | None
    final_url: str | None
    provenance: ImageProvenance
    quality_score: int
    relevance_score: int
    role: VisualRole
    width: int | None
    height: int | None
    explanation: str


class ArticleVisualResearchBundle(BaseModel):
    """The complete Visual Research result for one approved TELEGRAPH proposal - computed on
    demand (services/telegraph_visual_research.py::build_visual_research_bundle()), never
    persisted by this checkpoint (see module docstring). `images` is bounded and already role-
    assigned/eligibility-filtered - a caller never needs to re-apply quality/branding/duplicate
    rules itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    story_id: UUID
    images: list[ArticleVisualImage]
    total_candidates_considered: int
    total_rejected: int
