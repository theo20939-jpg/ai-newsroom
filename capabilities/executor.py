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
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from database.models.news_source import NewsSource
from services.article_cleaning import clean_extracted_text
from schemas.beginner_friendly import BeginnerFriendlyPlan
from services.editorial_plan_persistence import persist_shadow_plan
from services.editorial_planning_deterministic import build_deterministic_plan
from services.source_intelligence import classify_source_role
from services.source_intelligence_persistence import persist_source_intelligence
from services.story_context import build_story_timeline
from services.story_context_persistence import persist_story_context_snapshot
from services.telegraph_research_context import build_article_research_bundle, render_bundle_text
from services.telegraph_visual_research import build_visual_research_bundle, render_visual_bundle_summary
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
from services.evidence_package import build_evidence_package
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
from services.adaptive_length import apply_adaptive_length_shadow
from services.beginner_friendly import apply_beginner_friendly_shadow
from services.candidate_fact_safety import evaluate_candidate_fact_safety
from services.channel_relevance import apply_channel_relevance_shadow
from services.cost_recording import record_ai_execution
from services.cost_tracker import CostTracker
from services.editorial_brief import apply_editorial_brief_shadow
from services.editorial_completeness import apply_editorial_completeness_shadow
from services.editorial_scoring import apply_editorial_scoring_v2
from services.fact_safety import apply_fact_safety
from services.fact_safety_calibration import calibrate_fact_safety
from services.image_intelligence import run_shadow_discovery
from services.meme_opportunity import apply_meme_opportunity_shadow
from services.meme_safety import apply_meme_safety_originality_shadow
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
    # Production forensics round 1: 333/333 failed NEWS_ANALYSIS Research tasks (314 arXiv) hit
    # the original 450 ceiling exactly (finish_reason="length") before completing their
    # structured JSON - FAILED input content (avg 1801.6 chars) was ~3.3x COMPLETED (avg 550.8
    # chars). Raised 450 -> 700.
    # Production forensics round 2 (second canary): 700 was still insufficient for some real
    # long-form input - task d3fe7076-e075-4003-9c26-f138bf741063 (content_chars=1897) truncated
    # on all 3 attempts at 700; a direct diagnostic against the same task at 1000 succeeded with
    # meaningful headroom (output_tokens=732, finish_reason="stop"). Raised 700 -> 1000, the
    # smallest change consistent with this new evidence; no other capability's ceiling touched.
    "research": 1000,
    "intelligence": 500,
    "engagement": 350,
    "scoring": 250,
    "copywriting": 600,
    "quality": 400,
    # TELEGRAPH Checkpoint 5: its own capability name (never overloads "research"/"copywriting" -
    # see capabilities/article_generation_capability.py's own docstring), so a plain dict entry
    # is sufficient here, unlike deep_research's own distinct-override need in _build_context()
    # below (that one DOES overload the shared "research" name). A full long-form article is a
    # materially larger structured output than any NEWS capability produces - reasoned starting
    # point, not fit to any real output-size data yet.
    "article_generation": 6000,
}
_REASONING_EFFORT_BY_CAPABILITY: dict[str, Literal["none", "low", "medium", "high"]] = {
    "research": "none",
    "intelligence": "low",
    "engagement": "low",
    "scoring": "low",
    "copywriting": "low",
    "quality": "low",
    # TELEGRAPH Checkpoint 5: real editorial-style judgment (structuring a long-form article from
    # research evidence), closer to "copywriting" than to plain "research" extraction.
    "article_generation": "medium",
}

# TELEGRAPH Checkpoint 3: reasoned starting points for the "deep_research" step only (see
# _build_context()'s own comment on why this can't live in the two dicts above, which are keyed
# by capability name and shared with NEWS_ANALYSIS/CONTENT_GENERATION's own "research" step).
# Not fit to any real output-size data yet - matches this codebase's own established
# "reasoned default, refine later" convention (e.g. article_acquisition_reuse_window_hours).
# "medium" reasoning effort (vs. plain "research"'s "none"): this step synthesizes/deepens
# already-extracted evidence rather than performing flat extraction - real, if bounded,
# editorial-style judgment, closer to "intelligence"/"copywriting" than to "research" itself.
_TELEGRAPH_DEEP_RESEARCH_MAX_OUTPUT_TOKENS = 4000
_TELEGRAPH_DEEP_RESEARCH_REASONING_EFFORT: Literal["none", "low", "medium", "high"] = "medium"


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

        # Phase 19 M1/M2: only the "research" step ever reads full-article evidence (Contract §8
        # - Research is the sole factual-extraction seam); a DB query here for every other step
        # would be pure waste. Only attempted when article_acquisition_mode == "enforce" - byte-
        # identical to today whenever it is "off"/"shadow". Wrapped in try/except: setting
        # "enforce" before the Phase 19 M1 migration has been applied must degrade to the
        # rss_excerpt fallback (byte-identical to "off"), never crash the step - mirrors
        # services/story_memory.py's own established "caller catches the missing-table case"
        # convention (tests/test_triage_orchestrator_story_memory.py::
        # test_shadow_mode_without_migration_degrades_gracefully_not_crash).
        evidence_text: str | None = None
        evidence_completeness: str | None = None
        if step.capability == "research" and settings.article_acquisition_mode == "enforce":
            try:
                # SAVEPOINT (begin_nested), not the outer transaction - a failure here (e.g. the
                # migration not yet applied) must only unwind this one attempt, never invalidate
                # `task`/`news_event`, already loaded above and read again later in this method.
                async with self._session.begin_nested():
                    evidence = await build_evidence_package(self._session, news_event)
                evidence_text = evidence.selected_editorial_text
                evidence_completeness = evidence.completeness_level
            except Exception:
                logger.warning(
                    "article_evidence_package_unavailable_falling_back",
                    extra={"task_id": str(task.id), "event_id": str(task.event_id)},
                )

        # Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md): quote-sourcing root-
        # cause fix. Copywriting's OWN quote excerpt (capabilities/copywriting_capability.py::
        # _format_quote_source_excerpt()) previously read only `news_event.content` - the thin
        # RSS-teaser field - even when a far richer full article was already acquired for real
        # under article_acquisition_mode=shadow (confirmed directly: the real Research Gold story,
        # Phase 23.1O, had a 130-char news_event.content with zero quotes vs. an 11,289-char
        # acquired article containing several genuinely useful ones). Deliberately NOT
        # build_evidence_package() (that call above is enforce-gated and, separately, its own
        # `cleaned_text`-required branch never fires in this environment since the cleaning step
        # does not populate that column here - confirmed directly) - a narrow, direct read of the
        # already-acquired `raw_extracted_text`, cleaned on the fly with the already-existing,
        # zero-cost `services/article_cleaning.py::clean_extracted_text()` (never a new capability,
        # never an LLM call). Scoped to "copywriting" only - Research/Intelligence/`article_
        # evidence_text`'s own enforce gate above are completely untouched. `!= "off"` (not
        # enforce-only) since this reads already-persisted shadow-mode data for a narrower,
        # lower-stakes purpose (quote-sourcing only, still verified against source text before use -
        # services/quote_verification.py - never "additional facts").
        quote_source_text: str | None = None
        if step.capability == "copywriting" and settings.article_acquisition_mode != "off":
            try:
                async with self._session.begin_nested():
                    acquisition = await self._session.get(NewsEventArticleAcquisition, task.event_id)
                    if (
                        acquisition is not None
                        and acquisition.effective_completeness_status in ("FULL_TEXT", "PARTIAL_TEXT")
                        and acquisition.raw_extracted_text
                    ):
                        cleaning = clean_extracted_text(acquisition.raw_extracted_text, title=news_event.title)
                        quote_source_text = cleaning.cleaned_text
            except Exception:
                logger.warning(
                    "quote_source_text_unavailable_falling_back",
                    extra={"task_id": str(task.id), "event_id": str(task.event_id)},
                )

        # TELEGRAPH Checkpoint 3: build the deterministic article research bundle for exactly one
        # step - "deep_research" (capability="research") of a TELEGRAPH_RESEARCH workflow. Mirrors
        # _attach_story_context()'s own established shape (look up the anchor event's
        # NewsEventStoryLink, resolve story_id, call a bounded builder) - the one difference is
        # this MUST succeed for the step to do anything meaningful, so failure here is not
        # swallowed the way every "shadow" attach hook's failure is: an unresolvable Story for a
        # TELEGRAPH_RESEARCH task is a genuine configuration error (services.
        # telegraph_research_processor.process_approved_telegraph_proposal() always creates this
        # task with event_id == story.first_event_id, so a missing link/Story here means something
        # is structurally wrong, not a transient/optional condition).
        telegraph_research_bundle_text: str | None = None
        telegraph_deep_research_output: dict[str, Any] | None = None
        telegraph_visual_bundle_summary: str | None = None
        telegraph_editorial_channel: str | None = None
        state_for_bundle = WorkflowExecutionState.model_validate(task.workflow)

        if step.capability == "research" and state_for_bundle.workflow_name == WorkflowType.TELEGRAPH_RESEARCH:
            from database.models.story import Story
            from database.models.story_link import NewsEventStoryLink

            link = await self._session.get(NewsEventStoryLink, news_event.id)
            if link is None:
                raise PermanentStepFailureError(
                    f"TELEGRAPH_RESEARCH task {task.id}: no NewsEventStoryLink for anchor event "
                    f"{news_event.id} - cannot resolve the Story to research."
                )
            story = await self._session.get(Story, link.story_id)
            if story is None:
                raise PermanentStepFailureError(
                    f"TELEGRAPH_RESEARCH task {task.id}: Story {link.story_id} not found."
                )
            bundle = await build_article_research_bundle(self._session, story)
            telegraph_research_bundle_text = render_bundle_text(bundle)

        # TELEGRAPH Checkpoint 5: the "generate_article" step of a TELEGRAPH_ARTICLE workflow
        # reads the prior, already-COMPLETED TELEGRAPH_RESEARCH task's own result - never re-runs
        # Research. Resolved by (event_id, workflow_name) exactly like services.analysis_reuse.
        # find_source_news_analysis_task_id()'s own established pattern - both tasks share the
        # same anchor event_id (story.first_event_id) by construction (services.
        # telegraph_research_processor.py / services.telegraph_article_processor.py both create
        # their task with event_id=story.first_event_id). A missing or incomplete prior research
        # result is a genuine precondition violation (services.telegraph_article_processor.py's
        # own caller-side guard is expected to prevent this from ever being reached in practice -
        # see that module's own docstring) - raised as PermanentStepFailureError, never silently
        # degraded, since there is no safe fallback content to write an article from.
        if (
            step.capability == "article_generation"
            and state_for_bundle.workflow_name == WorkflowType.TELEGRAPH_ARTICLE
        ):
            from sqlalchemy import select

            from database.models.story import Story
            from database.models.story_link import NewsEventStoryLink
            from database.models.telegraph_shortlist import TelegraphTopicProposal

            link = await self._session.get(NewsEventStoryLink, news_event.id)
            if link is None:
                raise PermanentStepFailureError(
                    f"TELEGRAPH_ARTICLE task {task.id}: no NewsEventStoryLink for anchor event "
                    f"{news_event.id} - cannot resolve the Story to write about."
                )
            story = await self._session.get(Story, link.story_id)
            if story is None:
                raise PermanentStepFailureError(
                    f"TELEGRAPH_ARTICLE task {task.id}: Story {link.story_id} not found."
                )

            research_task_stmt = select(EditorialTask).where(
                EditorialTask.event_id == task.event_id,
                EditorialTask.status == TaskStatus.COMPLETED,
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.TELEGRAPH_RESEARCH.value,
            )
            research_task = (await self._session.execute(research_task_stmt)).scalars().first()
            if research_task is None:
                raise PermanentStepFailureError(
                    f"TELEGRAPH_ARTICLE task {task.id}: no COMPLETED TELEGRAPH_RESEARCH task "
                    f"found for event {task.event_id} - cannot generate an article without a "
                    f"completed Deep Research result."
                )
            deep_research_result = None
            for step_result in (research_task.workflow or {}).get("step_results", []):
                if step_result.get("step_name") == "deep_research" and step_result.get("status") == "SUCCESS":
                    deep_research_result = step_result.get("result")
                    break
            if not isinstance(deep_research_result, dict):
                raise PermanentStepFailureError(
                    f"TELEGRAPH_ARTICLE task {task.id}: research task {research_task.id} has no "
                    f"successful 'deep_research' step result to build an article from."
                )
            telegraph_deep_research_output = deep_research_result

            proposal = (
                await self._session.execute(
                    select(TelegraphTopicProposal).where(
                        TelegraphTopicProposal.research_task_id == research_task.id
                    )
                )
            ).scalars().first()
            if proposal is not None:
                visual_bundle = await build_visual_research_bundle(
                    self._session, proposal_id=proposal.id, story_id=story.id,
                )
                telegraph_visual_bundle_summary = render_visual_bundle_summary(visual_bundle)
                # Editorial channel split: classified once at shortlist-creation time (services/
                # editorial_channel_classifier.py) and persisted on the proposal - read here,
                # never re-classified. `.value` (a plain string) crosses into CapabilityContext,
                # never the ORM row or the enum type itself.
                telegraph_editorial_channel = proposal.editorial_channel.value

        context = self._build_context(
            task, news_event, step, attempt,
            evidence_text=evidence_text, evidence_completeness=evidence_completeness,
            quote_source_text=quote_source_text,
            telegraph_research_bundle_text=telegraph_research_bundle_text,
            telegraph_deep_research_output=telegraph_deep_research_output,
            telegraph_visual_bundle_summary=telegraph_visual_bundle_summary,
            telegraph_editorial_channel=telegraph_editorial_channel,
        )

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
                # Cost-accounting forensic fix: a gateway call can succeed (real provider spend)
                # and still lead the Capability to raise here (e.g. §9.1 floor validation failed
                # on a truncated response) - `error.calls`, if the Capability attached any, is
                # costed through the exact same `_record_cost()` seam the success path below
                # uses (which already only ever costs `status == "SUCCESS"` calls) before the
                # error is translated. Empty for every existing raise site that never attaches
                # calls - byte-identical behavior there.
                await self._record_cost(task, step, error.calls)
                raise StepExecutionError(str(error)) from error
            except CapabilityTimeoutError as error:
                raise StepExecutionError(str(error)) from error
            except (PermanentCapabilityError, ValidationCapabilityError, CapabilityConfigurationError) as error:
                await self._record_cost(task, step, error.calls)
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

        # Phase 17 M5: deterministic, zero-new-LLM-call Editorial Completeness Gate + Fact Safety
        # calibration (docs/phase17_m5_editorial_completeness_gate_shadow_report.md) - same
        # "quality" step as apply_fact_safety() immediately above, run after it (independent of
        # fact_safety_mode - M5 builds its own CandidateFactSafetyAudit + calibration layer
        # directly, never reads apply_fact_safety()'s own baseline-level "fact_safety" key). Only
        # when editorial_completeness_mode == "shadow" (default "off", byte-for-byte unchanged
        # behavior). Never read by any Capability, never changes ContentDraft.
        if step.capability == "quality" and settings.editorial_completeness_mode == "shadow":
            structured_output = self._attach_editorial_completeness(news_event, context, structured_output)

        # Phase 18 M1: deterministic, zero-LLM-call Meme Opportunity Detection (docs/
        # phase18_m1_meme_opportunity_report.md) - same "quality" step, after every Phase 15/17
        # quality/completeness hook above (so a story Fact Safety/Editorial Completeness already
        # flagged as thin/unresolved is visible to this hook too, via context/step_results - it
        # re-derives source sufficiency itself rather than depending on either prior hook having
        # actually run). Only when meme_opportunity_mode == "shadow" (default "off", byte-for-byte
        # unchanged behavior). Never read by any Capability, never changes ContentDraft, never
        # creates a MEME_GENERATION task - purely a persisted shadow recommendation.
        if step.capability == "quality" and settings.meme_opportunity_mode == "shadow":
            structured_output = self._attach_meme_opportunity(news_event, context, structured_output)

        # Phase 17 M1: deterministic, zero-new-LLM-call Editorial Brief shadow build (docs/
        # phase17_m1_editorial_brief_shadow_report.md) - only for "intelligence" (the earliest
        # step where both Research's facts and Intelligence's own just-computed judgment exist)
        # and only when editorial_brief_mode == "shadow" (default "off", byte-for-byte unchanged
        # behavior). Never read by CopywritingCapability, never changes ContentDraft - mirrors
        # apply_fact_safety's/_attach_image_intelligence's own "must not affect delivery"
        # discipline exactly: any failure here is logged and swallowed, never fails the step.
        if step.capability == "intelligence" and settings.editorial_brief_mode == "shadow":
            structured_output = self._attach_editorial_brief(news_event, context, structured_output)

        # Phase 17 M2: deterministic, zero-new-LLM-call Channel/Topic Relevance shadow assessment
        # (docs/phase17_m2_channel_topic_relevance_shadow_report.md) - same seam as M1's own
        # Editorial Brief hook above (also "intelligence", also gated on its own mode flag,
        # independent of editorial_brief_mode - this classifier calls services.editorial_brief.
        # classify_source_sufficiency() directly rather than depending on the Brief actually
        # having been attached). Never read by CopywritingCapability, never changes ContentDraft,
        # never blocks a task - REJECT is only ever a persisted shadow recommendation.
        if step.capability == "intelligence" and settings.channel_relevance_mode == "shadow":
            structured_output = self._attach_channel_relevance(news_event, context, structured_output)

        # Phase 19 M3: zero-cost, zero-LLM-call deterministic Editorial Plan scaffold (docs/
        # phase19_m0_audit.md) - same seam as Editorial Brief/Channel Relevance above (also
        # "intelligence", also gated on its own mode flag). Persists a row for review
        # (database.models.content_draft_editorial_plan) but never reads/writes ContentDraft and
        # is never attached to structured_output that Copywriting reads - Copywriting has no code
        # path to this data at all in this phase, which is what makes "shadow must not alter
        # Copywriting output" a structural guarantee, not just a convention. SAVEPOINT-guarded
        # exactly like _attach_article_evidence's own established pattern (Phase 19 M1/M2): a
        # missing migration must degrade to "no-op," never crash the step.
        if step.capability == "intelligence" and settings.editorial_planning_mode == "shadow":
            await self._attach_editorial_plan(news_event, context, structured_output)

        # Phase 19 M7: Story Timeline + Editorial Memory shadow scaffold - same seam as Editorial
        # Planning above (also "intelligence", also gated on its own mode flag, also deliberately
        # never attached to structured_output). Only meaningful when this event is story-linked
        # (story_memory_mode != "off" AND a NewsEventStoryLink actually exists) - a no-op
        # otherwise. SAVEPOINT-guarded exactly like _attach_editorial_plan's own established
        # pattern: a missing migration must degrade to a logged no-op, never crash the step.
        if step.capability == "intelligence" and settings.story_context_mode == "shadow":
            await self._attach_story_context(news_event)

        # Phase 19 M8: Source Intelligence shadow scaffold - same seam/pattern as Story Context
        # above. Only meaningful when this event is story-linked - a no-op otherwise.
        if step.capability == "intelligence" and settings.source_intelligence_mode == "shadow":
            await self._attach_source_intelligence(news_event)

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

        # Phase 17 M3: deterministic, zero-new-LLM-call Adaptive Length shadow plan (docs/
        # phase17_m3_adaptive_length_shadow_comparison_report.md) - only for "copywriting", after
        # Image Intelligence's own attach immediately above (so real candidates_accepted data is
        # available for an accurate photo-caption-vs-text-message delivery recommendation - unlike
        # M1's Editorial Brief and M2's Channel Relevance, both of which run earlier at
        # "intelligence" and therefore cannot see image-candidate data). Only when
        # adaptive_length_mode != "off" (default "off", byte-for-byte unchanged behavior). Never
        # read by CopywritingCapability - this hook runs strictly after Copywriting's own call
        # already completed for this step - never changes ContentDraft.
        if step.capability == "copywriting" and settings.adaptive_length_mode != "off":
            structured_output = self._attach_adaptive_length_plan(news_event, context, structured_output)

        # Phase 17 M4: deterministic, zero-new-LLM-call Beginner-Friendly plan (docs/
        # phase17_m4_beginner_friendly_copywriting_report.md) - same "copywriting" step, after
        # Adaptive Length's own attach immediately above (both run at the same step; ordering
        # between them does not matter since each builds its own inputs independently). Only when
        # beginner_copywriting_mode != "off" (default "off", byte-for-byte unchanged behavior).
        # Never read by CopywritingCapability, never changes ContentDraft.
        if step.capability == "copywriting" and settings.beginner_copywriting_mode != "off":
            structured_output = self._attach_beginner_friendly_plan(news_event, context, structured_output)

        # Phase 18 M3: deterministic, zero-LLM-call Meme Safety & Originality Gate (docs/
        # phase18_m3_meme_safety_originality_report.md) - only for "meme_concept" (the step whose
        # own just-succeeded structured_output is a real MemeConcept), only when
        # meme_safety_gate_mode == "shadow" (default "off", byte-for-byte unchanged behavior).
        # Never blocks, never mutates the concept itself.
        if step.capability == "meme_concept" and settings.meme_safety_gate_mode == "shadow":
            structured_output = self._attach_meme_safety_originality(news_event, context, structured_output)

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

    def _attach_channel_relevance(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (Phase 17 M2's own "classifier failure must not fail
        CONTENT_GENERATION, must not cause a retry, must not duplicate the task" requirement).
        Purely synchronous/deterministic. Any failure is logged (`article_topic_assessment_
        failed`) and swallowed, returning `structured_output` completely unchanged - the same
        discipline `_attach_editorial_brief`/`_attach_image_intelligence` already established.
        No raw content, the full assessment payload, or secrets are logged - only classification
        metadata (Phase 17 M2's own observability requirement)."""
        logger.info(
            "article_topic_assessment_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            research_output = context.business.workflow_state.step_results.get("research", {})
            result = apply_channel_relevance_shadow(
                news_event.title, news_event.content, news_event.category, research_output, structured_output,
            )
        except Exception:
            logger.warning(
                "article_topic_assessment_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        payload = result.get("channel_relevance")
        if isinstance(payload, dict):
            topic = payload.get("article_topic_assessment", {})
            fit = payload.get("channel_fit_assessment", {})
            decision = payload.get("shadow_decision", {})
            logger.info(
                "article_topic_assessment_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "topic": topic.get("primary_topic"),
                    "normalized_category": topic.get("normalized_category"),
                    "source_category_match": topic.get("category_match"),
                    "reason_codes": topic.get("reason_codes"),
                },
            )
            logger.info(
                "channel_fit_assessment_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "fit_decision": fit.get("fit_decision"),
                    "fit_score": fit.get("fit_score"),
                    "confidence": fit.get("confidence"),
                    "human_review_required": fit.get("human_review_required"),
                    "reason_codes": fit.get("reason_codes"),
                    "classifier_version": decision.get("classifier_version"),
                    "channel_profile_id": fit.get("channel_profile_id"),
                },
            )
        return result

    async def _attach_editorial_plan(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> None:
        """Phase 19 M3, shadow mode. Deliberately returns None, not `structured_output` - unlike
        every sibling `_attach_*` hook above, this one's whole point is that Copywriting has NO
        code path to read what it computes (Correction 3's explicit "shadow must not alter
        Copywriting output" requirement, enforced structurally, not just by convention). Builds
        the zero-cost, zero-LLM-call deterministic scaffold (services/editorial_planning_
        deterministic.py - never the real, LLM-backed EditorialPlanningCapability, which only the
        offline comparison script ever invokes) and persists one row for later human review.
        SAVEPOINT-guarded exactly like the evidence-package fetch earlier in this same method
        (Phase 19 M1/M2): a missing migration must degrade to a logged no-op, never crash the
        "intelligence" step."""
        try:
            async with self._session.begin_nested():
                research_output = context.business.workflow_state.step_results.get("research", {})
                story_match_type: str | None = None
                known_evidence_gaps: list[str] = []
                evidence_text = ""
                quote_candidates: list[str] = []
                selected_editorial_text_hash: str | None = None
                if settings.story_memory_mode != "off":
                    from database.models.story_link import NewsEventStoryLink

                    link = await self._session.get(NewsEventStoryLink, news_event.id)
                    if link is not None:
                        story_match_type = link.match_type
                if settings.article_acquisition_mode != "off":
                    from services.evidence_package import build_evidence_package

                    evidence = await build_evidence_package(self._session, news_event)
                    known_evidence_gaps = evidence.known_evidence_gaps
                    evidence_text = evidence.selected_editorial_text
                    quote_candidates = evidence.quote_candidates
                    selected_editorial_text_hash = evidence.selected_editorial_text_hash

                plan = build_deterministic_plan(
                    title=news_event.title, research_facts=research_output.get("facts"),
                    story_match_type=story_match_type, known_evidence_gaps=known_evidence_gaps,
                )
                await persist_shadow_plan(
                    self._session, event_id=news_event.id, plan=plan,
                    evidence_text=evidence_text, quote_candidates=quote_candidates,
                    selected_editorial_text_hash=selected_editorial_text_hash,
                )
        except Exception:
            logger.warning(
                "editorial_plan_shadow_scaffold_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )

    async def _attach_story_context(self, news_event: NewsEvent) -> None:
        """Phase 19 M7, shadow mode. Deliberately returns None and never touches
        structured_output - same structural "Copywriting has no code path to read this" guarantee
        as _attach_editorial_plan(). A no-op whenever this event has no NewsEventStoryLink (i.e.
        story_memory_mode was "off" at Triage time, or this event predates story linking) -
        Editorial Memory only ever describes a story that Story Memory itself already recognized.
        SAVEPOINT-guarded exactly like _attach_editorial_plan()."""
        try:
            async with self._session.begin_nested():
                from database.models.story_link import NewsEventStoryLink

                link = await self._session.get(NewsEventStoryLink, news_event.id)
                if link is None:
                    return

                timeline = await build_story_timeline(self._session, link.story_id)
                await persist_story_context_snapshot(
                    self._session, event_id=news_event.id, story_id=link.story_id, timeline=timeline,
                )
        except Exception:
            logger.warning(
                "story_context_shadow_scaffold_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )

    async def _attach_source_intelligence(self, news_event: NewsEvent) -> None:
        """Phase 19 M8, shadow mode. Deliberately returns None and never touches
        structured_output - same structural guarantee as _attach_editorial_plan()/
        _attach_story_context(). A no-op whenever this event has no NewsEventStoryLink.
        `is_first_in_story` reuses Story.first_event_id directly (no dependency on services.
        story_context's timeline builder - M7 and M8 stay independently shadow-only, per the
        overnight authorization's own requirement that both be provably isolated from each
        other and from Copywriting). SAVEPOINT-guarded exactly like its siblings."""
        try:
            async with self._session.begin_nested():
                from database.models.story import Story
                from database.models.story_link import NewsEventStoryLink

                link = await self._session.get(NewsEventStoryLink, news_event.id)
                if link is None:
                    return

                story = await self._session.get(Story, link.story_id)
                is_first_in_story = story is not None and story.first_event_id == news_event.id

                role = classify_source_role(
                    is_first_in_story=is_first_in_story, match_type=link.match_type,
                    title=news_event.title,
                )
                await persist_source_intelligence(
                    self._session, news_event_id=news_event.id, role=role,
                    is_first_in_story=is_first_in_story, match_type=link.match_type,
                    reliability_score=None,
                )
        except Exception:
            logger.warning(
                "source_intelligence_shadow_scaffold_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )

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

    def _attach_adaptive_length_plan(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (Phase 17 M3's own "policy builder failure must not fail
        the workflow, must not cause a retry" requirement). Purely synchronous/deterministic - no
        `await`. Any failure is logged (`adaptive_length_plan_failed`) and swallowed, returning
        `structured_output` completely unchanged - the same discipline `_attach_editorial_brief`/
        `_attach_channel_relevance` already established. No raw content or the full plan text in
        ordinary logs - only schema/classification metadata."""
        logger.info(
            "adaptive_length_plan_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            research_output = context.business.workflow_state.step_results.get("research", {})
            intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
            image_intelligence = structured_output.get("image_intelligence")
            has_image_candidate = (
                image_intelligence.get("candidates_accepted", 0) > 0
                if isinstance(image_intelligence, dict) else None
            )
            result = apply_adaptive_length_shadow(
                news_event.title, news_event.content, research_output, intelligence_output,
                has_image_candidate, structured_output,
            )
        except Exception:
            logger.warning(
                "adaptive_length_plan_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        plan = result.get("adaptive_length_plan")
        if isinstance(plan, dict):
            logger.info(
                "adaptive_length_plan_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "policy_version": plan.get("policy_version"),
                    "complexity": plan.get("complexity"),
                    "source_sufficiency": plan.get("source_sufficiency"),
                    "recommended_format": plan.get("recommended_format"),
                    "min_words": plan.get("min_words"),
                    "target_words": plan.get("target_words"),
                    "max_words": plan.get("max_words"),
                    "delivery_mode": plan.get("delivery_mode"),
                    "hard_character_limit": plan.get("hard_character_limit"),
                    "paragraph_target": plan.get("paragraph_target"),
                    "detail_target": plan.get("detail_target"),
                    "reason_codes": plan.get("reason_codes"),
                },
            )
        return result

    def _attach_beginner_friendly_plan(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (Phase 17 M4's own "plan builder failure must not fail the
        workflow, must not cause a retry" requirement). Purely synchronous/deterministic. Any
        failure is logged (`beginner_friendly_plan_failed`) and swallowed, returning
        `structured_output` completely unchanged - the same discipline `_attach_adaptive_
        length_plan` already established. No raw content or the full plan text in ordinary logs -
        only schema/classification metadata."""
        logger.info(
            "beginner_friendly_plan_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            research_output = context.business.workflow_state.step_results.get("research", {})
            intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
            image_intelligence = structured_output.get("image_intelligence")
            has_image_candidate = (
                image_intelligence.get("candidates_accepted", 0) > 0
                if isinstance(image_intelligence, dict) else None
            )
            result = apply_beginner_friendly_shadow(
                news_event.title, news_event.content, research_output, intelligence_output,
                has_image_candidate, structured_output,
            )
        except Exception:
            logger.warning(
                "beginner_friendly_plan_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        plan = result.get("beginner_friendly_plan")
        if isinstance(plan, dict):
            logger.info(
                "beginner_friendly_plan_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "policy_version": plan.get("policy_version"),
                    "audience_level": plan.get("audience_level"),
                    "explanation_required": plan.get("explanation_required"),
                    "subjects_to_explain_count": len(plan.get("subjects_to_explain") or []),
                    "terms_to_explain_count": len(plan.get("terms_to_explain") or []),
                    "ideal_target_words": (plan.get("ideal_range") or {}).get("target_words"),
                    "safe_target_words": (plan.get("safe_range") or {}).get("target_words"),
                    "paragraph_target": plan.get("paragraph_target"),
                    "jargon_risk": plan.get("jargon_risk"),
                    "reason_codes": plan.get("reason_codes"),
                },
            )
        return result

    def _attach_editorial_completeness(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (Phase 17 M5's own "gate failure must not fail the step,
        must not cause a retry, must not create a retry loop" requirement). Runs after
        `apply_fact_safety()`'s own baseline check, same "quality" step - reads the real
        Copywriting `title`/`body` and every upstream shadow artifact M1/M3/M4 already attached
        (`editorial_brief` at "intelligence", `adaptive_length_plan`/`beginner_friendly_plan` at
        "copywriting") - never recomputes any of them, never generates text, never calls the LLM
        Gateway. Builds its own fresh `CandidateFactSafetyAudit` (M4's own unmodified builder) +
        `CalibratedFactSafetyAssessment` (M5's own calibration layer) directly from
        `research`/`copywriting` step_results already on `CapabilityContext` at zero extra DB
        query - independent of `fact_safety_mode`/`apply_fact_safety()`'s own baseline-level
        result, a deliberately separate dimension (module docstring, "не смешивай"). Any failure
        is logged (`completeness_assessment_failed`) and swallowed, returning `structured_output`
        completely unchanged - the same discipline every prior M1-M4 attach method already
        established. No raw content, full draft text, or full EditorialBrief in ordinary logs -
        only schema/classification metadata (this milestone's own explicit observability
        requirement)."""
        logger.info(
            "completeness_assessment_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            research_output = context.business.workflow_state.step_results.get("research", {})
            intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
            copywriting_output = context.business.workflow_state.step_results.get("copywriting", {})
            title = copywriting_output.get("title")
            body = copywriting_output.get("body")
            if not isinstance(title, str) or not isinstance(body, str):
                return structured_output

            research_facts = (
                list(research_output.get("facts", []))
                if isinstance(research_output.get("facts"), list) else []
            )
            beginner_plan_data = copywriting_output.get("beginner_friendly_plan")
            beginner_plan = (
                BeginnerFriendlyPlan.model_validate(beginner_plan_data)
                if isinstance(beginner_plan_data, dict) else None
            )

            raw_audit = evaluate_candidate_fact_safety(
                title, body, news_event.title, news_event.content, research_facts, beginner_plan,
            )
            calibrated = calibrate_fact_safety(
                raw_audit, draft_title=title, news_event_title=news_event.title,
                news_event_content=news_event.content, research_facts=research_facts,
            )
            result = apply_editorial_completeness_shadow(
                intelligence_output, copywriting_output, calibrated, structured_output,
            )
        except Exception:
            logger.warning(
                "completeness_assessment_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        assessment = result.get("editorial_completeness")
        if isinstance(assessment, dict):
            logger.info(
                "completeness_assessment_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "policy_version": assessment.get("policy_version"),
                    "draft_kind": assessment.get("draft_kind"),
                    "source_sufficiency": assessment.get("source_sufficiency"),
                    "completeness_score": assessment.get("completeness_score"),
                    "required_count": assessment.get("required_criteria_count"),
                    "passed_count": assessment.get("passed_required_count"),
                    "partial_count": assessment.get("partial_required_count"),
                    "failed_count": assessment.get("failed_required_count"),
                    "headline_rewrite_risk": assessment.get("headline_rewrite_risk"),
                    "safe_length_status": assessment.get("safe_length_status"),
                    "editorial_recommendation": assessment.get("editorial_recommendation"),
                    "fact_safety_raw_status": calibrated.raw_audit_status.value,
                    "fact_safety_calibrated_status": calibrated.calibrated_status.value,
                    "suppressed_flag_count": len(calibrated.suppressed_false_positive_flags),
                    "unresolved_flag_count": len(calibrated.unresolved_flags),
                    "reason_codes": assessment.get("reason_codes"),
                },
            )
            result = {**result, "calibrated_fact_safety": calibrated.model_dump(mode="json")}
        return result

    def _attach_meme_opportunity(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (same discipline every M1-M5 Phase 17 hook above already
        established: a classifier failure must not fail the step, must not cause a retry, must
        not duplicate the task). Purely synchronous/deterministic - no `await`. Reads only
        `research` (facts/gaps) and, when present, the "copywriting" step's own already-attached
        `image_intelligence.candidates_accepted` (Phase 16) as a visual-potential signal - never
        recomputes either, never calls the LLM Gateway. Any failure is logged
        (`meme_opportunity_assessment_failed`) and swallowed, returning `structured_output`
        completely unchanged. No raw content or the full assessment payload in ordinary logs -
        only schema/classification metadata, matching every prior hook's own observability
        discipline."""
        logger.info(
            "meme_opportunity_assessment_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            research_output = context.business.workflow_state.step_results.get("research", {})
            copywriting_output = context.business.workflow_state.step_results.get("copywriting", {})
            image_intelligence = copywriting_output.get("image_intelligence")
            has_image_candidate = (
                image_intelligence.get("candidates_accepted", 0) > 0
                if isinstance(image_intelligence, dict) else None
            )
            result = apply_meme_opportunity_shadow(
                news_event.title, news_event.content, news_event.category, news_event.published_at,
                research_output, structured_output, has_image_candidate=has_image_candidate,
            )
        except Exception:
            logger.warning(
                "meme_opportunity_assessment_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        assessment = result.get("meme_opportunity")
        if isinstance(assessment, dict):
            logger.info(
                "meme_opportunity_assessment_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "policy_version": assessment.get("policy_version"),
                    "decision": assessment.get("decision"),
                    "composite_score": (assessment.get("signals") or {}).get("composite_score"),
                    "sensitivity_categories": assessment.get("sensitivity_categories"),
                    "source_sufficiency": assessment.get("source_sufficiency"),
                    "reason_codes": assessment.get("reason_codes"),
                },
            )
        return result

    def _attach_meme_safety_originality(
        self, news_event: NewsEvent, context: CapabilityContext, structured_output: dict[str, Any]
    ) -> dict[str, Any]:
        """Best-effort, non-blocking (same discipline every prior hook establishes: a gate
        failure must not fail the step, must not cause a retry). `structured_output` at this
        point is `MemeConceptCapability`'s own just-succeeded result - passed to `MemeConcept.
        model_validate()` inside `apply_meme_safety_originality_shadow()`; a malformed concept
        (should not happen, `MemeConceptCapability` already floor-validates it) degrades to the
        same logged-and-swallowed failure path as any other exception here. No `calibrated_fact_
        safety_status` is available yet - MEME_GENERATION has no "quality" step of its own as of
        M3 (workflows/definitions/meme_generation.py's own current step list) - `None` is passed,
        the documented, safe default `services.meme_safety.assess_meme_safety()` already handles
        explicitly."""
        logger.info(
            "meme_safety_originality_assessment_started",
            extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
        )
        try:
            result = apply_meme_safety_originality_shadow(
                structured_output, news_event.title, structured_output,
            )
        except Exception:
            logger.warning(
                "meme_safety_originality_assessment_failed",
                extra={"task_id": str(self._task_id), "event_id": str(news_event.id)},
            )
            return structured_output

        assessment = result.get("meme_safety_originality")
        if isinstance(assessment, dict):
            logger.info(
                "meme_safety_originality_assessment_completed",
                extra={
                    "task_id": str(self._task_id),
                    "event_id": str(news_event.id),
                    "policy_version": assessment.get("policy_version"),
                    "gate_decision": assessment.get("gate_decision"),
                    "safety_decision": (assessment.get("safety") or {}).get("decision"),
                    "originality_decision": (assessment.get("originality") or {}).get("decision"),
                    "sensitivity_categories": (assessment.get("safety") or {}).get("sensitivity_categories"),
                },
            )
        return result

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
        # Phase 18 M2 (docs/phase18_m2_meme_concept_report.md): MEME_GENERATION's own "research"/
        # "intelligence" steps reuse the same source NEWS_ANALYSIS task's results for identical
        # reasons CONTENT_GENERATION already does (module docstring) - a meme concept is built
        # from the exact same evidence a normal draft would be, for the same NewsEvent.
        if state.workflow_name not in (WorkflowType.CONTENT_GENERATION, WorkflowType.MEME_GENERATION):
            return None

        if self._source_news_analysis_task_id is False:  # not yet looked up this run
            self._source_news_analysis_task_id = await find_source_news_analysis_task_id(
                self._session, task.event_id
            )
        source_task_id = self._source_news_analysis_task_id
        if source_task_id is None:
            return None
        return await reuse_prior_result(self._session, source_task_id, step.capability, event_id=task.event_id)

    def _build_context(
        self, task: EditorialTask, news_event: NewsEvent, step: WorkflowStepDefinition, attempt: int,
        *, evidence_text: str | None = None, evidence_completeness: str | None = None,
        quote_source_text: str | None = None, telegraph_research_bundle_text: str | None = None,
        telegraph_deep_research_output: dict[str, Any] | None = None,
        telegraph_visual_bundle_summary: str | None = None,
        telegraph_editorial_channel: str | None = None,
    ) -> CapabilityContext:
        state = WorkflowExecutionState.model_validate(task.workflow)
        is_telegraph_deep_research = telegraph_research_bundle_text is not None

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
                article_evidence_text=evidence_text,
                article_evidence_completeness=evidence_completeness,
                quote_source_text=quote_source_text,
                telegraph_research_bundle_text=telegraph_research_bundle_text,
                telegraph_deep_research_output=telegraph_deep_research_output,
                telegraph_visual_bundle_summary=telegraph_visual_bundle_summary,
                telegraph_editorial_channel=telegraph_editorial_channel,
            ),
            execution=ExecutionContext(
                # TELEGRAPH Checkpoint 3: deep research reads a materially larger bundle and is
                # expected to produce a materially larger structured output than a normal
                # single-event "research" call - the shared _MAX_OUTPUT_TOKENS_BY_CAPABILITY/
                # _REASONING_EFFORT_BY_CAPABILITY dicts above are keyed by capability NAME
                # ("research"), which this step also uses (by design - see capabilities/
                # research_capability.py's own addendum), so a distinct override is needed here
                # rather than a second dict entry. NEWS_ANALYSIS/CONTENT_GENERATION/
                # MEME_GENERATION's own "research" step is completely unaffected - this branch
                # only fires when telegraph_research_bundle_text is not None.
                max_tokens=(
                    _TELEGRAPH_DEEP_RESEARCH_MAX_OUTPUT_TOKENS if is_telegraph_deep_research
                    else _MAX_OUTPUT_TOKENS_BY_CAPABILITY.get(step.capability)
                ),
                reasoning_effort=(
                    _TELEGRAPH_DEEP_RESEARCH_REASONING_EFFORT if is_telegraph_deep_research
                    else _REASONING_EFFORT_BY_CAPABILITY.get(step.capability)
                ),
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
