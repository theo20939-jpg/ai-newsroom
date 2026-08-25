"""Phase I.2: services.final_post_review_eligibility.check_final_post_preview_eligibility() tests.
Real Postgres (db_session fixture), hand-constructed EditorialTask.workflow step_results (never a
real LLM/processor run - this module's own job is checking already-persisted state, not producing
it) so every branch (Part A-I, media-required, source-required) is directly, deterministically
controllable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.event_recap_review import EventRecapReviewStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowStepResult, WorkflowType
from services import workflow_service
from services.event_recap_review_service import create_event_recap_review, set_decision
from services.final_post_review_eligibility import check_final_post_preview_eligibility

_VALID_RECAP_OUTPUT = {
    "recap_title": "Approved recap title", "recap_summary": "Summary.",
    "key_takeaways": ["Takeaway."], "uncertainty_notes": [],
}
_VALID_MEDIA_PLAN = {
    "tier": "story_pool",
    "representative": {
        "candidate_id": "cand-1", "originating_event_id": str(uuid.uuid4()), "media_type": "image",
        "recommended_role": "hero", "storage_key": None, "telegram_file_id": "file-1", "sha256": None,
        "remote_url": "https://example.com/hero.jpg",
    },
}
_VALID_AUTHORED_OUTPUT = {"title": "A public title", "body": "A public body."}
_PASS_FACT_SAFETY = {
    "version": "v1", "status": "pass", "mode": "shadow", "claims_checked": 1,
    "supported": 1, "uncertain": 0, "unsupported": 0, "highest_risk": None, "findings": [],
}
_BLOCK_FACT_SAFETY = {**_PASS_FACT_SAFETY, "status": "block", "findings": [{"claim": "x"}]}


def _step(step_name: str, result: dict | None) -> dict:
    now = datetime.now(timezone.utc)
    return WorkflowStepResult(
        step_name=step_name, status="SUCCESS", attempt=1, started_at=now, finished_at=now, result=result,
    ).model_dump(mode="json")


async def _seed_setup(
    session: AsyncSession,
    *,
    include_source_step: bool = True,
    include_authoring_step: bool = True,
    include_fact_safety_step: bool = True,
    authoring_prompt_version: str | None = "2",
    fact_safety_result: dict | None = _PASS_FACT_SAFETY,
    media_plan: dict | None = _VALID_MEDIA_PLAN,
    source_refs: list[str] | None = None,
    review_status: EventRecapReviewStatus = EventRecapReviewStatus.APPROVED,
    draft_status: str = "draft",
    final_post_authoring_workflow: bool = True,
) -> tuple[ContentDraft, EditorialTask]:
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid.uuid4()}.xml", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title="Anchor", content="B", category=EventCategory.AI, hash=f"h-{uuid.uuid4()}")
    session.add(event)
    await session.flush()

    recap_task_read = await workflow_service.create_task(
        session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.EVENT_RECAP, priority=TaskPriority.C),
    )
    recap_task = await session.get(EditorialTask, recap_task_read.id)
    recap_task.workflow = {**recap_task.workflow, "step_results": [_step("synthesize_recap", _VALID_RECAP_OUTPUT)]}
    await session.commit()

    review = await create_event_recap_review(session, recap_task_id=recap_task_read.id)
    if review_status != EventRecapReviewStatus.PENDING:
        review = await set_decision(session, review.id, review_status, decided_by_user_id=1)

    if final_post_authoring_workflow:
        fp_task_read = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.FINAL_POST_AUTHORING, priority=TaskPriority.C),
        )
    else:
        # Part B test: reuse the EVENT_RECAP task itself as the draft's own "source task" - proves
        # the eligibility check rejects a draft whose task is not FINAL_POST_AUTHORING.
        fp_task_read = recap_task_read

    fp_task = await session.get(EditorialTask, fp_task_read.id)
    step_results = []
    if include_source_step:
        bundle = {
            "source_event_recap_task_id": str(recap_task_read.id),
            "source_event_recap_review_id": str(review.id),
            "story_id": None, "anchor_event_id": str(event.id),
            "approved_recap": {
                "recap_title": _VALID_RECAP_OUTPUT["recap_title"], "recap_summary": _VALID_RECAP_OUTPUT["recap_summary"],
                "key_takeaways": _VALID_RECAP_OUTPUT["key_takeaways"], "uncertainty_notes": [],
            },
            "verified_facts": [], "source_refs": source_refs if source_refs is not None else ["https://example.com/a"],
            "selected_media_plan": media_plan, "legacy_snapshot_missing": False,
            "language": "ru",
        }
        if authoring_prompt_version is not None:
            bundle["authoring_prompt_version"] = authoring_prompt_version
        step_results.append(_step("final_post_source", bundle))
    if include_authoring_step:
        step_results.append(_step("final_post_authoring", _VALID_AUTHORED_OUTPUT))
    if include_fact_safety_step:
        step_results.append(_step("final_post_fact_safety", fact_safety_result))
    fp_task.workflow = {**fp_task.workflow, "step_results": step_results}
    await session.commit()

    draft = ContentDraft(
        id=uuid.uuid4(), task_id=fp_task_read.id, type=ContentType.POST,
        title=_VALID_AUTHORED_OUTPUT["title"], body=_VALID_AUTHORED_OUTPUT["body"], version=1, status=draft_status,
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    return draft, fp_task


@pytest.mark.asyncio
async def test_content_draft_not_found_is_ineligible(db_session: AsyncSession) -> None:
    result = await check_final_post_preview_eligibility(db_session, uuid.uuid4())
    assert result.eligible is False
    assert result.reason == "content_draft_not_found"


@pytest.mark.asyncio
async def test_fully_audited_new_draft_is_eligible(db_session: AsyncSession) -> None:
    draft, task = await _seed_setup(db_session)

    result = await check_final_post_preview_eligibility(db_session, draft.id)

    assert result.eligible is True
    assert result.reason is None
    assert result.task is not None and result.task.id == task.id
    assert result.final_post_source is not None
    assert result.authored_output == _VALID_AUTHORED_OUTPUT
    assert result.fact_safety_result == _PASS_FACT_SAFETY


@pytest.mark.asyncio
async def test_not_draft_status_is_ineligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_setup(db_session, draft_status="draft_blocked_fact_safety")
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "not_draft_status"


@pytest.mark.asyncio
async def test_wrong_source_workflow_type_is_ineligible(db_session: AsyncSession) -> None:
    """Part B: the draft's own task must be FINAL_POST_AUTHORING."""
    draft, _task = await _seed_setup(db_session, final_post_authoring_workflow=False, include_authoring_step=False, include_fact_safety_step=False)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "not_final_post_authoring"


@pytest.mark.asyncio
async def test_legacy_draft_missing_fact_safety_snapshot_fails_closed(db_session: AsyncSession) -> None:
    """Part B (legacy policy): a task missing final_post_fact_safety (the real Pixel/Silver Lake
    V2 shape) must fail with audit_snapshot_missing - never silently treated as eligible."""
    draft, _task = await _seed_setup(db_session, include_fact_safety_step=False, authoring_prompt_version=None)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "audit_snapshot_missing"


@pytest.mark.asyncio
async def test_missing_authoring_prompt_version_fails_closed(db_session: AsyncSession) -> None:
    """A final_post_source lacking authoring_prompt_version (pre-I.1.4 shape) is also legacy."""
    draft, _task = await _seed_setup(db_session, authoring_prompt_version=None)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "audit_snapshot_missing"


@pytest.mark.asyncio
async def test_fact_safety_block_is_ineligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_setup(db_session, fact_safety_result=_BLOCK_FACT_SAFETY)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "fact_safety_blocked"


@pytest.mark.asyncio
async def test_source_review_not_approved_is_ineligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_setup(db_session, review_status=EventRecapReviewStatus.NEEDS_REVISION)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "source_review_not_approved"


@pytest.mark.asyncio
async def test_media_missing_none_tier_is_ineligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_setup(db_session, media_plan={"tier": "none", "representative": None})
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "media_missing"


@pytest.mark.asyncio
async def test_media_missing_null_plan_is_ineligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_setup(db_session, media_plan=None)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "media_missing"


@pytest.mark.asyncio
async def test_source_missing_empty_refs_is_ineligible(db_session: AsyncSession) -> None:
    draft, _task = await _seed_setup(db_session, source_refs=[])
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is False
    assert result.reason == "source_missing"


@pytest.mark.asyncio
async def test_branded_fallback_media_plan_is_media_eligible(db_session: AsyncSession) -> None:
    """tier=branded_fallback with only a storage_key (no candidate_id/originating_event_id) still
    counts as real media for eligibility purposes."""
    plan = {
        "tier": "branded_fallback",
        "representative": {
            "candidate_id": None, "originating_event_id": None, "media_type": "image",
            "recommended_role": "hero", "storage_key": "fallback/x.jpg", "telegram_file_id": None,
            "sha256": "deadbeef", "remote_url": None,
        },
    }
    draft, _task = await _seed_setup(db_session, media_plan=plan)
    result = await check_final_post_preview_eligibility(db_session, draft.id)
    assert result.eligible is True
