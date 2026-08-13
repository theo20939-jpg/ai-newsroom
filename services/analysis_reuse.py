"""API cost optimization (docs/api_cost_optimization_report.md): reuse a completed
`NEWS_ANALYSIS` task's own persisted `research`/`intelligence` results in `CONTENT_GENERATION`
instead of re-running those two capabilities from scratch. Every `CONTENT_GENERATION` task is
already only ever created for an event with a real, `COMPLETED` `NEWS_ANALYSIS` task
(`worker/content_cycle.py::_select_eligible_events()`) - that prior task's `research`/
`intelligence` step results are the exact same evidence, for the exact same `NewsEvent`, that a
fresh call would (re)produce.

Zero new provider calls, zero new DB writes: this module only ever reads `EditorialTask` rows
already loaded by the normal workflow. Always falls back to `None` (meaning: perform a real
capability call) whenever a valid prior result cannot be established - never guesses, never
reuses across a different event, never reuses a malformed/incomplete/failed prior result.

Research reuse/enforce interaction fix (docs/research_reuse_entity_normalization_checkpoint.md
§A): the "exact same evidence" premise above is only true when nothing about the event's
available evidence changed between the two calls. Real, confirmed failure (the Snapdragon C and
VK forensic cases): under `article_acquisition_mode == "enforce"`, a NEWS_ANALYSIS-stage
`research` result can be produced BEFORE the article is ever acquired (acquisition happens later,
during CONTENT_GENERATION's own flow, per services/evidence_package.py's own docstring) - reusing
that stale result silently discards the richer, freshly-built `article_evidence_text` context
`capabilities/executor.py` had already assembled for this exact call, and Copywriting never sees
what the article actually said. The fix below reuses only already-existing metadata (the source
NEWS_ANALYSIS task's own `updated_at`, the acquisition row's own `created_at` and
`effective_completeness_status` - both already read elsewhere, by services/evidence_package.py)
to detect this one specific case and force a fresh call instead - no new cache subsystem, no
prompt/input hash, no change to Research's or Copywriting's own semantics."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask, TaskStatus
from schemas.workflow import WorkflowType
from services.article_acquisition import get_effective_acquisition
from services.evidence_package import TRUSTED_FULL_ARTICLE_STATUSES

logger = logging.getLogger(__name__)

# The minimal shape each capability's own real output always carries on success (mirrors each
# capability's own `expected_output_keys` declaration - see capabilities/research_capability.py
# / capabilities/intelligence_capability.py). A prior result missing any of these is treated as
# malformed, never reused.
_REQUIRED_KEYS_BY_CAPABILITY: dict[str, tuple[str, ...]] = {
    "research": ("facts", "confidence", "gaps"),
    "intelligence": ("significance", "angle", "audience_relevance", "recommendation"),
}

REUSABLE_CAPABILITIES = frozenset(_REQUIRED_KEYS_BY_CAPABILITY)


async def find_source_news_analysis_task_id(session: AsyncSession, event_id: UUID) -> UUID | None:
    """The most recent COMPLETED NEWS_ANALYSIS task for this exact `event_id` - never a
    different event's task, so cross-event reuse is structurally impossible. `None` when no such
    task exists (e.g. this event's own NEWS_ANALYSIS task somehow isn't COMPLETED yet - should
    not happen given content_cycle's own eligibility gate, but handled safely regardless)."""
    stmt = (
        select(EditorialTask.id)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.status == TaskStatus.COMPLETED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _extract_step_result(workflow: dict[str, Any] | None, capability_name: str) -> dict[str, Any] | None:
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") != capability_name:
            continue
        if step_result.get("status") != "SUCCESS":
            return None
        result = step_result.get("result")
        return result if isinstance(result, dict) else None
    return None


def _is_well_formed(capability_name: str, result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    required = _REQUIRED_KEYS_BY_CAPABILITY.get(capability_name)
    if required is None:
        return False
    return all(key in result for key in required)


async def _acquisition_postdates(session: AsyncSession, event_id: UUID, cutoff: datetime) -> bool:
    """True only when a successful, trusted-tier acquisition (see `TRUSTED_FULL_ARTICLE_STATUSES`)
    exists for this event AND was produced strictly after `cutoff`. `cutoff` is the source
    NEWS_ANALYSIS task's own `updated_at` - a safe, conservative upper bound on when its `research`
    step actually finished (research always completes before the rest of that same task, so real
    staleness can only be understated here, never overstated). Never true when
    `article_acquisition_mode != "enforce"` (no upgraded evidence context exists to make a cached
    result stale in the first place - byte-identical to today whenever `enforce` isn't active) or
    when no acquisition exists yet, or when the acquisition that does exist did not reach a
    trusted completeness tier (a failed/weak acquisition adds no richer evidence - reuse remains
    exactly as safe as it always was)."""
    if settings.article_acquisition_mode != "enforce":
        return False
    acquisition = await get_effective_acquisition(session, event_id)
    if acquisition is None or acquisition.effective_completeness_status not in TRUSTED_FULL_ARTICLE_STATUSES:
        return False
    return acquisition.created_at > cutoff


async def reuse_prior_result(
    session: AsyncSession, source_task_id: UUID, capability_name: str, *, event_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Returns the source NEWS_ANALYSIS task's own persisted result for `capability_name`
    ("research" or "intelligence" only - `REUSABLE_CAPABILITIES`) if it exists, is well-formed,
    and is not stale relative to newer evidence (see `_acquisition_postdates()`). `None`
    otherwise - the safe-fallback signal telling the caller to perform a real capability call,
    exactly as if this module did not exist.

    `event_id` is optional only so this function's existing contract (usable with just a task id)
    never breaks - omitting it simply skips the staleness check (matches the pre-fix behavior
    exactly), but every real caller (`capabilities/executor.py::_try_reuse()`) always supplies it."""
    if capability_name not in REUSABLE_CAPABILITIES:
        return None
    source_task = await session.get(EditorialTask, source_task_id)
    if source_task is None:
        return None
    result = _extract_step_result(source_task.workflow, capability_name)
    if not _is_well_formed(capability_name, result):
        return None
    if (
        capability_name == "research"
        and event_id is not None
        and await _acquisition_postdates(session, event_id, source_task.updated_at)
    ):
        return None
    return result
