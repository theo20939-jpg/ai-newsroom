"""EventRecapCapability - NINJA PULSE RECAP Phase R2 integration.

Phase A registered this capability (capabilities/registry.py) and mapped it (capabilities/
capability_mapping.py) so an EVENT_RECAP WorkflowDefinition step has a real, importable
implementation to resolve to - still true here (mirrors TELEGRAPH_RESEARCH/TELEGRAPH_ARTICLE's
own dormant-at-registration precedent, workflows/registry.py's own docstring): nothing in this
codebase creates an EVENT_RECAP task yet, no processor/CLI/scheduler exists (Phase B.2/B.3).

A genuinely NEW Capability class - never CopywritingCapability - registered under its own name
("event_recap", mapped to AICapability.INTELLIGENCE in capabilities/capability_mapping.py, the
semantically closest existing value: EVENT_RECAP is an analytical/planning synthesis over an
already-assembled evidence set, not a fresh editorial draft from raw source text the way
"copywriting"/"article_generation" are - mirrors editorial_planning -> INTELLIGENCE's own
precedent, reused rather than adding a new AICapability enum member/migration).

Phase B.1 (deterministic execution plumbing only): this class still deliberately does NOT call
services.event_recap.build_event_recap_candidate() or synthesize_event_recap() itself, and
services/event_recap.py is not modified anywhere in this checkpoint either. Both existing entry
points require an `AsyncSession` (`build_event_recap_candidate`) and a full `EventRecapCandidate`
dataclass (`synthesize_event_recap`) - neither fits inside a `Capability.execute(context:
CapabilityContext)` call, because `schemas/capability.py`'s own architecture contract is explicit:
"NewsEventSnapshot/WorkflowExecutionStateSnapshot are read-only snapshots built by
capabilities.executor.CapabilityExecutor - never the SQLAlchemy NewsEvent/EditorialTask rows
themselves... no ORM object crosses into a Capability." No DB session of any kind reaches a
Capability's own `execute()` - only `capabilities/executor.py::CapabilityExecutor` (which does
hold a session) is architecturally permitted to resolve a Story/EventRecapCandidate, exactly the
way it already does for `context.business.telegraph_deep_research_output`
(capabilities/executor.py's own TELEGRAPH_ARTICLE-only branch).

What changed in Phase B.1: `capabilities/executor.py` now has that hook - a narrow, EVENT_RECAP-
only branch that resolves the Story (via `NewsEventStoryLink`), calls the existing, unmodified
`services.event_recap.build_event_recap_candidate(session, story, force_shadow=True)`, and renders
its deterministic evidence via the existing, unmodified `render_event_recap_bundle_text()` - the
plain-text result crosses into `CapabilityContext.business.event_recap_evidence_text` (schemas/
capability.py). This class's own `execute()`:
  1. Resolves the exact same prompt `services.event_recap.synthesize_event_recap()` itself would
     resolve (reusing `EVENT_RECAP_PROMPT_NAME`/`EVENT_RECAP_PROMPT_VERSION` directly, never
     redefined here) - proves the prompt-repository wiring is correct end-to-end.
  2. Requires `context.business.event_recap_evidence_text` to be present (non-empty) - raises
     `CapabilityConfigurationError` otherwise (the same "missing context" contract Phase A already
     established, now reachable only when the executor hook genuinely found nothing to recap).
  3. Returns a plain SUCCESS `CapabilityResult` whose `structured_output` is a minimal, explicitly
     diagnostic preview of the deterministic evidence it received (`EVENT_RECAP_CAPABILITY_
     DEFINITION.expected_output_keys` matches this exact temporary shape, not the real
     `recap_title`/`recap_summary`/`key_takeaways`/`uncertainty_notes` synthesis contract - see
     that definition's own comment). It never calls `call_generate()`, never touches
     `self._gateway`, never reaches the LLM Gateway - Phase B.1's own explicit "deterministic
     execution plumbing only" boundary (`synthesize_event_recap()` remains this class's own future
     job, in a later, separately-authorized phase, not this one)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

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
    # Temporary Phase B.1 deterministic-plumbing output shape - matches this capability's own
    # actual execute() return value today (structured_output={"event_recap_evidence_preview":
    # ...}), not the real recap synthesis contract. The real
    # recap_title/recap_summary/key_takeaways/uncertainty_notes shape lands in Phase B.2, once
    # synthesize_event_recap() is actually wired in.
    expected_output_keys=["event_recap_evidence_preview"],
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
        started_at = datetime.now(timezone.utc)

        # Proves the prompt-repository wiring resolves the exact same (name, version)
        # services.event_recap.synthesize_event_recap() itself resolves - reused directly, never
        # redefined here. Phase B.1 does not use the resolved prompt for anything further (no
        # call_generate(), no Gateway) - this call exists purely to prove the wiring end-to-end.
        self._prompt_repository.resolve(EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION)

        evidence_text = context.business.event_recap_evidence_text
        if not evidence_text:
            logger.info(
                "event_recap_capability_missing_evidence",
                extra={
                    "capability_name": CAPABILITY_NAME,
                    "news_event_id": str(context.business.news_event.id),
                    "reason": "context.business.event_recap_evidence_text is None/empty - either "
                              "capabilities/executor.py's own EVENT_RECAP branch did not run for "
                              "this step, or it ran and found nothing to recap.",
                },
            )
            raise CapabilityConfigurationError(
                "event_recap: context.business.event_recap_evidence_text is missing - no "
                "deterministic R2 evidence was threaded into this CapabilityContext (see this "
                "module's own docstring for the capabilities/executor.py hook that is supposed "
                "to populate it).",
            )

        logger.info(
            "event_recap_capability_deterministic_success",
            extra={
                "capability_name": CAPABILITY_NAME,
                "news_event_id": str(context.business.news_event.id),
                "evidence_text_length": len(evidence_text),
            },
        )
        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            # Phase B.1's own temporary, explicitly diagnostic shape - proves the deterministic R2
            # evidence reached this capability intact, NOT the real recap_title/recap_summary/
            # key_takeaways/uncertainty_notes synthesis contract (no synthesize_event_recap() call
            # exists yet - see this module's own docstring).
            structured_output={"event_recap_evidence_preview": evidence_text},
            calls=[],  # zero Gateway calls made - see module docstring
            started_at=started_at, finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )
