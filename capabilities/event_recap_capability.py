"""EventRecapCapability - NINJA PULSE RECAP Phase R2 integration, Phase A: dormant registration
only. This capability is registered (capabilities/registry.py) and mapped (capabilities/
capability_mapping.py) so an EVENT_RECAP WorkflowDefinition step has a real, importable
implementation to resolve to - but nothing in this codebase creates an EVENT_RECAP task yet
(mirrors TELEGRAPH_RESEARCH/TELEGRAPH_ARTICLE's own dormant-at-registration precedent, workflows/
registry.py's own docstring).

A genuinely NEW Capability class - never CopywritingCapability - registered under its own name
("event_recap", mapped to AICapability.INTELLIGENCE in capabilities/capability_mapping.py, the
semantically closest existing value: EVENT_RECAP is an analytical/planning synthesis over an
already-assembled evidence set, not a fresh editorial draft from raw source text the way
"copywriting"/"article_generation" are - mirrors editorial_planning -> INTELLIGENCE's own
precedent, reused rather than adding a new AICapability enum member/migration).

Deliberately does NOT call services.event_recap.build_event_recap_candidate() or
synthesize_event_recap() itself, and services/event_recap.py is not modified anywhere in this
checkpoint. Both existing entry points require an `AsyncSession` (`build_event_recap_candidate`)
and a full `EventRecapCandidate` dataclass (`synthesize_event_recap`) - neither fits inside a
`Capability.execute(context: CapabilityContext)` call, because `schemas/capability.py`'s own
architecture contract is explicit: "NewsEventSnapshot/WorkflowExecutionStateSnapshot are read-only
snapshots built by capabilities.executor.CapabilityExecutor - never the SQLAlchemy NewsEvent/
EditorialTask rows themselves... no ORM object crosses into a Capability." No DB session of any
kind reaches a Capability's own `execute()` - only `capabilities/executor.py::CapabilityExecutor`
(which does hold a session) is architecturally permitted to resolve a Story/EventRecapCandidate
and thread a plain-data snapshot into `CapabilityContext.business`, exactly the way it already
does for `context.business.telegraph_deep_research_output` (capabilities/executor.py's own
TELEGRAPH_ARTICLE-only branch).

This checkpoint's own explicit scope is registration only (schemas/workflow.py, workflows/
definitions/event_recap.py, workflows/registry.py, capabilities/registry.py, capabilities/
capability_mapping.py) - it does NOT add that `capabilities/executor.py` hook. Until a future,
separately-authorized step adds it (Phase B), this Capability has no real Story data to act on:
`execute()` "prepares the call" as far as it honestly can - it resolves the exact same prompt
`services.event_recap.synthesize_event_recap()` itself resolves (reusing `services.event_recap.
EVENT_RECAP_PROMPT_NAME`/`EVENT_RECAP_PROMPT_VERSION` directly, never redefining them - proving
the prompt-repository wiring is correct end-to-end) and then raises `CapabilityConfigurationError`
(maps to `workflows.errors.PermanentStepFailureError` - never retried) rather than fabricating a
result or silently returning an empty one. It never reaches the LLM Gateway - structurally
impossible for this capability to make a paid call before that missing-context guard fires. This
is not a placeholder bug; it is Phase A's own explicit boundary, made structural rather than left
as a docstring promise, mirroring `ArticleGenerationCapability`'s own established `Capability`
Protocol shape and error-handling discipline otherwise (see that class's own docstring)."""
from __future__ import annotations

import logging

from capabilities.errors import CapabilityConfigurationError
from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "event_recap"

EVENT_RECAP_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=120),
    required_context=["news_event"],
    expected_output_keys=["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
)


class EventRecapCapability:
    """Implements the `Capability` Protocol. Holds only `LLMGateway`/`PromptRepository` - no
    `BudgetGuard`, no `CostTracker`, no `AsyncSession` (mirrors every other Capability's own §4.2
    constraint, and the "no ORM object crosses into a Capability" rule this class's own module
    docstring documents in full)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        # Proves the prompt-repository wiring resolves the exact same (name, version)
        # services.event_recap.synthesize_event_recap() itself resolves - reused directly, never
        # redefined here. This is the full extent of what this capability can "prepare" without a
        # DB session (see module docstring) - it never reaches call_generate()/the LLM Gateway.
        self._prompt_repository.resolve(EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION)

        logger.info(
            "event_recap_capability_not_yet_wired",
            extra={
                "capability_name": CAPABILITY_NAME,
                "news_event_id": str(context.business.news_event.id),
                "reason": "Phase A dormant registration only - no capabilities/executor.py hook "
                          "exists yet to resolve a Story/EventRecapCandidate for this event_id.",
            },
        )
        raise CapabilityConfigurationError(
            "event_recap: no Story/EventRecapCandidate available in CapabilityContext yet - "
            "Phase A registers this capability but does not wire capabilities/executor.py to "
            "resolve one (see this module's own docstring). This capability cannot run for real "
            "until that future, separately-authorized step lands.",
        )
