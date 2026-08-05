"""Meme human-feedback taxonomy (Phase 18 M9, docs/phase18_m9_human_feedback_report.md).

Exactly the brief's own M9 reason list - a rejection reason is always one of these eight values,
never free text alone (free-form context still has a place: `MemeCandidate.editor_decision_notes`,
optional, alongside the structured reason(s), never instead of them).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class MemeRejectionReason(str, Enum):
    NOT_FUNNY = "not_funny"
    UNCLEAR = "unclear"
    FACTUAL_RISK = "factual_risk"
    BAD_IMAGE = "bad_image"
    OFF_BRAND = "off_brand"
    TOO_TOXIC = "too_toxic"
    STALE = "stale"
    DUPLICATE_IDEA = "duplicate_idea"


class MemeFeedbackSummary(BaseModel):
    """A read-only report view of one `MemeCandidate` row's full human-feedback/cost state -
    built by `services/meme_candidate_service.py::build_feedback_summary()` from an already-loaded
    ORM row, never queried independently. Intended for a future reporting/analytics script
    (docs/phase18_m9_human_feedback_report.md §4) - not read by any Capability, never affects
    delivery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    status: str
    editor_decision: str | None
    editor_decision_reasons: list[str]
    editor_decision_notes: str | None
    concept_regeneration_count: int
    copy_regeneration_count: int
    image_regeneration_count: int
    cumulative_cost_usd: str
    published: bool
