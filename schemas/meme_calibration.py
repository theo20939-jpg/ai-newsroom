"""Meme Opportunity Human Calibration (Phase 18.6): schema for a human-reviewed calibration
dataset comparing the existing, unmodified `services.meme_opportunity.assess_meme_opportunity()`
classifier against human editorial judgement (docs/phase18_6_meme_calibration_report.md).

Deliberately not a database model - mirrors `schemas.meme_shadow_analytics`'s own Phase 18.5
precedent: plain, JSON-serializable Pydantic records written to a committed JSON artifact
(`scripts/phase18_6_calibration_dataset.json`), no migration. Adds ZERO new scoring/threshold/
safety logic of its own - `algorithm_score`/`algorithm_level`/`triggered_signals`/`safety_result`
are read straight from the existing classifier's own already-computed output (via
`services.meme_shadow_analytics.MemeShadowRecord`, Phase 18.5); this schema only adds a place for
a human's own, separately-scaled judgement to sit alongside it.

Unlike `schemas.meme_shadow_analytics.MemeShadowRecord` (which deliberately never carries raw
title/content - a pure analytics record), records here DO carry a short read-only display excerpt
of the real event, by the same design reasoning `docs/phase18_5_human_review_packet.md` already
established: a human reviewer must be able to read the actual story to judge it. This is a human
review packet in JSON form (paired with a markdown rendering of the same data), not an analytics
artifact - the same class of exception Phase 18.5 M4's own report already drew for its own packet.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_CALIBRATION_SCHEMA_VERSION = "v1"


class MemeReviewGroup(str, Enum):
    """The three sampling groups the brief itself defines - a display/grouping label only, never
    a second decision engine. `MEDIUM_CANDIDATE` mirrors `MemeOpportunityDecision.REVIEW`,
    `LOW_RANDOM` mirrors `NOT_SUITABLE`/`INSUFFICIENT_SOURCE`, `SAFETY_BLOCKED` mirrors
    `SENSITIVE_BLOCK` (see `schemas.meme_opportunity.MemeOpportunityDecision`)."""

    MEDIUM_CANDIDATE = "MEDIUM_CANDIDATE"
    LOW_RANDOM = "LOW_RANDOM"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


class MemeCalibrationHumanDecision(str, Enum):
    """The brief's own three-way "Decision" taxonomy for the human review packet."""

    ACCEPT = "ACCEPT"
    WEAK = "WEAK"
    REJECT = "REJECT"


class MemeCalibrationReason(str, Enum):
    """The brief's own fixed, closed "Meme reason" taxonomy - a human may pick more than one."""

    UNEXPECTED_RESULT = "unexpected_result"
    IRONY = "irony"
    CONFLICT = "conflict"
    ABSURDITY = "absurdity"
    COMPANY_DRAMA = "company_drama"
    AI_HYPE = "ai_hype"
    FAILURE_OR_MISTAKE = "failure_or_mistake"
    VISUAL_POTENTIAL = "visual_potential"
    COMMUNITY_REACTION = "community_reaction"
    OTHER = "other"


class MemeCalibrationSafetyOpinion(str, Enum):
    """The brief's own three-way "Safety opinion" taxonomy."""

    SAFE = "safe"
    QUESTIONABLE = "questionable"
    SHOULD_BLOCK = "should_block"


class MemeCalibrationRecord(BaseModel):
    """One calibration item: the existing classifier's already-computed output for one real
    `NewsEvent`, plus a place for a human's own separate judgement. Every `human_*` field is
    genuinely nullable and defaults to a not-yet-reviewed state - never pre-filled with a guess
    (mirrors Phase 18.5 M3's own "не заполнять автоматически" discipline, enforced here at the
    schema level via `None`/empty-list defaults rather than only at the markdown-rendering level).

    `human_score` is the brief's own separate 0-5 "meme potential" scale - deliberately NOT the
    same scale as `algorithm_score` (0-100); comparing them is exactly what `services.
    meme_calibration.score_correlation()` exists to do, not something this schema pre-normalizes
    away."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_CALIBRATION_SCHEMA_VERSION
    event_id: str
    group: MemeReviewGroup

    # --- Event display info (read-only reference for the human reviewer) ---
    title: str
    category: str
    source_name: str | None
    published_at: datetime | None
    content_excerpt: str

    # --- Existing algorithm output (read-only reference, computed by the unmodified Phase 18 M1
    # classifier via services.meme_shadow_analytics.MemeShadowRecord - never re-derived here) ---
    algorithm_score: int = Field(ge=0, le=100)
    algorithm_level: str
    triggered_signals: list[str] = Field(default_factory=list)
    safety_result: list[str] = Field(default_factory=list)

    # --- Human decision fields - genuinely nullable/empty until a human fills them in ---
    human_score: int | None = Field(default=None, ge=0, le=5)
    human_decision: MemeCalibrationHumanDecision | None = None
    reasons: list[MemeCalibrationReason] = Field(default_factory=list)
    safety_review: MemeCalibrationSafetyOpinion | None = None
    notes: str | None = None

    @property
    def is_reviewed(self) -> bool:
        """A record counts as reviewed once a human has recorded a decision - the single
        predicate every metric function in `services.meme_calibration` filters on, so "not yet
        reviewed" items are silently excluded from every computed statistic rather than treated
        as a false negative or a zero score."""
        return self.human_decision is not None


class MemeCalibrationDataset(BaseModel):
    """The full output of one extraction run - a header plus every selected record. Written
    verbatim to `scripts/phase18_6_calibration_dataset.json` by
    `scripts/phase18_6_generate_calibration_packet.py`, and re-read (after a human has filled in
    each record's `human_*` fields in place) by `scripts/phase18_6_calibration_analysis.py`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_CALIBRATION_SCHEMA_VERSION
    generated_at: datetime
    group_a_count: int
    group_b_count: int
    group_c_count: int
    records: list[MemeCalibrationRecord]
