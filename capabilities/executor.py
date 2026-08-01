"""CapabilityExecutor: implements workflows.runner.StepExecutor, bridging the
Workflow Engine (Phase 5) to the Capability Framework (Phase 6).

Constructed fresh per (session, task_id, registry), immediately before the
matching WorkflowRunner.run() call, using the same session and task_id -
constructor injection, zero changes to workflows/runner.py, workflows/
registry.py, or schemas/workflow.py (docs/phase6_architecture_contract.md
§5, rule 1).

API cost optimization (docs/api_cost_optimization_report.md §8) deliberately reverses Amendment
B (§16)'s original "CapabilityExecutor MUST NOT persist any AIExecution row" constraint - this
task's own explicit requirement is real, auditable, per-capability cost accounting, which
requires exactly this seam (the one place that already sees every successful CapabilityResult's
`calls`, already holds the real `task_id`/`event_id`/workflow name). `cost_tracker`/
`pricing_catalog` are optional constructor parameters (default `None` = no recording,
byte-for-byte the old behavior) - every existing caller/test that never passes them keeps
working unchanged; only the two real production call sites (worker/analysis_cycle.py,
scripts/run_content_generation.py) pass real ones, from `AIIntegrationLayer.cost_tracker`.
"""
import logging
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from schemas.capability import (
    BusinessContext,
    CapabilityCall,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from schemas.workflow import WorkflowExecutionState, WorkflowStepDefinition, WorkflowType
from capabilities.capability_mapping import resolve_ai_capability
from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityTimeoutError,
    PermanentCapabilityError,
    RetryableCapabilityError,
    UnknownCapabilityError,
    ValidationCapabilityError,
)
from capabilities.registry import CapabilityRegistry
from services.analysis_reuse import (
    REUSABLE_CAPABILITIES,
    find_source_news_analysis_task_id,
    reuse_prior_result,
)
from services.cost_recording import record_ai_execution
from services.cost_tracker import CostTracker
from services.editorial_brief import apply_editorial_brief_shadow
from services.editorial_scoring import apply_editorial_scoring_v2
from services.fact_safety import apply_fact_safety
from services.image_intelligence import run_shadow_discovery
from services.pricing_catalog import PricingCatalog
from workflows.errors import PermanentStepFailureError, StepExecutionError, TaskNotFoundError

logger = logging.getLogger(__name__)

# API cost optimization (docs/api_cost_optimization_report.md §4): centralized per-capability
# output-token ceilings and reasoning effort - one place, not per-capability-file, since every
# capabilities/*_capability.py already reads `context.execution.max_tokens` generically. Values
# are informed by real historical output sizes measured from persisted `WorkflowStepResult.result`
# JSON (never invented) - see the optimization report for the exact evidence and per-capability
# margin reasoning. "none" reasoning effort for Research (deterministic extraction from source
# text, not editorial judgment); "low" for every other capability (real, if modest, editorial
# judgment - significance, tone, factual review, copy).
_MAX_OUTPUT_TOKENS_BY_CAPABILITY: dict[str, int] = {
    "research": 450,
    "intelligence": 500,
    "engagement": 350,
    "scoring": 250,
    "copywriting": 600,
    "quality": 400,
}
_REASONING_EFFORT_BY_CAPABILITY: dict[str, Literal["none", "low", "medium", "high"]] = {
    "research": "none",
    "intelligence": "low",
    "engagement": "low",
    "scoring": "low",
    "copywriting": "low",
    "quality": "low",
}


class CapabilityExecutor:
    """Implements workflows.runner.StepExecutor by dispatching to a registered
    Capability. The only bridge between StepExecutor and the Capability
    Framework - never called directly by a Capability, never calling one
    Capability from another (P4)."""

    def __init__(
        self,
        session: AsyncSession,
        task_id: UUID,
        registry: CapabilityRegistry,
        *,
        cost_tracker: CostTracker | None = None,
        pricing_catalog: PricingCatalog | None = None,
    ) -> None:
        self._session = session
        self._task_id = task_id
        self._registry = registry
        self._cost_tracker = cost_tracker
        self._pricing_catalog = pricing_catalog
        self._attempts: dict[str, int] = {}
        # API cost optimization: memoized per executor instance (one per workflow run) so a
        # CONTENT_GENERATION task's "research" and "intelligence" steps both reuse the exact
        # same source NEWS_ANALYSIS task's evidence, never two different source tasks even in
        # the unlikely event more than one COMPLETED NEWS_ANALYSIS task exists for this event.
        # `False` (not yet looked up) is distinct from `None` (looked up, none found).
        self._source_news_analysis_task_id: UUID | None | Literal[False] = False

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        """Run one Workflow step's capability once and return its structured output.

        Raises StepExecutionError for a retryable failure, PermanentStepFailureError
        for one that must not be retried - never a bare CapabilityError, and
        never persists an AIExecution row (Amendment B, §16).
        """
        attempt = self._attempts.get(step.name, 0) + 1
        self._attempts[step.name] = attempt

        task = await self._session.get(EditorialTask, self._task_id)
        if task is None:
            raise TaskNotFoundError(f"No EditorialTask with id {self._task_id}")
        news_event = await self._session.get(NewsEvent, task.event_id)
        if news_event is None:
            raise PermanentStepFailureError(f"No NewsEvent with id {task.event_id} for task {task.id}")

        # Amendment A (§15): resolve the capability-name -> AICapability mapping
        # through the single centralized table. Not used for persistence here
        # (Phase 6 writes nothing) - validated eagerly so an unmapped capability
        # name fails fast as a configuration error, not silently.
        try:
            resolve_ai_capability(step.capability)
        except CapabilityConfigurationError as error:
            raise PermanentStepFailureError(str(error)) from error

        try:
            _definition, capability = self._registry.resolve(step.capability)
        except UnknownCapabilityError as error:
            raise PermanentStepFailureError(
                f"Cannot resolve capability '{step.capability}': {error}"
            ) from error

        context = self._build_context(task, news_event, step, attempt)

        # API cost optimization (docs/api_cost_optimization_report.md): CONTENT_GENERATION's
        # "research"/"intelligence" steps reuse the same event's already-COMPLETED
        # NEWS_ANALYSIS task's own persisted results instead of paying for an identical call -
        # same NewsEvent, same evidence, so a fresh call would (re)produce equivalent facts.
        # Only attempted for these two capability names, only for CONTENT_GENERATION, only on
        # attempt 1 (a retry always performs a real call - reusing a stale result across a retry
        # would defeat the retry's own purpose). Falls back to a real call (unchanged behavior)
        # whenever no valid prior result exists - never blocks, never raises.
        reused_output = await self._try_reuse(task, step, attempt)
        if reused_output is not None:
            logger.info(
                "capability_result_reused_from_news_analysis",
                extra={"task_id": str(self._task_id), "event_id": str(task.event_id), "capability": step.capability},
            )
            structured_output = reused_output
        else:
            try:
                result = await capability.execute(context)
            except RetryableCapabilityError as error:
                raise StepExecutionError(str(error)) from error
            except CapabilityTimeoutError as error:
                raise StepExecutionError(str(error)) from error
            except (PermanentCapabilityError, ValidationCapabilityError, CapabilityConfigurationError) as error:
                raise PermanentStepFailureError(str(error)) from error

            if result.status != "SUCCESS":
                raise PermanentStepFailureError(
                    f"Capability '{step.capability}' returned status={result.status} "
                    "without raising a CapabilityError - contract violation."
                )

            structured_output = result.structured_output or {}
            await self._record_cost(task, step, result.calls)

        # Phase 15 M4: deterministic Editorial Score V2 post-processing, only for the "scoring"
        # step, only after its own LLM call already succeeded above - see
        # services/editorial_scoring.py's own docstring for why this is the correct seam (it is
        # a no-op, zero-DB-query passthrough unless editorial_scoring_version == "v2").
        if step.capability == "scoring":
            structured_output = await apply_editorial_scoring_v2(
                self._session, news_event, structured_output, task_id=self._task_id
            )

        # Phase 15 M5: deterministic Fact Safety post-processing, only for the "quality" step -
        # the same architectural seam M4 already proved out for "scoring". Zero new DB queries:
        # `news_event` is already loaded above, and Research's completed step_results are already
        # present on `context.business.workflow_state.step_results` (see services/
        # fact_safety.py's own docstring for why this is the safest available boundary). A
        # no-op, zero-processing passthrough unless fact_safety_mode != "off".
        if step.capability == "quality":
            research_output = context.business.workflow_state.step_results.get("research", {})
            copywriting_output = context.business.workflow_state.step_results.get("copywriting", {})
            structured_output = apply_fact_safety(
                news_event.title, news_event.content, news_event.url,
                research_output, copywriting_output, structured_output,
            )

        # Phase 17 M1: deterministic, zero-new-LLM-call Editorial Brief shadow build (docs/
        # phase17_m1_editorial_brief_shadow_report.md) - only for "intelligence" (the earliest
        # step where both Research's facts and Intelligence's own just-computed judgment exist)
        # and only when editorial_brief_mode == "shadow" (default "off", byte-for-byte unchanged
        # behavior). Never read by CopywritingCapability, never changes ContentDraft - mirrors
        # apply_fact_safety's/_attach_image_intelligence's own "must not affect delivery"
        # discipline exactly: any failure here is logged and swallowed, never fails the step.
        if step.capability == "intelligence" and settings.editorial_brief_mode == "shadow":
            structured_output = self._attach_editorial_brief(news_event, context, structured_output)

        # Phase 16 M1: deterministic, zero-download Image Intelligence shadow discovery (docs/
        # phase16_m1_native_media_ingestion_report.md) - only for "copywriting" (the earliest step
        # where the drafted event's persisted content/url are certain to exist) and only when
        # image_intelligence_mode == "shadow" (default "off", byte-for-byte unchanged behavior).
        # Reconstructs candidates from news_event.content/url only - the adapter-time native-media
        # hints from services/collector.py never reach this later, separate worker process (no
        # migration exists to carry them, discovery report §11/§21). Never allowed to fail the
        # step: mirrors apply_fact_safety's own "must not affect delivery" discipline exactly.
        if step.capability == "copywriting" and settings.image_intelligence_mode == "shadow":
            structured_output = await self._attach_image_intelligence(news_event, structured_output)

        return structured_output

    def _attach_editorial_brief(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (Phase 17 M1's own "brief failure must not fail the step,
        must not cause a retry" requirement). Purely synchronous/deterministic - no I/O, so no
        `await` here unlike `_attach_image_intelligence` - but still wrapped in `try/except`
        since `apply_editorial_brief_shadow()`/`build_editorial_brief()` are ordinary Python
        code, not guaranteed exception-free for a genuinely malformed `research`/`intelligence`
        payload. Any failure is logged (`editorial_brief_failed`) and swallowed, returning
        `structured_output` completely unchanged - the same discipline `_attach_image_
        intelligence` already established. No raw news content, secrets, or the full brief text
        are logged - only schema/classification metadata (Phase 17 M1's own observability
        requirement)."""
        logger.info(
            "editorial_brief_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            research_output = context.business.workflow_state.step_results.get("research", {})
            result = apply_editorial_brief_shadow(
                news_event.title, news_event.content, research_output, structured_output,
            )
        except Exception:
            logger.warning(
                "editorial_brief_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        brief = result.get("editorial_brief")
        if isinstance(brief, dict):
            target_range = brief.get("target_word_range") or {}
            logger.info(
                "editorial_brief_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "schema_version": brief.get("schema_version"),
                    "source_sufficiency": brief.get("source_sufficiency"),
                    "recommended_format": brief.get("recommended_format"),
                    "target_min_words": target_range.get("min_words"),
                    "target_max_words": target_range.get("max_words"),
                    "populated_field_count": sum(
                        1 for name in (
                            "headline_fact", "subject_explanation", "event_details",
                            "background_context", "difference_or_change", "why_it_matters",
                            "what_next", "uncertainties",
                        )
                        if brief.get(name)
                    ),
                    "reason_codes": brief.get("source_sufficiency_reason_codes"),
                },
            )
        return result

    async def _attach_image_intelligence(
        self, news_event: NewsEvent, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking. Any failure - including being unable to resolve the event's
        NewsSource - is logged and swallowed, returning `structured_output` completely unchanged
        (copywriting's own fields are never touched, only a new "image_intelligence" key added).

        Phase 16 M2 (docs/phase16_m2_secure_fetch_and_validation_report.md §13): all networking
        (article-page fetch, image-byte fetch) and technical validation lives inside
        `services.image_intelligence.run_shadow_discovery()` - this method only orchestrates the
        one call and preserves its result, exactly as the M2 task brief requires ("The executor
        should only orchestrate the service call and preserve results").

        Phase 16 M5 (docs/phase16_m5_persistence_and_retention_report.md §19): passes this
        executor's own already-open `self._session`/`self._task_id` through so
        `run_shadow_discovery()` can persist - both additive, optional parameters that pre-M5
        callers never pass. Persistence itself is gated inside `run_shadow_discovery()` by
        `image_candidate_persistence_mode` (default "off") - this call site never branches on
        that setting itself, identical in spirit to how M1-M4 never branch on `image_
        intelligence_mode` here beyond the single top-level gate above."""
        try:
            source = await self._session.get(NewsSource, news_event.source_id)
            if source is None:
                return structured_output
            result = await run_shadow_discovery(
                event_id=news_event.id,
                source_type=source.type,
                content=news_event.content,
                article_url=news_event.url,
                mode=settings.image_intelligence_mode,
                event_title=news_event.title,
                source_name=source.name,
                session=self._session,
                editorial_task_id=self._task_id,
            )
            return {**structured_output, "image_intelligence": result.model_dump(mode="json")}
        except Exception:
            logger.warning(
                "image_intelligence_workflow_attach_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

    async def _record_cost(
        self, task: EditorialTask, step: WorkflowStepDefinition, calls: list[CapabilityCall]
    ) -> None:
        """API cost optimization. No-op unless both `cost_tracker` and `pricing_catalog` were
        supplied at construction (every existing test/caller that omits them keeps the old,
        zero-recording behavior). Writes the durable AIExecution row (services.cost_recording)
        and increments the fast Redis ledger BudgetGuard's pre-flight check already reads
        (services.cost_tracker) - both from the exact same CapabilityCall data, never invented."""
        if self._cost_tracker is None or self._pricing_catalog is None:
            return
        state = WorkflowExecutionState.model_validate(task.workflow)
        for call in calls:
            if call.status != "SUCCESS":
                continue
            await record_ai_execution(
                self._session,
                task_id=self._task_id,
                event_id=task.event_id,
                workflow_name=state.workflow_name.value,
                capability_name=step.capability,
                call=call,
                pricing_catalog=self._pricing_catalog,
            )
            await self._cost_tracker.record(self._task_id, step.capability, call)

    async def _try_reuse(
        self, task: EditorialTask, step: WorkflowStepDefinition, attempt: int
    ) -> dict[str, Any] | None:
        """API cost optimization. Returns a reusable prior result, or `None` (meaning: perform
        a real capability call - the unconditional, safe default). Never raises: any lookup
        failure is treated exactly like "no reusable result found"."""
        if step.capability not in REUSABLE_CAPABILITIES or attempt != 1:
            return None
        state = WorkflowExecutionState.model_validate(task.workflow)
        if state.workflow_name != WorkflowType.CONTENT_GENERATION:
            return None

        if self._source_news_analysis_task_id is False:  # not yet looked up this run
            self._source_news_analysis_task_id = await find_source_news_analysis_task_id(
                self._session, task.event_id
            )
        source_task_id = self._source_news_analysis_task_id
        if source_task_id is None:
            return None
        return await reuse_prior_result(self._session, source_task_id, step.capability)

    def _build_context(
        self, task: EditorialTask, news_event: NewsEvent, step: WorkflowStepDefinition, attempt: int
    ) -> CapabilityContext:
        state = WorkflowExecutionState.model_validate(task.workflow)

        news_event_snapshot = NewsEventSnapshot(
            id=news_event.id,
            title=news_event.title,
            summary=news_event.summary,
            content=news_event.content,
            url=news_event.url,
            category=news_event.category.value,
            published_at=news_event.published_at,
        )
        workflow_state_snapshot = WorkflowExecutionStateSnapshot(
            workflow_name=state.workflow_name.value,
            workflow_version=state.workflow_version,
            completed_steps=list(state.completed_steps),
            step_results={
                r.step_name: r.result
                for r in state.step_results
                if r.status == "SUCCESS" and r.result is not None
            },
        )

        return CapabilityContext(
            business=BusinessContext(
                news_event=news_event_snapshot,
                workflow_state=workflow_state_snapshot,
                # Explicit injection (docs/content_generation_language_final_implementation_plan.md)
                # - never left to BusinessContext.language's own implicit schema default.
                language=settings.default_content_language,
            ),
            execution=ExecutionContext(
                max_tokens=_MAX_OUTPUT_TOKENS_BY_CAPABILITY.get(step.capability),
                reasoning_effort=_REASONING_EFFORT_BY_CAPABILITY.get(step.capability),
            ),
            runtime=RuntimeContext(
                task_id=task.id,
                event_id=task.event_id,
                capability_name=step.capability,
                priority=task.priority,
                attempt=attempt,
                iteration_count=state.iteration_count,
            ),
        )
