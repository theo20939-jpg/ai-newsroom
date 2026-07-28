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
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from schemas.workflow import WorkflowType

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


async def reuse_prior_result(
    session: AsyncSession, source_task_id: UUID, capability_name: str
) -> dict[str, Any] | None:
    """Returns the source NEWS_ANALYSIS task's own persisted result for `capability_name`
    ("research" or "intelligence" only - `REUSABLE_CAPABILITIES`) if it exists and is
    well-formed. `None` otherwise - the safe-fallback signal telling the caller to perform a
    real capability call, exactly as if this module did not exist."""
    if capability_name not in REUSABLE_CAPABILITIES:
        return None
    source_task = await session.get(EditorialTask, source_task_id)
    if source_task is None:
        return None
    result = _extract_step_result(source_task.workflow, capability_name)
    if not _is_well_formed(capability_name, result):
        return None
    return result
