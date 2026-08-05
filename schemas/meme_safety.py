"""MemeSafetyOriginalityGateResult (Phase 18 M3): deterministic, shadow-only safety and
originality review of a generated `MemeConcept` (docs/phase18_m0_meme_discovery_report.md §4.3,
docs/phase18_m3_meme_safety_originality_report.md).

Two independent sub-assessments (Safety, Originality - the brief's own M3 structure), combined
into one gate decision. Mirrors `schemas/meme_opportunity.py`'s own established shape: frozen,
versioned, zero LLM/network/DB dependency in the schema itself.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_SAFETY_SCHEMA_VERSION = "v1"


class MemeGateDecision(str, Enum):
    """Shared three-way outcome for both the safety and originality sub-assessments, and for the
    combined gate. `BLOCK` on either sub-assessment always makes the combined decision `BLOCK`
    (mirrors `services.fact_safety`'s own "hard rejection wins regardless" precedence) -
    never a shadow-only recommendation that quietly downgrades a block to a review."""

    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class MemeSafetyAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: MemeGateDecision
    sensitivity_categories: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class MemeOriginalityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: MemeGateDecision
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class MemeSafetyOriginalityGateResult(BaseModel):
    """The complete, additive output attached to MEME_GENERATION's "meme_concept" step structured
    output when `meme_safety_gate_mode == "shadow"`. `gate_decision` is always the worse of
    `safety.decision`/`originality.decision` (BLOCK > REVIEW > PASS) - never computed
    independently, so it can never silently disagree with either sub-assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_SAFETY_SCHEMA_VERSION
    policy_version: str
    gate_decision: MemeGateDecision
    safety: MemeSafetyAssessment
    originality: MemeOriginalityAssessment
