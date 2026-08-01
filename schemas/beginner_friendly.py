"""BeginnerFriendlyPlan - Phase 17 M4 (docs/phase17_m4_beginner_friendly_copywriting_report.md).

A deterministic, versioned plan for how much explanation a candidate post may safely add, and
how much length that explanation realistically supports - built from `EditorialBrief` (M1) and
`AdaptiveLengthPlan` (M3). See `services/beginner_friendly.py` for the builder; this module only
defines the shape.

Shadow/comparison-only in M4: never changes production `CopywritingCapability`'s prompt or
`ContentDraft` - see `services/beginner_friendly.py`'s own module docstring for the full
production-safety discipline.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

BEGINNER_FRIENDLY_SCHEMA_VERSION = "v1"
BEGINNER_FRIENDLY_POLICY_VERSION = "v1"


class AudienceLevel(str, Enum):
    GENERAL = "general"
    TECH_INTERESTED = "tech_interested"
    SPECIALIST = "specialist"


class JargonRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExplanationProvenance(str, Enum):
    """Where an explanation's own content is allowed to come from - never "the model's general
    knowledge" as an unlabeled default (M4's own explicit fabrication ban)."""

    SOURCE_TITLE = "source_title"
    SOURCE_CONTENT = "source_content"
    RESEARCH_OUTPUT = "research_output"
    INTELLIGENCE_OUTPUT = "intelligence_output"
    EDITORIAL_BRIEF = "editorial_brief"
    DETERMINISTIC_DEFINITION = "deterministic_definition"
    UNKNOWN = "unknown"


class WordRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_words: int = Field(ge=0)
    target_words: int = Field(ge=0)
    max_words: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_ordering(self) -> "WordRange":
        if not (self.min_words <= self.target_words <= self.max_words):
            raise ValueError(
                f"word range must satisfy min <= target <= max, got "
                f"min={self.min_words} target={self.target_words} max={self.max_words}"
            )
        return self


class BeginnerFriendlyPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = BEGINNER_FRIENDLY_SCHEMA_VERSION
    policy_version: str = BEGINNER_FRIENDLY_POLICY_VERSION

    audience_level: AudienceLevel
    explanation_required: bool

    subjects_to_explain: list[str] = Field(default_factory=list)
    terms_to_explain: list[str] = Field(default_factory=list)
    assumed_knowledge: list[str] = Field(default_factory=list)
    unexplainable_terms: list[str] = Field(default_factory=list)

    explanation_budget: int = Field(ge=0)
    context_budget: int = Field(ge=0)
    detail_target: int = Field(ge=0)
    paragraph_target: int = Field(ge=1)

    why_it_matters_required: bool
    what_next_allowed: bool
    uncertainty_required: bool
    jargon_risk: JargonRisk

    ideal_range: WordRange
    safe_range: WordRange

    reason_codes: list[str] = Field(default_factory=list)
    evidence_constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_safe_within_ideal_ceiling(self) -> "BeginnerFriendlyPlan":
        if self.safe_range.max_words > self.ideal_range.max_words:
            raise ValueError(
                "safe_range must never exceed ideal_range's own ceiling - safe is a constrained "
                f"subset, got safe_max={self.safe_range.max_words} > ideal_max={self.ideal_range.max_words}"
            )
        return self
