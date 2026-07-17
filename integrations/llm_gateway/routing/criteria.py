"""RoutingCriteria, RoutingObjective, FallbackEligibility (docs/phase7_architecture_contract.md
§4.1, §5.1). FallbackEligibility is defined here, not in fallback/policy.py, since
RoutingCriteria.fallback references it and routing/ must not depend on fallback/ (avoiding a
circular import once fallback/policy.py lands in M15).
"""
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from database.models.editorial_task import TaskPriority


class RoutingObjective(str, Enum):
    BEST_QUALITY = "best_quality"
    LOWEST_COST = "lowest_cost"
    FASTEST = "fastest"
    REASONING = "reasoning"


class FallbackEligibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_cost_multiplier: Decimal = Decimal("3.0")  # candidate price <= multiplier x cheapest-in-set price
    max_additional_cost: Decimal | None = None  # optional absolute cap - if set, BOTH bounds apply
    allow_cost_ceiling_override_on_exhaustion: bool = False  # opt-in: widen past the bound rather than fail
    max_fallback_attempts: int = 3


class RoutingCriteria(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway_method: Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]
    capability_name: str
    priority: TaskPriority

    requires_tools: bool = False
    requires_vision: bool = False
    requires_streaming: bool = False
    requires_structured_output: bool = False
    input_image_count: int = 0
    input_pdf_page_count: int = 0

    preferred_model: str | None = None
    preferred_provider: str | None = None
    excluded_providers: list[str] = Field(default_factory=list)

    objective: RoutingObjective = RoutingObjective.BEST_QUALITY
    cost_ceiling: Decimal | None = None
    fallback: FallbackEligibility = Field(default_factory=FallbackEligibility)
