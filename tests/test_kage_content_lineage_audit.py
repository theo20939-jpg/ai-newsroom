"""Zero-provider persistence/restart proof for KAGE factual lineage."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.kage_content_lineage_audit import KageContentLineageAudit
from database.models.news_event import EventCategory
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import StoryTelegramDelivery
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.kage_content_lineage_audit import (
    LineageAuditBoundsError, bounded_audit, create_attempt_audit, reconstruct_lineage,
    update_attempt_audit, link_draft,
)
from services.kage_delivery_truth import record_terminal_outcome
from tests.test_content_worker_cycle import _make_event, factory, test_source  # noqa: F401


def test_audit_bounds_are_explicit_and_never_silently_truncate():
    with pytest.raises(LineageAuditBoundsError, match="chars"):
        bounded_audit({"source": "x" * 524_289})
    assert bounded_audit({"stage": {"api_key": "must-not-survive", "claim": "exact span"}}) == {
        "stage": {"claim": "exact span"}
    }
    assert bounded_audit({"input": "Authorization: Bearer hidden-value sk-abcdefgh1234"}) == {
        "input": "Authorization: Bearer [REDACTED] [REDACTED]"
    }
    with pytest.raises(LineageAuditBoundsError, match="document"):
        bounded_audit({key: "x" * 524_288 for key in ("a", "b", "c", "d")})


@pytest.mark.asyncio
async def test_blocked_lineage_survives_new_session_and_has_no_delivery(factory, test_source):
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        story = Story(title="Lineage fixture story", category=EventCategory.AI, topic_bucket="fixture",
                      first_event_id=event.id, event_count=1)
        session.add(story)
        await session.flush()
        story_link = NewsEventStoryLink(news_event_id=event.id, story_id=story.id,
                                        match_type="new_story", match_score=1.0)
        session.add(story_link)
        await session.flush()
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        task_id = task.id
        await create_attempt_audit(
            session, task_id=task_id, event_id=event.id, story_id=story.id,
            source_snapshot={"source_id": str(event.source_id), "source_url": event.url,
                             "research_input": "normalized source facts"},
        )
        draft = ContentDraft(task_id=task_id, type=ContentType.POST, title="Blocked title",
                             body="Blocked body", status="draft_blocked_fact_safety", version=1)
        session.add(draft)
        await session.flush()
        await link_draft(session, task_id=task_id, draft_id=draft.id)
        stage_names = ("research", "intelligence", "copywriting", "quality")
        stage_outputs = {
            "research": {"facts": [{"fact_id": 3, "text": "known evidence"}]},
            "intelligence": {"claims": [{"fact_id": 3, "text": "supported interpretation"}]},
            "copywriting": {"headline": "Exact fixture headline", "body": "Exact fixture body"},
            "quality": {"verdict": "PASS", "findings": []},
        }
        for name in stage_names:
            copywriting_input = {"facts": [{"fact_id": 3, "text": "known evidence"}]}
            await update_attempt_audit(
                session, task_id=task_id, section="stage",
                value={"name": name, "prompt_version": "fixture-1",
                       "input": copywriting_input if name == "copywriting" else f"input:{name}",
                       "provider_output": stage_outputs[name], "execution_id": str(uuid4())},
            )
        await update_attempt_audit(
            session, task_id=task_id, section="publication_factual_gate",
            value={"gate_version": "1", "gate_input": {"fact_ids": [3]},
                   "structured_result": {"FACTUAL_SAFETY": "FAIL", "HEADLINE_SAFETY": "FAIL",
                                         "BODY_SAFETY": "PASS", "UNSUPPORTED_CLAIMS": [
                                             {"span": "exact offending claim", "reason": "no support",
                                              "supporting_fact_ids": [3]}
                                         ]}},
        )
        task_row = await session.get(EditorialTask, task_id)
        assert task_row is not None
        task_row.workflow = {
            "workflow_name": "CONTENT_GENERATION", "workflow_version": 1,
            "step_results": [{"step_name": name, "status": "SUCCESS", "attempt": 1,
                              "started_at": datetime.now(timezone.utc).isoformat(),
                              "finished_at": datetime.now(timezone.utc).isoformat(),
                              "result": {"fixture": name}} for name in stage_names],
            "publication_outcome": {"status": "IN_FLIGHT", "task_id": str(task_id),
                                    "event_id": str(event.id), "draft_id": str(draft.id)},
        }
        await record_terminal_outcome(
            session, task_id=task_id, status="BLOCKED_FACTUAL_GATE", draft_id=draft.id,
            reason=None, message_id=None,
        )
        await session.commit()

    # A distinct AsyncSession reloads only durable storage; no prior Python result objects survive.
    async with factory() as reopened:
        lineage = await reconstruct_lineage(reopened, task_id)
        assert lineage is not None
        assert lineage["identity"]["event_id"] == str(event.id)
        assert lineage["identity"]["story_id"] == str(story.id)
        assert lineage["identity"]["generation_task_id"] == str(task_id)
        assert lineage["identity"]["draft_id"] == str(draft.id)
        assert lineage["identity"]["attempt_id"] == str(task_id)
        assert lineage["source"]["research_input"] == "normalized source facts"
        assert set(lineage["stages"]) == set(stage_names)
        assert set(lineage["workflow_stage_results"]) == set(stage_names)
        assert lineage["stages"]["research"]["provider_output"] == stage_outputs["research"]
        assert lineage["stages"]["intelligence"]["provider_output"] == stage_outputs["intelligence"]
        assert lineage["stages"]["copywriting"]["input"] == copywriting_input
        assert lineage["stages"]["copywriting"]["provider_output"] == stage_outputs["copywriting"]
        assert lineage["stages"]["quality"]["provider_output"] == stage_outputs["quality"]
        claim = lineage["publication_factual_gate"]["structured_result"]["UNSUPPORTED_CLAIMS"][0]
        assert claim == {"span": "exact offending claim", "reason": "no support", "supporting_fact_ids": [3]}
        assert lineage["publication_outcome"]["status"] == "BLOCKED_FACTUAL_GATE"
        assert lineage["publication_outcome"]["message_id"] is None
        receipts = await reopened.scalar(
            select(func.count()).select_from(StoryTelegramDelivery)
            .where(StoryTelegramDelivery.content_draft_id == lineage["identity"]["draft_id"])
        )
        assert receipts == 0

    # Keep the shared source fixture's teardown complete even if it predates this new sidecar table.
    async with factory() as cleanup:
        await cleanup.execute(delete(KageContentLineageAudit).where(KageContentLineageAudit.task_id == task_id))
        await cleanup.commit()
