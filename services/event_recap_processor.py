"""NINJA PULSE RECAP Phase R2 integration, Phase C.0: the one callable that turns a Story into a
completed (or FAILED) EVENT_RECAP `EditorialTask`. Direct structural sibling of services.
telegraph_article_processor.generate_article_for_researched_proposal() - same shape, same
discipline, adapted for the one real difference: EVENT_RECAP's input is already a Story directly
(no separate proposal/shortlist indirection - services/event_recap.py's own R1/R2 layer already
does the "is this Story worth recapping" determination deterministically, inside the workflow
itself, not as a caller-side artifact to look up first).

`generate_recap_for_story(story_id)` is the ONLY entry point this checkpoint exposes - nothing in
this codebase calls it automatically, exactly mirroring services.telegraph_research_processor.
process_approved_telegraph_proposal()'s own dormancy discipline (and services.
telegraph_article_processor.py's own identical one). A future checkpoint decides how/when a Story
is picked up for recap generation (scheduler/worker/CLI - explicitly out of this checkpoint's
scope).

Exactly-once mechanism (deliberately NOT a new consumed_at-style claim column, mirroring
services.telegraph_article_processor.py's own identical reasoning): services.workflow_service.
create_task()'s own existing one-task-per-(event_id, workflow_type) guard is reused directly - an
EVENT_RECAP task is anchored to `story.first_event_id` (the same anchor
`services.event_recap.EventRecapCandidate.anchor_event_id` already uses), so a second attempt at
recapping the same Story raises the same, existing `DuplicateActiveTaskError` any other
duplicate-task attempt in this codebase already raises. This function treats that exception as
"already handled" (looks up and returns the existing task instead of creating a second one) -
never as a hard failure, and never by retrying/overwriting.

Phase G.1 (race-safe readiness gate): unlike the Phase C.0 discipline this module used to follow
(let an ineligible Story reach `CREATED` and fail closed inside the executor), readiness is now
decided HERE, before any `EditorialTask` is created. Reason (Phase G.0.1/G.0.2's own forensic
findings): `services.workflow_service.create_task()`'s duplicate-task guard is PERMANENT and
matches a task of ANY status, including `FAILED` - a NOT_READY Story that creates a `FAILED` task
would be locked out of ever being recapped again, even after it naturally matures into a genuinely
READY Story later. `build_event_recap_candidate()` is deterministic and free (zero LLM/network
calls) - computing it once here, before task creation, costs nothing extra and is the only way to
keep a NOT_READY Story retry-able.

Race-safety (Phase G.0.2): the candidate is built EXACTLY ONCE per call to this function. If READY,
that SAME in-memory `EventRecapCandidate` - never a second, independently-requeried one - is
threaded through to `CapabilityExecutor` (via its `precomputed_event_recap_candidate` constructor
argument) for synthesis. A second, independent rebuild inside the executor would open a new,
snapshot-inconsistent transaction (`create_task()` commits in between) that could see a Story
update the first check never saw, flipping an already-READY decision to NOT_READY mid-run and
permanently poisoning the task via the same duplicate guard this whole design exists to avoid.

Disclosed, pre-existing limitation (not introduced by this checkpoint, mirrors services.
telegraph_article_processor.py's own identical disclosure): services.workflow_service.
create_task()'s own duplicate-active-task guard is a check-then-insert, not a single atomic
statement/unique constraint - two genuinely concurrent callers could theoretically both pass the
check and both insert a task for the same (event_id, workflow_type) before either commits. Out of
this checkpoint's scope to fix.

This file calls `services.event_recap.build_event_recap_candidate()` (Phase G.1, unmodified) and
`capabilities.executor.CapabilityExecutor`'s new optional `precomputed_event_recap_candidate`
constructor argument (Phase G.1, additive-only default `None` - every other caller/workflow type
unaffected) - no workflow definition, worker/scheduler, Telegram, or DB model is touched; this
file still only orchestrates the already-existing EditorialTask/WorkflowRunner/CapabilityExecutor
machinery for one more WorkflowType, exactly as services/telegraph_article_processor.py already
does for TELEGRAPH_ARTICLE.

Phase H.1 (Story media foundation): `EventRecapCandidate.selected_media` (services/event_recap.py,
computed inside the SAME single `build_event_recap_candidate()` call this module already made for
readiness) is persisted into `EditorialTask.workflow["step_results"]` as one extra, deterministic
entry - see `_persist_selected_media()`'s own docstring for why that is the safe slot (`workflows/
runner.py`'s `WorkflowExecutionState.model_validate()` forbids an unknown TOP-LEVEL key, so this is
not a new `task.workflow["event_recap_media"]` field). No Telegram rendering - this checkpoint only
makes the Story-level confirmed-membership pick durable and re-derivable later, exactly as Phase
G.1 did for the recap text itself.

Phase H.3B (Tier 2B, `discover_event_recap_media_if_needed()`) and Phase H.3C (Tier 3, `render_
branded_fallback_media()`) extend Phase H.1's media pick into a three-tier fallback chain, tried in
order, each only when every earlier tier found nothing: (1) confirmed Story media pool, (2)
confirmed-source article re-acquisition (real network, zero LLM), (3) a deterministic NINJA PULSE
branded card (zero network, zero LLM, zero paid image-generation call - Pillow only, `services.
brand_renderer.render_recap_fallback_card()`). All three run BEFORE `workflow_service.create_task()
`, against the SAME single `build_event_recap_candidate()` snapshot - `dataclasses.replace()`
updates only `selected_media`, never re-triggering readiness/evidence. A text-only review remains
the last-resort fail-soft outcome for a technical failure at every tier, never the expected result
of an ordinary Story simply lacking a source photo.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowStepResult, WorkflowType
from services import workflow_service
from services.brand_renderer import render_recap_fallback_card
from services.cost_tracker import CostTracker
from services.event_recap import (
    _MAX_MEDIA_PER_EVENT,
    _NO_MEDIA_PLAN,
    _select_representative_media,
    derive_recap_visual_subject,
    EventRecapCandidate,
    SelectedMediaItem,
    SelectedMediaPlan,
    build_event_recap_candidate,
    serialize_selected_media_plan,
)
from services.image_intelligence import run_shadow_discovery
from services.image_persistence import EditorialImageCandidate, _get_storage, get_editorial_image_candidates
from services.pricing_catalog import PricingCatalog
from workflows.errors import DuplicateActiveTaskError
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

# Reasoned default, matching services.telegraph_article_processor's own identical reasoning: a
# deliberate, human-triggered background task, never time-sensitive.
_EVENT_RECAP_TASK_PRIORITY = TaskPriority.C

# Phase H.3B: bounded "how many DIFFERENT effective events to attempt discovery for in one Story",
# not to be confused with services.event_recap._MAX_MEDIA_PER_EVENT (bounded candidates PER event,
# a distinct concern). No existing config/pattern in this codebase caps "events per Story" for any
# media purpose, so this is deliberately the smallest reasonable bound (mirrors _MAX_MEDIA_PER_
# EVENT's own small-bounded-by-design magnitude) rather than a new, larger config surface - never a
# mass crawler. Only reached at all when Tier 1 (H.1) found zero eligible media across the WHOLE
# effective evidence set, so 3 real network fetches is a real, disclosed cost, not a hidden one.
_MAX_MEDIA_DISCOVERY_EVENTS = 3

# Phase H.1: NOT a WorkflowDefinition step (workflows/definitions/event_recap.py is untouched -
# still exactly one real step, "synthesize_recap") - a plain, pre-populated `step_results` entry
# the processor writes directly, before `WorkflowRunner.run()` is ever called. Safe specifically
# because `WorkflowRunner._execute_steps()` filters `remaining_steps` by `definition.steps` names
# only (workflows/runner.py) - an extra `step_results` entry whose `step_name` is not in the
# definition is simply carried forward untouched, never mistaken for a real step to (re)execute.
# `WorkflowExecutionState` itself (`extra="forbid"`) only forbids unknown TOP-LEVEL fields, not
# extra list entries of an already-declared shape - this is why the plan is not (and cannot safely
# be) a new top-level `task.workflow["event_recap_media"]` key (Phase H.0.2's own proposal,
# corrected here after checking the actual `WorkflowExecutionState.model_validate()` call in
# `workflows/runner.py::run()`, which would reject an unknown top-level key outright).
_MEDIA_SELECTION_STEP_NAME = "select_recap_media"

EventRecapGenerationStatus = Literal["story_not_found", "not_ready", "already_exists", "generated"]


@dataclass(frozen=True)
class EventRecapGenerationOutcome:
    story_id: UUID
    status: EventRecapGenerationStatus
    task_id: UUID | None
    run_result: WorkflowRunResult | None
    # Phase G.1: non-empty only for status="not_ready" - the exact
    # `EventRecapBuildResult.rejection_reasons` the readiness pre-check produced (never a parallel
    # reason-code system). Empty tuple for every other status, including "generated".
    readiness_reasons: tuple[str, ...] = ()


async def _persist_selected_media(session: AsyncSession, task_id: UUID, candidate: EventRecapCandidate) -> None:
    """Phase H.1: writes the SAME `candidate.selected_media` already computed inside the single
    `build_event_recap_candidate()` call this run made (never recomputed, never a second Story/
    image query) into `EditorialTask.workflow["step_results"]`, as one extra, pre-populated,
    deterministic entry - BEFORE `WorkflowRunner.run()` ever touches this task. Keeps
    `synthesize_recap`'s own result dict exactly `{recap_title, recap_summary, key_takeaways,
    uncertainty_notes}` (the module's own explicit invariant) - media is a sibling `step_results`
    entry, never mixed into the LLM-structured-output result. `session.flush()` only (never
    `commit()` here) - the very next thing this function's caller does is `WorkflowRunner.run()`,
    which re-reads `task.workflow` from the SAME in-memory, identity-mapped ORM object and commits
    its own claim-update in the same transaction, so this write is durable without an extra,
    premature commit boundary."""
    task = await session.get(EditorialTask, task_id)
    assert task is not None, "task_id came from create_task() in the same session/transaction"
    now = datetime.now(timezone.utc)
    media_step_result = WorkflowStepResult(
        step_name=_MEDIA_SELECTION_STEP_NAME, status="SUCCESS", attempt=1,
        started_at=now, finished_at=now, error=None,
        result=serialize_selected_media_plan(candidate.selected_media),
    )
    workflow = dict(task.workflow or {})
    workflow["step_results"] = [
        media_step_result.model_dump(mode="json"), *workflow.get("step_results", []),
    ]
    task.workflow = workflow
    await session.flush()


def _effective_event_ids(candidate: EventRecapCandidate) -> list[UUID]:
    """Phase H.3B: the exact confirmed/origin-projected evidence-set event ids the SINGLE
    `build_event_recap_candidate()` call already established - `services.recap_event.
    cluster_announcements()`'s own `event_ids`, threaded through into every `AnnouncementSummary.
    member_event_ids` (services/event_recap.py::_build_announcement_summaries()). Union across all
    announcements, in announcement order, deduped. Never a second Story/NewsEventStoryLink query -
    an `uncertain_match` event that `build_event_recap_candidate()` itself did not fold into the
    candidate's own announcements (directly, or via R2.9 origin projection) can never appear here,
    satisfying the "no automatic uncertain_match use" invariant structurally, not by a new check."""
    seen: dict[UUID, None] = {}
    for announcement in candidate.announcements:
        for event_id in announcement.member_event_ids:
            seen.setdefault(event_id, None)
    return list(seen.keys())


async def _attempt_media_discovery_for_event(session: AsyncSession, event_id: UUID) -> None:
    """Phase H.3B (Tier 2B): re-acquires ONE effective event's own already-known article URL
    through the existing, unmodified `services.image_intelligence.run_shadow_discovery()` - no new
    HTTP client, HTML parser, quality/relevance logic, or persistence path. Skips outright if this
    event already has ANY `ImageCandidateRecord` row (eligible or not) - re-fetching the same page
    would deterministically reproduce the same result, so a prior attempt (successful or not) is
    never repeated ("не re-fetch все страницы без причины"). Fail-soft, never raises: a missing
    NewsEvent/NewsSource row, or any exception from `run_shadow_discovery()` itself (timeout, SSRF
    rejection, fetch failure, malformed HTML, or anything unexpected), is logged and treated as
    "found nothing" for this event - never escapes to the caller."""
    try:
        existing_count = (
            await session.execute(
                select(func.count()).select_from(ImageCandidateRecord).where(ImageCandidateRecord.news_event_id == event_id)
            )
        ).scalar_one()
        if existing_count > 0:
            return

        event = await session.get(NewsEvent, event_id)
        if event is None:
            return
        source = await session.get(NewsSource, event.source_id)
        if source is None:
            return

        await run_shadow_discovery(
            event_id=event.id, source_type=source.type, content=event.content, article_url=event.url,
            mode="shadow", event_title=event.title, source_name=source.name, session=session,
        )
    except Exception:  # noqa: BLE001 - fail-soft Tier-2B boundary, never blocks recap generation
        logger.warning(
            "event_recap_media_discovery_attempt_failed", extra={"event_id": str(event_id)}, exc_info=True,
        )


async def discover_event_recap_media_if_needed(
    session: AsyncSession, candidate: EventRecapCandidate,
) -> SelectedMediaPlan:
    """Phase H.3B (Tier 2B): only ever meaningfully called when `candidate.selected_media.tier ==
    "none"` (the caller's own responsibility - this function does not re-check it, matching the
    G.1/H.1 precedent of the caller owning its own gating). Attempts real, bounded, SSRF-safe
    article re-acquisition (`_attempt_media_discovery_for_event()`) for up to
    `_MAX_MEDIA_DISCOVERY_EVENTS` of the candidate's own effective evidence-set events
    (`_effective_event_ids()` - never a second Story query), then re-reads whatever
    `ImageCandidateRecord` rows now exist for that SAME event set and re-ranks them through the
    existing, unmodified `services.event_recap._select_representative_media()` - no new ranking
    algorithm. Returns a plan with `tier="discovered"` if a real, eligible candidate resulted, or
    the ordinary `tier="none"` plan (never raises) if nothing did - the caller decides whether to
    adopt it via `dataclasses.replace()`."""
    event_ids = _effective_event_ids(candidate)[:_MAX_MEDIA_DISCOVERY_EVENTS]

    for event_id in event_ids:
        await _attempt_media_discovery_for_event(session, event_id)

    image_pool: list[tuple[UUID, EditorialImageCandidate]] = []
    for event_id in event_ids:
        try:
            candidates = await get_editorial_image_candidates(session, news_event_id=event_id, limit=_MAX_MEDIA_PER_EVENT)
        except Exception:  # noqa: BLE001 - fail-soft: a re-query failure is "found nothing" for this event
            logger.warning(
                "event_recap_media_discovery_requery_failed", extra={"event_id": str(event_id)}, exc_info=True,
            )
            continue
        image_pool.extend((event_id, candidate) for candidate in candidates)

    plan = _select_representative_media(image_pool)
    if plan.representative is None:
        return plan
    return replace(plan, tier="discovered")


def render_branded_fallback_media(candidate: EventRecapCandidate) -> SelectedMediaPlan:
    """Phase H.3C (Tier 3): the LAST resort before a text-only review - only ever meaningfully
    called when both Tier 1 (H.1) and Tier 2B (H.3B) already found nothing (the caller's own
    responsibility, matching the same "caller owns its own gating" precedent `discover_event_
    recap_media_if_needed()` already established). A deterministic, zero-network, zero-LLM,
    zero-paid-image-call branded card - `services.brand_renderer.render_recap_fallback_card()`
    (Pillow only, official NNJ assets, no AI image generation) fed by `services.event_recap.
    derive_recap_visual_subject()` (deterministic entity/title extraction off the SAME candidate,
    no new LLM call). The rendered bytes are stored through the same `integrations.storage.
    image_storage.ImageStorage` abstraction Tier 1/2B candidates already resolve through (`services.
    image_persistence._get_storage()`, reused unmodified) - never a new storage mechanism.

    Sync, not async: both the renderer (pure Pillow/CPU) and the local storage write are
    synchronous, mirroring how `worker/content_cycle.py` already calls `render_branded_media()`
    directly from async code with no executor wrapping.

    Fail-soft by construction: a missing brand asset, a Pillow exception, or a storage failure is
    logged and returns the ordinary `tier="none"` plan - never raises, never blocks recap
    generation, never turns a cosmetic rendering problem into a task failure."""
    try:
        subject = derive_recap_visual_subject(candidate)
        render_result = render_recap_fallback_card(subject)
        if not render_result.success or render_result.image_bytes is None:
            logger.warning(
                "event_recap_branded_fallback_render_failed",
                extra={"story_id": str(candidate.story_id), "reason": render_result.fallback_reason},
            )
            return _NO_MEDIA_PLAN

        image_bytes = render_result.image_bytes
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        stored = _get_storage().store_validated_image(
            image_bytes, sha256=sha256, image_format="JPEG", max_bytes=settings.meme_image_max_bytes,
        )
        return SelectedMediaPlan(
            tier="branded_fallback",
            representative=SelectedMediaItem(
                media_type="image", recommended_role="hero",
                storage_key=stored.storage_key, sha256=stored.sha256,
            ),
        )
    except Exception:  # noqa: BLE001 - fail-soft Tier-3 boundary, never blocks recap generation
        logger.warning(
            "event_recap_branded_fallback_failed", extra={"story_id": str(candidate.story_id)}, exc_info=True,
        )
        return _NO_MEDIA_PLAN


async def find_event_recap_task_id(session: AsyncSession, event_id: UUID) -> UUID | None:
    """The most recent EVENT_RECAP task for this exact event_id, in any status - mirrors
    services.telegraph_article_processor.find_article_task_id()'s own established shape exactly
    (identical query pattern, different workflow_name scope: any status here, since a caller may
    want to inspect a RUNNING/FAILED recap task too, not only a COMPLETED one)."""
    stmt = (
        select(EditorialTask.id)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.EVENT_RECAP.value,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def generate_recap_for_story(
    session: AsyncSession,
    story_id: UUID,
    *,
    capability_registry: CapabilityRegistry,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> EventRecapGenerationOutcome:
    """Story lookup -> existing-task check -> readiness pre-check -> create (or find existing)
    EditorialTask -> run its EVENT_RECAP workflow. Returns without ever reaching the LLM Gateway
    if the Story does not exist, a task already exists for it, or it is not yet recap-worthy
    (structural cost boundary, exactly like services.telegraph_article_processor.py's own
    claim-first discipline, extended in Phase G.1 with a real readiness gate)."""
    story = await session.get(Story, story_id)
    if story is None:
        return EventRecapGenerationOutcome(
            story_id=story_id, status="story_not_found", task_id=None, run_result=None,
        )

    # Phase G.1: check for an existing task BEFORE building a candidate at all - a Story already
    # claimed (in any status) needs no readiness recomputation, mirroring find_event_recap_task_id()
    # 's own established "any status" duplicate-detection contract.
    existing_task_id = await find_event_recap_task_id(session, story.first_event_id)
    if existing_task_id is not None:
        return EventRecapGenerationOutcome(
            story_id=story_id, status="already_exists", task_id=existing_task_id, run_result=None,
        )

    # Phase G.1: built exactly once, before the EditorialTask exists. `research_complete=True` -
    # R2 EVENT_RECAP has no separate recap-research stage; its deterministic evidence bundle is
    # the complete input contract, therefore readiness treats research as satisfied for this
    # processor path. `force_shadow=False` - production/manual EVENT_RECAP no longer bypasses
    # readiness.
    build_result = await build_event_recap_candidate(session, story, force_shadow=False, research_complete=True)
    if build_result.rejected or build_result.candidate is None:
        return EventRecapGenerationOutcome(
            story_id=story_id, status="not_ready", task_id=None, run_result=None,
            readiness_reasons=tuple(build_result.rejection_reasons),
        )

    # Phase H.3B (Tier 2B): build_event_recap_candidate() itself is called exactly once above -
    # this only ENRICHES the media portion of that SAME candidate when Tier 1 (H.1) found nothing.
    # dataclasses.replace() produces a new object with every factual/readiness/evidence field
    # copied verbatim from the single build - never a second build_event_recap_candidate() call,
    # never a re-evaluated readiness.ready.
    candidate = build_result.candidate
    if candidate.selected_media.tier == "none":
        discovered_plan = await discover_event_recap_media_if_needed(session, candidate)
        if discovered_plan.representative is not None:
            candidate = replace(candidate, selected_media=discovered_plan)

    # Phase H.3C (Tier 3): only reached if Tier 1 AND Tier 2B both found nothing - the LAST
    # resort before a text-only review. Deterministic, zero-network, zero-LLM, zero-paid-image-
    # call - never blocks generation on failure (render_branded_fallback_media()'s own fail-soft
    # contract).
    if candidate.selected_media.tier == "none":
        fallback_plan = render_branded_fallback_media(candidate)
        if fallback_plan.representative is not None:
            candidate = replace(candidate, selected_media=fallback_plan)

    try:
        task_read = await workflow_service.create_task(
            session,
            EditorialTaskCreate(
                event_id=story.first_event_id, workflow_type=WorkflowType.EVENT_RECAP,
                priority=_EVENT_RECAP_TASK_PRIORITY,
            ),
        )
    except DuplicateActiveTaskError:
        # Concurrency safety-net only (disclosed, pre-existing check-then-insert race - see this
        # module's own docstring): the pre-check above found nothing, but another concurrent
        # caller won the race and created a task in between.
        existing_task_id = await find_event_recap_task_id(session, story.first_event_id)
        return EventRecapGenerationOutcome(
            story_id=story_id, status="already_exists", task_id=existing_task_id, run_result=None,
        )

    # Phase H.1/H.3B: persisted from the SAME candidate the readiness decision already used - only
    # `selected_media` may differ from build_result.candidate (Tier 2B enrichment above); every
    # other field is byte-identical to the single build() call, before the workflow runs, so it
    # survives regardless of what synthesize_recap itself does.
    await _persist_selected_media(session, task_read.id, candidate)

    # Phase G.1/H.3B: the SAME candidate object (readiness/evidence untouched, media possibly
    # enriched above) - never rebuilt, never a second build_event_recap_candidate() call.
    executor = CapabilityExecutor(
        session, task_read.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
        precomputed_event_recap_candidate=candidate,
    )
    runner = WorkflowRunner(executor)
    run_result = await runner.run(session, task_read.id)

    return EventRecapGenerationOutcome(
        story_id=story_id, status="generated", task_id=task_read.id, run_result=run_result,
    )
