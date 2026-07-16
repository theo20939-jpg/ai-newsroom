"""Single centralized mapping from a Workflow step's `capability` name to its
`AICapability` enum value (docs/phase6_architecture_contract.md §10, Amendment A).

This is the ONLY place the `"engagement" -> AICapability.INTELLIGENCE` alias
may be written. No adapter, CapabilityExecutor, or Capability implementation
may hardcode this mapping independently - every lookup MUST go through
resolve_ai_capability() below.

The alias is a temporary persistence stopgap only, not a redefinition of
Engagement as Intelligence - it exists solely because the current, already-
migrated AICapability enum has no ENGAGEMENT value. It MUST be reconsidered
before any real Engagement Capability is implemented (Amendment A, §15).
"""
from database.models.ai_execution import AICapability
from capabilities.errors import CapabilityConfigurationError

_CAPABILITY_NAME_TO_AI_CAPABILITY: dict[str, AICapability] = {
    "research": AICapability.RESEARCH,
    "intelligence": AICapability.INTELLIGENCE,
    "trend": AICapability.TREND,
    "scoring": AICapability.SCORING,
    "copywriting": AICapability.COPYWRITING,
    "creative": AICapability.CREATIVE,
    "quality": AICapability.QUALITY,
    # Amendment A: temporary persistence alias only - see module docstring.
    "engagement": AICapability.INTELLIGENCE,
}


def resolve_ai_capability(capability_name: str) -> AICapability:
    """Resolve a Workflow step's `capability` name to its AICapability enum value.

    Raises CapabilityConfigurationError if no mapping exists - this is a
    configuration bug (a capability was registered/used without a
    corresponding persistence-target mapping), never a retryable failure.
    """
    mapped = _CAPABILITY_NAME_TO_AI_CAPABILITY.get(capability_name)
    if mapped is None:
        raise CapabilityConfigurationError(
            f"No AICapability mapping exists for capability name '{capability_name}'. "
            "Add it to capabilities.capability_mapping._CAPABILITY_NAME_TO_AI_CAPABILITY."
        )
    return mapped
