"""Phase I.2, Part A/B/C/E: the eligibility gate a `ContentDraft` must pass before a Final Post
Preview is ever created or sent to Telegram. Pure DB reads only - no Telegram, no LLM, no mutation.

Deliberately a standalone module (not folded into `services/final_post_review_service.py` or
`services/final_post_review_notifier.py`): both the manual CLI worker and the notifier need this
exact same check, and it must be independently testable without any Telegram/aiogram dependency.

FAIL-CLOSED, never a best-effort guess: every branch below returns a specific `reason` code the
first time ANY required invariant is missing - Part A's own 9 checks (A-I), plus Part C (media
required) and Part E (source required), are evaluated in a fixed order so a genuinely LEGACY
`ContentDraft` (Pixel `2c4d32e5-...`, Silver Lake/Workday V2 `603cfbab-...` - both created before
Phase I.1.4's own durable `final_post_fact_safety`/`authoring_prompt_version` additions) always
fails at `"audit_snapshot_missing"` specifically, before ever reaching the media/source checks -
Phase I.2's own explicit "do not silently pretend a legacy draft is audited" requirement. Neither
draft, nor any other pre-I.1.4 task, is ever mutated or backfilled by this module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus
from schemas.workflow import WorkflowType

EligibilityReason = Literal[
    "content_draft_not_found",
    "not_draft_status",
    "task_not_found",
    "not_final_post_authoring",
    "audit_snapshot_missing",
    "fact_safety_blocked",
    "source_review_not_approved",
    "media_missing",
    "source_missing",
]


@dataclass(frozen=True)
class FinalPostPreviewEligibility:
    """`eligible=False` always sets `reason` to one of `EligibilityReason` above and leaves every
    other field `None` - a caller must never send anything to Telegram, and must never create a
    `FinalPostReview` row, when `eligible` is `False`. `eligible=True` also returns the already-
    resolved `task`/`final_post_source`/`authored_output`/`fact_safety_result` this check itself
    loaded, so the notifier never re-fetches or re-derives anything this function already did."""

    eligible: bool
    reason: EligibilityReason | None
    task: EditorialTask | None = None
    final_post_source: dict[str, Any] | None = None
    authored_output: dict[str, Any] | None = None
    fact_safety_result: dict[str, Any] | None = None


def _ineligible(reason: EligibilityReason) -> FinalPostPreviewEligibility:
    return FinalPostPreviewEligibility(eligible=False, reason=reason)


def _find_step_result(step_results: list[dict[str, Any]], step_name: str) -> dict[str, Any] | None:
    """Mirrors services.final_post_processor._find_step_result() exactly - duplicated, not
    imported, since that function is a module-private helper and this codebase's own established
    convention is to duplicate small, single-purpose helpers rather than couple modules that
    change for different reasons (see e.g. services/content_draft_service.py's own precedent)."""
    for step_result in step_results:
        if step_result.get("step_name") == step_name and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                return result
    return None


async def check_final_post_preview_eligibility(
    session: AsyncSession, content_draft_id: UUID,
) -> FinalPostPreviewEligibility:
    """The one entry point this module exposes. Checks, in order (Phase I.2's own Part A-E, an
    explicit A-I checklist plus the media/source gates):

    A. `ContentDraft.status == "draft"` (the sole status `create_from_final_post_authoring_result()`
       ever writes - anything else is not a reviewable draft for this gate).
    B. the source `EditorialTask.workflow["workflow_name"] == "FINAL_POST_AUTHORING"`.
    C/D/E/G. `final_post_source`/`final_post_authoring`/`final_post_fact_safety` step_results all
       exist, AND `final_post_source` carries `authoring_prompt_version` (Phase I.1.4's own durable
       additions - their absence is exactly what makes a LEGACY draft fail closed here).
    F. `final_post_fact_safety.status != "block"`.
    H/I. `final_post_source.source_event_recap_review_id` exists and resolves to an
       `EventRecapReview` whose `status` is still `APPROVED`.
    Part C (media required): `final_post_source.selected_media_plan` has a real representative
       (tier != "none", not missing/null) - a text-only Final Post Preview is never eligible.
    Part E (source required): `final_post_source.source_refs` is non-empty - a Preview with no
       verifiable source is never eligible (never invented from the current Story).
    """
    draft = await session.get(ContentDraft, content_draft_id)
    if draft is None:
        return _ineligible("content_draft_not_found")
    if draft.status != "draft":
        return _ineligible("not_draft_status")

    task = await session.get(EditorialTask, draft.task_id)
    if task is None:
        return _ineligible("task_not_found")
    if (task.workflow or {}).get("workflow_name") != WorkflowType.FINAL_POST_AUTHORING.value:
        return _ineligible("not_final_post_authoring")

    step_results = (task.workflow or {}).get("step_results", [])
    final_post_source = _find_step_result(step_results, "final_post_source")
    authored_output = _find_step_result(step_results, "final_post_authoring")
    fact_safety_result = _find_step_result(step_results, "final_post_fact_safety")

    if final_post_source is None or authored_output is None or fact_safety_result is None:
        return _ineligible("audit_snapshot_missing")
    if not final_post_source.get("authoring_prompt_version"):
        return _ineligible("audit_snapshot_missing")

    if fact_safety_result.get("status") == "block":
        return _ineligible("fact_safety_blocked")

    source_review_id_raw = final_post_source.get("source_event_recap_review_id")
    if not source_review_id_raw:
        return _ineligible("audit_snapshot_missing")
    review = await session.get(EventRecapReview, UUID(source_review_id_raw))
    if review is None or review.status != EventRecapReviewStatus.APPROVED:
        return _ineligible("source_review_not_approved")

    media_plan = final_post_source.get("selected_media_plan")
    if (
        not isinstance(media_plan, dict) or media_plan.get("tier") == "none"
        or not media_plan.get("representative")
    ):
        return _ineligible("media_missing")

    source_refs = final_post_source.get("source_refs")
    if not source_refs:
        return _ineligible("source_missing")

    return FinalPostPreviewEligibility(
        eligible=True, reason=None, task=task, final_post_source=final_post_source,
        authored_output=authored_output, fact_safety_result=fact_safety_result,
    )
