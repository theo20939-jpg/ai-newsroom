"""R2.10-RUNTIME-2 - services.event_recap_scheduler tests. Test matrix A-U per the phase's own
spec. Mirrors tests/test_event_recap_processor.py's own established fixture/helper-duplication
conventions exactly (real Postgres via the db_session fixture, FakeLLMGateway, zero network/cost -
no real LLM call anywhere in this file)."""
from __future__ import annotations

import ast
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services import image_persistence
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION, build_event_recap_candidate
from services.event_recap_scheduler import (
    EventRecapScanResult,
    _run_generation,
    _run_shadow_observation,
    _select_candidate_story_ids,
    run_event_recap_scan,
)
from services.recap_event import _CONFIRMED_MEMBERSHIP_MATCH_TYPES
from services.story_memory import NEW_STORY, RELATED_STORY, STORY_UPDATE, UNCERTAIN_MATCH
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEDULER_PATH = _REPO_ROOT / "services" / "event_recap_scheduler.py"

_VALID_RECAP_OUTPUT = {
    "recap_title": "Example Recap Title",
    "recap_summary": "Example recap summary sentence.",
    "key_takeaways": ["First takeaway.", "Second takeaway."],
    "uncertainty_notes": [],
}


@pytest.fixture(autouse=True)
def _isolated_image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001
    """Same isolation as tests/test_event_recap_processor.py's own identical fixture - generation-
    mode tests may reach Tier 3 branded-fallback rendering, which writes real bytes."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=EVENT_RECAP_PROMPT_NAME, version=EVENT_RECAP_PROMPT_VERSION,
            system="You are a fake recap analyst.", rules=["Never invent facts."],
            output_schema={
                "type": "object",
                "properties": {
                    "recap_title": {"type": "string"}, "recap_summary": {"type": "string"},
                    "key_takeaways": {"type": "array"}, "uncertainty_notes": {"type": "array"},
                },
                "required": ["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
            },
        )
    )
    return repository


def _registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability(gateway, _prompt_repository()))
    registry.seal()
    return registry


def _fake_gateway() -> FakeLLMGateway:
    return FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )


def _single_session_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Wraps an already-open test session (the `db_session` fixture, savepoint-based, rolled back
    at teardown) as a zero-arg `session_factory` callable - the shape `run_event_recap_scan()`
    itself requires. Never closes the wrapped session on exit (that remains db_session's own
    fixture-managed lifecycle) - mirrors tests/test_workflow_runner.py's own established
    `@asynccontextmanager`-around-a-shared-session precedent."""
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session
    return factory  # type: ignore[return-value]


async def _seed_not_ready_story(session: AsyncSession, *, updated_at: datetime | None = None) -> tuple[Story, NewsEvent]:
    """Duplicated from tests/test_event_recap_processor.py's own identically-named, identically-
    behaved helper (per this codebase's own established per-file-helper-duplication convention) -
    single-event Story, fails all three readiness minimums at once."""
    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True,
    )
    session.add(source)
    await session.flush()

    event = NewsEvent(
        source_id=source.id, title="Example headline for scheduler test", content="Body",
        category=EventCategory.AI, hash=f"test-hash-{uuid4()}",
    )
    session.add(event)
    await session.flush()

    story = Story(
        title=event.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="test", first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await session.flush()
    if updated_at is not None:
        story.updated_at = updated_at
        await session.flush()
    return story, event


_READY_EVENT_TITLES_URLS: tuple[tuple[str, str], ...] = (
    ("Apple unveils iPhone X", "https://techcrunch.com/c1"),
    ("Apple announces iPhone X pricing", "https://theverge.com/c2"),
    ("Apple reveals Watch Ultra 3", "https://engadget.com/c3"),
    ("Apple introduces Apple Intelligence upgrade", "https://arstechnica.com/c4"),
    ("Apple demos iPhone X", "https://9to5mac.com/c5"),
    ("Apple announces iPhone X pricing details", "https://macrumors.com/c6"),
)
_READY_EVENT_MINUTES_AGO_OFFSETS: tuple[int, ...] = (50, 40, 30, 20, 10, 0)


async def _seed_ready_story(session: AsyncSession, *, base_minutes_ago: int = 120) -> tuple[Story, list[NewsEvent]]:
    """Duplicated from tests/test_event_recap_processor.py's own identically-named helper (the
    same real, proven-READY 6-event/4-cluster/6-source fixture) - `base_minutes_ago=120` keeps the
    freshest event past the 90-minute cooling window by default; a smaller value (e.g. 30) keeps
    it WITHIN the cooling window, for §K's own cooling-transition test."""
    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True,
    )
    session.add(source)
    await session.flush()

    now = datetime.now(timezone.utc)
    events: list[NewsEvent] = []
    for (title, url), offset in zip(_READY_EVENT_TITLES_URLS, _READY_EVENT_MINUTES_AGO_OFFSETS):
        minutes_ago = base_minutes_ago + offset
        event = NewsEvent(
            source_id=source.id, title=title, url=url, content="Body",
            published_at=now - timedelta(minutes=minutes_ago), collected_at=now - timedelta(minutes=minutes_ago),
            category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
        )
        session.add(event)
        events.append(event)
    await session.flush()

    story = Story(
        title=events[0].title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=events[0].id, event_count=len(events),
    )
    session.add(story)
    await session.flush()
    for event in events:
        session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await session.flush()
    return story, events


async def _seed_existing_task(session: AsyncSession, event_id, *, status: TaskStatus) -> EditorialTask:  # noqa: ANN001
    """A minimal, real EditorialTask row for the SAME (event_id, EVENT_RECAP) shape
    find_event_recap_task_id()/`_select_candidate_story_ids()`'s own EXISTS-subquery both key on -
    never a fake/mocked row."""
    task = EditorialTask(
        event_id=event_id, priority=TaskPriority.C, status=status,
        workflow={"workflow_name": "EVENT_RECAP", "workflow_version": 1, "current_step": "synthesize_recap",
                  "completed_steps": [], "iteration_count": 0, "step_results": [], "failure": None},
    )
    session.add(task)
    await session.flush()
    return task


async def _event_recap_task_count(session: AsyncSession, event_id) -> int:  # noqa: ANN001
    return (
        await session.execute(
            select(func.count()).select_from(EditorialTask).where(
                EditorialTask.event_id == event_id,
                EditorialTask.workflow["workflow_name"].as_string() == "EVENT_RECAP",
            )
        )
    ).scalar_one()


async def _image_candidate_count(session: AsyncSession) -> int:
    from database.models.image_candidate_record import ImageCandidateRecord

    return (await session.execute(select(func.count()).select_from(ImageCandidateRecord))).scalar_one()


# --- R2.10-RUNTIME-3C helpers ------------------------------------------------------------------


async def _seed_mature_confirmed_story(
    session: AsyncSession, *, event_count: int = 6, last_confirmed_minutes_ago: int = 200,
) -> tuple[Story, list[NewsEvent]]:
    """A Story whose CONFIRMED member events are all well past the cooling window (real READY
    shape - reuses the same proven Apple/iPhone title set as `_seed_ready_story()` so it also
    genuinely passes readiness when `event_count>=4`, not merely `Story.event_count`), but whose
    `Story.updated_at` is left at its ordinary insert-time value - the RUNTIME-3C tests below
    independently control `updated_at`/add extra non-confirming links to prove the NEW selector no
    longer depends on it."""
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True)
    session.add(source)
    await session.flush()

    now = datetime.now(timezone.utc)
    titles = _READY_EVENT_TITLES_URLS[:event_count] if event_count <= len(_READY_EVENT_TITLES_URLS) else (
        _READY_EVENT_TITLES_URLS + tuple((f"Extra confirmed event {i}", f"https://example.com/extra-{i}") for i in range(event_count - len(_READY_EVENT_TITLES_URLS)))
    )
    events: list[NewsEvent] = []
    for offset, (title, url) in enumerate(titles):
        minutes_ago = last_confirmed_minutes_ago + (len(titles) - 1 - offset) * 5
        event = NewsEvent(
            source_id=source.id, title=title, url=url, content="Body",
            published_at=now - timedelta(minutes=minutes_ago), collected_at=now - timedelta(minutes=minutes_ago),
            category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
        )
        session.add(event)
        events.append(event)
    await session.flush()

    story = Story(
        title=events[0].title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=events[0].id, event_count=len(events),
    )
    session.add(story)
    await session.flush()
    for event in events:
        session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await session.flush()
    return story, events


async def _bump_story_updated_at(session: AsyncSession, story: Story, *, when: datetime) -> None:
    """Directly sets `Story.updated_at` to `when`, bypassing `onupdate=func.now()` - simulates the
    real-world effect of ANY write to the Story row (including one triggered by a non-confirming
    UNCERTAIN_MATCH/RELATED_STORY link's own creation) without needing to reproduce that write
    path's own exact mechanics."""
    story.updated_at = when
    await session.flush()


async def _add_story_link(
    session: AsyncSession, story_id, *, match_type: str, minutes_ago: float,
) -> NewsEvent:  # noqa: ANN001
    """One more real NewsEvent + NewsEventStoryLink pointed at an EXISTING story - used to add
    CONFIRMED or NON-CONFIRMING activity independently of the story's own original seeding."""
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True)
    session.add(source)
    await session.flush()
    now = datetime.now(timezone.utc)
    event = NewsEvent(
        source_id=source.id, title=f"Extra {match_type} event {uuid4()}", content="Body",
        published_at=now - timedelta(minutes=minutes_ago), collected_at=now - timedelta(minutes=minutes_ago),
        category=EventCategory.AI, hash=f"test-hash-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story_id, match_type=match_type, match_score=0.5))
    await session.flush()
    return event


# --- F: generation requires scheduler ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_without_scheduler_fails_closed(monkeypatch: pytest.MonkeyPatch, caplog) -> None:  # noqa: ANN001
    """Test F. §5's own invalid-state contract."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", False)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", True)

    async def _factory_must_not_be_called():
        raise AssertionError("session_factory must never be called when scheduler is disabled")

    with caplog.at_level("WARNING"):
        result = await run_event_recap_scan(session_factory=_factory_must_not_be_called)  # type: ignore[arg-type]

    assert result.mode == "disabled"
    assert any("event_recap_generation_enabled_without_scheduler_enabled" in r.message for r in caplog.records)


# --- A: scheduler disabled => zero RECAP query/call --------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_fully_disabled_issues_zero_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test A."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", False)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)

    async def _factory_must_not_be_called():
        raise AssertionError("session_factory must never be called when scheduler is disabled")

    result = await run_event_recap_scan(session_factory=_factory_must_not_be_called)  # type: ignore[arg-type]
    assert result == EventRecapScanResult(mode="disabled")


# --- B/C/D/E: shadow mode - read-only candidate evaluation, zero task/LLM/network -----------------------


@pytest.mark.asyncio
async def test_shadow_mode_observes_ready_and_not_ready_without_side_effects(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests B, C, D, E combined."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)

    ready_story, ready_events = await _seed_ready_story(db_session)
    not_ready_story, not_ready_event = await _seed_not_ready_story(db_session)

    images_before = await _image_candidate_count(db_session)

    result = await run_event_recap_scan(session_factory=_single_session_factory(db_session))

    assert result.mode == "shadow"
    assert result.scanned >= 2
    assert result.ready_observed >= 1
    assert result.not_ready_observed >= 1
    assert result.errors == 0

    # C: zero task created for the READY story.
    assert await _event_recap_task_count(db_session, ready_story.first_event_id) == 0
    assert await _event_recap_task_count(db_session, not_ready_story.first_event_id) == 0
    # E: zero Tier-2B network media acquisition occurred (would create new ImageCandidateRecord rows).
    assert await _image_candidate_count(db_session) == images_before
    # D: shadow mode never even receives a Gateway/registry - structurally zero LLM calls (see
    # test_shadow_mode_never_imports_processor_or_gateway_machinery below for the AST-level proof).


def test_shadow_mode_never_imports_processor_or_gateway_machinery() -> None:
    """Test D (structural half) + E (structural half). `_run_shadow_observation` must never
    reference `generate_recap_for_story`/`discover_event_recap_media_if_needed`/any Gateway name -
    AST-based, not a substring search."""
    tree = ast.parse(_SCHEDULER_PATH.read_text(encoding="utf-8"))
    shadow_fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_shadow_observation"
    )
    names_used: set[str] = set()
    for node in ast.walk(shadow_fn):
        if isinstance(node, ast.Name):
            names_used.add(node.id)
        elif isinstance(node, ast.Attribute):
            names_used.add(node.attr)
    forbidden = {"generate_recap_for_story", "discover_event_recap_media_if_needed", "CapabilityExecutor", "WorkflowRunner"}
    assert not (names_used & forbidden), names_used & forbidden


# --- G: bounded scan limit --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_limit_is_bounded(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test G."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)
    monkeypatch.setattr(settings, "event_recap_scan_limit", 2)

    for _ in range(4):
        await _seed_not_ready_story(db_session)

    result = await run_event_recap_scan(session_factory=_single_session_factory(db_session))
    assert result.scanned == 2


# --- R2.10-RUNTIME-3C: candidate-selection ordering fix -------------------------------------------


@pytest.mark.asyncio
async def test_candidate_query_orders_by_confirmed_activity_not_updated_at(db_session: AsyncSession) -> None:
    """Replaces the old `updated_at`-ordering test (that ordering key was the RUNTIME-3A root
    cause, no longer used at all). A Story with a genuinely OLDER confirmed event but an
    ARTIFICIALLY BUMPED `updated_at` (simulating non-confirming-match noise) must NOT outrank a
    Story with a genuinely MORE RECENT confirmed event and an untouched `updated_at` - proves the
    new ordering key survives exactly the distortion the old one didn't."""
    noisy_but_stale, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=300)
    await _bump_story_updated_at(db_session, noisy_but_stale, when=datetime.now(timezone.utc))  # simulated noise

    genuinely_fresh, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=10)

    ids = await _select_candidate_story_ids(db_session, limit=50)
    assert ids.index(genuinely_fresh.id) < ids.index(noisy_but_stale.id)


# --- A: current updated_at-only bug reproduced (regression proof, not a call to removed code) -------


@pytest.mark.asyncio
async def test_A_updated_at_only_ordering_would_have_missed_the_mature_story(db_session: AsyncSession) -> None:
    """Test A. Demonstrates the OLD bug's own mechanism directly against fixture data (not by
    calling removed code): a plain `ORDER BY Story.updated_at DESC LIMIT N` - literally the RUNTIME-
    2 query this phase replaces - fails to surface a genuinely mature, confirmed-active Story once
    enough noise-bumped Stories exist, while the NEW `_select_candidate_story_ids()` still finds it
    at the same bound."""
    now = datetime.now(timezone.utc)
    mature, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=250)
    # `Story.updated_at` defaults to insert time ("now") regardless of how old its CONFIRMED events
    # are - explicitly age it to simulate real production drift (the Story row itself hasn't been
    # touched by anything, confirming or not, since long before this test's own noisy writes).
    await _bump_story_updated_at(db_session, mature, when=now - timedelta(hours=2))

    for i in range(15):
        noisy, _ = await _seed_not_ready_story(db_session)
        await _bump_story_updated_at(db_session, noisy, when=now - timedelta(seconds=i))

    old_style_stmt = select(Story.id).order_by(Story.updated_at.desc()).limit(10)
    old_style_ids = list((await db_session.execute(old_style_stmt)).scalars().all())
    assert mature.id not in old_style_ids  # the reproduced bug

    new_ids = await _select_candidate_story_ids(db_session, limit=10)
    assert mature.id in new_ids  # the fix


# --- B: confirmed mature READY Story not crowded out by uncertain matches --------------------------


@pytest.mark.asyncio
async def test_B_mature_ready_story_not_crowded_out_by_uncertain_matches(db_session: AsyncSession) -> None:
    """Test B. A real READY-shaped Story (event_count=6, matches `_seed_ready_story()`'s own proven
    shape) survives a tight bound even when 30 OTHER Stories exist with heavily-bumped
    `Story.updated_at` from repeated non-confirming matches."""
    mature, _ = await _seed_mature_confirmed_story(db_session, event_count=6, last_confirmed_minutes_ago=200)

    now = datetime.now(timezone.utc)
    for i in range(30):
        noisy, event = await _seed_not_ready_story(db_session)
        for _ in range(5):
            await _add_story_link(db_session, noisy.id, match_type=UNCERTAIN_MATCH, minutes_ago=0.1)
        await _bump_story_updated_at(db_session, noisy, when=now - timedelta(seconds=i))

    ids = await _select_candidate_story_ids(db_session, limit=10)
    assert mature.id in ids


# --- C/D: RELATED_STORY / UNCERTAIN_MATCH do not raise scheduling freshness ------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("non_confirming_type", [RELATED_STORY, UNCERTAIN_MATCH])
async def test_C_D_non_confirming_match_does_not_raise_freshness(
    db_session: AsyncSession, non_confirming_type: str,
) -> None:
    """Tests C, D. A Story with only an OLD confirmed event gets a brand-new NON-CONFIRMING link
    (RELATED_STORY or UNCERTAIN_MATCH) - its computed candidate ordering must still reflect the OLD
    confirmed timestamp, not the new non-confirming one, so it must NOT outrank a genuinely fresher
    confirmed-active Story at a tight bound."""
    assert non_confirming_type not in _CONFIRMED_MEMBERSHIP_MATCH_TYPES  # sanity on the fixture itself

    old_confirmed_only, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=300)
    await _add_story_link(db_session, old_confirmed_only.id, match_type=non_confirming_type, minutes_ago=0.01)

    genuinely_fresh, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=10)

    ids = await _select_candidate_story_ids(db_session, limit=1)
    assert ids == [genuinely_fresh.id]


# --- E: confirmed membership activity DOES influence freshness (positive control) -------------------


@pytest.mark.asyncio
async def test_E_confirmed_activity_does_raise_freshness(db_session: AsyncSession) -> None:
    """Test E. The positive control for C/D: adding a genuinely NEW CONFIRMED event (STORY_UPDATE)
    to an otherwise-stale Story DOES make it outrank a fresher-but-untouched one."""
    story_a, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=300)
    story_b, _ = await _seed_mature_confirmed_story(db_session, last_confirmed_minutes_ago=10)

    await _add_story_link(db_session, story_a.id, match_type=STORY_UPDATE, minutes_ago=0.01)

    ids = await _select_candidate_story_ids(db_session, limit=1)
    assert ids == [story_a.id]


# --- I: COOLING Story remains selectable ------------------------------------------------------------


@pytest.mark.asyncio
async def test_I_cooling_story_remains_selectable(db_session: AsyncSession) -> None:
    """Test I. A Story matching the COOLING shape (enough structural volume, cooling window not yet
    elapsed) still appears in the candidate window via Window A (fresh confirmed activity)."""
    story, _ = await _seed_ready_story(db_session, base_minutes_ago=10)  # within the cooling window

    ids = await _select_candidate_story_ids(db_session, limit=50)
    assert story.id in ids


# --- K: build_event_recap_candidate remains sole readiness authority (AST, no reimplementation) -----


def test_K_selector_never_reimplements_readiness() -> None:
    """Test K. AST-based (not substring) check: the selector module may reference
    `settings.recap_min_event_count` (the deliberate, disclosed, permissive Window-B pre-filter -
    §6's own explicitly-allowed exception) but must never reference announcement clustering, source
    counting, integrity, or cooling-window arithmetic - those remain exclusively `build_event_recap_
    candidate()`'s own job."""
    tree = ast.parse(_SCHEDULER_PATH.read_text(encoding="utf-8"))
    names_used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names_used.add(node.id)
        elif isinstance(node, ast.Attribute):
            names_used.add(node.attr)
    forbidden = {
        "cluster_announcements", "count_unique_sources", "evaluate_recap_story_integrity",
        "evaluate_recap_readiness", "recap_cooling_window_minutes", "recap_min_announcement_count",
        "recap_min_unique_sources",
    }
    assert not (names_used & forbidden), names_used & forbidden
    assert "recap_min_event_count" in names_used  # the one deliberate, disclosed exception


# --- F: candidate limit remains bounded across a rich, mixed corpus --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 5, 17, 50])
async def test_F_candidate_limit_remains_bounded(db_session: AsyncSession, limit: int) -> None:
    """Test F. Bounded under a rich, mixed corpus (both windows well-populated), not just the
    trivial small-fixture case already covered by `test_scan_limit_is_bounded`."""
    for _ in range(3):
        await _seed_mature_confirmed_story(db_session)
    for _ in range(3):
        await _seed_not_ready_story(db_session)

    ids = await _select_candidate_story_ids(db_session, limit=limit)
    assert len(ids) <= limit


# --- G: any-status task exclusion preserved for a MATURE (Window B) Story --------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.COMPLETED, TaskStatus.FAILED])
async def test_G_any_status_task_excludes_mature_story_too(db_session: AsyncSession, status: TaskStatus) -> None:
    """Test G (Window B half - the existing parametrized test above already covers Window A's own
    single-confirmed-link shape). A structurally-mature Story with an existing EVENT_RECAP task of
    ANY status must remain excluded, proving the exclusion clause is applied inside BOTH windows,
    not just the original single-window query."""
    story, events = await _seed_mature_confirmed_story(db_session)
    await _seed_existing_task(db_session, events[0].id, status=status)

    ids = await _select_candidate_story_ids(db_session, limit=50)
    assert story.id not in ids


# --- I: existing any-status EVENT_RECAP tasks excluded --------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.COMPLETED, TaskStatus.FAILED])
async def test_any_status_existing_task_excludes_story(db_session: AsyncSession, status: TaskStatus) -> None:
    """Test I. Every real TaskStatus enum value."""
    story, event = await _seed_not_ready_story(db_session)
    await _seed_existing_task(db_session, event.id, status=status)

    ids = await _select_candidate_story_ids(db_session, limit=50)
    assert story.id not in ids


@pytest.mark.asyncio
async def test_story_without_existing_task_is_included(db_session: AsyncSession) -> None:
    story, _event = await _seed_not_ready_story(db_session)
    ids = await _select_candidate_story_ids(db_session, limit=50)
    assert story.id in ids


# --- J: NOT_READY selected again in later cycle -------------------------------------------------------


@pytest.mark.asyncio
async def test_not_ready_story_reselected_across_two_conceptual_cycles(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test J."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)
    story, _event = await _seed_not_ready_story(db_session)
    factory = _single_session_factory(db_session)

    cycle1 = await run_event_recap_scan(session_factory=factory)
    assert story.id in await _select_candidate_story_ids(db_session, limit=50)
    cycle2 = await run_event_recap_scan(session_factory=factory)

    assert cycle1.not_ready_observed >= 1
    assert cycle2.not_ready_observed >= 1
    assert await _event_recap_task_count(db_session, story.first_event_id) == 0


# --- K: cooling-to-READY without new event, observed next cycle ------------------------------------------


@pytest.mark.asyncio
async def test_cooling_to_ready_transition_observed_without_new_event(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test K. Critical runtime test - the exact same Story, no new NewsEvent inserted between the
    two calls, matures from COOLING (not_ready, cooling_observed) to READY purely via `now`
    advancing past `recap_cooling_window_minutes`.

    R2.10-RUNTIME-3C note: `tests/conftest.py`'s own `db_session` fixture connects to a real,
    separate `settings.test_database_url` - but that database carries genuine, long-accumulated
    COMMITTED rows from unrelated integration tests that use a separate, genuinely-committing
    connection (e.g. `tests/test_triage_orchestrator_claims.py::independent_session_factory()`-
    style concurrency proofs) - 646 real Story rows confirmed present, ambient to every test in
    this file. The OLD `Story.updated_at`-ordered selector happened to always rank a just-inserted
    test row above that ambient cruft, incidentally shielding whole-scan aggregate assertions from
    it; the NEW confirmed-activity-ordered selector (this phase's own fix) surfaces a different,
    larger slice of that same ambient data. "Zero other READY-shaped Story anywhere in the scanned
    window" was never a real invariant this test was entitled to assume - so this test now checks
    the SEEDED Story's own transition directly (via `build_event_recap_candidate()`, the same
    authoritative function the scheduler itself calls) rather than the whole-scan aggregate
    `ready_observed` counter, while still exercising the real `run_event_recap_scan()` pipeline
    end-to-end to prove it completes cleanly at both points in time."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)

    # base_minutes_ago=30: freshest event 30 minutes before "real now" - well inside the 90-minute
    # cooling window, so every OTHER threshold (event/announcement/source counts) already clears,
    # only cooling blocks it.
    story, events = await _seed_ready_story(db_session, base_minutes_ago=30)
    published_ats = [e.published_at for e in events if e.published_at is not None]
    freshest_event_at = max(published_ats)
    factory = _single_session_factory(db_session)

    # Cycle N: "now" = real creation time - still within the cooling window.
    now_n = freshest_event_at + timedelta(minutes=10)
    cycle_n = await run_event_recap_scan(session_factory=factory, now=now_n)
    assert cycle_n.errors == 0
    still_cooling = await build_event_recap_candidate(db_session, story, force_shadow=False, now=now_n, research_complete=True)
    assert still_cooling.candidate is None
    assert await _event_recap_task_count(db_session, story.first_event_id) == 0

    # Cycle N+1: "now" advanced past the 90-minute cooling window - NO new event was inserted.
    now_n_plus_1 = freshest_event_at + timedelta(minutes=settings.recap_cooling_window_minutes + 5)
    cycle_n_plus_1 = await run_event_recap_scan(session_factory=factory, now=now_n_plus_1)
    assert cycle_n_plus_1.errors == 0
    now_ready = await build_event_recap_candidate(db_session, story, force_shadow=False, now=now_n_plus_1, research_complete=True)
    assert now_ready.candidate is not None
    assert await _event_recap_task_count(db_session, story.first_event_id) == 0  # shadow mode - still zero


# --- L/M: generation mode delegates to processor exactly once; generated status counted ------------------


@pytest.mark.asyncio
async def test_generation_mode_calls_processor_exactly_once_for_ready_story(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests L, M. R2.10-RUNTIME-3C note: `result.generated`/`gateway.received_requests` are
    asserted `>= 1` rather than `== 1` - the ambient test-database pollution documented on
    `test_cooling_to_ready_transition_observed_without_new_event` above means other, real,
    genuinely-READY Stories may legitimately also be selected and generated in the SAME cycle
    (correct generation-mode behavior, not a defect) - the specific, meaningful invariant this test
    actually verifies is that THIS Story got exactly one task/call, checked directly below."""
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", True)

    story, _events = await _seed_ready_story(db_session)
    gateway = _fake_gateway()
    registry = _registry(gateway)

    result = await run_event_recap_scan(
        session_factory=_single_session_factory(db_session), capability_registry=registry,
    )

    assert result.mode == "generation"
    assert result.generated >= 1
    assert len(gateway.received_requests) >= 1
    assert await _event_recap_task_count(db_session, story.first_event_id) == 1  # exactly one for THIS story


# --- N: already_exists handled safely ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_exists_counted_safely(db_session: AsyncSession) -> None:
    """Test N. Directly exercises `_run_generation()`'s own already_exists branch (the ordinary
    candidate query already excludes such a Story - this proves the processor's own fallback is
    still correctly counted if ever reached, e.g. under a genuine concurrent-creation race)."""
    story, event = await _seed_not_ready_story(db_session)
    await _seed_existing_task(db_session, event.id, status=TaskStatus.CREATED)
    gateway = _fake_gateway()
    registry = _registry(gateway)

    result = await _run_generation(
        db_session, [story.id], capability_registry=registry, cost_tracker=None, pricing_catalog=None,
    )
    assert result.already_exists == 1
    assert result.errors == 0
    assert gateway.received_requests == []


# --- O: one Story failure does not corrupt summary/other candidates --------------------------------------


@pytest.mark.asyncio
async def test_one_failing_story_does_not_abort_the_scan(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test O. The failing Story is processed SECOND deliberately: the production `except:
    session.rollback()` per-item recovery is correct (it must clear a poisoned transaction before
    continuing), but in THIS test both Stories were seeded, uncommitted, in the very same
    savepoint-backed `db_session` - a rollback triggered by the FIRST item would also undo the
    SECOND item's still-uncommitted row (a test-fixture artifact of sharing one session across
    seed+exercise, not a production concern: a real cycle's session only ever reads pre-committed
    Story rows in shadow mode, never anything inserted earlier in the same session). Ordering the
    failure last avoids that artifact while still proving isolation - the first (healthy) Story's
    observation is fully counted before the second Story's failure and rollback ever occur."""
    healthy_story, _ = await _seed_not_ready_story(db_session)
    failing_story, _ = await _seed_not_ready_story(db_session)

    import services.event_recap_scheduler as scheduler_module

    real_build = scheduler_module.build_event_recap_candidate

    async def _flaky_build(session, story, **kwargs):  # noqa: ANN001
        if story.id == failing_story.id:
            raise RuntimeError("simulated per-item failure")
        return await real_build(session, story, **kwargs)

    monkeypatch.setattr(scheduler_module, "build_event_recap_candidate", _flaky_build)

    result = await _run_shadow_observation(
        db_session, [healthy_story.id, failing_story.id], now=datetime.now(timezone.utc),
    )
    assert result.errors == 1
    assert result.not_ready_observed == 1  # the first, healthy Story was fully observed before the failure
    assert result.scanned == 2


# --- P/Q: eventness shadow metadata visible when its flag ON, never alters readiness ----------------------


@pytest.mark.asyncio
async def test_eventness_rule_c_shadow_visible_when_flag_on(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test P (Rule C half - see the dedicated Rule A limitation test below for why Rule A cannot
    be exercised this way).

    `count_unique_sources()` (real readiness gate) and `EventnessShadowFeatures.source_domains`
    (RULE_C) both key off `_normalize_domain(event.url)`, but they are NOT the same computation:
    `count_unique_sources()` falls back to a per-NewsSource-row `source:{source_id}` identity for
    any event with no resolvable URL domain, while `source_domains` only ever collects domains from
    events that DO have one (a `None` URL contributes nothing to it). Reusing the exact same
    proven-4-cluster title/offset shape as `_seed_ready_story()`, this fixture gives 2 of the 6
    events `url=None` from 2 DISTINCT NewsSource rows (source-id-fallback identities) and the other
    4 events `url="https://github.com/..."` (a single shared domain identity) - real readiness sees
    3 distinct identities (>= recap_min_unique_sources=2, clearing the floor), while RULE_C's own
    domain-only view sees exactly `{"github.com"}` and fires. This is the same real mechanism behind
    G3-E1's own confirmed real GitHub-only positives (their non-GitHub member events typically carry
    no clean per-article URL either)."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", True)

    source_a = NewsSource(name="Fallback Source A", type=SourceType.RSS, url=f"https://example.com/a-{uuid4()}.xml", active=True)
    source_b = NewsSource(name="Fallback Source B", type=SourceType.RSS, url=f"https://example.com/b-{uuid4()}.xml", active=True)
    github_source = NewsSource(name="GH Source", type=SourceType.RSS, url=f"https://example.com/gh-{uuid4()}.xml", active=True)
    db_session.add_all([source_a, source_b, github_source])
    await db_session.flush()

    now = datetime.now(timezone.utc)
    base_minutes_ago = 120
    urls_and_sources: list[tuple[str | None, object]] = [
        (None, source_a.id), (None, source_b.id),
        ("https://github.com/org/repo-2", github_source.id), ("https://github.com/org/repo-3", github_source.id),
        ("https://github.com/org/repo-4", github_source.id), ("https://github.com/org/repo-5", github_source.id),
    ]
    events = []
    for (title, _url_unused), offset, (url, source_id) in zip(
        _READY_EVENT_TITLES_URLS, _READY_EVENT_MINUTES_AGO_OFFSETS, urls_and_sources,
    ):
        minutes_ago = base_minutes_ago + offset
        event = NewsEvent(
            source_id=source_id, title=title, url=url, content="Body",
            published_at=now - timedelta(minutes=minutes_ago), collected_at=now - timedelta(minutes=minutes_ago),
            category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
        )
        db_session.add(event)
        events.append(event)
    await db_session.flush()

    story = Story(
        title=events[0].title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=events[0].id, event_count=len(events),
    )
    db_session.add(story)
    await db_session.flush()
    for event in events:
        db_session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await db_session.flush()

    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)
    result = await run_event_recap_scan(session_factory=_single_session_factory(db_session))

    # R2.10-RUNTIME-3C: `>= 1` rather than `== 1` for `ready_observed` - see the ambient
    # test-database pollution note on `test_cooling_to_ready_transition_observed_without_new_event`
    # above; `rule_c_triggered` stays an exact `== 1` since ambient noise is never GitHub-only
    # shaped and cannot spuriously trigger it.
    assert result.ready_observed >= 1
    assert result.eventness_rule_c_triggered == 1


def test_rule_a_shadow_structurally_unobservable_on_not_ready_story(db_session: AsyncSession) -> None:
    """Test P (Rule A half, documented as a finding, not a false-positive pass). A NOT_READY,
    RULE_A-shaped Story (unique_source_count<=1, below settings.recap_min_unique_sources=2) can
    never return a `candidate` under force_shadow=False, and therefore can never expose
    `eventness_shadow` at all - proves the module docstring's own disclosed limitation directly,
    rather than asserting something the architecture cannot actually deliver."""
    pytest.skip(
        "documented, not tested via a live scan: RULE_A's own condition (unique_source_count<=1) "
        "is structurally below recap_min_unique_sources (2) - see services/event_recap_scheduler.py's "
        "own module docstring 'DISCLOSED LIMITATION' section for the full proof."
    )


@pytest.mark.asyncio
async def test_eventness_shadow_flag_off_still_runs_real_readiness(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Q (independence half, §12)."""
    monkeypatch.setattr(settings, "recap_eventness_shadow_enabled", False)
    monkeypatch.setattr(settings, "event_recap_scheduler_enabled", True)
    monkeypatch.setattr(settings, "event_recap_generation_enabled", False)

    _story, _events = await _seed_ready_story(db_session)
    result = await run_event_recap_scan(session_factory=_single_session_factory(db_session))

    assert result.mode == "shadow"
    assert result.ready_observed >= 1  # real readiness still evaluated
    assert result.eventness_rule_a_triggered == 0
    assert result.eventness_rule_c_triggered == 0


# --- R: Rule D absent --------------------------------------------------------------------------------


def test_rule_d_absent_from_scheduler_source() -> None:
    """Test R. AST-based, not a substring search (this module's own docstring legitimately
    discusses "RULE_D" in prose)."""
    tree = ast.parse(_SCHEDULER_PATH.read_text(encoding="utf-8"))
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
    offending = {i for i in identifiers if "rule_d" in i.lower()}
    assert offending == set()


# --- S: config defaults all False --------------------------------------------------------------------


def test_config_defaults_all_false() -> None:
    """Test S."""
    assert settings.event_recap_scheduler_enabled is False
    assert settings.event_recap_generation_enabled is False
    assert settings.event_recap_scan_limit == 50


# --- T: no migration/schema changes --------------------------------------------------------------------


def test_no_new_alembic_migration_added() -> None:
    """Test T."""
    import subprocess

    result = subprocess.run(
        ["git", "diff", "--name-only", "ee802413f6d1f51f92dea5e575affcc00774d8c8"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    changed = [p for p in (*result.stdout.splitlines(), *untracked.stdout.splitlines()) if p.strip()]
    assert not any(p.startswith("alembic/") for p in changed), changed


# --- no eventness rejection reasons leak into duplicate/task-creation logic --------------------------


def test_scheduler_never_calls_workflow_service_create_task_directly() -> None:
    """§6/§8 - the scheduler must never reimplement task creation; only generate_recap_for_story()
    (imported lazily inside _run_generation) may ever call workflow_service.create_task(). AST-based
    (not a substring search) - this module's own docstring legitimately discusses
    `workflow_service.create_task()` in prose."""
    tree = ast.parse(_SCHEDULER_PATH.read_text(encoding="utf-8"))
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                call_names.add(func.attr)
            elif isinstance(func, ast.Name):
                call_names.add(func.id)
    assert "create_task" not in call_names
