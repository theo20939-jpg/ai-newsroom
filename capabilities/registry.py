"""CapabilityRegistry: resolves a capability name to its registered
(CapabilityDefinition, Capability) pair.

Identical shape to workflows.registry.WorkflowRegistry: mutable via
register() only until seal() is called, after which register() raises
CapabilityRegistryAlreadySealedError. No dynamic discovery (docs/
phase6_architecture_contract.md §6, §9/P9).

Phase 6/7 shipped no concrete Capability implementation (Research/Intelligence/
etc. remained future work) - build_registry() returned an empty, sealed
registry, exactly mirroring how WorkflowType.DAILY_DIGEST is declared but
never registered in Phase 5. Phase 8 M4 registers the first one: see
build_registry()'s own docstring below.

M19 (docs/phase7_architecture_contract.md §19 rule 2): build_registry() gains the
injected-dependency signature the frozen contract specifies -
`build_registry(gateway, prompt_repository, budget_guard, tool_registry) -> CapabilityRegistry`,
"the sole boot-sequence entry point that constructs every Capability with its dependencies
injected." All four parameters are accepted and type-checked here, matching the contract
exactly, but none is threaded anywhere yet: this milestone still ships an empty, sealed
registry (no concrete Capability exists to inject them into). Note the same real-but-harmless
inconsistency §19 rule 2's own text carries forward from before Amendment C (§25) was appended:
`budget_guard` appears in this signature, yet Amendment C explicitly forbids a `Capability`
from ever holding or calling `BudgetGuard` directly. Amendment C never edits §19 rule 2's text
(§26's append-only discipline forbids in-place edits to prior sections), so resolving whether
a future concrete Capability actually receives `budget_guard` - almost certainly it must not,
per Amendment C - is deferred to whichever future milestone builds the first real Capability;
nothing here decides it. The previous, zero-argument `build_registry()` had a module-level
`registry = build_registry()` singleton (constructed at import time); that singleton is removed
in this milestone since the new signature cannot be satisfied at import time without
constructing a real Gateway/PromptRepository/BudgetGuard as a side effect of merely importing
this module - callers now go through `integrations.llm_gateway.boot.assemble_ai_integration_
layer()` instead, exactly as the contract's fixed boot order (§19 rule 3) specifies.
"""
import logging
from typing import Protocol

from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityDefinition
from capabilities.errors import (
    CapabilityRegistryAlreadySealedError,
    DuplicateCapabilityRegistrationError,
    UnknownCapabilityError,
)
from integrations.llm_gateway.protocol import LLMGateway
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.protocol import PromptRepository
from services.budget_guard import BudgetGuard

from capabilities.article_generation_capability import (
    ARTICLE_GENERATION_CAPABILITY_DEFINITION,
    ArticleGenerationCapability,
)
from capabilities.copywriting_capability import COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability
from capabilities.editorial_planning_capability import (
    EDITORIAL_PLANNING_CAPABILITY_DEFINITION,
    EditorialPlanningCapability,
)
from capabilities.media_vision_review_capability import (
    MEDIA_VISION_REVIEW_CAPABILITY_DEFINITION,
    MediaVisionReviewCapability,
)
from capabilities.media_subject_match_capability import (
    MEDIA_SUBJECT_MATCH_CAPABILITY_DEFINITION,
    MediaSubjectMatchCapability,
)
from capabilities.engagement_capability import ENGAGEMENT_CAPABILITY_DEFINITION, EngagementCapability
from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
from capabilities.final_post_authoring_capability import (
    FINAL_POST_AUTHORING_CAPABILITY_DEFINITION,
    FinalPostAuthoringCapability,
)
from capabilities.intelligence_capability import INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability
from capabilities.meme_concept_capability import MEME_CONCEPT_CAPABILITY_DEFINITION, MemeConceptCapability
from capabilities.meme_copywriting_capability import (
    MEME_COPYWRITING_CAPABILITY_DEFINITION,
    MemeCopywritingCapability,
)
from capabilities.quality_capability import QUALITY_CAPABILITY_DEFINITION, QualityCapability
from capabilities.research_capability import RESEARCH_CAPABILITY_DEFINITION, ResearchCapability
from capabilities.scoring_capability import SCORING_CAPABILITY_DEFINITION, ScoringCapability

logger = logging.getLogger(__name__)


class Capability(Protocol):
    """One AI-capability module. See P3/P4. Never calls a provider SDK.
    Never calls another Capability. Communicates only through CapabilityContext
    (in) and CapabilityResult (out)."""

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        """Run once. Raises only CapabilityError subtypes - never a bare Exception."""
        ...


class CapabilityRegistry:
    """Resolves a capability name to its registered, immutable
    (CapabilityDefinition, Capability) pair."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._capabilities: dict[str, Capability] = {}
        self._sealed = False

    def register(self, definition: CapabilityDefinition, capability: Capability) -> None:
        """Register one (CapabilityDefinition, Capability) pair.

        Raises CapabilityRegistryAlreadySealedError if the registry has been
        sealed, or DuplicateCapabilityRegistrationError if `definition.name`
        is already registered - regardless of `definition.version`.
        """
        if self._sealed:
            raise CapabilityRegistryAlreadySealedError(
                f"Cannot register '{definition.name}' version {definition.version}: "
                "this CapabilityRegistry is sealed and accepts no further registrations."
            )
        if definition.name in self._definitions:
            existing = self._definitions[definition.name]
            raise DuplicateCapabilityRegistrationError(
                f"Capability '{definition.name}' is already registered "
                f"(version {existing.version}); cannot register version {definition.version} again."
            )
        self._definitions[definition.name] = definition
        self._capabilities[definition.name] = capability
        logger.info("Registered capability %s version %d", definition.name, definition.version)

    def seal(self) -> None:
        """Permanently stop accepting further register() calls."""
        self._sealed = True

    def resolve(self, name: str) -> tuple[CapabilityDefinition, Capability]:
        """Return the registered (CapabilityDefinition, Capability) pair for `name`.

        Raises UnknownCapabilityError if unregistered. Read-only regardless of
        seal state - resolve() works identically before and after sealing.
        """
        definition = self._definitions.get(name)
        capability = self._capabilities.get(name)
        if definition is None or capability is None:
            raise UnknownCapabilityError(f"No Capability registered for name '{name}'")
        return definition, capability


def build_registry(
    gateway: LLMGateway,
    prompt_repository: PromptRepository,
    budget_guard: BudgetGuard,
    tool_registry: ToolRegistry,
) -> CapabilityRegistry:
    """Build and seal the CapabilityRegistry (docs/phase7_architecture_contract.md §19 rule 2,
    docs/phase8_capability_contract.md §5.1).

    The sole boot-sequence entry point that constructs every Capability with its dependencies
    injected. Phase 8 M4 registers the first one - ScoringCapability, constructed with only
    `gateway` and `prompt_repository` (contract §4.2/§5.3): `budget_guard` and `tool_registry`
    continue to be accepted, type-checked, and passed to nothing (§5.3, §18 rule 19 -
    unchanged by this milestone; this module's own docstring explains why `budget_guard`
    remains in this signature at all despite Amendment C forbidding any Capability from ever
    holding or calling BudgetGuard directly).
    """
    registry = CapabilityRegistry()
    registry.register(SCORING_CAPABILITY_DEFINITION, ScoringCapability(gateway, prompt_repository))
    registry.register(QUALITY_CAPABILITY_DEFINITION, QualityCapability(gateway, prompt_repository))
    registry.register(RESEARCH_CAPABILITY_DEFINITION, ResearchCapability(gateway, prompt_repository))
    registry.register(INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability(gateway, prompt_repository))
    registry.register(COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(gateway, prompt_repository))
    registry.register(ENGAGEMENT_CAPABILITY_DEFINITION, EngagementCapability(gateway, prompt_repository))
    # Phase 19 M3: registered like every other capability (real, resolvable, cost-tracked via
    # capability_mapping.py's "editorial_planning" -> AICapability.INTELLIGENCE entry) even
    # though no live WorkflowDefinition step references it yet - exactly mirroring the
    # meme_concept/meme_copywriting precedent immediately below. The only caller of its real,
    # LLM-backed execute() in this phase is the manually-invoked comparison script
    # (scripts/phase19_m3_editorial_plan_comparison.py) - the live CONTENT_GENERATION path's own
    # "shadow" behavior never reaches this Capability at all (see
    # capabilities/executor.py::_attach_editorial_plan()).
    registry.register(EDITORIAL_PLANNING_CAPABILITY_DEFINITION, EditorialPlanningCapability(gateway, prompt_repository))
    # Phase 19 M13: registered like every other capability (real, resolvable, cost-tracked via
    # capability_mapping.py's "media_vision_review" -> AICapability.QUALITY entry) even though no
    # live WorkflowDefinition step references it - same "meme_concept"/"editorial_planning"
    # precedent. The only caller of its real, LLM-backed execute() is the manually-invoked,
    # never-auto-run harness script (scripts/phase19_m13_vision_review_manual.py) - there is no
    # scheduled/automatic live-worker path to this capability at all.
    registry.register(MEDIA_VISION_REVIEW_CAPABILITY_DEFINITION, MediaVisionReviewCapability(gateway, prompt_repository))
    # CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1: registered like every other capability (real,
    # resolvable, cost-tracked via capability_mapping.py's "media_subject_match" -> AICapability.
    # QUALITY entry) even though no live WorkflowDefinition step references it - mirrors
    # media_vision_review's own identical dormant-registration precedent exactly. The only caller
    # of its real, LLM-backed execute() is the manually-invoked, never-auto-run harness script
    # (scripts/_cross_platform_media_research_canary_1.py) - no scheduled/automatic live-worker
    # path reaches it.
    registry.register(MEDIA_SUBJECT_MATCH_CAPABILITY_DEFINITION, MediaSubjectMatchCapability(gateway, prompt_repository))
    # Phase 18 M2: registered like every other capability (real, resolvable, cost-tracked via
    # capability_mapping.py's "meme_concept" -> AICapability.CREATIVE entry) even though no
    # WorkflowDefinition references it yet - WorkflowType.MEME_GENERATION itself stays
    # unregistered in WorkflowRegistry until enough steps exist for a coherent run (docs/
    # phase18_m0_meme_discovery_report.md §4.3), exactly mirroring how CONTENT_GENERATION's own
    # "copywriting" capability could in principle have been registered before Phase 10 M2
    # registered the workflow that actually uses it.
    registry.register(MEME_CONCEPT_CAPABILITY_DEFINITION, MemeConceptCapability(gateway, prompt_repository))
    # Phase 18 M4: registered alongside meme_concept, same rationale (real, resolvable,
    # cost-tracked via "meme_copywriting" -> AICapability.COPYWRITING).
    registry.register(MEME_COPYWRITING_CAPABILITY_DEFINITION, MemeCopywritingCapability(gateway, prompt_repository))
    # TELEGRAPH Checkpoint 5: registered like every other capability (real, resolvable, cost-
    # tracked via capability_mapping.py's "article_generation" -> AICapability.COPYWRITING
    # entry) even though no live/automatic path calls it - services.telegraph_article_processor.
    # generate_article_for_researched_proposal() is the only caller, and nothing calls that
    # automatically, mirroring meme_concept/editorial_planning's own precedent exactly.
    registry.register(ARTICLE_GENERATION_CAPABILITY_DEFINITION, ArticleGenerationCapability(gateway, prompt_repository))
    # NINJA PULSE RECAP Phase R2 integration, Phase A: registered like every other capability
    # (real, resolvable, cost-tracked via capability_mapping.py's "event_recap" ->
    # AICapability.INTELLIGENCE entry) even though no live/automatic path calls it, and its own
    # execute() cannot reach the LLM Gateway yet (capabilities/event_recap_capability.py's own
    # docstring) - mirrors article_generation/meme_concept's own dormant-registration precedent.
    registry.register(EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability(gateway, prompt_repository))
    # Phase I.1 (Approved EVENT_RECAP -> Final Post Authoring Core): registered like every other
    # capability (real, resolvable, cost-tracked via capability_mapping.py's "final_post_authoring"
    # -> AICapability.COPYWRITING entry) even though no live/automatic path calls it -
    # services.final_post_processor.generate_final_post_for_review() is the only caller, and
    # nothing calls that automatically, mirroring article_generation/event_recap's own identical
    # dormant-registration precedent.
    registry.register(
        FINAL_POST_AUTHORING_CAPABILITY_DEFINITION, FinalPostAuthoringCapability(gateway, prompt_repository),
    )
    registry.seal()
    return registry
