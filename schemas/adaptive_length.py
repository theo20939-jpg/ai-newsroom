"""AdaptiveLengthPlan - Phase 17 M3 (docs/phase17_m3_adaptive_length_shadow_comparison_report.md).

A deterministic, versioned length/structure plan for one NewsEvent, built from `EditorialBrief`
(Phase 17 M1) and, when available, real Image Intelligence candidate data (Phase 16) - never a
free-form word-count guess. See `services/adaptive_length.py` for the builder; this module only
defines the shape.

Shadow/comparison-only in M3: `recommended_format`/`min_words`/`target_words`/`max_words` are
*computed and persisted* for later analysis - `CopywritingCapability`'s real production prompt
never reads this plan, `ContentDraft` is never touched by it (see the module docstring of
`services/adaptive_length.py` for the full production-safety discipline).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.editorial_brief import RecommendedFormat, SourceSufficiency

ADAPTIVE_LENGTH_SCHEMA_VERSION = "v1"
ADAPTIVE_LENGTH_POLICY_VERSION = "v1"


class Complexity(str, Enum):
    """Deterministic story-complexity bucket - never inferred from raw source length alone
    (services/adaptive_length.py::determine_complexity()'s own explicit rule, mirroring Phase 17
    M0's "long text is not automatically quality" finding)."""

    SIMPLE = "simple"
    NORMAL = "normal"
    COMPLEX = "complex"
    FOLLOW_UP = "follow_up"
    INSUFFICIENT = "insufficient"


class DeliveryMode(str, Enum):
    """What the eventual Telegram send would actually be - determines which character budget
    (`hard_character_limit`) applies. `UNKNOWN` when Image Intelligence has not run yet or is
    off (`image_intelligence_mode != "shadow"`) - never guessed."""

    PHOTO_CAPTION = "photo_caption"
    TEXT_MESSAGE = "text_message"
    UNKNOWN = "unknown"


class PlanSection(str, Enum):
    """A closed, small editorial-structure vocabulary - never a rigid per-post template
    (M3's own "natural editorial structure, not a mechanical checklist" instruction)."""

    HEADLINE = "headline"
    LEAD = "lead"
    SUBJECT_EXPLANATION = "subject_explanation"
    EVENT_DETAILS = "event_details"
    BACKGROUND_CONTEXT = "background_context"
    WHY_IT_MATTERS = "why_it_matters"
    WHAT_NEXT = "what_next"
    UNCERTAINTY_NOTE = "uncertainty_note"


class LengthConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AdaptiveLengthPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = ADAPTIVE_LENGTH_SCHEMA_VERSION
    policy_version: str = ADAPTIVE_LENGTH_POLICY_VERSION

    recommended_format: RecommendedFormat
    complexity: Complexity
    source_sufficiency: SourceSufficiency

    min_words: int = Field(ge=0)
    target_words: int = Field(ge=0)
    max_words: int = Field(ge=0)
    hard_character_limit: int = Field(gt=0)
    delivery_mode: DeliveryMode

    paragraph_target: int = Field(ge=1)
    detail_target: int = Field(ge=0)

    required_sections: list[PlanSection] = Field(default_factory=list)
    optional_sections: list[PlanSection] = Field(default_factory=list)
    omitted_sections: list[PlanSection] = Field(default_factory=list)

    reason_codes: list[str] = Field(default_factory=list)
    confidence: LengthConfidence
    safety_constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_word_range_ordering(self) -> "AdaptiveLengthPlan":
        if not (self.min_words <= self.target_words <= self.max_words):
            raise ValueError(
                f"word range must satisfy min <= target <= max, got "
                f"min={self.min_words} target={self.target_words} max={self.max_words}"
            )
        return self
