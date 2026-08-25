"""services/final_post_processor.py - Phase I.1: Approved EVENT_RECAP -> Final Post Authoring Core.

`generate_final_post_for_review(review_id)` is the ONLY entry point this checkpoint exposes -
nothing in this codebase calls it automatically, mirroring services.event_recap_processor.
generate_recap_for_story()'s own dormancy discipline exactly. A future checkpoint (I.2/I.3)
decides how/when a Final Post review/publication happens - explicitly out of this checkpoint's
scope. This module never sends Telegram, never publishes anything, and never creates a second
review row of any kind.

APPROVED ONLY (instruction item 9): only an `EventRecapReview.status == APPROVED` reaches
authoring. PENDING/NEEDS_REVISION return `"not_approved"` - no task, no LLM call, no ContentDraft.

PROVENANCE (Correction #1): `EditorialTask.event_id` anchor equality is NOT treated as sufficient
linkage on its own. `build_final_post_source_bundle()` resolves the exact source
`EventRecapReview`/EVENT_RECAP task and threads `source_event_recap_task_id`,
`source_event_recap_review_id`, `story_id`, `anchor_event_id` explicitly through the deterministic
authoring bundle - durably persisted onto the new FINAL_POST_AUTHORING task's own
`workflow["step_results"]` as one pre-populated `"final_post_source"` entry (`_persist_final_post_
source()`, mirroring `services.event_recap_processor._persist_selected_media()`'s own established
mechanism/safety exactly - a plain `step_results` entry, never a new top-level `task.workflow` key).

LEGACY APPROVED RECAP POLICY (Correction #2, decided from real, empirical evidence - see
`build_final_post_source_bundle()`'s own docstring): a real, read-only check of the approved Pixel
EVENT_RECAP task (fa24bb17-919a-44e5-ad13-748f59dad3eb) confirmed that `verified_facts`/
`source_refs`/`story_id` were NOT durably persisted anywhere before this phase - only the approved
recap TEXT itself (`recap_title`/`recap_summary`/`key_takeaways`/`uncertainty_notes`) and the media
plan were. `anchor_event_id` needs no lookup at all (it is `EditorialTask.event_id` itself, always
present). `services.event_recap_processor` now additionally persists a `"event_recap_source_
snapshot"` step_result for every FUTURE EVENT_RECAP run (story_id/anchor_event_id/verified_facts/
source_refs, from the SAME single candidate build that already produced the approved text - never
recomputed). For a LEGACY task lacking that snapshot, this module does NOT rebuild the Story: it
authors from the approved recap text ALONE (`verified_facts=[]`, `source_refs=[]`), and resolves
`story_id` via one stable, already-existing `NewsEventStoryLink` FK lookup by `anchor_event_id` -
a fixed-relationship read, never new fact reconstruction. `legacy_snapshot_missing: bool` records
this transparently in the bundle itself, for downstream audit/reporting. This was chosen over a
`source_snapshot_missing` fail-closed outcome because the approved recap text is itself durable and
was itself the actual object of human approval - it is a complete, legitimate (if less
richly-evidenced) source of truth on its own, never a reconstruction.

IDEMPOTENCY (instruction item 10): the deterministic authoring source bundle's own `anchor_event_id`
is used as `EditorialTaskCreate.event_id` - the SAME anchor `services.event_recap_processor` already
used for its own EVENT_RECAP task, so `services.workflow_service.create_task()`'s existing
one-task-per-(event_id, workflow_type) guard doubles as this workflow's exactly-once mechanism too
(mirrors TELEGRAPH_ARTICLE's identical anchoring to its own TELEGRAPH_RESEARCH task's event_id).
A second `generate_final_post_for_review()` call for the same (or a different) approved review of
the same anchor event returns `"already_exists"` - no second LLM call, no second ContentDraft.

FACT-SAFETY (instruction items 14/15): after the one authoring LLM call, `evaluate_fact_safety()`
(reused, unmodified) checks the authored title/body against the approved recap's own text +
persisted verified facts (never the current, possibly-drifted Story). A `"block"` verdict prevents
`ContentDraft` creation entirely - the FINAL_POST_AUTHORING task itself stays `COMPLETED` (the LLM
call succeeded; authoring is not retried), but this function's own outcome is `"fact_safety_
blocked"`, never silently downgraded to a normal `"generated"` result. `"review"`/`"pass"` both
allow ContentDraft creation, mirroring `services.content_draft_service._draft_status_for()`'s own
established "review does not itself block persistence" semantics.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus
from database.models.story_link import NewsEventStoryLink
from schemas.content_draft import ContentDraftRead
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowStepResult, WorkflowType
from services import workflow_service
from services.content_draft_service import ContentDraftService
from services.cost_tracker import CostTracker
from services.event_recap_review_service import get_event_recap_review
from services.fact_safety import FactEvidence, evaluate_fact_safety
from services.pricing_catalog import PricingCatalog
from workflows.errors import DuplicateActiveTaskError
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

# Reasoned default, matching services.event_recap_processor's own identical reasoning: a
# deliberate, human-triggered (post-approval) background task, never time-sensitive.
_FINAL_POST_TASK_PRIORITY = TaskPriority.C

# Phase I.1: NOT a WorkflowDefinition step (workflows/definitions/final_post_authoring.py is
# untouched - still exactly one real step, "final_post_authoring") - a plain, pre-populated
# `step_results` entry this module writes directly, before `WorkflowRunner.run()` is ever called.
# Safe for the identical reason services.event_recap_processor._persist_selected_media()'s own
# docstring documents in full (WorkflowRunner._execute_steps() filters by definition.steps names
# only; WorkflowExecutionState's extra="forbid" only forbids unknown TOP-LEVEL fields).
_FINAL_POST_SOURCE_STEP_NAME = "final_post_source"

_RECAP_STEP_NAME = "synthesize_recap"
_RECAP_MEDIA_STEP_NAME = "select_recap_media"
_RECAP_SOURCE_SNAPSHOT_STEP_NAME = "event_recap_source_snapshot"
_AUTHORING_STEP_NAME = "final_post_authoring"

FinalPostGenerationStatus = Literal[
    "review_not_found", "not_approved", "source_missing", "already_exists",
    "authoring_failed", "fact_safety_blocked", "generated",
]


@dataclass(frozen=True)
class FinalPostGenerationOutcome:
    review_id: UUID
    status: FinalPostGenerationStatus
    task_id: UUID | None
    run_result: WorkflowRunResult | None
    content_draft: ContentDraftRead | None = None
    # Populated only once fact-safety actually ran (status="fact_safety_blocked" or "generated") -
    # `evaluate_fact_safety()`'s own categorical "pass"/"review"/"block", never invented here.
    fact_safety_status: str | None = None


def _find_step_result(step_results: list[dict[str, Any]], step_name: str) -> dict[str, Any] | None:
    for step_result in step_results:
        if step_result.get("step_name") == step_name and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                return result
    return None


async def build_final_post_source_bundle(
    session: AsyncSession, review: EventRecapReview,
) -> dict[str, Any] | None:
    """Assembles the deterministic, JSON-safe authoring source bundle for one APPROVED
    `EventRecapReview` - the caller's own responsibility to have already checked `status ==
    APPROVED` (this function does not re-check it). Returns `None` only when the source EVENT_RECAP
    task itself, or its `synthesize_recap` result, cannot be found at all (a genuine data-integrity
    gap, never expected in practice - the review's own `recap_task_id` FK guarantees the task row
    exists, and it cannot have been approved without a successful synthesis).

    See this module's own docstring for the full LEGACY APPROVED RECAP POLICY reasoning. In short:
    `anchor_event_id` is always `recap_task.event_id` (no lookup needed). `story_id`/
    `verified_facts`/`source_refs` come from the `"event_recap_source_snapshot"` step_result when
    present (every EVENT_RECAP task created after this phase); for an older task lacking it,
    `story_id` is resolved via one `NewsEventStoryLink` FK lookup by `anchor_event_id` and
    `verified_facts`/`source_refs` are left empty - never reconstructed from the current Story.
    `legacy_snapshot_missing` records which path was taken, transparently, for downstream audit."""
    recap_task = await session.get(EditorialTask, review.recap_task_id)
    if recap_task is None:
        return None

    step_results = (recap_task.workflow or {}).get("step_results", [])
    recap_result = _find_step_result(step_results, _RECAP_STEP_NAME)
    if recap_result is None:
        return None

    media_plan = _find_step_result(step_results, _RECAP_MEDIA_STEP_NAME)
    snapshot = _find_step_result(step_results, _RECAP_SOURCE_SNAPSHOT_STEP_NAME)

    anchor_event_id = recap_task.event_id
    legacy_snapshot_missing = snapshot is None
    if snapshot is not None:
        story_id = snapshot.get("story_id")
        verified_facts = snapshot.get("verified_facts") or []
        source_refs = snapshot.get("source_refs") or []
    else:
        link = await session.get(NewsEventStoryLink, anchor_event_id)
        story_id = str(link.story_id) if link is not None else None
        verified_facts = []
        source_refs = []

    return {
        "source_event_recap_task_id": str(recap_task.id),
        "source_event_recap_review_id": str(review.id),
        "story_id": story_id,
        "anchor_event_id": str(anchor_event_id),
        "approved_recap": {
            "recap_title": recap_result.get("recap_title"),
            "recap_summary": recap_result.get("recap_summary"),
            "key_takeaways": recap_result.get("key_takeaways") or [],
            "uncertainty_notes": recap_result.get("uncertainty_notes") or [],
        },
        "verified_facts": verified_facts,
        "source_refs": source_refs,
        "selected_media_plan": media_plan,
        "legacy_snapshot_missing": legacy_snapshot_missing,
        "language": settings.default_content_language,
    }


async def find_final_post_authoring_task_id(session: AsyncSession, event_id: UUID) -> UUID | None:
    """Mirrors services.event_recap_processor.find_event_recap_task_id()'s own established shape
    exactly - any status, since a caller may want to inspect a RUNNING/FAILED task too."""
    stmt = (
        select(EditorialTask.id)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.FINAL_POST_AUTHORING.value,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _persist_final_post_source(session: AsyncSession, task_id: UUID, bundle: dict[str, Any]) -> None:
    """Mirrors services.event_recap_processor._persist_selected_media()'s own mechanism/safety
    exactly - see this module's own docstring for the full reasoning. `session.flush()` only:
    the very next thing the caller does is `WorkflowRunner.run()`, which commits this same
    transaction."""
    task = await session.get(EditorialTask, task_id)
    assert task is not None, "task_id came from create_task() in the same session/transaction"
    now = datetime.now(timezone.utc)
    step_result = WorkflowStepResult(
        step_name=_FINAL_POST_SOURCE_STEP_NAME, status="SUCCESS", attempt=1,
        started_at=now, finished_at=now, error=None, result=bundle,
    )
    workflow = dict(task.workflow or {})
    workflow["step_results"] = [step_result.model_dump(mode="json"), *workflow.get("step_results", [])]
    task.workflow = workflow
    await session.flush()


def _authored_output(run_result: WorkflowRunResult) -> dict[str, Any] | None:
    for step_result in run_result.step_results:
        if step_result.step_name == _AUTHORING_STEP_NAME and step_result.status == "SUCCESS":
            return step_result.result
    return None


def _fact_safety_evidence(bundle: dict[str, Any]) -> FactEvidence:
    """The approved recap's own text is the sole factual authority - never the current, possibly-
    drifted Story (module docstring). `research_facts` carries the persisted `verified_facts`
    (empty for a legacy bundle - never fabricated)."""
    approved = bundle["approved_recap"]
    source_content = "\n\n".join(
        part for part in (
            approved.get("recap_summary") or "",
            "\n".join(approved.get("key_takeaways") or []),
            "\n".join(approved.get("uncertainty_notes") or []),
        ) if part
    )
    research_facts = [
        f"{fact.get('fact_type')}: {fact.get('value')}" for fact in bundle.get("verified_facts") or []
    ]
    return FactEvidence(
        source_title=approved.get("recap_title") or "",
        source_content=source_content,
        source_url=None,
        research_facts=research_facts,
    )


async def generate_final_post_for_review(
    session: AsyncSession,
    review_id: UUID,
    *,
    capability_registry: CapabilityRegistry,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> FinalPostGenerationOutcome:
    """Review lookup -> approved-only gate -> source-bundle assembly -> existing-task check ->
    create (or find existing) EditorialTask -> run its FINAL_POST_AUTHORING workflow -> fact-safety
    check -> conditional ContentDraft creation. Returns without ever reaching the LLM Gateway if
    the review does not exist, is not APPROVED, its source bundle cannot be assembled, or a
    FINAL_POST_AUTHORING task already exists for its anchor event (structural cost boundary,
    mirroring services.event_recap_processor.generate_recap_for_story()'s own identical
    claim-first discipline)."""
    review = await get_event_recap_review(session, review_id)
    if review is None:
        return FinalPostGenerationOutcome(
            review_id=review_id, status="review_not_found", task_id=None, run_result=None,
        )

    if review.status != EventRecapReviewStatus.APPROVED:
        return FinalPostGenerationOutcome(
            review_id=review_id, status="not_approved", task_id=None, run_result=None,
        )

    bundle = await build_final_post_source_bundle(session, review)
    if bundle is None:
        return FinalPostGenerationOutcome(
            review_id=review_id, status="source_missing", task_id=None, run_result=None,
        )

    anchor_event_id = UUID(bundle["anchor_event_id"])

    # Check for an existing task BEFORE creating one - mirrors generate_recap_for_story()'s own
    # identical claim-first discipline.
    existing_task_id = await find_final_post_authoring_task_id(session, anchor_event_id)
    if existing_task_id is not None:
        return FinalPostGenerationOutcome(
            review_id=review_id, status="already_exists", task_id=existing_task_id, run_result=None,
        )

    try:
        task_read = await workflow_service.create_task(
            session,
            EditorialTaskCreate(
                event_id=anchor_event_id, workflow_type=WorkflowType.FINAL_POST_AUTHORING,
                priority=_FINAL_POST_TASK_PRIORITY,
            ),
        )
    except DuplicateActiveTaskError:
        # Concurrency safety-net only (disclosed, pre-existing check-then-insert race - mirrors
        # generate_recap_for_story()'s own identical disclosure): the pre-check above found
        # nothing, but another concurrent caller won the race and created a task in between.
        existing_task_id = await find_final_post_authoring_task_id(session, anchor_event_id)
        return FinalPostGenerationOutcome(
            review_id=review_id, status="already_exists", task_id=existing_task_id, run_result=None,
        )

    await _persist_final_post_source(session, task_read.id, bundle)

    executor = CapabilityExecutor(
        session, task_read.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
        precomputed_final_post_source=bundle,
    )
    runner = WorkflowRunner(executor)
    run_result = await runner.run(session, task_read.id)

    if run_result.status != "COMPLETED":
        return FinalPostGenerationOutcome(
            review_id=review_id, status="authoring_failed", task_id=task_read.id, run_result=run_result,
        )

    authored = _authored_output(run_result)
    if authored is None:
        return FinalPostGenerationOutcome(
            review_id=review_id, status="authoring_failed", task_id=task_read.id, run_result=run_result,
        )

    evidence = _fact_safety_evidence(bundle)
    fact_safety_result = evaluate_fact_safety(authored.get("title") or "", authored.get("body") or "", evidence)
    fact_safety_status = fact_safety_result.get("status")

    if fact_safety_status == "block":
        logger.warning(
            "final_post_authoring_fact_safety_blocked",
            extra={
                "review_id": str(review_id), "task_id": str(task_read.id),
                "fact_safety_status": fact_safety_status,
                "fact_safety_findings": fact_safety_result.get("findings"),
            },
        )
        return FinalPostGenerationOutcome(
            review_id=review_id, status="fact_safety_blocked", task_id=task_read.id, run_result=run_result,
            fact_safety_status=fact_safety_status,
        )

    draft_service = ContentDraftService(session)
    content_draft = await draft_service.create_from_final_post_authoring_result(task_read.id, run_result)

    return FinalPostGenerationOutcome(
        review_id=review_id, status="generated", task_id=task_read.id, run_result=run_result,
        content_draft=content_draft, fact_safety_status=fact_safety_status,
    )
