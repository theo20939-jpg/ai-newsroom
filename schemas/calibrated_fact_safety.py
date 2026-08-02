"""CalibratedFactSafetyAssessment - Phase 17 M5 (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

A calibration layer over the existing, unmodified `CandidateFactSafetyAudit`
(`schemas/candidate_fact_safety.py`, Phase 17 M4) - never a replacement, never a rewrite of the
raw audit itself. `services/fact_safety_calibration.py::calibrate_fact_safety()` re-reads the raw
audit's own flag strings and suppresses a small, explicit, named set of known false-positive
classes (Russian inflection, quoted titles, company-legal suffixes, hedge/uncertainty language,
confirmed what-next synthesis, definition/regex-fragment mismatches) - every suppression carries
its own reason code (`schemas/fact_safety_calibration_reason_codes` convention, see the service
module), so a flag is never silently dropped. Deliberately conservative: a flag not matched by a
named suppression rule is always kept as `unresolved_flags`, never assumed safe.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from schemas.candidate_fact_safety import AuditSeverity, FactSafetyStatus

CALIBRATED_FACT_SAFETY_SCHEMA_VERSION = "v1"
CALIBRATED_FACT_SAFETY_POLICY_VERSION = "v1"


class SuppressedFlag(BaseModel):
    """One raw-audit flag the calibration layer decided is a known false positive - always paired
    with the specific, named rule that suppressed it (never a bare boolean)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    flag: str
    reason_code: str


class CalibratedFactSafetyAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = CALIBRATED_FACT_SAFETY_SCHEMA_VERSION
    policy_version: str = CALIBRATED_FACT_SAFETY_POLICY_VERSION

    raw_audit_status: FactSafetyStatus
    calibrated_status: FactSafetyStatus

    true_positive_flags: list[str] = Field(default_factory=list)
    suppressed_false_positive_flags: list[SuppressedFlag] = Field(default_factory=list)
    unresolved_flags: list[str] = Field(default_factory=list)

    severity: AuditSeverity | None = None
    reason_codes: list[str] = Field(default_factory=list)
    human_review_required: bool
