"""CandidateFactSafetyAudit - Phase 17 M4 (docs/phase17_m4_beginner_friendly_copywriting_report.md).

A deterministic second-pass audit over one generated candidate's title/body - never a new LLM
call. See `services/candidate_fact_safety.py` for the builder; this module only defines the shape.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

CANDIDATE_FACT_SAFETY_SCHEMA_VERSION = "v1"


class FactSafetyStatus(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


class AuditSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CandidateFactSafetyAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = CANDIDATE_FACT_SAFETY_SCHEMA_VERSION
    status: FactSafetyStatus
    supported_claim_count: int = Field(ge=0)
    unsupported_claim_flags: list[str] = Field(default_factory=list)
    numeric_flags: list[str] = Field(default_factory=list)
    entity_flags: list[str] = Field(default_factory=list)
    causal_flags: list[str] = Field(default_factory=list)
    definition_flags: list[str] = Field(default_factory=list)
    severity: AuditSeverity | None = None
    reason_codes: list[str] = Field(default_factory=list)
