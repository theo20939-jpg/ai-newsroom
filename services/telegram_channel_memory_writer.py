"""SOCIAL-INTELLIGENCE-OPS-1, spec §45-§48: TelegramChannelMemoryWriter - a safe writer tied to
the REAL Telegram content lifecycle, preferring the successful FinalPostReview/publication handoff
(services/final_post_publication.py::publish_approved_final_post() is the ONE place in this
codebase that ever sets `FinalPostReview.published_at`/`published_telegram_message_id` on an
actual send - this writer never invents a publication).

CRITICAL: this module is NOT wired into any runtime publication path this phase (spec §46's own
"do not alter public publication behavior" instruction) - `write_channel_memory_from_final_post_
review()` is a real, tested, callable service, invocable from a future safe post-publication
bookkeeping step, but nothing in bot/services/worker calls it automatically yet.

CRITICAL (idempotency, spec §47): repeated calls for the SAME already-recorded review must never
create a duplicate row - `content_draft_id` is looked up first, and an existing memory row is
returned unchanged rather than re-inserted.

CRITICAL (spec §48 "record only actual known data"): every field is populated from a real,
resolvable canonical row (ContentDraft/EditorialTask/NewsEvent/NewsSource/ContentDraftStoryLink/
Story) or left None - never guessed. Several TelegramChannelMemory columns
(presentation_type/media_type/visual_family/template/renderer_version/content_objective/
campaign_id/experiment_id) have no resolvable canonical source anywhere in this codebase's current
ContentDraft/EditorialTask/NewsEvent chain and are deliberately left None rather than fabricated -
noted in this phase's final report as a real gap for a future phase to close once those fields
exist somewhere upstream."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask
from database.models.final_post_review import FinalPostReview
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from database.models.telegram_channel_memory import StoryRole, TelegramChannelMemory


async def _existing_memory_for_draft(session: AsyncSession, content_draft_id: uuid.UUID) -> TelegramChannelMemory | None:
    stmt = select(TelegramChannelMemory).where(TelegramChannelMemory.content_draft_id == content_draft_id)
    return (await session.execute(stmt)).scalars().first()


def _story_role(is_story_update: bool | None) -> StoryRole | None:
    """Only ever FIRST/UPDATE, derived from the one real signal this codebase resolves
    (ContentDraftStoryLink.is_story_update) - FOLLOW_UP/RECAP require a distinction this chain
    cannot honestly make today, so they are never guessed into either bucket."""
    if is_story_update is None:
        return None
    return StoryRole.UPDATE if is_story_update else StoryRole.FIRST


async def write_channel_memory_from_final_post_review(
    session: AsyncSession, review: FinalPostReview,
) -> TelegramChannelMemory | None:
    """Returns None (never raises, never writes) when `review` has no real recorded publication
    yet - a legitimate "nothing to record" state, not an error."""
    if review.published_at is None:
        return None

    existing = await _existing_memory_for_draft(session, review.content_draft_id)
    if existing is not None:
        return existing

    content_draft = await session.get(ContentDraft, review.content_draft_id)
    task = await session.get(EditorialTask, content_draft.task_id) if content_draft is not None else None
    event = await session.get(NewsEvent, task.event_id) if task is not None else None
    source = await session.get(NewsSource, event.source_id) if event is not None else None

    story_link = (await session.execute(
        select(ContentDraftStoryLink).where(ContentDraftStoryLink.content_draft_id == review.content_draft_id)
    )).scalars().first()
    story = await session.get(Story, story_link.story_id) if story_link is not None else None

    memory = TelegramChannelMemory(
        post_id=str(review.published_telegram_message_id) if review.published_telegram_message_id is not None else None,
        content_draft_id=review.content_draft_id,
        story_id=story.id if story is not None else None,
        event_id=event.id if event is not None else None,
        campaign_id=None,
        category=event.category.value if event is not None else None,
        topics=list(story.keywords) if story is not None and story.keywords else None,
        entities=list(story.entities) if story is not None and story.entities else None,
        source=source.name if source is not None else None,
        headline=content_draft.title if content_draft is not None else None,
        story_role=_story_role(story_link.is_story_update if story_link is not None else None),
        published_at=review.published_at,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory
