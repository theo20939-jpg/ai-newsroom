"""Meme Intelligence Calibration Update (Phase 18.7): schemas for the v2 calibration layer over
the existing, unmodified M1 (`services.meme_opportunity.assess_meme_opportunity`) and M3
(`services.meme_opportunity.detect_sensitive_categories`, reused by `services.meme_safety`)
classifiers (docs/phase18_7_calibration_results.md).

Deliberately not a rewrite of `schemas.meme_opportunity`/`schemas.meme_safety` - both remain
untouched. These are new, additive "v2" result shapes produced by `services.
meme_calibration_rules`, each wrapping an unmodified v1 result and recording exactly what the
calibration layer changed and why, so a v2 decision is always traceable back to its v1 origin.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from schemas.meme_opportunity import MemeOpportunityDecision

MEME_CALIBRATION_RULES_SCHEMA_VERSION = "v1"

# Policy version identifiers - the brief's own explicit "M1 rules version v1 -> v2" / "M3 safety
# rules v1 -> v2" requirement. `services.meme_opportunity.POLICY_VERSION`/`services.meme_safety.
# POLICY_VERSION` remain "v1" and unchanged (those modules are never edited); these are the
# separate, additive calibration layer's own version identifiers.
MEME_OPPORTUNITY_CALIBRATION_POLICY_VERSION = "v2"
MEME_SAFETY_CALIBRATION_POLICY_VERSION = "v2"


class MemeOpportunityAssessmentV2(BaseModel):
    """The v2 calibration result for one M1 assessment. Always traces back to the exact v1
    outcome it was computed from (`base_decision`/`base_composite_score`) - never presented
    without that provenance. `decision`/`adjusted_composite_score` are only ever recomputed when
    `base_decision` is neither `SENSITIVE_BLOCK` nor `INSUFFICIENT_SOURCE` (those two v1
    short-circuits are never overridden by calibration - mirrors v1's own "hard rejection wins
    regardless" precedence, applied here to the calibration layer too)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_CALIBRATION_RULES_SCHEMA_VERSION
    policy_version: str = MEME_OPPORTUNITY_CALIBRATION_POLICY_VERSION
    base_decision: MemeOpportunityDecision
    base_composite_score: int = Field(ge=0, le=100)
    decision: MemeOpportunityDecision
    adjusted_composite_score: int = Field(ge=0, le=100)
    calibration_score_delta: int
    calibration_evidence: list[str] = Field(default_factory=list)


class SafetyContextExceptionResultV2(BaseModel):
    """The v2 calibration result for one sensitivity scan (`services.meme_opportunity.
    detect_sensitive_categories()`'s own output, filtered). `categories`/`evidence` are the v1
    result minus every phrase match that a context exception exempted; `suppressed_evidence`
    lists exactly what was exempted and why, so a false-positive fix is always auditable, never a
    silent change. An exemption is never applied when an `override_marker` (a real-world-violence
    indicator) is also present in the same text - Finding 4's own "remain conservative"
    requirement, enforced structurally here, not just by convention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_CALIBRATION_RULES_SCHEMA_VERSION
    policy_version: str = MEME_SAFETY_CALIBRATION_POLICY_VERSION
    base_categories: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    suppressed_evidence: list[str] = Field(default_factory=list)
