"""Phase 23.1I Part B/G - duplicate-delivery guard tests (docs/
phase23_1i_live_editorial_hardening_report.md).

Pure-function cases (1, 2, 5) plus a documented, deliberate non-case (3/4 collapse - see
`test_story_update_is_never_blocked_material_or_not` below) driven directly by Part A's own
investigation: `services/story_delta_engine.py`'s material-update classification is neither wired
into the live pipeline nor persisted anywhere in the real database (its migration was created but
never applied) - `should_block_duplicate_delivery()` therefore cannot distinguish a materially
different STORY_UPDATE from a non-material one, and per the phase brief's own explicit "do not
invent missing state" instruction, never blocks STORY_UPDATE at all.

CASE 6 (the real Armenia pair) is captured here too, using the exact real headline strings from
the two Phase 23.1H events - `services/story_memory.py`'s own `score_candidate()`, called in
complete isolation (no session, no DB row, a plain in-memory `Story` object never added to any
session) - locking in the investigation's own finding as a permanent regression test: even the
current matcher does not consider these two real headlines a match.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType
from core.config import settings
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    extract_story_signature,
    is_story_update_match,
    score_candidate,
)
from services.story_duplicate_guard import (
    check_duplicate_story_delivery,
    check_update_would_fail_closed,
    should_block_duplicate_delivery,
)
from services.story_telegram_delivery import record_delivery
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    _make_event,
    factory,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    test_source,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
)

# ---------------------------------------------------------------------------
# CASE 1 / 2 - SEMANTIC_DUPLICATE / SUPPORTING_SOURCE with a prior delivery -> blocked
# ---------------------------------------------------------------------------


def test_case_1_semantic_duplicate_with_prior_delivery_is_blocked() -> None:
    assert should_block_duplicate_delivery(SEMANTIC_DUPLICATE, has_prior_root_delivery=True) is True


def test_case_2_supporting_source_with_prior_delivery_is_blocked() -> None:
    assert should_block_duplicate_delivery(SUPPORTING_SOURCE, has_prior_root_delivery=True) is True


# ---------------------------------------------------------------------------
# CASE 3/4 - STORY_UPDATE always allowed, material or not (documented limitation, not a bug)
# ---------------------------------------------------------------------------


def test_story_update_is_never_blocked_material_or_not() -> None:
    """Phase 23.1I Part A confirmed `delta_classification` (the only real signal that could
    distinguish a material update from a non-material one) is neither computed by the live
    pipeline nor persisted in the real database. The phase brief's own Part B explicitly
    instructs: do not invent missing state. STORY_UPDATE is Story Memory's own existing
    definition of "a materially different title, a real new development" (services/
    story_memory.py's own module docstring) - the closest real signal available - so it is never
    blocked, regardless of a prior delivery. This single test intentionally covers what the phase
    brief's Case 3 ("no material change -> blocked") and Case 4 ("material update -> allowed")
    would otherwise test separately - with current real persisted state, they collapse into one
    identical, always-allowed behavior."""
    assert should_block_duplicate_delivery(STORY_UPDATE, has_prior_root_delivery=True) is False


# ---------------------------------------------------------------------------
# CASE 5 - different Story (no prior delivery on THIS story) -> allowed
# ---------------------------------------------------------------------------


def test_case_5_different_story_is_allowed() -> None:
    assert should_block_duplicate_delivery(NEW_STORY, has_prior_root_delivery=False) is False


# ---------------------------------------------------------------------------
# Additional pure-function coverage
# ---------------------------------------------------------------------------


def test_no_story_link_at_all_is_never_blocked() -> None:
    """story_memory_mode == 'off' (today's real default) - no NewsEventStoryLink exists, so
    match_type is None. Must never block - this is the exact "purely additive, zero regression"
    guarantee for every environment where Story Memory did not run."""
    assert should_block_duplicate_delivery(None, has_prior_root_delivery=True) is False
    assert should_block_duplicate_delivery(None, has_prior_root_delivery=False) is False


def test_semantic_duplicate_without_a_prior_delivery_is_allowed() -> None:
    """This IS the first delivery attempt for the Story - nothing to duplicate against yet."""
    assert should_block_duplicate_delivery(SEMANTIC_DUPLICATE, has_prior_root_delivery=False) is False


def test_uncertain_match_is_never_blocked() -> None:
    """Mirrors Story Memory's own established 'false suppression is worse than a duplicate'
    design philosophy - uncertainty is never grounds for suppression."""
    assert should_block_duplicate_delivery(UNCERTAIN_MATCH, has_prior_root_delivery=True) is False


def test_related_story_is_never_blocked() -> None:
    """RELATED_STORY is explicitly non-blocking/informational only by Story Memory's own design
    (services/story_memory.py's own module docstring) - never merges, never suppresses."""
    assert should_block_duplicate_delivery(RELATED_STORY, has_prior_root_delivery=True) is False


# ---------------------------------------------------------------------------
# CASE 6 - the real Armenia pair: even the current matcher does not consider these a match
# ---------------------------------------------------------------------------


def test_case_6_armenia_pair_real_headlines_do_not_match_under_the_current_matcher() -> None:
    """Locks in Phase 23.1I Part A's own investigation finding (docs/
    phase23_1i_live_editorial_hardening_report.md §2): using the exact real headline text from
    the two Phase 23.1H live events, scored in complete isolation (a plain in-memory Story object,
    never added to any session - zero DB writes, zero contamination from other real Story rows),
    the current Phase 20 matcher's combined score stays far below even the 0.35 UNCERTAIN_MATCH
    threshold. This is not a Story Memory bug this phase fixes - it is a real, disclosed
    limitation: two genuinely differently-worded headlines about arguably the same event, sharing
    almost no distinctive vocabulary, are beyond what a deterministic keyword/entity matcher
    (without embeddings/LLM assistance, explicitly out of scope) can reliably catch."""
    title_a = "Крупнейшая в СНГ ИИ-фабрика NVIDIA появится в Армении — Firebird развернула 15 из 300 МВт"
    title_b = "В Армении открыли один из самых больших дата-центров в Европе - Zerkalo"
    category_a = EventCategory.GADGETS
    category_b = EventCategory.AI

    sig_a = extract_story_signature(title_a, category_a)
    sig_b = extract_story_signature(title_b, category_b)

    story_a = Story(
        id=uuid4(), title=title_a, category=category_a,
        entities=sig_a.entities, keywords=sig_a.keywords, topic_bucket=sig_a.topic_bucket,
        first_event_id=uuid4(), event_count=1,
    )

    combined, entity_overlap, title_overlap = score_candidate(title_b, sig_b, category_b, story_a.title, story_a)

    assert combined < 0.35  # would classify as NEW_STORY, not any degree of match
    assert entity_overlap < 0.2  # near-zero real entity overlap between these two specific headlines


@pytest.mark.parametrize("match_type", [SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE, UNCERTAIN_MATCH, RELATED_STORY])
def test_no_prior_delivery_is_always_allowed_regardless_of_match_type(match_type: str) -> None:
    """`has_prior_root_delivery=False` short-circuits every match_type - there is nothing to be a
    duplicate OF yet, so this can never legitimately be the reason a send is withheld."""
    assert should_block_duplicate_delivery(match_type, has_prior_root_delivery=False) is False


# ---------------------------------------------------------------------------
# Orchestration-level tests (real DB, services.story_duplicate_guard.check_duplicate_story_delivery)
# ---------------------------------------------------------------------------


async def _make_story_with_link(
    factory_: async_sessionmaker[AsyncSession], source: object, *, match_type: str, root_title: str | None = None,
) -> tuple[object, object]:
    """Phase 23.1P: also links a `root_event` (matching real production shape - `services.
    triage_orchestrator._apply_story_memory()` unconditionally creates a NewsEventStoryLink for
    EVERY event including a brand-new story's own first/root one, match_type=NEW_STORY) so
    `services.story_delta_engine.compute_story_delta()` - now consulted by
    `check_duplicate_story_delivery()` - has a real prior title to compare `event`'s own title
    against, instead of an empty pool (which `classify_delta()` correctly, defensively reports as
    `UNCERTAIN_DELTA`, never a confident same-title rewording). `root_title` defaults to `event`'s
    own title (byte-identical rewording -> NO_NEW_FACTS -> would_suppress=True) - the correct
    shape for a genuine near-duplicate; callers exercising a real STORY_UPDATE pass a materially
    different `root_title` instead."""
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        root_event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        root_event.title = root_title if root_title is not None else event.title
        await session.flush()
        story = Story(
            id=uuid4(), title=root_event.title, category=EventCategory.AI, entities=[], keywords=[],
            topic_bucket="product", first_event_id=root_event.id, event_count=2,
        )
        session.add(story)
        await session.flush()
        session.add(NewsEventStoryLink(news_event_id=root_event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
        session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9))
        await session.commit()
    return story, event


@pytest.mark.asyncio
async def test_orchestration_no_story_link_is_never_blocked(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))

    async with factory() as check_session:
        result = await check_duplicate_story_delivery(check_session, event.id)

    assert result.blocked is False
    assert result.match_type is None
    assert "did not run" in result.reason


@pytest.mark.asyncio
async def test_orchestration_semantic_duplicate_with_real_root_delivery_is_blocked(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    story, event = await _make_story_with_link(factory, test_source, match_type=SEMANTIC_DUPLICATE)

    # A real, prior, successful root delivery for this same Story - a different draft's send.
    async with factory() as session:
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
        await record_delivery(
            session, story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=-1004297182444,
            telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
            delivery_status=DeliveryStatus.SENT, sent_at=datetime.now(timezone.utc),
        )
        await session.commit()

    async with factory() as check_session:
        result = await check_duplicate_story_delivery(check_session, event.id)

    assert result.blocked is True
    assert result.story_id == story.id
    assert result.match_type == SEMANTIC_DUPLICATE
    # Phase 23.1P: V1 (match_type) alone is no longer sufficient - blocked here because the V2
    # delta engine ALSO agrees (event's title is byte-identical to the story's root title, per
    # `_make_story_with_link()`'s own default -> NO_NEW_FACTS -> would_suppress=True).
    assert result.delta_classification == "no_new_facts"
    assert result.would_suppress is True


@pytest.mark.asyncio
async def test_orchestration_semantic_duplicate_without_a_prior_delivery_is_allowed(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    story, event = await _make_story_with_link(factory, test_source, match_type=SEMANTIC_DUPLICATE)

    async with factory() as check_session:
        result = await check_duplicate_story_delivery(check_session, event.id)

    assert result.blocked is False  # nothing delivered for this Story yet - this IS the first post


@pytest.mark.asyncio
async def test_orchestration_v1_would_block_but_v2_delta_shows_real_new_information_allowed(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
) -> None:
    """Phase 23.1P: the real, evidenced precision gain V2 adds over V1 alone (forensics table,
    docs/phase23_1p_story_memory_quotes_gate_report.md - two syndicated-wire articles scoring a
    near-identical-title SEMANTIC_DUPLICATE match under V1, but whose actual numeric claim
    differs). `event`'s own title carries a genuinely new material claim (a dollar figure) never
    present in the story's root title - `classify_delta()` must classify this MATERIAL_UPDATE, and
    `compute_would_suppress()` must therefore NOT suppress even though match_type alone says
    SEMANTIC_DUPLICATE and a root delivery already exists."""
    story, event = await _make_story_with_link(
        factory, test_source, match_type=SEMANTIC_DUPLICATE,
        root_title="2 Unstoppable AI Stocks That Will Join Amazon in the Trillion Club by 2027",
    )
    async with factory() as session:
        ev = await session.get(type(event), event.id)
        ev.title = "2 Unstoppable AI Stocks That Will Join Amazon in the $3 Trillion Club by 2027"
        await session.commit()

        root_task = EditorialTask(
            id=uuid4(), event_id=story.first_event_id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
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
        await record_delivery(
            session, story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=-1004297182444,
            telegram_message_id=1000, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
            delivery_status=DeliveryStatus.SENT, sent_at=datetime.now(timezone.utc),
        )
        await session.commit()

    async with factory() as check_session:
        result = await check_duplicate_story_delivery(check_session, event.id)

    assert result.match_type == SEMANTIC_DUPLICATE  # V1 alone would have blocked this
    assert result.delta_classification == "material_update"
    assert result.blocked is False
    assert result.would_suppress is False


# ---------------------------------------------------------------------------
# NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §B):
# is_story_update_match() and check_update_would_fail_closed()
# ---------------------------------------------------------------------------


def test_is_story_update_match_true_for_every_confident_outcome() -> None:
    for match_type in (STORY_UPDATE, SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, RELATED_STORY):
        assert is_story_update_match(match_type) is True


def test_is_story_update_match_false_for_new_story_uncertain_and_none() -> None:
    assert is_story_update_match(NEW_STORY) is False
    assert is_story_update_match(UNCERTAIN_MATCH) is False
    assert is_story_update_match(None) is False


@pytest.mark.asyncio
async def test_update_fail_closed_check_is_noop_unless_enforce(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"off"/"shadow" must never fail-closed-drop - shadow still generates and sends as a
    standalone post purely to observe the would-be rate (services/story_telegram_delivery.py's own
    module docstring); short-circuiting for those modes would silently change that observability
    behavior, not just save cost."""
    story, event = await _make_story_with_link(factory, test_source, match_type=STORY_UPDATE)
    for mode in ("off", "shadow"):
        monkeypatch.setattr(settings, "telegram_story_reply_mode", mode)
        async with factory() as session:
            result = await check_update_would_fail_closed(session, event.id)
        assert result.would_fail_closed is False
        assert "not enforce" in result.reason


@pytest.mark.asyncio
async def test_update_fail_closed_check_true_when_no_root_under_enforce(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    story, event = await _make_story_with_link(factory, test_source, match_type=STORY_UPDATE)

    async with factory() as session:
        result = await check_update_would_fail_closed(session, event.id)

    assert result.would_fail_closed is True
    assert result.story_id == story.id
    assert result.match_type == STORY_UPDATE


@pytest.mark.asyncio
async def test_update_fail_closed_check_false_when_root_resolvable_under_enforce(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    story, event = await _make_story_with_link(factory, test_source, match_type=STORY_UPDATE)

    async with factory() as session:
        root_task = EditorialTask(
            id=uuid4(), event_id=story.first_event_id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
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
        await record_delivery(
            session, story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=-1004297182444,
            telegram_message_id=777, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
            delivery_status=DeliveryStatus.SENT, sent_at=datetime.now(timezone.utc),
        )
        await session.commit()

    async with factory() as session:
        result = await check_update_would_fail_closed(session, event.id)

    assert result.would_fail_closed is False


@pytest.mark.asyncio
async def test_update_fail_closed_check_false_for_new_story(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    _story, event = await _make_story_with_link(factory, test_source, match_type=NEW_STORY)

    async with factory() as session:
        result = await check_update_would_fail_closed(session, event.id)

    assert result.would_fail_closed is False


@pytest.mark.asyncio
async def test_update_fail_closed_check_false_with_no_story_link(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))

    async with factory() as session:
        result = await check_update_would_fail_closed(session, event.id)

    assert result.would_fail_closed is False
    assert "did not run" in result.reason
