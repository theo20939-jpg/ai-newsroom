"""Phase 18.10 M3: worker.content_cycle's story-linked Telegram reply/delivery wiring.

Reuses tests/test_content_worker_cycle.py's own established fixtures (factory/test_source/
_isolated_freshness_window/_make_event/_make_completed_news_analysis_task) via import - a
Phase-18.10-scoped extension, kept in its own file to avoid growing that already-large module.

No real Telegram send anywhere in this file - `bot` is always a plain AsyncMock, exactly like
every other content_cycle test in this codebase. Every test explicitly pins
image_editorial_preview_enabled/content_generation_dry_run via monkeypatch rather than relying on
this environment's ambient .env values (which are non-default in this dev environment - see
docs/phase18_10_editorial_intelligence_report.md's own disclosed test-environment notes) - the
same explicit-override discipline tests/test_content_worker_cycle.py's own
_isolated_freshness_window fixture already established.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_quote import ContentDraftQuote
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.content_draft_reply_routing_proposal import ContentDraftReplyRoutingProposal
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery
from services.telegram_notifier import NotificationOutcome
from tests.test_content_worker_cycle import (  # noqa: F401,F811 - fixtures reused via import
    _make_completed_news_analysis_task,
    _make_event,
    _real_capability_registry,
    _isolated_freshness_window,
    factory,
    test_source,
)
from worker.content_cycle import run_content_cycle

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2

_MIGRATION_SKIP_REASON = (
    "Requires Alembic migrations c2bc6affb100/0fac25b59455 (stories/news_event_story_links/"
    "content_draft_story_links/story_telegram_deliveries tables, Phase 18.10) and 280fa1e7d6d2 "
    "(content_draft_reply_routing_proposals table, Phase 19 M7) to be applied first - both ship "
    "unapplied by explicit instruction (design-only). Remove this skip once applied."
)


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


async def _make_story_linked_draft(
    factory: async_sessionmaker[AsyncSession], test_source, *, is_story_update: bool,  # noqa: F811
) -> tuple[Story, NewsEvent]:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
        story = Story(
            id=uuid4(), title=event.title, category=EventCategory.AI, entities=[], keywords=[],
            topic_bucket="product", first_event_id=event.id, event_count=1,
        )
        session.add(story)
        await session.flush()
        await session.commit()
    return story, event


@pytest.fixture
def _deterministic_delivery_settings(monkeypatch: pytest.MonkeyPatch):
    """Forces the plain send_editorial_card path and live (non-dry-run) sends, regardless of
    this environment's own ambient .env values - so this file's assertions are never at the
    mercy of local configuration drift."""
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "editorial_chat_id", 123456789)


@pytest.mark.asyncio
async def test_off_mode_never_queries_story_link_or_records_delivery(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None,
) -> None:
    """The default, byte-identical-to-pre-18.10 path - telegram_story_reply_mode == "off" must
    never attempt a ContentDraftStoryLink lookup or a delivery record, and must behave exactly as
    before (send happens, notified counts as usual). Does not need the Phase 18.10/19 migrations
    at all, since the new code path is never entered."""
    assert settings.telegram_story_reply_mode == "off"  # this test's own precondition

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=42)),
    ) as mock_notify, patch("worker.content_cycle.record_delivery") as mock_record_delivery:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_called_once()
    # reply_to_message_id must be explicitly None (a normal, non-story-linked send), never
    # simply omitted - proves the new parameter is wired through even in the inert/off case.
    assert mock_notify.call_args.kwargs["reply_to_message_id"] is None
    mock_record_delivery.assert_not_called()
    assert result.completed == 1
    assert result.notified == 1
    assert result.story_fail_closed_review == 0
    assert result.story_delivery_persistence_failed == 0


@pytest.mark.asyncio
async def test_story_memory_shadow_alone_never_affects_telegram_delivery(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 19 M7 regression test for the disclosed defect (docs/phase19_m0_audit.md sec7,
    docs/phase19_m6_story_memory_calibration_report.md sec3.1): a real, already-committed
    Phase 18.10 bug gated reply-threading (including a fail-closed skip) directly on
    story_memory_mode != "off", so story_memory_mode == "shadow" could itself change Telegram
    delivery behavior - contradicting "shadow never changes production behavior". This proves the
    fix: with story_memory_mode == "shadow" AND a real story_update link AND NO root delivery
    (a case that, before the fix, would have skipped the send entirely via the fail-closed route),
    the send must still happen as a normal standalone post, because telegram_story_reply_mode
    stays at its default ("off")."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    assert settings.telegram_story_reply_mode == "off"  # this test's own precondition
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE

    async with factory() as probe_session:
        if not await _table_exists(probe_session, "stories"):
            pytest.skip(_MIGRATION_SKIP_REASON)

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=1001)),
    ) as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_called_once()  # NOT skipped - this is the exact case the old code would have skipped
    assert mock_notify.call_args.kwargs["reply_to_message_id"] is None
    assert result.story_fail_closed_review == 0
    assert result.story_reply_would_fail_closed_shadow == 0  # shadow itself is also off here
    assert result.notified == 1


@pytest.mark.asyncio
async def test_enforce_mode_story_update_with_existing_root_replies_to_it(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An update whose story already has a SENT root delivery must be sent as a reply to that
    root message's telegram_message_id - end to end, through the real create_from_result() ->
    ContentDraftStoryLink creation -> determine_reply_target() -> send_editorial_card() chain.
    Only reachable under telegram_story_reply_mode == "enforce" (not story_memory_mode alone -
    see the regression test above)."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE

    async with factory() as probe_session:
        if not await _table_exists(probe_session, "content_draft_reply_routing_proposals"):
            pytest.skip(_MIGRATION_SKIP_REASON)

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        # A real "root" ContentDraft (representing an earlier, already-sent post for this story) -
        # story_telegram_deliveries.content_draft_id genuinely FK-references content_drafts.id,
        # so a fake/random UUID here would fail once the migration is applied (a real,
        # previously-undiscovered gap in this fixture, found during Phase 19 M7 validation).
        # Deliberately its own, separate NewsEvent (never `event` itself) - worker/content_cycle.
        # py::_select_eligible_events() excludes any event that already has a CONTENT_GENERATION
        # task, so reusing `event.id` here would make the test's own real event ineligible.
        root_event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        root_task = EditorialTask(
            id=uuid4(), event_id=root_event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
            workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
        )
        session.add(root_task)
        await session.flush()
        root_draft = ContentDraft(
            id=uuid4(), task_id=root_task.id, type=ContentType.POST, title="root", body="root body",
            version=1, status="draft",
        )
        session.add(root_draft)
        await session.flush()
        session.add(
            StoryTelegramDelivery(
                id=uuid4(), story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=123456789,
                telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
                delivery_status=DeliveryStatus.SENT, idempotency_key=f"root-{uuid4()}",
                sent_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=1001)),
    ) as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["reply_to_message_id"] == 999
    assert result.story_fail_closed_review == 0

    async with factory() as session:
        # Filtered by this test's own story_id - see the sibling shadow-mode test below for why
        # an unfiltered `.first()` is fragile against pre-existing, unrelated teardown-FK debris.
        proposal = (
            await session.execute(
                select(ContentDraftReplyRoutingProposal).where(
                    ContentDraftReplyRoutingProposal.story_id == story.id
                )
            )
        ).scalars().first()
        assert proposal is not None
        assert proposal.applied is True
        assert proposal.action == "send_as_reply"


@pytest.mark.asyncio
async def test_enforce_mode_story_update_with_no_root_fails_closed_never_sends(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An update whose story has NO root delivery must never be sent as a standalone post - the
    explicit, non-negotiable fail-closed requirement - under telegram_story_reply_mode ==
    "enforce"."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE

    async with factory() as probe_session:
        if not await _table_exists(probe_session, "content_draft_reply_routing_proposals"):
            pytest.skip(_MIGRATION_SKIP_REASON)

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch("worker.content_cycle.send_editorial_card") as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_not_called()
    assert result.story_fail_closed_review == 1
    assert result.notified == 0


@pytest.mark.asyncio
async def test_shadow_mode_persists_proposal_but_never_skips_or_changes_the_real_send(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """telegram_story_reply_mode == "shadow": the same no-root story_update case as the enforce
    fail-closed test above must still send as a standalone post (never skipped), while a
    ContentDraftReplyRoutingProposal row records what WOULD have happened
    (action="fail_closed_route_to_review", applied=False)."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "shadow")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE

    async with factory() as probe_session:
        if not await _table_exists(probe_session, "content_draft_reply_routing_proposals"):
            pytest.skip(_MIGRATION_SKIP_REASON)

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=2002)),
    ) as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["reply_to_message_id"] is None
    assert result.story_fail_closed_review == 0
    assert result.story_reply_would_fail_closed_shadow == 1
    assert result.notified == 1

    async with factory() as session:
        # Filtered by this test's own story_id - a pre-existing, unrelated teardown-FK cleanup
        # gap (docs/phase23_1n1... "12 errors, pre-existing teardown-only FK pattern") can leave
        # an earlier test's own proposal row (e.g. the enforce-mode test above, applied=True)
        # un-deleted in the shared test DB; an unfiltered `.first()` could pick up that stale row
        # instead of this test's own, causing a flaky false failure unrelated to any real code
        # behavior. Each test creates its own unique story_id, so filtering by it is exact.
        proposal = (
            await session.execute(
                select(ContentDraftReplyRoutingProposal).where(
                    ContentDraftReplyRoutingProposal.story_id == story.id
                )
            )
        ).scalars().first()
        assert proposal is not None
        assert proposal.applied is False
        assert proposal.action == "fail_closed_route_to_review"


# ---------------------------------------------------------------------------
# Phase 23.1Q - the same reply-target decision (computed above, mode-agnostically) was silently
# dropped specifically when editorial_delivery_mode == "router" (docs/phase23_1p_story_memory_
# quotes_gate_report.md §"newly-discovered items" / docs/phase22_telegram_editorial_routing_
# report.md §8's own disclosed limitation) - services/telegram_routing.py's send functions had no
# reply_to_message_id parameter at all until this phase. These tests prove the fix end-to-end,
# through the real router branch, asserting directly on the real aiogram Bot mock (never patching
# send_editorial_card - the legacy tests above already cover that path exhaustively).
# ---------------------------------------------------------------------------


def _router_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "router")
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)


@pytest.mark.asyncio
async def test_router_mode_story_update_with_existing_root_replies_to_it(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The router-mode analogue of test_enforce_mode_story_update_with_existing_root_replies_to_it
    above - same real story/root-delivery setup, but delivered through the real
    send_to_editorial_destination() call (not the legacy send_editorial_card()), proving
    reply_to_message_id actually reaches the real Bot.send_message call for router-mode NEWS
    delivery, which it silently never did before this phase. Uses V8-family output (not V6) so
    this also exercises the real render_v81_news_card_html() path - the NINJA PULSE footer
    (Phase 23.1Q) is wired only into that call site, never the legacy render_editorial_card()
    fallback V6 output takes, so a V6 fixture here would not actually prove the footer survives
    an UPDATE reply."""
    _router_settings(monkeypatch)
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE
    from tests.test_router_media_integration import _v82_capability_registry

    async with factory() as probe_session:
        if not await _table_exists(probe_session, "content_draft_reply_routing_proposals"):
            pytest.skip(_MIGRATION_SKIP_REASON)

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        root_event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        root_task = EditorialTask(
            id=uuid4(), event_id=root_event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
            workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
        )
        session.add(root_task)
        await session.flush()
        root_draft = ContentDraft(
            id=uuid4(), task_id=root_task.id, type=ContentType.POST, title="root", body="root body",
            version=1, status="draft",
        )
        session.add(root_draft)
        await session.flush()
        session.add(
            StoryTelegramDelivery(
                id=uuid4(), story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=_REAL_CHAT_ID,
                telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
                delivery_status=DeliveryStatus.SENT, idempotency_key=f"root-{uuid4()}",
                sent_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1001

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_message.assert_called_once()
    assert fake_bot.send_message.call_args.kwargs["reply_to_message_id"] == 999
    assert result.story_fail_closed_review == 0
    assert result.notified == 1

    # Phase 23.1Q: the NINJA PULSE footer must survive an UPDATE reply exactly like a root post -
    # reply-threading is purely about the send call's reply_to_message_id, never about which
    # renderer built the HTML, so both use the identical render_v81_news_card_html() output.
    sent_text = fake_bot.send_message.call_args.args[1]
    assert sent_text.count("NINJA PULSE. Подписаться 🥷") == 1
    assert '<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>' in sent_text

    async with factory() as session:
        delivery = (
            await session.execute(
                select(StoryTelegramDelivery).where(
                    StoryTelegramDelivery.story_id == story.id,
                    StoryTelegramDelivery.delivery_type == DeliveryType.REPLY,
                )
            )
        ).scalars().first()
        assert delivery is not None
        assert delivery.reply_to_message_id == 999
        assert delivery.telegram_message_id == 1001


@pytest.mark.asyncio
async def test_router_mode_verified_quote_renders_in_the_v8_family_card(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real, already-verified quote (services/quote_lookup.py::get_quote_for_draft(), patched
    at its exact call site per this codebase's own established "patch the DB lookup, don't
    hand-seed a full verification pipeline" convention - see tests/test_router_media_integration.
    py's own module docstring) must actually appear in the delivered V8-family card once
    quote_telegram_rendering_mode == "enforce" - the exact gap docs/phase23_1p_story_memory_
    quotes_gate_report.md §19 disclosed (a real quote was extracted but never displayed)."""
    _router_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "quote_telegram_rendering_mode", "enforce")
    from tests.test_router_media_integration import _v82_capability_registry

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    fake_quote = ContentDraftQuote(
        content_draft_id=uuid4(),  # never dereferenced - get_quote_for_draft() itself is patched
        quote_text="We built this because reasoning matters more than raw speed.",
        translated_text=None, speaker="A Company Spokesperson",
    )

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 2001

    with patch("worker.content_cycle.get_quote_for_draft", new=AsyncMock(return_value=fake_quote)):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    fake_bot.send_message.assert_called_once()
    sent_text = fake_bot.send_message.call_args.args[1]
    assert "<blockquote>We built this because reasoning matters more than raw speed.</blockquote>" in sent_text
    assert "— A Company Spokesperson" in sent_text
    # The mandatory one-paragraph main body must still survive whole, unmodified by the quote.
    assert "OpenAI released a new flagship model" in sent_text
    # Phase 23.1Q: footer present exactly once, and strictly AFTER the quote block (headline ->
    # body -> quote -> footer, the required order).
    assert sent_text.count("NINJA PULSE. Подписаться 🥷") == 1
    assert sent_text.index("</blockquote>") < sent_text.index("NINJA PULSE. Подписаться 🥷")


@pytest.mark.asyncio
async def test_router_mode_quote_shadow_mode_never_renders(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """quote_telegram_rendering_mode == "shadow" (this project's real, current .env value) must
    look the quote up (proving the lookup path works) without ever changing real output - the
    exact "shadow never changes production behavior" guarantee this codebase already establishes
    for story_memory_mode/fact_safety_mode, now also verified for quotes specifically."""
    _router_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "quote_telegram_rendering_mode", "shadow")
    from tests.test_router_media_integration import _v82_capability_registry

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    fake_quote = ContentDraftQuote(
        content_draft_id=uuid4(), quote_text="We built this because reasoning matters more than raw speed.",
        translated_text=None, speaker="A Company Spokesperson",
    )

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 2002

    with patch(
        "worker.content_cycle.get_quote_for_draft", new=AsyncMock(return_value=fake_quote),
    ) as mock_get_quote:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_get_quote.assert_called_once()  # the lookup path runs even in shadow
    assert result.notified == 1
    sent_text = fake_bot.send_message.call_args.args[1]
    assert "<blockquote>" not in sent_text
    assert "We built this" not in sent_text


@pytest.mark.asyncio
async def test_router_mode_multi_image_update_preserves_reply_to_message_id(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 8 (Media Roadmap Recovery step 1): a confirmed UPDATE with a resolvable root and
    multiple ranked images must be delivered as a real Telegram media-group reply -
    reply_to_message_id must point to the root independently of the media-group/topic routing
    (services/telegram_routing.py::send_media_group_to_editorial_destination() threads it through
    exactly like the other two send functions - never overwritten by message_thread_id, a
    structurally separate parameter)."""
    _router_settings(monkeypatch)
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE
    from tests.test_router_media_integration import _fake_candidate, _v82_capability_registry

    async with factory() as probe_session:
        if not await _table_exists(probe_session, "content_draft_reply_routing_proposals"):
            pytest.skip(_MIGRATION_SKIP_REASON)

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        event_row = await session.get(NewsEvent, event.id)
        assert event_row is not None
        event_row.url = "https://example.com/article"  # needed for the source-button assertion below
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        root_event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        root_task = EditorialTask(
            id=uuid4(), event_id=root_event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
            workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
        )
        session.add(root_task)
        await session.flush()
        root_draft = ContentDraft(
            id=uuid4(), task_id=root_task.id, type=ContentType.POST, title="root", body="root body",
            version=1, status="draft",
        )
        session.add(root_draft)
        await session.flush()
        session.add(
            StoryTelegramDelivery(
                id=uuid4(), story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=_REAL_CHAT_ID,
                telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
                delivery_status=DeliveryStatus.SENT, idempotency_key=f"root-{uuid4()}",
                sent_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    from unittest.mock import MagicMock
    fake_bot.send_media_group.return_value = [MagicMock(message_id=1001), MagicMock(message_id=1002)]
    candidates = [
        _fake_candidate(candidate_id="u1", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="u2", rank=2, quality_score=85, relevance_score=85),
    ]

    with patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_not_called()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2
    assert kwargs["reply_to_message_id"] == 999  # points to root, independent of media/topic routing
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID  # topic routing unaffected by reply-threading
    assert result.router_media_group_sent == 1
    assert result.story_fail_closed_review == 0

    # Media-quality corrective phase: the real [Source] button must still be attached (via
    # edit_message_reply_markup on the group's FIRST message) even for an UPDATE reply - the
    # button fix and reply-threading are independent mechanisms that must not interfere.
    fake_bot.edit_message_reply_markup.assert_called_once()
    edit_args, edit_kwargs = fake_bot.edit_message_reply_markup.call_args
    assert edit_kwargs["chat_id"] == _REAL_CHAT_ID
    assert edit_kwargs["message_id"] == 1001  # the group's first message, not the reply target
    assert edit_kwargs["reply_markup"].inline_keyboard[0][0].url == "https://example.com/article"

    async with factory() as session:
        delivery = (
            await session.execute(
                select(StoryTelegramDelivery).where(
                    StoryTelegramDelivery.story_id == story.id,
                    StoryTelegramDelivery.delivery_type == DeliveryType.REPLY,
                )
            )
        ).scalars().first()
        assert delivery is not None
        assert delivery.reply_to_message_id == 999
        assert delivery.telegram_message_id == 1001
