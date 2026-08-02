"""Phase 17 rollout policy - M6.1 (docs/phase17_m6_1_production_cutover_readiness_report.md).

A versioned, declarative record of which Phase 17 rollout stage is active and which components
are enabled at that stage - documentation/planning metadata only. Nothing in the codebase reads
this schema to change behavior today; each Phase 17 mode flag (`core/config.py`) remains the
single real, enforced source of truth. This schema exists so a future cutover decision has one
place recording *intended* stage/component state, never an executable switch itself.
"""
from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, ConfigDict, Field

ROLLOUT_POLICY_SCHEMA_VERSION = "v1"


class RolloutStage(IntEnum):
    """Strictly increasing - a later stage is always a superset of an earlier one's enabled
    components (never a lateral move)."""

    STAGE_0_ALL_OFF = 0
    STAGE_1_SHADOW_ASSESSMENT = 1
    STAGE_2_CANDIDATE_NOT_DELIVERED = 2
    STAGE_3_CANARY_LIMITED_DELIVERY = 3
    STAGE_4_BROADER_ROLLOUT = 4
    STAGE_5_RELEVANCE_ENFORCEMENT = 5


class FallbackBehavior(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fail_open: bool  # True = fall back to the stable production Copywriting path on error
    fallback_prompt_version: str
    max_consecutive_fallbacks_before_pause: int = Field(gt=0)


class RolloutPolicy(BaseModel):
    """One declared rollout configuration. `enabled_components` names the Phase 17
    `core.config.settings` mode flags this stage expects to be non-"off" - purely descriptive,
    never applied automatically."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = ROLLOUT_POLICY_SCHEMA_VERSION
    rollout_version: str
    stage: RolloutStage
    enabled_components: list[str] = Field(default_factory=list)
    candidate_percentage: int = Field(ge=0, le=100)
    allowed_scope_description: str  # e.g. "preview chat only" - never a raw chat ID literal here
    fallback: FallbackBehavior
    minimum_confidence: str  # "high" | "medium" | "low" - advisory, not enforced by this schema
    rollback_trigger_thresholds: dict[str, float] = Field(default_factory=dict)
