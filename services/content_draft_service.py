"""ContentDraftService: the only component authorized to create a ContentDraft row (Phase 10,
docs/phase10_production_content_pipeline_architecture_contract.md §7/§7.1).

Class-based, constructor-injected with the same AsyncSession the caller already used for
WorkflowRunner.run() - mirrors services/budget_guard.py's RedisBudgetGuard constructor-injection
shape (§7.1's own precedent), not the plain-function style of services/workflow_service.py.

Called by the caller (Milestone 4's CLI script) only after WorkflowRunner.run() has returned a
COMPLETED WorkflowRunResult - never before, never for a FAILED result (§7.1, §9). This module
does not itself branch on `result.status`: a FAILED run has no "copywriting" step_results entry
to find (the chain never reaches that step, or copywriting itself failed), so calling this on a
FAILED result fails loudly via _copywriting_output()'s own lookup, rather than silently
persisting wrong or partial data.
"""
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from schemas.content_draft import ContentDraftRead
from schemas.workflow import WorkflowRunResult


def _copywriting_output(result: WorkflowRunResult) -> dict[str, Any]:
    """Locate the "copywriting" entry in `result.step_results` (a list, per
    schemas/workflow.py's WorkflowStepResult shape) and return its `.result` dict.

    Raises ValueError if absent - a real, reachable case only when this is called on a result
    that never reached a successful "copywriting" step (misuse of the calling convention above),
    never silently substituted with empty/None values (Contract §7.1: no reformatting, no
    silent discarding of required structured content)."""
    for step_result in result.step_results:
        if step_result.step_name == "copywriting" and step_result.status == "SUCCESS":
            if step_result.result is None:
                raise ValueError(
                    f"WorkflowRunResult for task {result.task_id} has a SUCCESS 'copywriting' "
                    "step with no result payload."
                )
            return step_result.result
    raise ValueError(
        f"WorkflowRunResult for task {result.task_id} has no successful 'copywriting' step "
        "result - create_from_result() MUST only be called on a COMPLETED result."
    )


def _fact_safety_status(result: WorkflowRunResult) -> str | None:
    """Phase 15 M5: locate the "quality" step's `fact_safety.status` ("pass"/"review"/"block"),
    if present - `None` when fact safety never ran (`fact_safety_mode == "off"`, or a historical
    task predating M5) or the "quality" step itself is absent, mirroring `_copywriting_output()`'s
    own lookup shape but never raising: whether fact safety produced a result is optional
    metadata for this function's own status-setting decision below, not a requirement for
    ContentDraft persistence to succeed at all (that contract remains "copywriting" alone,
    unchanged from Phase 10)."""
    for step_result in result.step_results:
        if step_result.step_name == "quality" and step_result.status == "SUCCESS" and step_result.result:
            fact_safety = step_result.result.get("fact_safety")
            if isinstance(fact_safety, dict):
                status = fact_safety.get("status")
                if isinstance(status, str):
                    return status
    return None


def _draft_status_for(fact_safety_status: str | None) -> str:
    """Phase 15 M5.8 enforcement design: outside `fact_safety_mode == "enforce"`, this always
    returns "draft" - byte-identical to pre-M5 behavior (shadow mode must never change delivery
    or persistence, per M5.6). Only in "enforce" mode does a "review"/"block" fact-safety verdict
    change the persisted `ContentDraft.status` - free-text column (`database/models/
    content_draft.py`'s own documented "not a constrained enum" design), so this needs no
    migration. This is visibility, not deletion: the draft row, its full text, and the
    fact-safety findings in `EditorialTask.workflow` all remain fully queryable - only
    `worker/content_cycle.py`'s own delivery decision (a separate change) actually withholds the
    live Telegram send."""
    if settings.fact_safety_mode != "enforce" or fact_safety_status is None:
        return "draft"
    if fact_safety_status == "block":
        return "draft_blocked_fact_safety"
    if fact_safety_status == "review":
        return "draft_review_fact_safety"
    return "draft"


def _to_read_schema(draft: ContentDraft) -> ContentDraftRead:
    """Build ContentDraftRead from an ORM row - mirrors services/workflow_service.py's
    _to_read_schema() shape exactly."""
    return ContentDraftRead(
        id=draft.id,
        task_id=draft.task_id,
        type=draft.type,
        title=draft.title,
        body=draft.body,
        # ContentDraft.hashtags is typed Mapped[dict | None] (pre-existing ORM imprecision -
        # database/models/content_draft.py's own JSON column stores whatever's assigned; this
        # Capability's output schema (Contract §5) guarantees a list at runtime, never a dict).
        hashtags=draft.hashtags,  # type: ignore[arg-type]
        version=draft.version,
        status=draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


class ContentDraftService:
    """Constructed with the same AsyncSession the caller already used for
    WorkflowRunner.run() - never opens a new session or connection (Contract §7.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_result(self, task_id: UUID, result: WorkflowRunResult) -> ContentDraftRead:
        """Create exactly one ContentDraft row from `result`'s "copywriting" step output.

        Owns its own, single, deterministic commit - a separate transaction from
        WorkflowRunner.run()'s own already-closed final commit. Raises uncaught on failure
        (Contract §7.1: MUST NOT swallow). Phase 10 writes exactly one status ("draft"), one
        version (1), one type (ContentType.POST) - no migration, no schema change. Phase 15 M5:
        `status` varies from "draft" only when `fact_safety_mode == "enforce"` AND the "quality"
        step's fact-safety verdict is "review"/"block" - see `_draft_status_for()`'s own
        docstring. In every other case (mode "off"/"shadow", or a "pass" verdict) this is
        byte-identical to the pre-M5 behavior.
        """
        copywriting_output = _copywriting_output(result)

        draft = ContentDraft(
            task_id=task_id,
            type=ContentType.POST,
            title=copywriting_output["title"],
            body=copywriting_output["body"],
            hashtags=copywriting_output["hashtags"],
            version=1,
            status=_draft_status_for(_fact_safety_status(result)),
        )
        self._session.add(draft)
        await self._session.commit()
        await self._session.refresh(draft)
        return _to_read_schema(draft)
