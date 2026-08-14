"""Phase 18.10 M1/M2: story_memory_mode wiring in services.triage_orchestrator.run_triage_cycle().

Kept as a separate file from tests/test_triage_orchestrator_cycle.py (rather than extending it)
to avoid touching that file's own documented pre-existing cross-test-isolation sensitivity
(real_committed_event()-based, genuinely committed, not SAVEPOINT-rolled-back) - same fixture
reuse convention, isolated blast radius for this phase's own new tests.
"""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_memory import NEW_STORY, RELATED_STORY, MatchResult, extract_story_signature
from services.triage_orchestrator import TriageCycleReport, _apply_story_memory, run_triage_cycle
from tests.test_triage_orchestrator_claims import independent_session_factory, real_committed_event


@pytest.mark.asyncio
async def test_default_off_mode_never_touches_story_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default, byte-identical-to-pre-18.10 path - story_memory_mode == "off" must produce
    zero story-related counters and never query/mutate anything story-related. Does not need the
    (unapplied) story-memory migration at all, since _apply_story_memory() is never even called
    in this mode - confirms the off-path has zero footprint, not just zero behavior change."""
    monkeypatch.setattr(settings, "story_memory_mode", "off")

    engine, session_factory = independent_session_factory()
    try:
        async with real_committed_event(session_factory):
            report = await run_triage_cycle(session_factory=session_factory)

        assert report.story_new == 0
        assert report.story_updates == 0
        assert report.story_supporting_sources == 0
        assert report.story_semantic_duplicates == 0
        assert report.story_uncertain_matches == 0
    finally:
        await engine.dispose()


def test_received_events_property_sums_claimed_and_recovered() -> None:
    report = TriageCycleReport(events_claimed=3, events_recovered=2)
    assert report.received_events == 5


@pytest.mark.skip(
    reason=(
        "Phase 20 M3 finding (unrelated to Story Memory V2 itself): this test's own precondition "
        "- the 'stories'/'news_event_story_links' tables NOT existing yet - is now false against "
        "the real dev DB. Migration c2bc6affb100 was applied during the Phase 19 Activation Stage "
        "1 pass (docs/phase19_activation_review.md), confirmed via `alembic current` this session. "
        "With the tables present, story_memory_mode='shadow' now succeeds normally instead of "
        "hitting the 'relation does not exist' except-Exception branch this test exists to prove "
        "safe - so it no longer exercises its own intended scenario, and its real_committed_event() "
        "cleanup (tests/test_triage_orchestrator_claims.py) isn't written to also delete the real "
        "Story row that now genuinely gets created, causing a FK violation on teardown. Not a Phase "
        "20 regression - would fail identically on main. Needs a disposable, genuinely-unmigrated "
        "DB (mirroring the Phase 19 audit's own §3 technique) to test this scenario for real again; "
        "out of scope for this milestone."
    )
)
@pytest.mark.asyncio
async def test_shadow_mode_without_migration_degrades_gracefully_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact safety property this compatibility fix relies on: if story_memory_mode is
    enabled before the Phase 18.10 migration has been applied (the "stories"/
    "news_event_story_links" tables don't exist yet), run_triage_cycle() must NOT crash or
    corrupt other events - _run_phase_b()'s own pre-existing `except Exception` handler catches
    the "relation does not exist" error exactly like any other Phase B failure, leaves the event
    PROCESSING with no task (automatically recoverable once the migration lands), and the cycle
    itself completes normally."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")

    engine, session_factory = independent_session_factory()
    try:
        async with real_committed_event(session_factory) as event_id:
            report = await run_triage_cycle(session_factory=session_factory)  # must not raise

            assert report.other_failures >= 1
            assert report.tasks_created == 0

            from sqlalchemy import select

            from database.models.editorial_task import EditorialTask
            from database.models.news_event import EventStatus, NewsEvent

            async with session_factory() as session:
                event = await session.get(NewsEvent, event_id)
                assert event is not None
                assert event.status == EventStatus.PROCESSING  # recoverable, not lost

                tasks = (
                    await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
                ).scalars().all()
                assert tasks == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_apply_story_memory_wires_related_story_into_report(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 20 M8 finding: RELATED_STORY (services/story_memory.py, added M5) was never wired
    into TriageCycleReport's counters - a real, narrow observability gap, fixed as part of M8's
    own verification pass. RELATED_STORY must also NOT bump the pointed-at story's event_count
    (it is explicitly not a same-story match).

    Updated for Phase 20 M11.1 (Story Identity Invariant): RELATED_STORY now creates its own
    Story rather than pointing the link at the unrelated candidate - see
    tests/test_story_identity_invariant.py for the dedicated identity-behavior test suite this
    assertion now defers to; this test keeps its original scope (the counter wiring itself)."""
    root_source = NewsSource(name=f"phase20-m8-test-{uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(root_source)
    await db_session.flush()
    root_event = NewsEvent(
        source_id=root_source.id, title="Root story event", category=EventCategory.AI,
        hash=f"phase20-m8-test-{uuid4()}",
    )
    db_session.add(root_event)
    await db_session.flush()
    signature = extract_story_signature(root_event.title, EventCategory.AI)
    root_story = Story(
        id=uuid4(), title=root_event.title, category=EventCategory.AI, entities=signature.entities,
        keywords=signature.keywords, topic_bucket=signature.topic_bucket, first_event_id=root_event.id,
        event_count=1,
    )
    db_session.add(root_story)
    await db_session.flush()

    new_source = NewsSource(name=f"phase20-m8-test-{uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(new_source)
    await db_session.flush()
    new_event = NewsEvent(
        source_id=new_source.id, title="A different but entity-related event", category=EventCategory.AI,
        hash=f"phase20-m8-test-{uuid4()}",
    )
    db_session.add(new_event)
    await db_session.flush()

    async def _fake_match_story(_session: AsyncSession, *, title: str, category: EventCategory):  # noqa: ANN001, ARG001
        return signature, MatchResult(
            RELATED_STORY, root_story.id, 0.25, "test: entity-related, not same story", entity_overlap=0.25,
        )

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)

    report = TriageCycleReport()
    await _apply_story_memory(db_session, new_event, report)

    assert report.story_related == 1
    assert report.story_new == 0
    assert report.story_updates == 0
    assert report.story_supporting_sources == 0
    assert report.story_semantic_duplicates == 0
    assert report.story_uncertain_matches == 0

    await db_session.refresh(root_story)
    assert root_story.event_count == 1  # unchanged - RELATED_STORY is never a same-story match

    from sqlalchemy import select

    link = (
        await db_session.execute(
            select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == new_event.id)
        )
    ).scalar_one()
    # M11.1: RELATED_STORY now gets its own Story, never the unrelated candidate's.
    assert link.story_id != root_story.id
    own_story = await db_session.get(Story, link.story_id)
    assert own_story is not None
    assert own_story.first_event_id == new_event.id
    assert link.match_type == RELATED_STORY


@pytest.mark.asyncio
async def test_google_news_publisher_suffix_is_stripped_before_story_matching(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed Google News provenance: publisher suffix is metadata, not Story identity."""
    source = NewsSource(
        name=f"story-memory-google-provenance-{uuid4()}",
        type=SourceType.RSS,
        active=True,
    )
    db_session.add(source)
    await db_session.flush()

    raw_title = (
        "\u0418\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0439 "
        "\u0438\u043d\u0442\u0435\u043b\u043b\u0435\u043a\u0442 "
        "\u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0435\u0442 "
        "\u043d\u043e\u0432\u044b\u0435 "
        "\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 "
        "- Vietnam.vn"
    )
    expected_title = raw_title.rsplit(" - ", 1)[0]

    event = NewsEvent(
        source_id=source.id,
        title=raw_title,
        url="https://news.google.com/rss/articles/test-story-memory-provenance",
        category=EventCategory.AI,
        hash=f"story-memory-google-provenance-{uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()

    seen: dict[str, str] = {}

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        seen["title"] = title
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            NEW_STORY,
            None,
            1.0,
            "test: new story",
            entity_overlap=0.0,
        )

    monkeypatch.setattr(
        "services.triage_orchestrator.match_story",
        _fake_match_story,
    )

    await _apply_story_memory(db_session, event, TriageCycleReport())

    assert seen["title"] == expected_title
    assert "vietnam vn" not in extract_story_signature(
        seen["title"], EventCategory.AI
    ).entities


@pytest.mark.asyncio
async def test_non_google_title_suffix_is_preserved_before_story_matching(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Title shape alone is insufficient: semantic '- X' tails on direct URLs stay untouched."""
    source = NewsSource(
        name=f"story-memory-direct-provenance-{uuid4()}",
        type=SourceType.RSS,
        active=True,
    )
    db_session.add(source)
    await db_session.flush()

    raw_title = "Apple expands streaming service - Apple TV"

    event = NewsEvent(
        source_id=source.id,
        title=raw_title,
        url="https://example.com/apple-tv-story",
        category=EventCategory.AI,
        hash=f"story-memory-direct-provenance-{uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()

    seen: dict[str, str] = {}

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        seen["title"] = title
        signature = extract_story_signature(title, category)
        return signature, MatchResult(
            NEW_STORY,
            None,
            1.0,
            "test: new story",
            entity_overlap=0.0,
        )

    monkeypatch.setattr(
        "services.triage_orchestrator.match_story",
        _fake_match_story,
    )

    await _apply_story_memory(db_session, event, TriageCycleReport())

    assert seen["title"] == raw_title
