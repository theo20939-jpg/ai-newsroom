"""CapabilityDefinition/CapabilityConfig (Phase 6).

Mirrors WorkflowDefinition/WorkflowStepDefinition deliberately, for
consistency with the already-approved Phase 5 pattern (see
docs/phase6_architecture_contract.md §2). Registered once, at process start,
in capabilities.registry.CapabilityRegistry.
"""
from pydantic import BaseModel, ConfigDict, Field


class CapabilityConfig(BaseModel):
    """The tunable, non-identity part of a CapabilityDefinition. Provider-agnostic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: int = Field(ge=1)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: float = Field(default=0, ge=0)
    preferred_model: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    allow_stream: bool = False
    allow_tools: bool = False


class CapabilityDefinition(BaseModel):
    """The static, versioned declaration of a capability's identity and constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: int = Field(ge=1)
    config: CapabilityConfig
    required_context: list[str]
    expected_output_keys: list[str]
