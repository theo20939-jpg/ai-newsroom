"""ChannelProfile - Phase 17 M2 (docs/phase17_m2_channel_topic_relevance_shadow_report.md).

An explicit, versioned, data-only description of one Telegram channel's editorial topic policy -
never hardcoded inside `services/channel_relevance.py`'s classifier logic (M2's own explicit
instruction). Concrete instances live in `services/channel_profiles.py`.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from schemas.topic_taxonomy import ArticleTopic

CHANNEL_PROFILE_SCHEMA_VERSION = "v1"


class ChannelProfile(BaseModel):
    """`required_relationships` is a short list of named, classifier-recognized rule identifiers
    (e.g. `"conditional_topic_requires_tech_centrality"`) - not a free-form DSL. The classifier
    documents, in its own module docstring, exactly which rule names it understands; an unlisted
    name is simply inert (recorded, never silently invented into behavior)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str
    schema_version: str = CHANNEL_PROFILE_SCHEMA_VERSION
    display_name: str

    primary_topics: list[ArticleTopic] = Field(default_factory=list)
    secondary_topics: list[ArticleTopic] = Field(default_factory=list)
    allowed_adjacent_topics: list[ArticleTopic] = Field(default_factory=list)
    excluded_topics: list[ArticleTopic] = Field(default_factory=list)
    conditional_topics: list[ArticleTopic] = Field(default_factory=list)
    required_relationships: list[str] = Field(default_factory=list)

    language: str
    audience: str
    editorial_notes: str | None = None
