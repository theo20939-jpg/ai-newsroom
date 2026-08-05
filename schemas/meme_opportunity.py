"""MemeOpportunityAssessment (Phase 18 M1): deterministic, shadow-only classification of whether
a NewsEvent is worth attempting a meme for at all (docs/phase18_m0_meme_discovery_report.md §6,
docs/phase18_m1_meme_opportunity_report.md).

Mirrors schemas/article_relevance.py's/schemas/editorial_brief.py's own established shape: a
frozen, versioned Pydantic contract for a purely deterministic classifier
(services/meme_opportunity.py) - zero LLM calls, zero network calls, zero DB writes. Attached
additively under a single "meme_opportunity" key on CONTENT_GENERATION's "quality" step output,
exactly like Phase 17 M2's "channel_relevance"/M5's "editorial_completeness" keys - never read by
any Capability, never changes ContentDraft.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_OPPORTUNITY_SCHEMA_VERSION = "v1"


class MemeOpportunityDecision(str, Enum):
    """The five-way taxonomy fixed by docs/phase18_m0_meme_discovery_report.md §6 - adopts
    INSUFFICIENT_SOURCE (the label M1's own task brief names as a decision outcome) over the
    M0-section's differently-named INSUFFICIENT_CONTEXT; see that report's §6 for the disclosed
    discrepancy."""

    MEME_READY = "MEME_READY"
    REVIEW = "REVIEW"
    NOT_SUITABLE = "NOT_SUITABLE"
    SENSITIVE_BLOCK = "SENSITIVE_BLOCK"
    INSUFFICIENT_SOURCE = "INSUFFICIENT_SOURCE"


class MemeOpportunitySignals(BaseModel):
    """Every component score is 0-100, independently computed, independently inspectable
    (`evidence` on the parent assessment traces each back to matched phrases) - never a single
    opaque number. `composite_score` is the documented weighted combination
    (services/meme_opportunity.py::_COMPOSITE_WEIGHTS), not a separate signal of its own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    irony_contrast_score: int = Field(ge=0, le=100)
    audience_relatability_score: int = Field(ge=0, le=100)
    visual_potential_score: int = Field(ge=0, le=100)
    topic_fit_score: int = Field(ge=0, le=100)
    freshness_score: int = Field(ge=0, le=100)
    composite_score: int = Field(ge=0, le=100)


class MemeOpportunityAssessment(BaseModel):
    """The complete, additive output attached to CONTENT_GENERATION's "quality" step structured
    output when `meme_opportunity_mode == "shadow"`. Never blocks, never mutates anything else -
    a shadow recommendation only (mirrors ChannelFitAssessment's own "REJECT is only ever a
    persisted shadow recommendation" discipline)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_OPPORTUNITY_SCHEMA_VERSION
    policy_version: str
    decision: MemeOpportunityDecision
    signals: MemeOpportunitySignals
    # Category names from services.meme_opportunity's own sensitivity lexicon - empty unless
    # decision == SENSITIVE_BLOCK (the sensitivity scan is a hard, evidence-only short-circuit).
    sensitivity_categories: list[str] = Field(default_factory=list)
    # services.editorial_brief.SourceSufficiency's own .value - reused directly, never
    # reclassified independently (docs/phase18_m0_meme_discovery_report.md §3.5).
    source_sufficiency: str
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
