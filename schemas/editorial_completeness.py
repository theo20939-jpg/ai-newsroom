"""EditorialCompletenessAssessment - Phase 17 M5 (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

A deterministic, versioned shadow assessment of whether a *finished* draft (production baseline
or a saved M3/M4/M4.1 candidate) covers what its own upstream plans (`EditorialBrief`,
`AdaptiveLengthPlan`, `BeginnerFriendlyPlan`) said was available and required - never a new LLM
call, never a general quality/readability score. See `services/editorial_completeness.py` for the
deterministic builder; this module only defines the shape.

Deliberately a SEPARATE dimension from Fact Safety (`schemas/calibrated_fact_safety.py`), Channel
Relevance (`schemas/article_relevance.py`), and Style/Readability - this schema never folds those
into one opaque score (M5's own explicit "не смешивай" requirement). `editorial_recommendation`
is the only cross-cutting field, and it is always explainable back to the individual `criteria`
list plus the separate, passed-in Fact Safety status - never computed from hidden state.

Shadow-only: computed and persisted into `EditorialTask.workflow`'s existing
`step_results["quality"]` JSON blob for later analysis - never read by any Capability, never
changes `ContentDraft`, never blocks a task.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from schemas.editorial_brief import SourceSufficiency

EDITORIAL_COMPLETENESS_SCHEMA_VERSION = "v1"
EDITORIAL_COMPLETENESS_POLICY_VERSION = "v1"


class CriterionStatus(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class CompletenessConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DraftKind(str, Enum):
    """Which text is being assessed - never inferred, always passed in explicitly by the caller,
    so the gate can never accidentally score a candidate as if it were the real delivered draft
    or vice versa."""

    PRODUCTION_BASELINE = "production_baseline"
    SHADOW_CANDIDATE = "shadow_candidate"
    UNKNOWN = "unknown"


class HeadlineRewriteRisk(str, Enum):
    """M0's own disclosed gap (docs/phase17_m0_output_quality_discovery_report.md §6): the old
    vocabulary-overlap-only proxy measured 0.0% (0/269) against a real manual-audit rate of
    18.75-21.9% - word overlap alone cannot distinguish "the same fact reworded" from "the same
    fact plus something new." `services/editorial_completeness.py::assess_headline_rewrite_risk()`
    fixes this by counting genuinely NEW claims (numeric/date/entity, reusing
    `services.fact_safety.extract_claims`) and editorial-framing signals (uncertainty/why-it-
    matters/gap disclosure) the body adds beyond the headline - never vocabulary overlap alone."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_APPLICABLE = "not_applicable"


class SafeLengthStatus(str, Enum):
    WITHIN_RANGE = "within_range"
    BELOW_RANGE = "below_range"
    ABOVE_RANGE = "above_range"
    NOT_APPLICABLE = "not_applicable"


class ParagraphStatus(str, Enum):
    ADEQUATE = "adequate"
    WEAK = "weak"
    NOT_APPLICABLE = "not_applicable"


class EditorialRecommendation(str, Enum):
    READY = "READY"
    REVIEW = "REVIEW"
    NOT_READY = "NOT_READY"
    INSUFFICIENT_SOURCE = "INSUFFICIENT_SOURCE"


class CompletenessCriterionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: str
    status: CriterionStatus
    score: float = Field(ge=0.0, le=1.0)
    required: bool
    evidence_available: bool
    matched_evidence: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    confidence: CompletenessConfidence


class EditorialCompletenessAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = EDITORIAL_COMPLETENESS_SCHEMA_VERSION
    policy_version: str = EDITORIAL_COMPLETENESS_POLICY_VERSION

    draft_kind: DraftKind
    source_sufficiency: SourceSufficiency

    criteria: list[CompletenessCriterionResult] = Field(default_factory=list)
    required_criteria_count: int = Field(ge=0)
    passed_required_count: int = Field(ge=0)
    partial_required_count: int = Field(ge=0)
    failed_required_count: int = Field(ge=0)

    completeness_score: float = Field(ge=0.0, le=1.0)
    confidence: CompletenessConfidence

    headline_rewrite_risk: HeadlineRewriteRisk
    safe_length_status: SafeLengthStatus
    paragraph_status: ParagraphStatus

    editorial_recommendation: EditorialRecommendation
    reason_codes: list[str] = Field(default_factory=list)
