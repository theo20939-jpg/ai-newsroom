"""EventRecapCapability - NINJA PULSE RECAP Phase R2 integration.

Phase A registered this capability (capabilities/registry.py) and mapped it (capabilities/
capability_mapping.py) so an EVENT_RECAP WorkflowDefinition step has a real, importable
implementation to resolve to - still true here (mirrors TELEGRAPH_RESEARCH/TELEGRAPH_ARTICLE's
own dormant-at-registration precedent, workflows/registry.py's own docstring): nothing in this
codebase creates an EVENT_RECAP task yet, no processor/CLI/scheduler exists (Phase B.3+).

A genuinely NEW Capability class - never CopywritingCapability - registered under its own name
("event_recap", mapped to AICapability.INTELLIGENCE in capabilities/capability_mapping.py, the
semantically closest existing value: EVENT_RECAP is an analytical/planning synthesis over an
already-assembled evidence set, not a fresh editorial draft from raw source text the way
"copywriting"/"article_generation" are - mirrors editorial_planning -> INTELLIGENCE's own
precedent, reused rather than adding a new AICapability enum member/migration).

Phase B.1 (deterministic execution plumbing only) established that `capabilities/executor.py`'s
own EVENT_RECAP branch resolves the Story (via `NewsEventStoryLink`) and calls the existing,
unmodified `services.event_recap.build_event_recap_candidate(session, story, force_shadow=True)`
- the one, architecturally-required place this can happen, since `schemas/capability.py`'s own
contract is explicit: "no ORM object crosses into a Capability", and `build_event_recap_candidate`
needs an `AsyncSession` no `Capability.execute()` ever receives.

Phase B.2 (this checkpoint): the executor hook now also threads the FULL, already-built
`EventRecapCandidate` itself into `context.business.event_recap_candidate` (schemas/capability.py
- a plain dataclass, never an ORM row; typed `Any` there specifically to avoid a real circular
import between schemas/capability.py and services/event_recap.py - see that field's own comment).
This class's own `execute()`:
  1. Requires `context.business.event_recap_candidate` to be present - raises
     `CapabilityConfigurationError` otherwise (the same "missing context" contract Phase A/B.1
     already established).
  2. Calls the existing, completely unmodified `services.event_recap.synthesize_event_recap()` -
     never a reimplementation of prompt resolution/request building/fact verification/quality-flag
     detection, all of which stay exactly where they already lived. Passes a small `call_observer`
     callback (services/event_recap.py's own new, purely additive parameter) to capture the real
     `CapabilityCall` `call_generate()` produces internally - `synthesize_event_recap()` itself
     never returns that object, so without this observer `CapabilityResult.calls`/error `calls=`
     could never be populated, and `capabilities/executor.py::CapabilityExecutor._record_cost()`
     (which reads exactly that list, on both the success and error paths) would silently record
     zero cost for a real, paid call.
  3. On `EventRecapSynthesisError` (Gateway failure, or malformed/incomplete structured output -
     services/event_recap.py's own docstring), raises `RetryableCapabilityError` with the captured
     call(s) attached - `WorkflowStepDefinition.max_attempts` (already 3, workflows/definitions/
     event_recap.py) governs the retry budget, exactly like every other Capability; this class does
     not distinguish finer-grained retryable-vs-permanent causes within that one exception type,
     since `call_observer` only ever receives the `CapabilityCall`, never the raw `finish_reason`/
     response (Phase B.2's own deliberately narrow scope).
  4. On success, returns a plain SUCCESS `CapabilityResult` whose `structured_output` is the real
     `recap_title`/`recap_summary`/`key_takeaways`/`uncertainty_notes` contract
     (`EVENT_RECAP_CAPABILITY_DEFINITION.expected_output_keys` matches this exactly again, no
     longer Phase B.1's temporary `event_recap_evidence_preview` shape), with `calls=` populated
     from the observer. `publishable` is never read or set here - it stays unconditionally `False`
     on the `EventRecapCandidate` `synthesize_event_recap()` itself returns (services/event_recap.py's
     own module docstring); this class never constructs/publishes anything from that candidate at
     all, it only reads four plain string/list fields off it into `structured_output`."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from capabilities.errors import CapabilityConfigurationError, RetryableCapabilityError
from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityCall, CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from services.event_recap import EventRecapSynthesisError, synthesize_event_recap

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "event_recap"

EVENT_RECAP_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=120),
    required_context=["news_event"],
    # The real synthesis contract (services/event_recap.py::EventRecapCandidate's own
    # recap_title/recap_summary/key_takeaways/uncertainty_notes fields) - matches this
    # capability's own actual structured_output as of Phase B.2.
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
        started_at = datetime.now(timezone.utc)

        candidate = context.business.event_recap_candidate
        if candidate is None:
            logger.info(
                "event_recap_capability_missing_candidate",
                extra={
                    "capability_name": CAPABILITY_NAME,
                    "news_event_id": str(context.business.news_event.id),
                    "reason": "context.business.event_recap_candidate is None - either "
                              "capabilities/executor.py's own EVENT_RECAP branch did not run for "
                              "this step, or it ran and found nothing to recap.",
                },
            )
            raise CapabilityConfigurationError(
                "event_recap: context.business.event_recap_candidate is missing - no "
                "EventRecapCandidate was threaded into this CapabilityContext (see this module's "
                "own docstring for the capabilities/executor.py hook that is supposed to "
                "populate it).",
            )

        calls: list[CapabilityCall] = []

        try:
            updated = await synthesize_event_recap(
                candidate, self._gateway, self._prompt_repository,
                runtime=context.runtime, call_observer=calls.append,
            )
        except EventRecapSynthesisError as error:
            raise RetryableCapabilityError(str(error), calls=calls) from error

        logger.info(
            "event_recap_capability_synthesis_success",
            extra={
                "capability_name": CAPABILITY_NAME,
                "news_event_id": str(context.business.news_event.id),
                "fact_verification_status": updated.fact_verification.status,
                "quality_flags": updated.quality_flags,
            },
        )
        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={
                "recap_title": updated.recap_title,
                "recap_summary": updated.recap_summary,
                "key_takeaways": updated.key_takeaways,
                "uncertainty_notes": updated.uncertainty_notes,
            },
            calls=calls,
            started_at=started_at, finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )
