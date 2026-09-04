"""R2.10-RUNTIME-2 - flag-gated EVENT_RECAP automation scheduler.

Owns exactly four things (never reimplements any of them - always delegates to the real,
unmodified functions that already decide these questions):
  1. bounded candidate Story selection (`_select_candidate_story_ids()` - a plain SQL query only);
  2. shadow/readiness-only iteration (`services.event_recap.build_event_recap_candidate()`,
     force_shadow=False - the real, unmodified readiness decision);
  3. generation-mode delegation (`services.event_recap_processor.generate_recap_for_story()` -
     the real, unmodified processor, called exactly once per candidate Story);
  4. a bounded, deterministic `EventRecapScanResult` summary + one structured log line.

No RECAP readiness logic, no eventness rule, no media logic, no task-creation logic, and no
duplicate-detection logic is duplicated here - see the module docstring of each function above for
why this module never becomes "a second implementation" of any of them.

Three operational states, controlled by two INDEPENDENT flags (R2.10-RUNTIME-1's own design
correction - a single flag cannot express "observe real readiness naturally, without ever
creating a Story-generation task"):

  STATE 1 - OFF (`event_recap_scheduler_enabled=False`, the default in every environment today):
    `run_event_recap_scan()` returns `EventRecapScanResult(mode="disabled")` immediately - no
    Story query is ever issued, byte-identical to this module not existing at all.

  STATE 2 - SHADOW / READINESS OBSERVATION (`event_recap_scheduler_enabled=True`,
    `event_recap_generation_enabled=False`): for each bounded candidate Story, calls
    `build_event_recap_candidate(session, story, force_shadow=False, now=now,
    research_complete=True)` directly - the exact real production readiness decision, never a
    second/divergent one - and does NOTHING else with the result beyond counting it. Creates NO
    EditorialTask, performs NO synthesis, NO Tier-2B network media acquisition, and writes NOTHING
    to the database (see `_run_shadow_observation()`'s own docstring for the read-only proof).

  STATE 3 - GENERATION (`event_recap_scheduler_enabled=True`,
    `event_recap_generation_enabled=True`): for each bounded candidate Story, calls
    `generate_recap_for_story()` - the real, unmodified processor - EXACTLY ONCE. Readiness is
    decided by that call alone; this module never pre-checks or re-checks it (§8's own explicit
    "no double readiness in generation mode" requirement - `build_event_recap_candidate()` is
    NEVER called directly in this mode, only inside the processor's own call).

Invalid state (`event_recap_generation_enabled=True` while `event_recap_scheduler_enabled=False`)
fails closed: generation never runs (STATE 1's own early return already guarantees this), and a
single structured warning distinguishes this misconfiguration from the ordinary "everything off"
case - documented invariant: generation REQUIRES scheduler, never the reverse.

DISCLOSED LIMITATION (Rule A shadow observability, found during this phase's own forensic work,
not fixed here - out of this phase's own minimal-surface scope, services/event_recap.py is
explicitly not touched): `EventRecapCandidate.eventness_shadow` (R2.10G3-E1) is only ever computed
on the branch of `build_event_recap_candidate()` reached when `readiness.ready` is True - which,
under `force_shadow=False` (the real semantics this module deliberately uses per §9 - never
`force_shadow=True`), means a NOT_READY Story returns `candidate=None` and NEVER reaches eventness
shadow computation at all. RULE_A's own trigger shape (`unique_source_count<=1`) is structurally
BELOW `settings.recap_min_unique_sources` (2, the ordinary readiness floor) - a Story matching
RULE_A's shape can therefore never become READY under current thresholds, and so this module's own
STATE 2 will, as designed, almost never observe `rule_a_triggered=True` in practice. RULE_C has no
such structural conflict (source DOMAIN, not source COUNT) and can co-occur with a READY Story.
This is a real architectural finding for a future phase to weigh - not something this module
attempts to route around (e.g. by silently reaching for `force_shadow=True`, which §9 explicitly
forbids for this exact reason: that would no longer be "what production readiness would say
naturally").

Concurrency: this module assumes the CURRENT deployment topology - exactly one automation_worker
replica running exactly one sequential cycle loop (confirmed via `docker ps` during R2.10G3-E1S/
RUNTIME-1 - no other topology is deployed today). `services.workflow_service.create_task()`'s own
check-then-insert duplicate guard (used transitively by `generate_recap_for_story()`) has no DB-
level unique constraint or row lock - a disclosed, system-wide gap shared by every WorkflowType in
this codebase, not something this module introduces or fixes. Scaling automation_worker to
multiple replicas would require revisiting this - no speculative distributed lock is added here.

FAILED-task caveat (system-wide, unchanged, not fixed here): `workflow_service.create_task()`'s
duplicate guard matches ANY task status, including FAILED - once an EVENT_RECAP task exists and
later fails, that Story is permanently excluded from automatic re-generation by every future
cycle's own candidate query (`_select_candidate_story_ids()` excludes it exactly like it excludes
a COMPLETED one). This is the same accepted contract every other WorkflowType in this codebase
already lives with (see `services/workflow_service.py`'s own "Phase 15 M1" docstring) - not a new
risk this module introduces, and not silently fixed here.

AI-layer wiring caveat: `worker/main.py` does not currently assemble an AI integration layer (only
`worker/content_main.py` does, for content_worker). This module's own `capability_registry`
parameter therefore defaults to `None`; if `event_recap_generation_enabled` were ever set True
without ALSO updating `worker/main.py` to construct and pass a real registry, generation mode
fails closed (a single structured error log, zero Stories processed) rather than crashing or
silently constructing new infrastructure inside a periodic worker cycle. Wiring `worker/main.py`
itself (mirroring `worker/content_main.py`'s own established one-time-at-startup assembly) is
explicitly out of this phase's own minimal-surface scope (§3's own file list does not include
`worker/main.py`) and is left for the phase that actually enables generation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.story import Story
from database.session import async_session_factory
from schemas.workflow import WorkflowType
from services.cost_tracker import CostTracker
from services.event_recap import build_event_recap_candidate
from services.pricing_catalog import PricingCatalog

logger = logging.getLogger(__name__)

ScanMode = Literal["disabled", "shadow", "generation"]

# A reason-string substring exactly matching services.recap_event.evaluate_recap_readiness()'s own
# fixed cooling-reason format (`f"cooling window not elapsed ({...}m < {...}m)"`) - the ONLY
# sub-classification this module attempts within "not ready" under force_shadow=False, since that
# call's own return value otherwise collapses DISCOVERED/ACTIVE/COOLING/integrity-ineligible into
# one undifferentiated `candidate=None` (see this module's own docstring). A best-effort,
# string-matched signal, disclosed as such - never a clean state read.
_COOLING_REASON_SUBSTRING = "cooling window not elapsed"


@dataclass
class EventRecapScanResult:
    """Deterministic, bounded summary - never persisted to the database. Field groups:
    generation-mode counters mirror `EventRecapGenerationStatus` exactly (never a fabricated fifth
    status, §13); shadow-mode counters are additive-only diagnostics, all zero in generation mode
    and vice versa."""

    mode: ScanMode
    scanned: int = 0
    errors: int = 0

    # Generation-mode counters (mirrors EventRecapGenerationStatus exactly - no other status exists).
    story_not_found: int = 0
    not_ready: int = 0
    already_exists: int = 0
    generated: int = 0

    # Shadow-mode counters.
    ready_observed: int = 0
    not_ready_observed: int = 0
    cooling_observed: int = 0
    eventness_rule_a_triggered: int = 0
    eventness_rule_c_triggered: int = 0


async def _select_candidate_story_ids(session: AsyncSession, *, limit: int) -> list[UUID]:
    """Bounded, read-only, network-free. Excludes any Story whose `first_event_id` already has an
    EVENT_RECAP EditorialTask of ANY status - the exact same any-status exclusion semantics
    `services.event_recap_processor.find_event_recap_task_id()` already establishes (never a
    second, differently-scoped duplicate rule), expressed as one set-based EXISTS subquery instead
    of a per-row lookup - mirrors `worker/content_cycle.py::_select_eligible_events()`'s own
    `~exists(...)` duplicate-exclusion shape exactly. No full-table scan: ORDER BY + LIMIT are
    both evaluated DB-side."""
    stmt = (
        select(Story.id)
        .where(
            ~exists(
                select(1)
                .select_from(EditorialTask)
                .where(
                    EditorialTask.event_id == Story.first_event_id,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.EVENT_RECAP.value,
                )
            )
        )
        .order_by(Story.updated_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _run_shadow_observation(
    session: AsyncSession, story_ids: list[UUID], *, now: datetime,
) -> EventRecapScanResult:
    """STATE 2. Read-only: only ever calls `session.get()` (a SELECT) and
    `build_event_recap_candidate()` (itself read-only, network-free, LLM-free - see that
    function's own docstring/R2.10-RUNTIME-1's own empirical proof). Never calls
    `workflow_service.create_task()`, never calls `generate_recap_for_story()`, never touches
    Tier-2B media discovery. `force_shadow=False` - real production readiness semantics, never
    the offline-diagnostic `force_shadow=True` shape (§9's own explicit instruction)."""
    result = EventRecapScanResult(mode="shadow")
    for story_id in story_ids:
        result.scanned += 1
        try:
            story = await session.get(Story, story_id)
            if story is None:
                continue
            build_result = await build_event_recap_candidate(
                session, story, force_shadow=False, now=now, research_complete=True,
            )
            if build_result.candidate is not None:
                result.ready_observed += 1
                shadow = build_result.candidate.eventness_shadow
                if shadow is not None:
                    if shadow.rule_a_triggered:
                        result.eventness_rule_a_triggered += 1
                    if shadow.rule_c_triggered:
                        result.eventness_rule_c_triggered += 1
            else:
                result.not_ready_observed += 1
                reasons_text = " ".join(build_result.rejection_reasons).lower()
                if _COOLING_REASON_SUBSTRING in reasons_text:
                    result.cooling_observed += 1
        except Exception:  # noqa: BLE001 - one malformed Story must not abort the whole scan (§21)
            result.errors += 1
            await session.rollback()  # defensive: reset any aborted transaction state before the next Story
            logger.warning("event_recap_shadow_observation_failed", extra={"story_id": str(story_id)}, exc_info=True)
    return result


async def _run_generation(
    session: AsyncSession, story_ids: list[UUID], *,
    capability_registry: CapabilityRegistry, cost_tracker: CostTracker | None, pricing_catalog: PricingCatalog | None,
) -> EventRecapScanResult:
    """STATE 3. Calls `generate_recap_for_story()` - the single authoritative generation decision
    - EXACTLY ONCE per candidate Story (§8/§13). Never re-evaluates readiness itself. Never
    retries a Story within the same cycle regardless of the status returned.

    `generate_recap_for_story` is imported HERE, not at module level: that processor transitively
    imports `capabilities.executor.CapabilityExecutor`/`workflows.runner.WorkflowRunner` (the real
    LLM-execution machinery) - a module-level import would load that machinery into
    automation_worker's own process merely by importing `worker/cycle.py`, even when generation is
    permanently disabled (the default in every environment). Deferred so that machinery is only
    ever loaded into memory the first time generation mode actually runs."""
    from services.event_recap_processor import generate_recap_for_story

    result = EventRecapScanResult(mode="generation")
    for story_id in story_ids:
        result.scanned += 1
        try:
            outcome = await generate_recap_for_story(
                session, story_id, capability_registry=capability_registry,
                cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
            )
            if outcome.status == "story_not_found":
                result.story_not_found += 1
            elif outcome.status == "not_ready":
                result.not_ready += 1
            elif outcome.status == "already_exists":
                result.already_exists += 1
            elif outcome.status == "generated":
                result.generated += 1
        except Exception:  # noqa: BLE001 - one malformed Story must not abort the whole scan (§21)
            result.errors += 1
            await session.rollback()
            logger.exception("event_recap_generation_failed", extra={"story_id": str(story_id)})
    return result


async def run_event_recap_scan(
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    capability_registry: CapabilityRegistry | None = None,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
    now: datetime | None = None,
) -> EventRecapScanResult:
    """The one entry point `worker/cycle.py::run_automation_cycle()` calls, every cycle,
    unconditionally - this function itself decides whether to do anything at all, based on the two
    independent flags (§4/§5). `now` is accepted (never required) so tests can simulate cooling-
    window maturation without a real sleep or a new NewsEvent (§15) - every real caller
    (`worker/cycle.py`) leaves it `None`, resolved to the real current time."""
    if not settings.event_recap_scheduler_enabled:
        if settings.event_recap_generation_enabled:
            # §5's own required "clear structured warning" - the invalid-state case, distinguished
            # from the ordinary all-off case. Generation never runs either way (STATE 1's own
            # early return already guarantees that) - this is purely a diagnostic signal that a
            # misconfiguration exists, not a second gate.
            logger.warning(
                "event_recap_generation_enabled_without_scheduler_enabled",
                extra={"event_recap_scheduler_enabled": False, "event_recap_generation_enabled": True},
            )
        return EventRecapScanResult(mode="disabled")

    resolved_now = now or datetime.now(timezone.utc)

    async with session_factory() as session:
        story_ids = await _select_candidate_story_ids(session, limit=settings.event_recap_scan_limit)

        if settings.event_recap_generation_enabled:
            if capability_registry is None:
                # See module docstring's own "AI-layer wiring caveat" - fails closed, never
                # silently constructs new AI-layer infrastructure inside a periodic worker cycle.
                logger.error(
                    "event_recap_generation_enabled_but_no_capability_registry_supplied",
                    extra={"candidate_count": len(story_ids)},
                )
                result = EventRecapScanResult(mode="generation", errors=1)
            else:
                result = await _run_generation(
                    session, story_ids, capability_registry=capability_registry,
                    cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
                )
        else:
            result = await _run_shadow_observation(session, story_ids, now=resolved_now)

    logger.info(
        "event_recap_scan_finished",
        extra={
            "mode": result.mode, "scanned": result.scanned, "errors": result.errors,
            "story_not_found": result.story_not_found, "not_ready": result.not_ready,
            "already_exists": result.already_exists, "generated": result.generated,
            "ready_observed": result.ready_observed, "not_ready_observed": result.not_ready_observed,
            "cooling_observed": result.cooling_observed,
            "rule_a_shadow": result.eventness_rule_a_triggered, "rule_c_shadow": result.eventness_rule_c_triggered,
        },
    )
    return result
