"""Meme Shadow Analytics (Phase 18.5): normalized records for a read-only, offline audit of the
existing `services.meme_opportunity.assess_meme_opportunity()` classifier against real,
already-persisted `NewsEvent` rows (docs/phase18_5_meme_shadow_validation_discovery.md).

Deliberately not a database model - this phase's own discovery (§5) evaluated and rejected both
`EditorialTask.workflow` JSON and a new table; records are plain, JSON-serializable Pydantic
models written to a local artifact file, mirroring every prior Phase 15/17/18 shadow-validation
exercise's own established convention.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_SHADOW_RECORD_SCHEMA_VERSION = "v1"


class MemeOpportunityLabel(str, Enum):
    """Human-friendly relabeling of `schemas.meme_opportunity.MemeOpportunityDecision` for this
    phase's own reporting vocabulary (brief's own "HIGH/MEDIUM/LOW/BLOCKED" terms) - a display
    mapping only, never a second decision engine. See `services.meme_shadow_analytics.
    LABEL_BY_DECISION` for the exact, single source of truth for this mapping."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    BLOCKED = "BLOCKED"


class MemeShadowRecord(BaseModel):
    """One normalized shadow-collection record for one real `NewsEvent`, produced by
    `services.meme_shadow_analytics.build_shadow_record()`. Never contains the event's full
    title/content text - only identifying/classification metadata - matching every Phase 17/18
    shadow hook's own "no raw content in persisted/logged artifacts" discipline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_SHADOW_RECORD_SCHEMA_VERSION
    event_id: str
    category: str
    source_name: str | None
    opportunity_decision: str
    opportunity_label: MemeOpportunityLabel
    composite_score: int = Field(ge=0, le=100)
    reason_codes: list[str] = Field(default_factory=list)
    sensitivity_categories: list[str] = Field(default_factory=list)
    evidence_patterns: list[str] = Field(default_factory=list)
    source_sufficiency: str
    collected_at: datetime


class MemeHumanReviewDecision(str, Enum):
    """Phase 18.5 M2's own "false positive tracking foundation" requirement: a real, versioned
    taxonomy a human reviewer will use in M3's packet - not yet populated anywhere (M3's packet
    leaves every `human_decision` field genuinely blank; M2 only prepares the schema itself).
    Mirrors `schemas.meme_feedback.MemeRejectionReason`'s own established "small, closed,
    brief-specified taxonomy" shape from Phase 18 M9."""

    GOOD_MEME_CANDIDATE = "good_meme_candidate"
    WEAK_CANDIDATE = "weak_candidate"
    NOT_A_MEME = "not_a_meme"
    UNSAFE = "unsafe"


class MemeShadowCollectionResult(BaseModel):
    """The full output of one collection run - a header plus every record. Written verbatim to
    `scripts/_phase18_5_shadow_collection_results.json` by the collection script."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_SHADOW_RECORD_SCHEMA_VERSION
    collected_at: datetime
    events_scanned: int
    records: list[MemeShadowRecord]
