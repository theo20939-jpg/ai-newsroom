"""Event-level duplicate-delivery guard over the real persisted schema (source_event_id stays NULL)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.kage_content_lineage_audit import KageContentLineageAudit
from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery
from services.kage_content_lineage_audit import create_attempt_audit
from services.kage_delivery_truth import authorize_failed_transport_retry, event_publication_state
from services.story_telegram_delivery import record_delivery
from tests.test_content_worker_cycle import factory, test_source  # noqa: F401

# The accepted natural production canary (message 2864), reproduced with its real identifiers.
CANARY_EVENT = UUID("0c61fab4-90ca-4cf8-a9d8-1e6909a5c027")
CANARY_STORY = UUID("16452fcf-b28a-4145-b2ed-b663f381f3b7")
CANARY_TASK = UUID("edba304b-e544-4f60-94b7-399b8154864f")
CANARY_DRAFT = UUID("91a0a5ba-0a3a-4ffd-ade1-3439ba8de117")
CANARY_RECEIPT = UUID("d94585f9-19b5-4021-ae31-39307f6f2170")


async def _event(session, source, event_id=None) -> NewsEvent:
    event = NewsEvent(id=event_id or uuid4(), source_id=source.id, title=f"Publication-state fixture {uuid4()}",
                      content="Fixture content.", category=EventCategory.AI, hash=f"pub-state-{uuid4()}",
                      published_at=datetime.now(timezone.utc))
    session.add(event)
    await session.flush()
    return event


async def _story(session, event, story_id=None) -> Story:
    story = Story(id=story_id or uuid4(), title="Publication-state fixture story", category=EventCategory.AI,
                  topic_bucket="fixture", first_event_id=event.id, event_count=1)
    session.add(story)
    await session.flush()
    session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type="new_story", match_score=1.0))
    await session.flush()
    return story


async def _attempt(session, event, *, outcome=None, task_id=None, draft_id=None, workflow_name="CONTENT_GENERATION"):
    workflow = {"workflow_name": workflow_name, "workflow_version": 1, "step_results": []}
    if outcome is not None:
        workflow["publication_outcome"] = {"status": outcome, "event_id": str(event.id)}
    task = EditorialTask(id=task_id or uuid4(), event_id=event.id, priority=TaskPriority.B,
                         status=TaskStatus.COMPLETED if outcome == "DELIVERED" else TaskStatus.FAILED,
                         workflow=workflow)
    session.add(task)
    await session.flush()
    draft = ContentDraft(id=draft_id or uuid4(), task_id=task.id, type=ContentType.POST, title="t", body="b",
                         status="draft", version=1)
    session.add(draft)
    await session.flush()
    return task, draft


async def _receipt(session, story, draft, *, status=DeliveryStatus.SENT, message_id=2864, receipt_id=None):
    row = await record_delivery(session, story_id=story.id, content_draft_id=draft.id,
                                telegram_chat_id=-1004297182444, telegram_message_id=message_id,
                                reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
                                delivery_status=status, sent_at=datetime.now(timezone.utc))
    if receipt_id is not None:
        row.id = receipt_id
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_accepted_canary_event_is_already_delivered_with_null_source_event_id(factory, test_source):
    async with factory() as session:
        event = await _event(session, test_source, CANARY_EVENT)
        story = await _story(session, event, CANARY_STORY)
        _, draft = await _attempt(session, event, outcome="DELIVERED", task_id=CANARY_TASK, draft_id=CANARY_DRAFT)
        await _receipt(session, story, draft, receipt_id=CANARY_RECEIPT)
        await session.commit()
    async with factory() as reopened:
        receipt = await reopened.get(StoryTelegramDelivery, CANARY_RECEIPT)
        assert receipt.source_event_id is None
        assert receipt.content_draft_id == CANARY_DRAFT and receipt.telegram_message_id == 2864
        state = await event_publication_state(reopened, CANARY_EVENT)
    assert state == {
        "event_id": str(CANARY_EVENT), "already_delivered": True,
        "delivered_task_ids": [str(CANARY_TASK)], "sent_receipt_ids": [str(CANARY_RECEIPT)],
        "in_flight_task_ids": [],
    }


@pytest.mark.asyncio
async def test_receipt_alone_or_outcome_alone_each_prove_delivery(factory, test_source):
    async with factory() as session:
        receipt_only = await _event(session, test_source)
        story = await _story(session, receipt_only)
        _, draft = await _attempt(session, receipt_only, outcome=None)
        await _receipt(session, story, draft, message_id=11)
        outcome_only = await _event(session, test_source)  # unlinked story: no receipt row is written
        await _attempt(session, outcome_only, outcome="DELIVERED")
        await session.commit()
    async with factory() as s:
        assert (await event_publication_state(s, receipt_only.id))["already_delivered"] is True
        assert (await event_publication_state(s, outcome_only.id))["already_delivered"] is True


@pytest.mark.asyncio
async def test_failed_or_blocked_attempts_only_are_not_a_delivery(factory, test_source):
    async with factory() as session:
        event = await _event(session, test_source)
        story = await _story(session, event)
        await _attempt(session, event, outcome="BLOCKED_FACTUAL_GATE")
        _, failed_draft = await _attempt(session, event, outcome="DELIVERY_FAILED")
        await _receipt(session, story, failed_draft, status=DeliveryStatus.FAILED, message_id=None)
        await _attempt(session, event, outcome=None)
        await session.commit()
    async with factory() as s:
        state = await event_publication_state(s, event.id)
    assert state["already_delivered"] is False
    assert state["sent_receipt_ids"] == [] and state["delivered_task_ids"] == []


@pytest.mark.asyncio
async def test_in_flight_is_reported_separately_and_not_called_delivered(factory, test_source):
    async with factory() as session:
        event = await _event(session, test_source)
        task, _ = await _attempt(session, event, outcome="IN_FLIGHT")
        await session.commit()
    async with factory() as s:
        state = await event_publication_state(s, event.id)
    assert state["already_delivered"] is False
    assert state["in_flight_task_ids"] == [str(task.id)]


@pytest.mark.asyncio
async def test_other_event_in_the_same_story_is_not_falsely_blocked(factory, test_source):
    async with factory() as session:
        delivered = await _event(session, test_source)
        story = await _story(session, delivered)
        _, draft = await _attempt(session, delivered, outcome="DELIVERED")
        await _receipt(session, story, draft, message_id=21)
        sibling = await _event(session, test_source)
        session.add(NewsEventStoryLink(news_event_id=sibling.id, story_id=story.id,
                                       match_type="same_story", match_score=0.9))
        await session.commit()
    async with factory() as s:
        assert (await event_publication_state(s, delivered.id))["already_delivered"] is True
        assert (await event_publication_state(s, sibling.id))["already_delivered"] is False


@pytest.mark.asyncio
async def test_non_generation_workflows_are_ignored(factory, test_source):
    async with factory() as session:
        event = await _event(session, test_source)
        await _attempt(session, event, outcome="DELIVERED", workflow_name="NEWS_ANALYSIS")
        await session.commit()
    async with factory() as s:
        assert (await event_publication_state(s, event.id))["already_delivered"] is False


@pytest.mark.asyncio
async def test_draft_idempotency_key_still_rejects_a_second_receipt_for_the_same_draft(factory, test_source):
    async with factory() as session:
        event = await _event(session, test_source)
        story = await _story(session, event)
        _, draft = await _attempt(session, event, outcome="DELIVERED")
        first = await _receipt(session, story, draft, message_id=31)
        assert first.idempotency_key == f"content_draft:{draft.id}"
        await session.commit()
    async with factory() as session:
        # the draft already has a receipt; a second one must fail at the DB unique constraint
        with pytest.raises(IntegrityError):
            await _receipt(session, story, draft, message_id=32)
        await session.rollback()
    async with factory() as s:
        count = len((await s.execute(select(StoryTelegramDelivery.id)
                                     .where(StoryTelegramDelivery.content_draft_id == draft.id))).all())
        assert count == 1


@pytest.mark.asyncio
async def test_source_event_id_column_alone_would_have_missed_the_delivery(factory, test_source):
    """The pre-fix guard's exact predicate, kept as a regression witness."""
    async with factory() as session:
        event = await _event(session, test_source)
        story = await _story(session, event)
        _, draft = await _attempt(session, event, outcome="DELIVERED")
        await _receipt(session, story, draft, message_id=41)
        await session.commit()
    async with factory() as s:
        old = (await s.execute(select(StoryTelegramDelivery.id)
                               .where(StoryTelegramDelivery.source_event_id == event.id))).all()
        assert old == []
        assert (await event_publication_state(s, event.id))["already_delivered"] is True


@pytest.mark.asyncio
async def test_founder_authorized_retry_archives_failed_transport_without_erasing_history(
    factory, test_source,
):
    async with factory() as session:
        event = await _event(session, test_source)
        task, draft = await _attempt(session, event)
        failed = {
            "status": "VISUAL_HOLD",
            "reason": "media_send_failed",
            "task_id": str(task.id),
            "event_id": str(event.id),
            "draft_id": str(draft.id),
            "message_id": None,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        task.workflow = {**task.workflow, "publication_outcome": failed}
        draft.status = "hold_for_visual"
        await create_attempt_audit(
            session, task_id=task.id, event_id=event.id, story_id=None,
            source_snapshot={"event_title": event.title},
        )
        await session.commit()
        await authorize_failed_transport_retry(
            session, task_id=task.id, draft_id=draft.id,
            authorized_by="founder_manual_topic_inspection",
        )
        await session.commit()

    async with factory() as session:
        saved_task = await session.get(EditorialTask, task.id)
        saved_draft = await session.get(ContentDraft, draft.id)
        saved_audit = await session.get(KageContentLineageAudit, task.id)
    assert saved_task.workflow["publication_outcome"] is None
    assert saved_task.workflow["publication_outcome_history"] == [failed]
    assert saved_task.workflow["publication_retry_authorizations"][0]["reason"] == (
        "founder_confirmed_message_absent"
    )
    assert saved_draft.status == "draft"
    assert saved_audit.audit["publication_outcome"] is None
    assert saved_audit.audit["publication_outcome_history"] == [failed]
