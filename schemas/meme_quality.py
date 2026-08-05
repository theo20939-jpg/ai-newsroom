"""MemeQualityAssessment (Phase 18 M7): the single pre-preview gate combining every upstream
signal (M1 opportunity, M3 safety/originality, M6 render contrast/safe-zone, plus M7's own
factual-alignment/clarity/brand-fit checks) into one decision (docs/
phase18_m7_meme_quality_gate_report.md).

Mirrors `schemas/meme_safety.py`'s own established shape: frozen, versioned, zero LLM/network/DB
dependency in the schema itself.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_QUALITY_SCHEMA_VERSION = "v1"


class MemeQualityDecision(str, Enum):
    """Exactly the brief's own five-way M7 decision set."""

    READY_FOR_EDITOR = "READY_FOR_EDITOR"
    REVIEW = "REVIEW"
    REGENERATE_CONCEPT = "REGENERATE_CONCEPT"
    REGENERATE_IMAGE = "REGENERATE_IMAGE"
    REJECT = "REJECT"


class MemeQualityChecks(BaseModel):
    """One boolean per brief-listed dimension - `True` means "passed," never "not applicable"
    (a dimension this milestone cannot evaluate at all, e.g. true "brand fit" without a defined
    brand voice document, is deliberately still attempted at a coarse level rather than always
    reporting `True` by default - see services/meme_quality.py's own docstring for exactly what
    each check does and does not verify)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factual_alignment: bool
    punchline_clarity: bool
    readability: bool
    originality: bool
    brand_fit: bool
    meme_safety: bool
    visual_quality: bool
    mobile_friendliness: bool


class MemeQualityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_QUALITY_SCHEMA_VERSION
    policy_version: str
    decision: MemeQualityDecision
    checks: MemeQualityChecks
    reason_codes: list[str] = Field(default_factory=list)
