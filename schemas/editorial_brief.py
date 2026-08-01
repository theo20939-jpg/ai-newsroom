"""EditorialBrief - Phase 17 M1 (docs/phase17_m1_editorial_brief_shadow_report.md).

A structured editorial plan built *before* Copywriting, from data already available at the
"intelligence" workflow step - `NewsEventSnapshot` (title/content/summary/url/category) plus
Research's `facts`/`gaps` and Intelligence's own `significance`/`angle`/`recommendation`. See
`services/editorial_brief.py` for the deterministic builder that populates this schema; this
module only defines the shape.

Shadow-only in M1 (docs/phase17_m0_output_quality_discovery_report.md §14/§18): computed and
persisted into `EditorialTask.workflow`'s existing `step_results["intelligence"]` JSON blob for
later M2-M6 analysis - `CopywritingCapability` never reads it, `ContentDraft` is never touched.

Every content-bearing field is deterministic, built only from evidence already on the
CapabilityContext - no field is ever filled by asking an LLM to draw on pretrained world
knowledge (`subject_explanation`/`background_context` structurally require that and are always
left `None`/empty in M1 - see `services/editorial_brief.py` module docstring for the full
LLM/cost-boundary rationale). `evidence_notes` records, per field, whether its value is
`confirmed` (directly present in NewsEvent/Research/Intelligence), `inferred` (derived by a
documented deterministic rule), `unknown` (looked for, not found), or `unavailable` (this
field structurally cannot be filled without a new LLM call in M1) - never a free-text
justification that could duplicate large amounts of source text.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EDITORIAL_BRIEF_SCHEMA_VERSION = "v1"


class SourceSufficiency(str, Enum):
    """Deterministic classification of how much real material the source gives Copywriting to
    work with - see `services/editorial_brief.py::classify_source_sufficiency()`. Never inferred
    from raw text length alone (docs/phase17_m0_output_quality_discovery_report.md §10's own
    "long text is not automatically quality" warning)."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    HEADLINE_ONLY = "headline_only"
    EMPTY = "empty"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class RecommendedFormat(str, Enum):
    """Shadow-only recommendation in M1 - never read by Copywriting, never blocks a task.
    `reject_candidate` reflects source-material insufficiency only, never channel/topic fit
    (that is M2's job - docs/phase17_m0_output_quality_discovery_report.md §11's own explicit
    "must not conflate" warning). `follow_up` is defined for schema completeness but is
    structurally unreachable in M1: it requires `difference_or_change`, which needs storyline
    memory that does not exist until M7+."""

    SHORT_UPDATE = "short_update"
    STANDARD_NEWS = "standard_news"
    EXPLAINER = "explainer"
    FOLLOW_UP = "follow_up"
    INSUFFICIENT_SOURCE = "insufficient_source"
    REJECT_CANDIDATE = "reject_candidate"


class FieldConfidence(str, Enum):
    """Per-field provenance tag (Fact Safety discipline, §17 of the M0 report): a field is never
    allowed to look as authoritative as directly-sourced text when it isn't."""

    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


EvidenceSource = Literal["news_event", "research", "intelligence", "derived", "none"]


class TargetWordRange(BaseModel):
    """Structured, not a free-form string - `max_words` is always `>= min_words`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_words: int = Field(ge=0)
    max_words: int = Field(ge=0)


class FieldProvenance(BaseModel):
    """Where one EditorialBrief field's value came from - never the full source text, only a
    confidence tag, a coarse source label, and short machine-readable reason codes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: FieldConfidence
    source: EvidenceSource
    reason_codes: list[str] = Field(default_factory=list)


class EditorialBrief(BaseModel):
    """The complete, versioned editorial plan for one NewsEvent. Every list/dict field uses
    `default_factory` - no mutable default is ever shared across instances."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = EDITORIAL_BRIEF_SCHEMA_VERSION

    headline_fact: str | None = None
    subject_explanation: str | None = None
    event_details: list[str] = Field(default_factory=list)
    background_context: list[str] = Field(default_factory=list)
    difference_or_change: str | None = None
    why_it_matters: list[str] = Field(default_factory=list)
    what_next: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    recommended_format: RecommendedFormat
    target_word_range: TargetWordRange

    source_sufficiency: SourceSufficiency
    source_sufficiency_reason_codes: list[str] = Field(default_factory=list)

    evidence_notes: dict[str, FieldProvenance] = Field(default_factory=dict)
