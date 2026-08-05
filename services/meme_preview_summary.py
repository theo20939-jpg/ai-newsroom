"""Short, editor-facing summary builders for the Telegram meme preview (Phase 18 M8, docs/
phase18_m8_telegram_editorial_preview_report.md). Pure functions, no I/O - turn M3's/M7's own
structured assessments into one short line each, never the full raw JSON (mirrors
`bot/formatting.py`'s own "editorial card, not a technical readout" discipline).
"""
from __future__ import annotations

from schemas.meme_quality import MemeQualityAssessment
from schemas.meme_safety import MemeSafetyOriginalityGateResult


def build_safety_summary(gate: MemeSafetyOriginalityGateResult) -> str:
    parts = [f"Safety: {gate.safety.decision.value}", f"Originality: {gate.originality.decision.value}"]
    if gate.safety.sensitivity_categories:
        parts.append(f"Flags: {', '.join(gate.safety.sensitivity_categories)}")
    return " | ".join(parts)


def build_quality_summary(assessment: MemeQualityAssessment) -> str:
    failed_checks = [name for name, passed in assessment.checks.model_dump().items() if not passed]
    if not failed_checks:
        return f"Quality: {assessment.decision.value} (all checks passed)"
    return f"Quality: {assessment.decision.value} (failed: {', '.join(failed_checks)})"
