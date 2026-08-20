"""NINJA PULSE RECAP Phase R2 - EVENT_RECAP shadow foundation test matrix.

Pure-function cases build plain NewsEvent/AnnouncementCluster objects directly in memory
(deterministic, offline, no DB, no network, no LLM). DB-touching cases use the shared `db_session`
fixture (tests/conftest.py), mirroring tests/test_recap_event.py's own established construction
pattern exactly. LLM-touching cases use `tests/fakes/fake_gateway.py::FakeLLMGateway` and
`tests/fakes/fake_prompt_repository.py::FakePromptRepository` - zero paid model calls anywhere in
this file (spec's own explicit "Use fake LLM Gateway in tests. Zero paid model calls.")."""
from __future__ import annotations

import ast
import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.protocol import CapabilityUsage, GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import RuntimeContext
from database.models.editorial_task import TaskPriority
from services.event_recap import (
    EventRecapCandidate,
    EventRecapSynthesisError,
    FACT_MULTI_SOURCE_CONFIRMED,
    FACT_SINGLE_SOURCE_ONLY,
    _build_announcement_summaries,
    _build_timeline,
    _build_verified_facts,
    _is_generic_entity_phrase,
    _publisher_suffix_numbers,
    _synthesis_verified_facts,
    _verify_synthesis_facts,
    build_event_recap_candidate,
    render_event_recap_bundle_text,
    synthesize_event_recap,
)
from services.recap_event import cluster_announcements
from services.story_memory import NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE, UNCERTAIN_MATCH
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

_PROMPT = RenderedPrompt(
    name="event_recap",
    version="2",
    system="You are a test analyst.",
    rules=["Never invent facts."],
    output_schema={
        "type": "object",
        "properties": {
            "recap_title": {"type": "string"},
            "recap_summary": {"type": "string"},
            "key_takeaways": {"type": "array", "items": {"type": "string"}},
            "uncertainty_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
        "additionalProperties": False,
    },
)


def _event(*, title: str, url: str, minutes_ago: float, source_id: uuid.UUID | None = None) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(), source_id=source_id or uuid.uuid4(), title=title, category=EventCategory.TECH,
        url=url, published_at=_NOW - timedelta(minutes=minutes_ago), collected_at=_NOW - timedelta(minutes=minutes_ago),
        hash=f"h-{uuid.uuid4()}",
    )


async def _make_story(
    db_session, titles: list[str], *, spacing_minutes: float = 10.0, match_types: list[str] | None = None,
    anchor_index: int = 0,
) -> tuple[Story, list[NewsEvent]]:
    """Mirrors tests/test_recap_event.py's own DB fixture construction pattern exactly."""
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name="Test", type=SourceType.RSS, url=f"https://example.com/feed-{uuid.uuid4()}.xml", active=True)
    db_session.add(source)
    await db_session.flush()

    n = len(titles)
    events = [
        _event(title=t, url=f"https://example.com/{i}-{uuid.uuid4()}", minutes_ago=(n - i - 1) * spacing_minutes, source_id=source.id)
        for i, t in enumerate(titles)
    ]
    for event in events:
        db_session.add(event)
    await db_session.flush()

    story = Story(
        title=titles[anchor_index], category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="product", first_event_id=events[anchor_index].id, event_count=n,
    )
    db_session.add(story)
    await db_session.flush()

    types = match_types or ([NEW_STORY] + [STORY_UPDATE] * (n - 1))
    for event, match_type in zip(events, types):
        db_session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9))
    await db_session.flush()

    return story, events


# ---------------------------------------------------------------------------
# Rejection / fail-closed behavior (DB-backed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integrity_fail_rejects_candidate(db_session):
    """A generic-opener false grouping (the real R1.2 "What are you doing this weekend?" pattern)
    must fail Story Integrity and be rejected - never reach announcement/readiness/candidate
    construction at all."""
    story, _events = await _make_story(db_session, [
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies in a used car you just bought?",
        "What the world's oldest telecommunications company is doing to survive",
        "What software do you use daily to get work done?",
    ])
    result = await build_event_recap_candidate(db_session, story, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None
    assert any("coherent_ratio" in r or "integrity" in r.lower() for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_declared_first_event_id_outside_confirmed_membership_is_origin_projected(db_session):
    """R2.9A reconciliation (checkpoint commit AFTER 7ebfd82 - services/recap_origin_projection.py):
    this fixture's own shape - `story.first_event_id` is UNCERTAIN_MATCH's own link, pointing to
    THIS Story, with no conflicting other-Story relationship - is EXACTLY R2.9's own fail-closed
    origin-projection ELIGIBILITY contract (see services/recap_origin_projection.py's own
    `classify_origin_projection()`). This test's name and contract changed from "...fails_closed"
    because "the candidate is unconditionally rejected" is no longer this fixture's outcome for the
    REASON it originally was (anchor-missing) - see test_origin_projection_ineligible_missing_own_
    link_still_fails_closed() below for a genuinely unsafe shape that still rejects for that reason.

    STORAGE LAYER (unchanged by R2.9 - still the real, historical R1.5A.2-era finding this test
    originally proved): the origin event's own link is UNCERTAIN_MATCH, excluded from confirmed
    membership by services.recap_event._CONFIRMED_MEMBERSHIP_MATCH_TYPES, so `story.first_event_id`
    is NOT among load_story_events()'s own result - never silently rewritten, never mutated.

    Real finding worth preserving explicitly (never guessed): these three generic, near-duplicate
    filler titles ("Original story-originating article", "Follow-up coverage of the same story",
    "More follow-up coverage of the same story") have NO extractable proper-noun entities (Phase 20
    Checkpoint 6's own sentence-initial-capitalization exclusion), so evaluate_recap_story_integrity
    () - frozen, unmodified - falls back to plain title-overlap coherence and correctly finds the
    origin insufficiently coherent with the other two (anchor_coherent_ratio=0.0). This demonstrates
    origin projection is NEVER an integrity bypass: the candidate is still rejected under
    force_shadow=True, but now for a real INTEGRITY reason, never for anchor-missing and never by
    silently substituting a different anchor."""
    story, events = await _make_story(
        db_session,
        ["Original story-originating article", "Follow-up coverage of the same story", "More follow-up coverage of the same story"],
        match_types=[UNCERTAIN_MATCH, STORY_UPDATE, SUPPORTING_SOURCE],
    )
    origin_event = events[0]

    from services.recap_event import load_story_events
    from services.recap_origin_projection import ORIGIN_PROJECTION_ELIGIBLE, resolve_recap_origin_projection

    confirmed = await load_story_events(db_session, story.id)
    assert origin_event.id not in {e.id for e in confirmed}  # storage-layer finding preserved

    # Eligibility is a property of the LINK shape alone - independent of whether Integrity will
    # ultimately pass or fail for the resulting effective member set.
    declared_event, decision = await resolve_recap_origin_projection(db_session, story)
    assert declared_event is not None and declared_event.id == origin_event.id
    assert decision.reason_code == ORIGIN_PROJECTION_ELIGIBLE
    assert decision.eligible is True

    # Without force_shadow (mirrors the original test's own call): still rejected, but no longer on
    # anchor-missing grounds.
    result = await build_event_recap_candidate(db_session, story, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None
    assert not any("first_event_id" in r and "not among" in r for r in result.rejection_reasons), (
        f"must not still be rejecting on anchor-missing grounds after R2.9: {result.rejection_reasons}"
    )

    # With force_shadow=True (bypasses only the READINESS gate, never Integrity): origin projection
    # is applied (proven via the real, unmodified evaluate_recap_story_integrity() call it feeds),
    # yet the candidate is still correctly rejected - on Integrity grounds this time, proving
    # projection is not a bypass.
    forced = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert forced.rejected is True
    assert forced.candidate is None
    assert any("anchor_coherent_ratio" in r for r in forced.rejection_reasons), (
        f"expected a real Integrity rejection reason, got: {forced.rejection_reasons}"
    )


@pytest.mark.asyncio
async def test_origin_projection_ineligible_missing_own_link_still_fails_closed(db_session):
    """R2.9 must not reduce fail-closed coverage for genuinely unsafe missing-anchor states -
    mirrors services/recap_event.py's own R1.5A.2 fail-closed fix. Here the declared origin's own
    NewsEventStoryLink row does not exist at all (constructed directly, bypassing `_make_story()`'s
    own normal link-writing loop) - `services/recap_origin_projection.py::classify_origin_
    projection()` returns ORIGIN_LINK_MISSING (ineligible), so build_event_recap_candidate() must
    still reject exactly as before R2.9, never silently substituting any anchor."""
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name="Test", type=SourceType.RSS, url=f"https://example.com/feed-{uuid.uuid4()}.xml", active=True)
    db_session.add(source)
    await db_session.flush()

    origin_event = _event(title="An event with no link row at all", url="https://example.com/no-link", minutes_ago=20, source_id=source.id)
    member_event = _event(title="A confirmed member of some other story", url="https://example.com/member", minutes_ago=10, source_id=source.id)
    db_session.add(origin_event)
    db_session.add(member_event)
    await db_session.flush()

    story = Story(
        title=origin_event.title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="product", first_event_id=origin_event.id, event_count=2,
    )
    db_session.add(story)
    await db_session.flush()
    # Only the member gets a link - origin_event's own NewsEventStoryLink is deliberately absent.
    db_session.add(NewsEventStoryLink(news_event_id=member_event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.9))
    await db_session.flush()

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None
    assert any("first_event_id" in r and "confirmed" in r for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_readiness_not_ready_without_force_is_rejected(db_session):
    """R2 never runs Recap Research (research_complete is always False - module docstring), so
    readiness.ready is always False for a real Story; without force_shadow this must reject."""
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "$314 AI dividend payment explained for Taiwan residents",
    ])
    result = await build_event_recap_candidate(db_session, story, force_shadow=False, now=_NOW)
    assert result.rejected is True
    assert result.candidate is None


@pytest.mark.asyncio
async def test_readiness_override_explicitly_recorded(db_session):
    """The exact same not-READY Story, with force_shadow=True, must build a candidate AND record
    readiness_overridden=True unconditionally - never a silent bypass."""
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "$314 AI dividend payment explained for Taiwan residents",
    ])
    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is False
    assert result.candidate is not None
    assert result.candidate.readiness_overridden is True
    assert result.candidate.readiness_state != ""
    assert result.candidate.publishable is False


@pytest.mark.asyncio
async def test_source_evidence_references_preserved(db_session):
    """Announcement/candidate-level source_refs must trace back to the real confirmed events'
    own URLs - never fabricated, never dropped."""
    story, events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    candidate = result.candidate
    assert candidate is not None
    real_urls = {e.url for e in events}
    assert set(candidate.source_refs) <= real_urls
    assert candidate.source_refs  # at least one real reference preserved


# ---------------------------------------------------------------------------
# Pure-function cases: announcement conversion / timeline / verified facts
# ---------------------------------------------------------------------------


def test_announcement_clusters_converted_correctly():
    events = [
        _event(title="Taiwan approves $314 AI dividend for every citizen", url="https://a.example/1", minutes_ago=20),
        _event(title="Government confirms $314 per person AI dividend program in Taiwan", url="https://b.example/2", minutes_ago=10),
        _event(title="$314 AI dividend payment explained for Taiwan residents", url="https://c.example/3", minutes_ago=0),
    ]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})

    assert len(summaries) == len(clusters)
    total_members = sum(len(s.member_event_ids) for s in summaries)
    assert total_members == len(events)
    for summary in summaries:
        assert set(summary.member_event_ids) <= {e.id for e in events}
        assert summary.evidence_reference_count >= 1


def test_duplicate_news_events_do_not_produce_duplicate_timeline_entries():
    """Three near-identical/syndicated reports of ONE announcement must collapse into exactly one
    AnnouncementSummary and therefore exactly one timeline entry - never one per raw NewsEvent."""
    title = "Schools embrace AI and VR tools to modernize classrooms"
    events = [_event(title=title, url=f"https://example.com/{i}", minutes_ago=(2 - i) * 2) for i in range(3)]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    assert len(clusters) == 1  # sanity: these really do collapse under R1's own frozen logic

    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    timeline = _build_timeline(summaries)
    assert len(timeline) == 1
    assert set(timeline[0].supporting_event_ids) == {e.id for e in events}


def test_chronological_timeline_order():
    events = [
        _event(title="Taiwan approves $314 AI dividend for every citizen", url="https://a.example/1", minutes_ago=0),
        _event(title="Apple unveils iPhone X", url="https://b.example/2", minutes_ago=500),
        _event(title="Apple announces iPhone X pricing", url="https://c.example/3", minutes_ago=400),
    ]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    timeline = _build_timeline(summaries)

    timestamps = [entry.timestamp for entry in timeline]
    assert timestamps == sorted(timestamps)


def test_verified_facts_multi_vs_single_source_status():
    events = [
        _event(title="Taiwan approves $314 AI dividend for every citizen", url="https://a.example/1", minutes_ago=20),
        _event(title="Government confirms $314 per person AI dividend program in Taiwan", url="https://b.example/2", minutes_ago=10),
        _event(title="Apple unveils Watch Ultra 3", url="https://c.example/3", minutes_ago=0),
    ]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    facts = _build_verified_facts(summaries)

    numeric_facts = {f.value: f for f in facts if f.fact_type == "numeric"}
    assert "314" in numeric_facts
    assert numeric_facts["314"].status == FACT_MULTI_SOURCE_CONFIRMED
    assert numeric_facts["314"].source_count >= 2
    assert all(f.conflicting_evidence is False for f in facts)  # R2's disclosed, deliberate limitation


def test_verified_fact_single_source_status():
    events = [_event(title="Apple unveils Watch Ultra 3", url="https://a.example/1", minutes_ago=0)]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    facts = _build_verified_facts(summaries)
    assert all(f.status == FACT_SINGLE_SOURCE_ONLY for f in facts)


# ---------------------------------------------------------------------------
# Phase R2.2 - production-shaped evidence-hygiene fixtures (real Sverdlovsk/Taiwan production
# titles, verbatim, from the R2.1/R2.2 checkpoint messages). Publisher-suffix entities must never
# leak into AnnouncementSummary.content_entities or VerifiedFactCandidate - reusing R1's own
# `_sanitized_announcement_signature()`/`_publisher_suffix_entities()`, never a duplicated
# algorithm.
# ---------------------------------------------------------------------------


def _summaries_and_facts(titles: list[str], *, gap_minutes: float = 30.0):
    events = [_event(title=t, url=f"https://example.com/{i}", minutes_ago=(len(titles) - i - 1) * gap_minutes) for i, t in enumerate(titles)]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    facts = _build_verified_facts(summaries)
    return events, clusters, summaries, facts


def test_sverdlovsk_production_titles_publisher_entities_do_not_leak():
    """Real production titles, verbatim, from the R2.2 checkpoint message. Before this fix,
    verified_facts included the spurious publisher-suffix entities "информационн"/"областн" -
    "информационн" (from the cleanly-suffixed title A, " - Информационный") must be gone after
    R2.2; "свердловск" (genuine repeated content entity) must remain. R1's own frozen
    announcement_count (3, NOT tuned here) and timeline entry count are asserted unchanged."""
    titles = [
        "Свердловские дерматологи тестируют технологии искусственного интеллекта для диагностики рака кожи - Информационный",
        "В Свердловской области тестируют искусственный интеллект для диагностики рака кожи - pervomedia.ru",
        "Свердловские дерматологи смогут выявлять рак кожи при помощи искусственного интеллекта - Областная газета |",
    ]
    events, clusters, summaries, facts = _summaries_and_facts(titles)

    assert len(clusters) == 3  # R1's own frozen result - never tuned here
    timeline = _build_timeline(summaries)
    assert len(timeline) == 3

    all_entities = {entity for s in summaries for entity in s.content_entities}
    all_fact_values = {f.value for f in facts if f.fact_type == "entity"}
    assert "информационн" not in all_entities
    assert "информационн" not in all_fact_values
    assert "свердловск" in all_entities
    assert "свердловск" in all_fact_values

    # Known, disclosed R1 boundary case (never patched here - R1 is frozen): title C's suffix
    # ends in a bare "|" with nothing following it, which `_TRAILING_SUFFIX_RE`'s own end-anchored
    # capture cannot match (confirmed by direct execution: `_publisher_suffix_entities()` returns
    # an EMPTY set for this exact title) - so R1's own function does not classify "областн" as
    # publisher-only for this specific title, and it is NOT stripped. This is real, existing,
    # frozen R1 behavior being correctly and faithfully reused, not an R2 contamination bug.
    from services.recap_event import _publisher_suffix_entities

    assert _publisher_suffix_entities(titles[2]) == set()

    source_refs = list(dict.fromkeys(ref for s in summaries for ref in s.source_refs))
    assert len(source_refs) == 3
    assert set(source_refs) <= {e.url for e in events}


def test_sverdlovsk_evidence_reference_count_distinguishes_from_readiness_source_count():
    """Item 6/7: 3 distinct evidence URLs (no canonical URLs persisted, so falls back to raw URL
    identity per `_evidence_reference_identity()`'s own documented priority order) must be visible
    as evidence_reference_count=3, independent of whatever R1's own count_unique_sources() would
    compute for readiness (frozen, untouched, never recomputed here)."""
    from services.event_recap import _evidence_reference_identity

    titles = [
        "Свердловские дерматологи тестируют технологии искусственного интеллекта для диагностики рака кожи - Информационный",
        "В Свердловской области тестируют искусственный интеллект для диагностики рака кожи - pervomedia.ru",
        "Свердловские дерматологи смогут выявлять рак кожи при помощи искусственного интеллекта - Областная газета |",
    ]
    events, clusters, summaries, facts = _summaries_and_facts(titles)
    identities = {_evidence_reference_identity(e, None) for e in events}
    assert len(identities) == 3  # distinct raw URLs, since no canonical URL is available offline


def test_taiwan_production_titles_publisher_entities_never_become_verified_facts():
    """Real production titles, verbatim (R1.5B.1/R2.2 checkpoint messages). Content entities
    (тайвань/ии) must be the ONLY entities reaching verified_facts; none of the four real
    publisher suffixes may leak in. announcement_count must remain R1's own frozen 2 (never
    tuned here)."""
    titles = [
        "Тайвань выплатит каждому гражданину страны около $314 «дивидендов от ИИ» - Ведомости",
        "Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
        "Тайвань выплатит каждому гражданину «дивиденды от ИИ» в $314 - Эксперт",
        "Тайвань выплатит всем своим гражданам «дивиденды» от мирового бума ИИ - CNews.ru",
    ]
    events, clusters, summaries, facts = _summaries_and_facts(titles, gap_minutes=75.0)
    assert len(clusters) == 2  # R1's own frozen result - never tuned here

    entity_fact_values = {f.value for f in facts if f.fact_type == "entity"}
    assert entity_fact_values <= {"тайвань", "ии"}
    for publisher_entity in ("ведомост", "хабр", "эксперт", "cnews ru"):
        assert publisher_entity not in entity_fact_values
        assert publisher_entity not in {e for s in summaries for e in s.content_entities}


def test_entity_present_in_both_core_and_suffix_is_not_incorrectly_removed():
    """Safety fixture (item 13's own explicit requirement): a word appearing BOTH in a title's core
    content AND (coincidentally) in its trailing publisher suffix must survive sanitization -
    `_publisher_suffix_entities()`'s own "suffix minus core" rule, reused unchanged."""
    titles = ["Tesla unveils new Model Z with major upgrades - Tesla News Network"]
    _events, _clusters, summaries, _facts = _summaries_and_facts(titles, gap_minutes=0.0)
    assert len(summaries) == 1
    assert "tesla" in summaries[0].content_entities  # retained - also present in core content
    assert "tesla news network" not in summaries[0].content_entities  # suffix-only, correctly removed


def test_evidence_contamination_invariant_never_fires_on_real_fixtures():
    """Defense-in-depth: `_assert_no_publisher_contamination()` must never raise on any of the
    real production-shaped fixtures above - confirms the invariant and the actual sanitization
    are consistent with each other, not merely that no exception happened to propagate."""
    for titles in (
        [
            "Свердловские дерматологи тестируют технологии искусственного интеллекта для диагностики рака кожи - Информационный",
            "В Свердловской области тестируют искусственный интеллект для диагностики рака кожи - pervomedia.ru",
            "Свердловские дерматологи смогут выявлять рак кожи при помощи искусственного интеллекта - Областная газета |",
        ],
        [
            "Тайвань выплатит каждому гражданину страны около $314 «дивидендов от ИИ» - Ведомости",
            "Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
        ],
        ["Tesla unveils new Model Z with major upgrades - Tesla News Network"],
    ):
        _summaries_and_facts(titles)  # raises EventRecapEvidenceContaminationError on violation


# ---------------------------------------------------------------------------
# Phase R2.4 - synthesis evidence projection + fact-verification adapter fix (real production
# finding: a real Sverdlovsk synthesis call leaked the bare SINGLE_SOURCE_ONLY entity token
# "областн" into the model's own uncertainty_notes, and a separate real false BLOCK on the
# LLM-generated title "Тестирование ИИ для диагностики рака кожи в Свердловской области" against
# real Sverdlovsk evidence). services/fact_safety.py itself is NOT modified anywhere in this
# section - every fix here is entirely on the RECAP side (evidence projection + which title text
# is passed to the existing, unmodified evaluate_fact_safety()).
# ---------------------------------------------------------------------------

_SVERDLOVSK_TITLES = [
    "Свердловские дерматологи тестируют технологии искусственного интеллекта для диагностики рака кожи - Информационный",
    "В Свердловской области тестируют искусственный интеллект для диагностики рака кожи - pervomedia.ru",
    "Свердловские дерматологи смогут выявлять рак кожи при помощи искусственного интеллекта - Областная газета |",
]
_SVERDLOVSK_GENERATED_TITLE = "Тестирование ИИ для диагностики рака кожи в Свердловской области"
_SVERDLOVSK_GENERATED_SUMMARY = (
    "Свердловские дерматологи начали тестирование технологий искусственного интеллекта для "
    "диагностики рака кожи."
)


def _candidate_from_titles(titles: list[str], story_title: str, *, gap_minutes: float = 30.0) -> EventRecapCandidate:
    events, clusters, summaries, facts = _summaries_and_facts(titles, gap_minutes=gap_minutes)
    timeline = _build_timeline(summaries)
    source_refs = list(dict.fromkeys(ref for s in summaries for ref in s.source_refs))
    return EventRecapCandidate(
        story_id=uuid.uuid4(), anchor_event_id=events[0].id, story_title=story_title, generated_at=_NOW,
        readiness_state="COOLING", readiness_overridden=True, story_integrity_eligible=True,
        story_integrity_reasons=[], announcement_count=len(clusters), readiness_source_count=1,
        evidence_reference_count=len(source_refs), announcements=summaries, timeline=timeline,
        verified_facts=facts, source_refs=source_refs, media_candidates=[],
    )


def test_synthesis_evidence_excludes_bare_single_source_entity_token():
    """Items 11.A/11.B/11.C: the real Sverdlovsk production fixture. "областн" (a real,
    disclosed, frozen-R1 suffix-parser boundary artifact - never patched here) must NOT appear in
    the synthesis-facing bundle text, but must still be visible in the full diagnostic candidate;
    real announcement headlines must still appear in the synthesis evidence."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")

    # B. diagnostic candidate retains it
    assert any(f.fact_type == "entity" and f.value == "областн" for f in candidate.verified_facts)

    # A. synthesis-facing bundle text does not
    bundle_text = render_event_recap_bundle_text(candidate)
    assert "областн" not in bundle_text

    # C. real announcement headlines still present
    for title in _SVERDLOVSK_TITLES:
        assert title in bundle_text


def test_synthesis_evidence_never_exposes_internal_vocabulary():
    """Item 11.F / item 8: "entity", "SINGLE_SOURCE_ONLY", "MULTI_SOURCE_CONFIRMED", "bundle" as
    internal-status jargon must not appear in the synthesis-facing bundle text."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    bundle_text = render_event_recap_bundle_text(candidate)
    for forbidden in ("SINGLE_SOURCE_ONLY", "MULTI_SOURCE_CONFIRMED", "[entity]", "[numeric]"):
        assert forbidden not in bundle_text


def test_generated_title_with_real_evidence_does_not_receive_false_block():
    """Item 11.D: the exact real production generated title, checked against the exact real
    Sverdlovsk evidence, must not BLOCK (the real, observed production regression) - confirmed by
    direct execution to land on "review" (still flagged, never silently hidden - evaluate_fact_
    safety()'s own "unknown -> REVIEW, not BLOCK" design), never "block"."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    verification = _verify_synthesis_facts(candidate, _SVERDLOVSK_GENERATED_TITLE, _SVERDLOVSK_GENERATED_SUMMARY, [])
    assert verification.status != "block"


def test_genuinely_unsupported_numeric_claim_still_blocks():
    """Item 11.E / item 12: a fabricated percentage must still BLOCK - the fix must never weaken
    detection of a genuinely unsupported, high-severity claim type."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    verification = _verify_synthesis_facts(
        candidate, _SVERDLOVSK_GENERATED_TITLE, "Точность системы составляет 95%.", [],
    )
    assert verification.status == "block"
    assert verification.unsupported >= 1


def test_genuinely_unsupported_entity_claim_is_still_flagged():
    """Item 11.E / item 12: a fabricated vendor entity, not present anywhere in evidence, must
    still be flagged (unsupported) - never silently dropped by the projection or the title-source
    change."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    verification = _verify_synthesis_facts(
        candidate, _SVERDLOVSK_GENERATED_TITLE, "Систему разработала компания OpenAI.", [],
    )
    assert verification.status != "pass"
    assert any("OpenAI" in claim for claim in verification.flagged_claims)


def test_synthesis_evidence_includes_meaningful_numbers_regardless_of_source_count():
    """Item 12: a generic numeric single-source-fact case (not Sverdlovsk-specific) - a
    meaningful number must remain in synthesis evidence even when it appears in only one
    announcement."""
    candidate = _candidate_from_titles(
        ["Apple unveils new Watch Ultra priced at $999"], "Apple unveils new Watch Ultra",
    )
    bundle_text = render_event_recap_bundle_text(candidate)
    numeric_facts = [f for f in candidate.verified_facts if f.fact_type == "numeric"]
    assert numeric_facts and all(f.value in bundle_text for f in numeric_facts)


def test_synthesis_evidence_includes_multi_source_entities():
    """Item 12: a generic multi-source-entity case (Taiwan fixture, not Sverdlovsk) - a
    multi-source entity must remain in synthesis evidence."""
    candidate = _candidate_from_titles(
        [
            "Тайвань выплатит каждому гражданину страны около $314 «дивидендов от ИИ» - Ведомости",
            "Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
        ],
        "Тайвань одобрил выплату дивидендов от ИИ", gap_minutes=75.0,
    )
    bundle_text = render_event_recap_bundle_text(candidate)
    assert "тайвань" in bundle_text


def test_english_story_same_adapter_behavior_no_sverdlovsk_specific_logic():
    """Item 12: the exact same generic mechanism must apply to a wholly unrelated English-language
    Story - proves nothing in the fix is Sverdlovsk- or Russian-specific."""
    candidate = _candidate_from_titles(
        [
            "Researchers test new AI screening tool for early cancer detection - Daily Health Wire",
            "New AI tool trialled for cancer screening in regional hospitals - MedNewsToday",
        ],
        "Researchers test new AI screening tool for early cancer detection", gap_minutes=30.0,
    )
    bundle_text = render_event_recap_bundle_text(candidate)
    for forbidden in ("SINGLE_SOURCE_ONLY", "MULTI_SOURCE_CONFIRMED"):
        assert forbidden not in bundle_text
    verification = _verify_synthesis_facts(
        candidate, "AI Tool Trialled For Cancer Screening", "Researchers are testing a new AI tool for cancer screening.", [],
    )
    assert verification.status != "block"


# ---------------------------------------------------------------------------
# Phase R2.5 - editorial semantics hygiene (real production finding: a real Sverdlovsk synthesis
# call echoed "independent"/"независимыми" - traced to R2.4's own wording, "mentioned across
# multiple independent reports" - and echoed "bundle"/"evidence bundle" - traced to both v1's own
# prompt system text and services/event_recap.py's own "EVIDENCE BUNDLE:" request-building label).
# Item 10: readiness_source_count vs evidence_reference_count must never be conflated into an
# "independent sources" claim.
# ---------------------------------------------------------------------------


def test_synthesis_evidence_never_claims_independence_from_reference_count_alone():
    """Item 10: the real Sverdlovsk shape - readiness_source_count=1 (one collector NewsSource
    row), evidence_reference_count=3 (three distinct stored URLs) - must never produce
    "independent"/"independently confirmed" language merely because reference_count > 1."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    assert candidate.readiness_source_count == 1
    assert candidate.evidence_reference_count == 3
    bundle_text = render_event_recap_bundle_text(candidate)
    lowered = bundle_text.lower()
    assert "independent" not in lowered
    assert "независим" not in lowered  # Russian stem: независимый/независимыми/независимых/...


def test_synthesis_evidence_never_claims_independence_even_with_higher_readiness_source_count():
    """Item 10: even when readiness_source_count=evidence_reference_count=3 (every event has its
    own distinct collector NewsSource row too), no real deterministic publisher-independence
    signal exists in this codebase (module docstring's own explicit note) - the wording must still
    never claim independence."""
    events, clusters, summaries, facts = _summaries_and_facts(
        [
            "Taiwan approves $314 AI dividend for every citizen",
            "Government confirms $314 per person AI dividend program in Taiwan",
            "$314 AI dividend payment explained for Taiwan residents",
        ],
        gap_minutes=30.0,
    )
    timeline = _build_timeline(summaries)
    source_refs = list(dict.fromkeys(ref for s in summaries for ref in s.source_refs))
    candidate = EventRecapCandidate(
        story_id=uuid.uuid4(), anchor_event_id=events[0].id, story_title="Taiwan AI dividend",
        generated_at=_NOW, readiness_state="COOLING", readiness_overridden=True,
        story_integrity_eligible=True, story_integrity_reasons=[], announcement_count=len(clusters),
        readiness_source_count=3, evidence_reference_count=3, announcements=summaries,
        timeline=timeline, verified_facts=facts, source_refs=source_refs, media_candidates=[],
    )
    bundle_text = render_event_recap_bundle_text(candidate)
    assert "independent" not in bundle_text.lower()


def test_describe_fact_provenance_never_uses_independence_language():
    """Direct, minimal proof of the root cause fixed: _describe_fact_provenance() itself (the
    exact function whose R2.4 wording produced the real leak) must never emit "independent"."""
    from services.event_recap import FACT_MULTI_SOURCE_CONFIRMED as _MULTI, VerifiedFactCandidate, _describe_fact_provenance

    multi = VerifiedFactCandidate(fact_type="entity", value="свердловск", source_event_ids=[], source_count=3, status=_MULTI)
    text = _describe_fact_provenance(multi)
    assert "independent" not in text.lower()
    assert "multiple" in text.lower() or "stored" in text.lower()


# ---------------------------------------------------------------------------
# LLM synthesis (FakeLLMGateway/FakePromptRepository - zero paid calls)
# ---------------------------------------------------------------------------


def _runtime() -> RuntimeContext:
    return RuntimeContext(
        task_id=uuid.uuid4(), event_id=uuid.uuid4(), capability_name="event_recap_synthesis_shadow",
        priority=TaskPriority.C, attempt=1, iteration_count=0,
    )


async def _candidate_for_synthesis(db_session):
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.candidate is not None
    return result.candidate


def _prompt_repository() -> FakePromptRepository:
    repo = FakePromptRepository()
    repo.register(_PROMPT)
    return repo


@pytest.mark.asyncio
async def test_synthesis_makes_exactly_one_gateway_call(db_session):
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["Taiwan approved a $314 AI dividend for every citizen."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())
    assert len(gateway.received_requests) == 1
    assert gateway.received_requests[0].response_mode == "json_schema"
    assert updated.recap_title == "Taiwan AI dividend approved"
    assert updated.publishable is False


@pytest.mark.asyncio
async def test_fewer_than_max_takeaways_allowed_no_padding(db_session):
    """spec item 10: a valid recap can have fewer than the 5-8 target - synthesis must never pad."""
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["Taiwan approved a $314 AI dividend for every citizen."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())
    assert len(updated.key_takeaways) == 1  # not padded up to any minimum


@pytest.mark.asyncio
async def test_unsupported_claim_flagged_never_silently_published(db_session):
    """A takeaway asserting a fact absent from the evidence bundle (a different, unconfirmed
    number) must be flagged by fact verification - and publishable must remain False regardless."""
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": [
                "Taiwan approved a $314 AI dividend for every citizen.",
                "The dividend program is now confirmed to cost $999999 in total.",
            ],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())
    assert updated.fact_verification.status in ("review", "block")
    assert updated.fact_verification.unsupported >= 1 or updated.fact_verification.uncertain >= 1
    assert updated.publishable is False
    assert any(flag.startswith("fact_verification_") for flag in updated.quality_flags)


@pytest.mark.asyncio
async def test_synthesis_raises_on_gateway_error(db_session):
    candidate = await _candidate_for_synthesis(db_session)
    # call_generate() only translates the real Gateway error family (integrations.llm_gateway.
    # errors) into a CapabilityError - an arbitrary exception type would propagate uncaught
    # through call_generate() itself, which is out of scope for this test.
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no routable candidate"))
    with pytest.raises(EventRecapSynthesisError):
        await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())


@pytest.mark.asyncio
async def test_synthesis_raises_on_malformed_output(db_session):
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={"recap_title": "Missing other required keys"},
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    with pytest.raises(EventRecapSynthesisError):
        await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())


@pytest.mark.asyncio
async def test_synthesis_raises_when_structured_output_is_not_a_dict(db_session):
    """Phase R2.10B offline matrix (case B): a Gateway/model that returns no structured output at
    all (or a non-dict shape, e.g. the model emitted plain text instead of JSON) must fail closed,
    never be silently coerced or partially accepted."""
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text="not structured JSON", structured_output=None,
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    with pytest.raises(EventRecapSynthesisError):
        await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())


@pytest.mark.asyncio
async def test_synthesis_ignores_unexpected_extra_fields(db_session):
    """Phase R2.10B offline matrix (case G): extra/unexpected keys beyond the four the prompt
    schema declares (e.g. a model that adds its own "confidence_score" or "sources_used" field)
    must never break synthesis and must never leak into the candidate - only the four declared
    fields are ever read."""
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["Taiwan approved a $314 AI dividend for every citizen."],
            "uncertainty_notes": [],
            "confidence_score": 0.97,
            "sources_used": ["https://example.com/unexpected-extra-field"],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())
    assert updated.recap_title == "Taiwan AI dividend approved"
    assert updated.publishable is False
    assert not hasattr(updated, "confidence_score")
    assert not hasattr(updated, "sources_used")


def test_detect_internal_vocabulary_leak_finds_known_terms():
    """Item 11/12: the deterministic guard's own unit behavior - a real-shaped leak (the exact
    literal phrases production output was observed to contain) must be detected."""
    from services.event_recap import _detect_internal_vocabulary_leak

    leaked = _detect_internal_vocabulary_leak(
        "Тестирование ИИ", "В evidence bundle не приведены данные о точности.", [], ["В bundle нет числовых показателей."],
    )
    assert "bundle" in leaked


def test_detect_internal_vocabulary_leak_clean_text_finds_nothing():
    """Item 11/12: ordinary, clean editorial text must never false-positive."""
    from services.event_recap import _detect_internal_vocabulary_leak

    leaked = _detect_internal_vocabulary_leak(
        "Тестирование ИИ для диагностики рака кожи",
        "Свердловские дерматологи начали тестирование технологий искусственного интеллекта.",
        ["Метод пока проверяется только в одном регионе."],
        ["Результаты испытаний пока не опубликованы."],
    )
    assert leaked == []


@pytest.mark.asyncio
async def test_synthesis_flags_internal_vocabulary_leak_but_stays_unpublishable(db_session):
    """Item 11/12 end-to-end: if a (fake, non-paid) synthesis response DOES leak internal
    vocabulary, synthesize_event_recap() must record a disclosed quality_flags entry - never
    silently rewrite the text (item 11's own explicit prohibition) - and publishable must remain
    False regardless, exactly as it always is."""
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["The evidence bundle does not specify additional details."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())
    assert any(flag.startswith("internal_vocabulary_leak_detected") for flag in updated.quality_flags)
    assert "bundle" in updated.quality_flags[-1]
    assert updated.publishable is False
    # Never rewritten - the raw (leaking) text is preserved verbatim for editorial review.
    assert "evidence bundle" in updated.key_takeaways[0]


def test_prompt_v2_removes_bundle_language_v1_remains_untouched():
    """Item 6/7: structural proof of the prompt-level root cause and its fix - v1's own system
    text still contains "bundle" (untouched, immutable); v2's does not, and v2 adds an explicit
    internal-vocabulary-prohibition rule."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v1 = repo.resolve("event_recap", "1")
    v2 = repo.resolve("event_recap", "2")

    assert "bundle" in v1.system.lower()
    assert "bundle" not in v2.system.lower()
    # "bundle" may appear in v2's rules ONLY as a quoted example inside the explicit prohibition
    # rule itself (it must name the term it forbids) - never as ordinary descriptive prose
    # elsewhere, unlike v1's system text which uses it as working vocabulary throughout.
    rules_mentioning_bundle = [rule for rule in v2.rules if "bundle" in rule.lower()]
    assert len(rules_mentioning_bundle) == 1
    assert "internal" in rules_mentioning_bundle[0].lower() and "pipeline" in rules_mentioning_bundle[0].lower()
    assert any("independent" in rule.lower() for rule in v2.rules)


def test_bundle_text_is_deterministic_and_bounded():
    """render_event_recap_bundle_text() must be pure - identical candidate, identical text."""
    events = [
        _event(title="Taiwan approves $314 AI dividend for every citizen", url="https://a.example/1", minutes_ago=0),
    ]
    events_by_id = {e.id: e for e in events}
    clusters = cluster_announcements(events)
    summaries = _build_announcement_summaries(events_by_id, clusters, {})
    timeline = _build_timeline(summaries)
    facts = _build_verified_facts(summaries)

    candidate = EventRecapCandidate(
        story_id=uuid.uuid4(), anchor_event_id=events[0].id, story_title="Taiwan AI dividend", generated_at=_NOW,
        readiness_state="ACTIVE", readiness_overridden=True, story_integrity_eligible=True, story_integrity_reasons=[],
        announcement_count=len(clusters), readiness_source_count=1, evidence_reference_count=1,
        announcements=summaries, timeline=timeline,
        verified_facts=facts, source_refs=[events[0].url], media_candidates=[],
    )
    text_a = render_event_recap_bundle_text(candidate)
    text_b = render_event_recap_bundle_text(candidate)
    assert text_a == text_b
    assert "Taiwan AI dividend" in text_a


# ---------------------------------------------------------------------------
# Safety structural checks
# ---------------------------------------------------------------------------


def test_deterministic_build_never_touches_llm_gateway():
    """build_event_recap_candidate() must have no gateway/LLM-shaped parameter - a structural
    guarantee that the deterministic path cannot make an LLM call, matching the CLI's own
    --with-llm-gated design."""
    import inspect

    from services.event_recap import build_event_recap_candidate as build_fn

    params = inspect.signature(build_fn).parameters
    assert "gateway" not in params
    assert "prompt_repository" not in params


def test_cli_script_defers_llm_gateway_import_until_with_llm_flag():
    """scripts/_recap_r2_event_shadow.py must not import the LLM Gateway boot machinery at module
    level - only inside the --with-llm branch - so the safe default path never even imports it."""
    source = Path("scripts/_recap_r2_event_shadow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.add(node.module)
        elif isinstance(node, ast.Import):
            module_level_imports.update(alias.name for alias in node.names)
    assert "integrations.llm_gateway.boot" not in module_level_imports


def test_no_bot_or_worker_or_telegram_imports_anywhere_in_r2():
    """Structural proof no Telegram/worker/scheduler path is reachable from R2 code."""
    for path in ("services/event_recap.py", "scripts/_recap_r2_event_shadow.py"):
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("bot"), f"{path} imports from bot.*"
                assert not node.module.startswith("worker"), f"{path} imports from worker.*"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("bot"), f"{path} imports bot.*"
                    assert not alias.name.startswith("worker"), f"{path} imports worker.*"


def test_no_db_write_calls_in_event_recap_service_or_cli():
    """AST audit mirroring every prior RECAP production script's own safety check. `.add()`/
    `.add_all()`/`.merge()` are ambiguous in isolation (plain Python set/dict/list also expose
    `.add()` - services/event_recap.py legitimately uses `set.add()` for token collection), so
    those three are only flagged when called on a receiver whose own name suggests a DB session
    (contains "session"); `.delete()`/`.commit()`/`.execute_many()` and the bare `insert`/
    `update`/`delete` names are unambiguous regardless of receiver and always flagged."""
    session_scoped_attrs = {"add", "add_all", "merge"}
    unambiguous_attrs = {"delete", "commit", "execute_many"}
    forbidden_names = {"insert", "update"}
    for path in ("services/event_recap.py", "scripts/_recap_r2_event_shadow.py"):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in unambiguous_attrs:
                    pytest.fail(f"{path}:{node.lineno}: forbidden write-like call .{func.attr}()")
                if isinstance(func, ast.Attribute) and func.attr in session_scoped_attrs:
                    receiver = func.value
                    if isinstance(receiver, ast.Name) and "session" in receiver.id.lower():
                        pytest.fail(f"{path}:{node.lineno}: forbidden session write call .{func.attr}()")
                if isinstance(func, ast.Name) and func.id in forbidden_names:
                    pytest.fail(f"{path}:{node.lineno}: forbidden write-like call {func.id}()")


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("_recap_r2_event_shadow_test_import", "scripts/_recap_r2_event_shadow.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_json_serialization_stable(db_session):
    """The CLI's own _serialize()/_RecapJSONEncoder must produce stable, valid, round-trippable
    JSON for both an accepted candidate and a rejected result."""
    cli = _load_cli_module()

    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    accepted = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    payload_a = json.dumps(cli._serialize(accepted), cls=cli._RecapJSONEncoder, indent=2)
    payload_b = json.dumps(cli._serialize(accepted), cls=cli._RecapJSONEncoder, indent=2)
    assert payload_a == payload_b
    parsed = json.loads(payload_a)
    assert parsed["rejected"] is False
    assert parsed["candidate"]["publishable"] is False
    assert isinstance(parsed["candidate"]["story_id"], str)  # UUID serialized as string

    rejected_story, _ = await _make_story(db_session, [
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies in a used car you just bought?",
        "What the world's oldest telecommunications company is doing to survive",
    ])
    rejected = await build_event_recap_candidate(db_session, rejected_story, now=_NOW)
    payload_rejected = json.dumps(cli._serialize(rejected), cls=cli._RecapJSONEncoder, indent=2)
    parsed_rejected = json.loads(payload_rejected)
    assert parsed_rejected["rejected"] is True
    assert parsed_rejected["candidate"] is None


# ---------------------------------------------------------------------------
# Phase R2.6b - evidence semantic quality: publisher-derived numeric contamination +
# generic entity-phrase noise (real production findings: Yakutia Story "... - RuNews24" leaked
# numeric "24"; Nvidia Story's English Title-Case headline leaked entity phrases "chip company
# just bought"/"his own stock"/"million"). Both fixed as synthesis-projection-only corrections -
# the raw, forensic EventRecapCandidate.verified_facts/AnnouncementSummary.meaningful_numbers/
# .content_entities are NEVER mutated; only _synthesis_verified_facts()/render_event_recap_
# bundle_text() (the LLM-facing view) change. services/recap_event.py, services/story_memory.py,
# services/fact_safety.py are untouched anywhere in this section.
# ---------------------------------------------------------------------------

_YAKUTIA_TITLES_WITH_PUBLISHER_NUMBER = [
    "В Якутии разработают проект ЦОД для создания дальневосточного кластера искусственного интеллекта - RuNews24",
    "В Якутии разрабатывают проект создания дальневосточного ИИ-кластера на базе ЦОД - ЯСИА",
]

_NVIDIA_STOCK_TITLE = (
    "The CEO of This Nvidia-Backed Artificial Intelligence (AI) Chip Company Just Bought "
    "$10 Million of His Own Stock."
)


def test_runews24_publisher_suffix_number_is_not_a_synthesis_numeric_fact():
    """Real production finding: "24" in "... - RuNews24" must never reach the LLM-facing evidence,
    but the raw forensic candidate keeps it (proof projection never mutates forensic data)."""
    candidate = _candidate_from_titles(_YAKUTIA_TITLES_WITH_PUBLISHER_NUMBER, "Якутия ИИ-кластер")

    assert any(f.fact_type == "numeric" and f.value == "24" for f in candidate.verified_facts)

    projected = _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)
    assert not any(f.fact_type == "numeric" and f.value == "24" for f in projected)

    bundle_text = render_event_recap_bundle_text(candidate)
    # The TIMELINE section legitimately echoes each announcement's real, raw headline as a display
    # label (pre-existing, out of scope here - a human editor should see the real published
    # headline) - only the FACT-bearing sections (VERIFIED FACTS, and each announcement's own
    # numbers= field) must never expose "24" as if it were extracted evidence.
    facts_section = bundle_text.split("VERIFIED FACTS", 1)[1]
    assert "24" not in facts_section.split("ANNOUNCEMENTS (detail):", 1)[0]
    for line in facts_section.splitlines():
        if line.strip().startswith("- #"):
            numbers_field = line.split("numbers=", 1)[1].split("|", 1)[0]
            assert "24" not in numbers_field


def test_24_7_news_style_publisher_suffix_number_is_not_a_synthesis_numeric_fact():
    """A different publisher-suffix shape ("24/7 News") - proves the fix is generic suffix-vs-core
    logic, never a Yakutia-specific or RuNews24-specific string match."""
    titles = [
        "Apple unveils new AI feature for iPhone - 24/7 News",
        "Apple confirms new AI feature rollout for iPhone - TechRadar",
    ]
    candidate = _candidate_from_titles(titles, "Apple new AI feature")
    assert any(f.fact_type == "numeric" and f.value == "24" for f in candidate.verified_facts)
    projected = _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)
    assert not any(f.fact_type == "numeric" and f.value == "24" for f in projected)


def test_9to5mac_style_publisher_suffix_never_produces_spurious_single_digit_numeric_facts():
    """"9to5Mac" contains digits "9"/"5", but neither ever reaches _extract_meaningful_numbers() at
    all (a single lone digit is never "meaningful" - a pre-existing, unrelated design decision this
    fix does not touch) - regression guard proving this publisher-suffix shape stays safe."""
    titles = [
        "Apple announces new product line refresh - 9to5Mac",
        "Apple confirms new product line refresh details - MacRumors",
    ]
    candidate = _candidate_from_titles(titles, "Apple new product line")
    assert not any(f.fact_type == "numeric" for f in candidate.verified_facts)


def test_substantive_dollar_amount_remains_numeric_evidence_when_not_publisher_derived():
    """"$10 Million" in the real Nvidia title has no trailing-suffix segment at all - it is
    substantive content, not publisher noise, and must survive projection unchanged."""
    candidate = _candidate_from_titles([_NVIDIA_STOCK_TITLE], _NVIDIA_STOCK_TITLE)
    assert any(f.fact_type == "numeric" and f.value == "10" for f in candidate.verified_facts)
    projected = _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)
    assert any(f.fact_type == "numeric" and f.value == "10" for f in projected)


def test_raw_candidate_retains_full_forensic_numeric_and_entity_facts():
    """The raw, forensic EventRecapCandidate.verified_facts is never filtered by the R2.6b fix -
    every one of the real Nvidia title's noisy entities is still present in the raw candidate,
    exactly as it always was (diagnostic/provenance value preserved)."""
    candidate = _candidate_from_titles([_NVIDIA_STOCK_TITLE], _NVIDIA_STOCK_TITLE)
    raw_entities = {f.value for f in candidate.verified_facts if f.fact_type == "entity"}
    assert {"chip company just bought", "his own stock", "million", "ceo", "ai"} <= raw_entities


def test_generic_entity_phrases_are_excluded_from_synthesis_projection():
    """The real Nvidia production finding: "chip company just bought"/"his own stock"/"million"
    must never reach the LLM-facing evidence bundle."""
    candidate = _candidate_from_titles([_NVIDIA_STOCK_TITLE], _NVIDIA_STOCK_TITLE)
    projected_values = {
        f.value for f in _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)
    }
    assert "chip company just bought" not in projected_values
    assert "his own stock" not in projected_values
    assert "million" not in projected_values

    bundle_text = render_event_recap_bundle_text(candidate)
    assert "chip company just bought" not in bundle_text
    assert "his own stock" not in bundle_text


def test_is_generic_entity_phrase_detects_pronoun_and_magnitude_noise():
    assert _is_generic_entity_phrase("his own stock")
    assert _is_generic_entity_phrase("chip company just bought")
    assert _is_generic_entity_phrase("million")
    assert not _is_generic_entity_phrase("nvidia")
    assert not _is_generic_entity_phrase("openai")
    assert not _is_generic_entity_phrase("artificial intelligence")


def test_legitimate_multi_source_entities_are_retained_even_when_generic_phrase_is_also_present():
    """A genuine, legitimate multi-source entity ("nvidia ceo") must survive projection even
    though a co-occurring generic phrase ("his own stock", also multi-source) does not - proves the
    filter operates independently of source_count/status, never over-removing real content."""
    titles = [
        "Nvidia CEO boosts His Own Stock position again",
        "Nvidia CEO increases His Own Stock holdings this week",
    ]
    candidate = _candidate_from_titles(titles, "Nvidia CEO stock activity")
    raw_multi_source_entities = {
        f.value for f in candidate.verified_facts
        if f.fact_type == "entity" and f.status == FACT_MULTI_SOURCE_CONFIRMED
    }
    assert "his own stock" in raw_multi_source_entities  # raw candidate: both present
    assert "nvidia ceo" in raw_multi_source_entities

    projected_values = {
        f.value for f in _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)
    }
    assert "nvidia ceo" in projected_values  # legitimate entity retained
    assert "his own stock" not in projected_values  # generic phrase removed despite being multi-source


def test_publisher_suffix_numbers_returns_empty_when_no_trailing_suffix_exists():
    assert _publisher_suffix_numbers("Apple unveils new AI chip with 40 percent faster inference") == set()


# ---------------------------------------------------------------------------
# Phase R2.10A.1 - MissingGreenlet runtime hardening regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missinggreenlet_regression_no_story_refresh_needed(db_session):
    """Real, reproducible `sqlalchemy.exc.MissingGreenlet` hazard (not a fixture/test artifact) -
    proven BEFORE the fix by reverting services/event_recap.py's `last_event_at` line back to
    `max(..., default=story.updated_at)`. `Story.updated_at` (database/models/story.py) is a
    server-side `onupdate=func.now()` column: any earlier flush in the SAME session that mutates
    the Story row (e.g. services/triage_orchestrator.py's own `matched_story.event_count += 1`,
    exactly reproduced here) leaves it expired with no explicit `session.refresh()` in between - an
    eager, unconditional read of an expired scalar (as a `max(..., default=...)` argument, always
    evaluated by Python regardless of whether the iterable is empty) then triggers an implicit
    lazy-load outside a greenlet context. Root cause fix: `events` is provably non-empty at that
    point on every call path that reaches it (see services/event_recap.py's own comment there), so
    the `story.updated_at` fallback was unreachable dead code - removing it removes the hazard with
    zero behavior change. This test must pass WITHOUT any `db_session.refresh(story)` call - adding
    one back would silently mask a regression rather than prove the fix."""
    story, events = await _make_story(db_session, [
        "Marvell and Google expand their chip development deal",
        "Marvell pops 6% on AI chip deal with Google - CNBC",
    ], match_types=[NEW_STORY, STORY_UPDATE])

    # Mirrors services/triage_orchestrator.py::_apply_story_memory()'s own confirmed-continuation
    # bump exactly - the real production sequence that leaves `story.updated_at` expired.
    story.event_count += 1
    await db_session.flush()
    # Deliberately NO db_session.refresh(story) here - this is the point of the regression test.

    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.rejected is False
    assert result.candidate is not None
