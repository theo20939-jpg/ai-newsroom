"""Single centralized mapping from a Workflow step's `capability` name to its
`AICapability` enum value (docs/phase6_architecture_contract.md §10; Amendment A resolved by
Phase 18.10 M9, docs/phase18_10_editorial_intelligence_report.md).

This is the single place a Workflow step's capability name is mapped to its persistence-target
`AICapability` enum value. No adapter, CapabilityExecutor, or Capability implementation may
hardcode this mapping independently - every lookup MUST go through resolve_ai_capability() below.

History: from Phase 6 through Phase 18.9, "engagement" was aliased to AICapability.INTELLIGENCE
here as a temporary persistence stopgap, because the AICapability enum had no ENGAGEMENT value.
Phase 18.9's live test quantified the real cost of that gap (a real capability's spend silently
mislabeled), and Phase 18.10 M9 resolved it: AICapability.ENGAGEMENT now exists
(database/migrations/versions/8b9d649bc69b_*), and "engagement" maps to it directly below. The
Redis cost ledger (services/cost_tracker.py) was never affected by this alias - it always used
the raw capability-name string - so this change only corrects the Postgres label; total spend was
always accurate.
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
    "engagement": AICapability.ENGAGEMENT,
    # Phase 18 M2 (docs/phase18_m0_meme_discovery_report.md §4.3): CREATIVE has existed in
    # AICapability, unused, since before this phase - reused here rather than adding a new enum
    # value/migration, exactly as the M0 report's architecture decision recorded.
    "meme_concept": AICapability.CREATIVE,
    # Phase 18 M4: a real copywriting call (top/bottom text, caption, alt text) - maps to the
    # existing COPYWRITING value, not CREATIVE, since that is semantically what this step does
    # (docs/phase18_m4_meme_copywriting_report.md).
    "meme_copywriting": AICapability.COPYWRITING,
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
