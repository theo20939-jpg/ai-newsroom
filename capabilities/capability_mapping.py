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
    # Phase 19 M3: an analytical/planning step, semantically closest to INTELLIGENCE - reused
    # rather than adding a new enum value/migration, exactly mirroring the meme_concept ->
    # CREATIVE reuse decision above.
    "editorial_planning": AICapability.INTELLIGENCE,
    # Phase 19 M13: a review/validation step, semantically closest to QUALITY - reused rather
    # than adding a new enum value/migration, mirroring the editorial_planning -> INTELLIGENCE
    # reuse decision above.
    "media_vision_review": AICapability.QUALITY,
    # TELEGRAPH Checkpoint 5: a genuinely new Capability (never CopywritingCapability reused -
    # see capabilities/article_generation_capability.py's own docstring for why), mapped to the
    # semantically closest existing value rather than adding a new enum/migration - it IS writing
    # copy, just long-form and TELEGRAPH-scoped, mirroring editorial_planning -> INTELLIGENCE's
    # own precedent exactly.
    "article_generation": AICapability.COPYWRITING,
    # NINJA PULSE RECAP Phase R2 integration, Phase A: an analytical/planning synthesis over an
    # already-assembled evidence set (services/event_recap.py), never a fresh editorial draft from
    # raw source text - semantically closest to INTELLIGENCE, mirroring editorial_planning ->
    # INTELLIGENCE's own precedent exactly, reused rather than adding a new enum value/migration.
    "event_recap": AICapability.INTELLIGENCE,
    # Phase I.1 (Approved EVENT_RECAP -> Final Post Authoring Core): a genuinely new Capability
    # (never CopywritingCapability/EventRecapCapability - see capabilities/
    # final_post_authoring_capability.py's own docstring for why), mapped to the semantically
    # closest existing value rather than adding a new enum/migration - it IS writing publish-ready
    # public copy from an already-approved source (unlike "event_recap"'s own internal-review-only
    # synthesis), mirroring "article_generation" -> COPYWRITING's own precedent exactly ("it IS
    # writing copy, just long-form/RECAP-authoring-scoped").
    "final_post_authoring": AICapability.COPYWRITING,
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
