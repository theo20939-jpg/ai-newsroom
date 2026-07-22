"""Phase 11 read-only Editorial Inbox query service (docs/
phase11_telegram_editorial_inbox_architecture_contract.md §6/§7).

Plain-function module - mirrors services/workflow_service.py's shape, not
services/content_draft_service.py's class shape (that class exists specifically as ContentDraft's
sole *writer*, not a pattern this read-only service should copy).

MUST NOT (Contract §7, binding): import aiogram; trigger AI generation; invoke WorkflowRunner,
CapabilityExecutor, or any Capability; mutate ContentDraft/EditorialTask/any workflow state;
publish anything. Every operation below is a session.execute(select(...))/session.get() read -
no session.add()/commit() appears anywhere in this module.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from schemas.editorial_inbox import EditorialInboxCard


def _to_card(draft: ContentDraft, event: NewsEvent) -> EditorialInboxCard:
    return EditorialInboxCard(
        draft_id=draft.id,
        draft_title=draft.title,
        draft_body=draft.body,
        # ContentDraft.hashtags is typed Mapped[dict | None] (pre-existing ORM imprecision -
        # database/models/content_draft.py's own JSON column stores whatever's assigned; Phase 10's
        # CopywritingCapability output schema guarantees a list at runtime, never a dict - mirrors
        # services/content_draft_service.py:56-59's identical convention).
        hashtags=draft.hashtags,  # type: ignore[arg-type]
        draft_created_at=draft.created_at,
        news_title=event.title,
        news_category=event.category.value,
        news_url=event.url,
        news_published_at=event.published_at,
    )


async def get_latest_editorial_cards(
    session: AsyncSession, *, limit: int = 5
) -> list[EditorialInboxCard]:
    """Return the `limit` most recent eligible editorial drafts, newest-first (Contract §6).

    Eligible: linked EditorialTask.status == COMPLETED. Ordered created_at DESC, id DESC
    (deterministic tie-break - UUIDs carry no chronological meaning, this is purely for stable,
    reproducible ordering). No relationship() is added anywhere - the join below is an explicit,
    hand-written join condition inside a select() statement, not the ORM's declarative
    relationship() feature (Contract §5/§21's prohibition targets the latter, not the former).

    Duplicate-ContentDraft-per-task is schema-permitted (no unique constraint on task_id) but not
    reachable through any current code path (ContentDraftService is constructed only from
    scripts/run_content_generation.py, which always creates a fresh EditorialTask per invocation) -
    this function does not invent deduplication logic; the frozen ordering already handles the
    case correctly if it ever occurred.
    """
    stmt = (
        select(ContentDraft)
        .join(EditorialTask, ContentDraft.task_id == EditorialTask.id)
        .where(EditorialTask.status == TaskStatus.COMPLETED)
        .order_by(ContentDraft.created_at.desc(), ContentDraft.id.desc())
        .limit(limit)
    )
    drafts = (await session.execute(stmt)).scalars().all()

    cards: list[EditorialInboxCard] = []
    for draft in drafts:
        task = await session.get(EditorialTask, draft.task_id)
        assert task is not None  # guaranteed by the join+filter above (referential integrity)
        event = await session.get(NewsEvent, task.event_id)
        assert event is not None  # NewsEvent.id is a real FK target, never dangling
        cards.append(_to_card(draft, event))
    return cards
