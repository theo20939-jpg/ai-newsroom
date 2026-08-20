"""NINJA PULSE RECAP Phase R2.7 - Story Anchor Lifecycle Forensic + reproduction + diagnostic tests.

Part 1 (root-cause reproduction, overnight checkpoint Part II item 14): proves, using ONLY current,
unmodified production code (`services/triage_orchestrator.py::_apply_story_memory()`,
`services/recap_event.py::load_story_events()`/`build_event_recap_candidate()`), that a Story's own
declared `first_event_id` can be - and, for a real, non-trivial class of Stories, ALWAYS is -
NOT among "confirmed" membership FROM THE MOMENT OF CREATION. This is not "staleness" (no later
mutation, merge, or reclassification is involved or required) - it is a creation-time semantic
mismatch between two independently-written, correct-in-isolation pieces of code:

  1. `services/triage_orchestrator.py::_apply_story_memory()` (Phase 20 M11.1, Story Identity
     Invariant): deliberately creates a brand-new Story, with `first_event_id=event.id`, for BOTH
     the `RELATED_STORY` outcome and a weak-entity-overlap `UNCERTAIN_MATCH` outcome - proven by
     `tests/test_story_identity_invariant.py::test_related_story_root_event_gets_its_own_story()`/
     `test_uncertain_match_with_weak_entity_overlap_gets_its_own_story()`, both EXISTING, PASSING
     tests that explicitly assert `own_story.first_event_id == new_event.id` alongside
     `link.match_type == RELATED_STORY` / `UNCERTAIN_MATCH` for that SAME event's own link row.
  2. `services/recap_event.py::_CONFIRMED_MEMBERSHIP_MATCH_TYPES` (Phase R1.x, written
     independently, for RECAP's own "is this event a confirmed continuation of the Story's own
     history" question) EXCLUDES both `RELATED_STORY` and `UNCERTAIN_MATCH` by its own explicit,
     documented design ("present in the link table 'for observability' only, never a confirmed
     continuation").

Neither piece of code is wrong on its own terms - `first_event_id` correctly records ORIGIN
identity (the event that caused Story creation), and `_CONFIRMED_MEMBERSHIP_MATCH_TYPES` correctly
answers a DIFFERENT question (which events represent confirmed, high-confidence continuations).
The mismatch is that `services/event_recap.py::build_event_recap_candidate()` (and, transitively,
`services/recap_event.py::evaluate_recap_story_integrity()`'s own anchor-must-be-a-confirmed-member
precondition) implicitly assumes these two concepts coincide - true for `NEW_STORY`/`STORY_UPDATE`/
`SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE`-created Stories, never true for `RELATED_STORY`- or
weak-`UNCERTAIN_MATCH`-created ones.

Part 2: the diagnostic-only, READ-ONLY `scripts/_recap_r2_7_anchor_lifecycle_forensic.py`'s own
pure classification/simulation functions - hypothetical-anchor Story Integrity simulation, the
"obvious AI/tech" forensic flag, and the pure repair-candidate simulation - loaded the same way
every prior `scripts/_recap_r2_*` diagnostic test file already does (that directory is not a
package), via `importlib.util.spec_from_file_location`.

NO production DB, NO LLM, NO Gateway, NO provider, NO network, NO writes anywhere in this file -
DB-touching cases use only the shared `db_session` fixture (tests/conftest.py, SAVEPOINT-rolled-
back local test DB), mirroring `tests/test_story_identity_invariant.py`'s own established pattern.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.event_recap import build_event_recap_candidate
from services.recap_event import (
    _CONFIRMED_MEMBERSHIP_MATCH_TYPES,
    load_story_events,
)
from services.story_memory import (
    RELATED_STORY,
    UNCERTAIN_MATCH,
    MatchResult,
    extract_story_signature,
)
from services.triage_orchestrator import TriageCycleReport, _apply_story_memory


def _load_r27_module():
    import sys as _sys

    spec = importlib.util.spec_from_file_location(
        "_recap_r2_7_anchor_lifecycle_forensic_test_import",
        "scripts/_recap_r2_7_anchor_lifecycle_forensic.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The module's own `@dataclass(frozen=True)` class (RepairCandidate), combined with `from
    # __future__ import annotations`, needs to resolve string annotations via `sys.modules[cls.
    # __module__]` at class-definition time - registering the module before exec_module() avoids
    # `AttributeError: 'NoneType' object has no attribute '__dict__'`.
    _sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


r27 = _load_r27_module()

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


async def _seed_existing_story(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> Story:
    source = NewsSource(name=f"r27-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"r27-test-{uuid4()}")
    session.add(event)
    await session.flush()
    signature = extract_story_signature(title, category)
    story = Story(
        id=uuid4(), title=title, category=category, entities=signature.entities,
        keywords=signature.keywords, topic_bucket=signature.topic_bucket, first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    return story


async def _new_event(session: AsyncSession, title: str, *, category: EventCategory = EventCategory.AI) -> NewsEvent:
    source = NewsSource(name=f"r27-test-{uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title=title, category=category, hash=f"r27-test-{uuid4()}")
    session.add(event)
    await session.flush()
    return event


# ---------------------------------------------------------------------------
# Part 1 - root-cause reproduction (overnight checkpoint Part II item 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_related_story_creation_produces_anchor_missing_from_confirmed_members_at_birth(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BEFORE state: a real NewsEvent, freshly triaged, scores RELATED_STORY against an unrelated
    older Story. AFTER _apply_story_memory() runs (ONE real, current, unmodified production
    operation - not a later mutation): a brand-new Story exists with first_event_id == that event,
    but the SAME event's own NewsEventStoryLink.match_type == RELATED_STORY, which load_story_events
    ()/_CONFIRMED_MEMBERSHIP_MATCH_TYPES excludes. build_event_recap_candidate() then fails closed
    on this Story exactly as R2.6c's real production scan observed (17/60 anchor_missing_fail)."""
    unrelated = await _seed_existing_story(db_session, "Unrelated older story about something else entirely")
    root_event = await _new_event(db_session, "Cloudflare launches Kitesurf, a browser built for AI agents")

    # BEFORE: no Story rooted at root_event exists yet.
    before = (await db_session.execute(select(Story).where(Story.first_event_id == root_event.id))).scalars().all()
    assert before == []

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(RELATED_STORY, unrelated.id, 0.25, "test: related but not same story", entity_overlap=0.25)

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)
    report = TriageCycleReport()
    await _apply_story_memory(db_session, root_event, report)  # the ONE real lifecycle operation

    link = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    new_story = await db_session.get(Story, link.story_id)
    assert new_story is not None

    # AFTER: the new Story's own declared anchor is its own root_event ...
    assert new_story.first_event_id == root_event.id
    # ... but that SAME event's own link is NOT a confirmed membership match_type ...
    assert link.match_type == RELATED_STORY
    assert link.match_type not in _CONFIRMED_MEMBERSHIP_MATCH_TYPES
    # ... so it is exactly the anchor-missing state, present the moment the Story was created -
    # never a later "staleness".
    confirmed = await load_story_events(db_session, new_story.id)
    assert root_event.id not in {e.id for e in confirmed}
    assert confirmed == []  # this Story has literally zero confirmed members

    result = await build_event_recap_candidate(db_session, new_story, force_shadow=True, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None
    # This Story has ZERO confirmed members at all (not merely a mismatched anchor among others),
    # so build_event_recap_candidate()'s own fail-closed branch takes its "no confirmed member
    # events loaded" wording rather than the "first_event_id ... not among confirmed" wording -
    # both are the SAME anchor-is-None fail-closed code path (services/event_recap.py's own
    # `if events else` branch), just worded differently depending on whether any OTHER confirmed
    # member exists.
    assert any("confirmed" in r for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_weak_uncertain_match_creation_produces_the_identical_anchor_missing_state(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second, independent trigger path (module docstring) - a weak-entity-overlap
    UNCERTAIN_MATCH also creates its own Story with the same creation-time mismatch."""
    unrelated = await _seed_existing_story(db_session, "Some unrelated older story, coincidentally similar wording")
    root_event = await _new_event(
        db_session, "Российские школьники в третий раз стали чемпионами на Международной олимпиаде по ИИ",
    )

    async def _fake_match_story(_session, *, title, category):  # noqa: ANN001
        signature = extract_story_signature(title, category)
        return signature, MatchResult(UNCERTAIN_MATCH, unrelated.id, 0.46, "test: coincidental uncertain match", entity_overlap=0.1)

    monkeypatch.setattr("services.triage_orchestrator.match_story", _fake_match_story)
    report = TriageCycleReport()
    await _apply_story_memory(db_session, root_event, report)

    link = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == root_event.id))
    ).scalar_one()
    new_story = await db_session.get(Story, link.story_id)
    assert new_story is not None
    assert new_story.first_event_id == root_event.id
    assert link.match_type == UNCERTAIN_MATCH

    result = await build_event_recap_candidate(db_session, new_story, force_shadow=True, now=_NOW)
    assert result.rejected is True
    assert any("confirmed" in r for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_ordinary_new_story_creation_never_produces_anchor_missing_state(db_session: AsyncSession) -> None:
    """Negative control: an ordinary NEW_STORY creation (no monkeypatch - the real match_story()
    scoring a genuinely fresh title) must NOT reproduce the bug - proving this is specific to the
    RELATED_STORY/weak-UNCERTAIN_MATCH paths, not a general Story-creation defect."""
    from services.triage_orchestrator import _apply_story_memory as apply_story_memory

    event = await _new_event(db_session, "Completely novel unrelated headline about a brand new topic nobody has covered")
    report = TriageCycleReport()
    await apply_story_memory(db_session, event, report)

    link = (
        await db_session.execute(select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == event.id))
    ).scalar_one()
    assert link.match_type in _CONFIRMED_MEMBERSHIP_MATCH_TYPES

    story = await db_session.get(Story, link.story_id)
    assert story is not None
    confirmed = await load_story_events(db_session, story.id)
    assert story.first_event_id in {e.id for e in confirmed}


# ---------------------------------------------------------------------------
# Part 2 - R2.7 diagnostic script's own pure functions
# ---------------------------------------------------------------------------


def _event(title: str, minutes_ago: float, *, category: EventCategory = EventCategory.TECH) -> NewsEvent:
    return NewsEvent(
        id=uuid4(), source_id=uuid4(), title=title, category=category,
        url=f"https://example.com/{uuid4()}", published_at=_NOW - timedelta(minutes=minutes_ago),
        collected_at=_NOW - timedelta(minutes=minutes_ago), hash=f"h-{uuid4()}",
    )


def test_hypothetical_anchor_simulation_pass_when_members_are_coherent():
    members = [
        _event("Alibaba releases Qwen3.8-27B open-weight AI model", 30),
        _event("Alibaba confirms Qwen3.8-27B model release with benchmark results", 0),
    ]
    hypothetical_anchor = members[0]
    result = r27.simulate_hypothetical_anchor_integrity(hypothetical_anchor, members)
    assert result.eligible is True


def test_hypothetical_anchor_simulation_fail_when_members_are_incoherent():
    members = [
        _event("What are you doing this weekend?", 30),
        _event("What happens when a hybrid battery dies in a used car you just bought?", 20),
        _event("What the world's oldest telecommunications company is doing to survive", 10),
        _event("What software do you use daily to get work done?", 0),
    ]
    result = r27.simulate_hypothetical_anchor_integrity(members[0], members)
    assert result.eligible is False


def test_hypothetical_anchor_simulation_never_mutates_inputs():
    members = [_event("Alibaba releases Qwen3.8-27B open-weight AI model", 30)]
    before_id = members[0].id
    r27.simulate_hypothetical_anchor_integrity(members[0], members)
    assert members[0].id == before_id  # same object, untouched


def test_earliest_confirmed_member_selection():
    members = [
        _event("Second report", 5),
        _event("First report, earliest", 30),
        _event("Third report", 0),
    ]
    earliest = r27.earliest_confirmed_member(members)
    assert earliest.title == "First report, earliest"


def test_most_coherent_confirmed_member_selection():
    members = [
        _event("Alibaba releases Qwen3.8-27B open-weight AI model", 30),
        _event("Alibaba confirms Qwen3.8-27B model release with benchmark results", 20),
        _event("Unrelated wire copy about a football match", 0),
    ]
    most_coherent = r27.most_coherent_confirmed_member(members)
    assert most_coherent is not None
    assert most_coherent.id != members[2].id  # the outlier is never the most coherent choice


def test_obvious_ai_tech_signal_detects_known_examples():
    assert r27.obvious_ai_tech_signal("OpenAI and Hugging Face patch security vulnerability")
    assert r27.obvious_ai_tech_signal("Yandex AI Search now shows advertising in results")
    assert r27.obvious_ai_tech_signal("Alibaba Qwen model update improves reasoning")
    assert r27.obvious_ai_tech_signal("Grok AI video contest opens for entries")
    assert r27.obvious_ai_tech_signal("Илон Маск представил обучения ИИ на новых данных")


def test_obvious_ai_tech_signal_does_not_flag_unrelated_titles():
    assert not r27.obvious_ai_tech_signal("Local council approves new parking regulations downtown")
    assert not r27.obvious_ai_tech_signal("Stock market closes higher after earnings season")


def test_repair_simulation_never_mutates_story_or_links():
    """Part V - the pure repair-candidate simulation must never touch the passed-in Story/event
    objects (no ORM flush/commit inside it - a pure function over already-loaded data only)."""
    story = Story(
        id=uuid4(), title="placeholder", category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="product", first_event_id=uuid4(), event_count=2,
    )
    members = [
        _event("Alibaba releases Qwen3.8-27B open-weight AI model", 30),
        _event("Alibaba confirms Qwen3.8-27B model release with benchmark results", 0),
    ]
    original_first_event_id = story.first_event_id
    candidate = r27.simulate_repair_candidate(story, members)
    assert story.first_event_id == original_first_event_id  # never mutated
    assert candidate.repair_candidate_anchor_id == members[0].id
    assert candidate.hypothetical_integrity.eligible is True
