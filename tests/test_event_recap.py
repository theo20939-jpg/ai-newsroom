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
    EVENT_RECAP_PROMPT_NAME,
    EVENT_RECAP_PROMPT_VERSION,
    EventRecapCandidate,
    EventRecapSynthesisError,
    EventRecapTelegramPreviewTooLongError,
    FACT_MULTI_SOURCE_CONFIRMED,
    FACT_SINGLE_SOURCE_ONLY,
    _build_announcement_summaries,
    _build_timeline,
    _build_verified_facts,
    _is_generic_entity_phrase,
    _publisher_suffix_numbers,
    _select_representative_media,
    _synthesis_verified_facts,
    _verify_synthesis_facts,
    build_event_recap_candidate,
    render_event_recap_bundle_text,
    render_event_recap_telegram_preview,
    synthesize_event_recap,
)
from services.image_persistence import EditorialImageCandidate
from services.recap_event import cluster_announcements
from services.story_memory import NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE, UNCERTAIN_MATCH
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

_PROMPT = RenderedPrompt(
    name="event_recap",
    version="3",
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


def test_bundle_text_marks_anchor_announcement_as_origin():
    """ANNOUNCEMENT CONTEXT section: the announcement whose `stable_event_id` matches the
    candidate's own `anchor_event_id` must be rendered as [ORIGIN] - deterministic, no LLM/keyword
    inference involved."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    anchor_summary = next(a for a in candidate.announcements if a.stable_event_id == candidate.anchor_event_id)

    bundle_text = render_event_recap_bundle_text(candidate)

    assert "ANNOUNCEMENT CONTEXT:" in bundle_text
    assert f"- [ORIGIN]\n{anchor_summary.headline}" in bundle_text


def test_bundle_text_marks_non_anchor_announcements_as_follow_up():
    """ANNOUNCEMENT CONTEXT section: every announcement whose `stable_event_id` does NOT match the
    candidate's own `anchor_event_id` must be rendered as [FOLLOW_UP]."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    follow_up_summaries = [a for a in candidate.announcements if a.stable_event_id != candidate.anchor_event_id]
    assert follow_up_summaries  # sanity: fixture actually has non-anchor announcements

    bundle_text = render_event_recap_bundle_text(candidate)

    for summary in follow_up_summaries:
        assert f"- [FOLLOW_UP]\n{summary.headline}" in bundle_text


def test_bundle_text_contains_announcement_context_section():
    """Phase R2.10: ANNOUNCEMENT CONTEXT (ORIGIN/FOLLOW_UP roles) must still be present in the
    synthesis-facing bundle text."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    bundle_text = render_event_recap_bundle_text(candidate)
    assert "ANNOUNCEMENT CONTEXT:" in bundle_text


def test_bundle_text_contains_timeline_section():
    """Phase R2.10: TIMELINE (publication chronology) must still be present in the synthesis-facing
    bundle text."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    bundle_text = render_event_recap_bundle_text(candidate)
    assert "TIMELINE (order of PUBLICATION only" in bundle_text


def test_bundle_text_no_longer_contains_announcements_detail_section():
    """Phase R2.10 correction (real diagnostic finding, Story
    2cb29dab-de57-493d-bf2b-09f80db875a7): the "ANNOUNCEMENTS (detail)" section repeated the same
    announcement headlines already shown in ANNOUNCEMENT CONTEXT and TIMELINE as a third
    one-bullet-per-announcement block - a structural signal that pushed synthesis toward one
    key_takeaway per announcement regardless of prompt-level wording. It must no longer appear in
    the LLM-facing bundle text. `EventRecapCandidate.announcements` itself (cluster_id,
    meaningful_numbers, content_entities, evidence_reference_count) is untouched - only this
    rendering changes."""
    candidate = _candidate_from_titles(_SVERDLOVSK_TITLES, "Свердловские дерматологи тестируют искусственный интеллект для диагностики рака кожи")
    bundle_text = render_event_recap_bundle_text(candidate)
    assert "ANNOUNCEMENTS (detail)" not in bundle_text
    # The underlying candidate data itself is untouched by this rendering-only change.
    assert all(a.cluster_id is not None for a in candidate.announcements)
    assert candidate.announcement_count == len(candidate.announcements)


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
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")
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
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")
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
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")
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
        await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")


@pytest.mark.asyncio
async def test_synthesis_raises_on_malformed_output(db_session):
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={"recap_title": "Missing other required keys"},
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    with pytest.raises(EventRecapSynthesisError):
        await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")


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
        await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")


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
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")
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
    updated = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru")
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


# ---------------------------------------------------------------------------
# R2.11 prompt-versioning cleanup - prompts/event_recap/v2.yaml was repeatedly edited in place
# across five real fixes (0beed1d/2cf8b51/9cc7f5a/bfec230/5704b1a), violating this codebase's own
# "a prompt is immutable once published" discipline (the same discipline v2.yaml's own header
# comment already states, and prompts/research/v3.yaml already follows). Pure versioning
# migration, never a behavior change: prompts/event_recap/v3.yaml now carries EXACTLY the content
# that was active v2 through all five real R2 shadow validations reported in this checkpoint
# (macOS 27, Nvidia/Poolside, Apple Music, Bryansk, Samsung Galaxy S27 Ultra, VK vs Apple) - only
# `version` changed 2 -> 3. `prompts/event_recap/v2.yaml` itself was restored, via `git checkout
# 51feac0 -- prompts/event_recap/v2.yaml` (never retyped by hand), to the exact content it had at
# 51feac0 - the commit that created it and the last commit before 0beed1d's first in-place edit.
# `EVENT_RECAP_PROMPT_VERSION` now points at "3" (services/event_recap.py) - v2 stays on disk,
# unused by any runtime path, purely as an accurate historical record of what was actually
# published at that version number.
# ---------------------------------------------------------------------------

# The exact 16 rule strings added across the five real R2 fixes, in the order they were
# introduced - every one of these must survive, verbatim, in v3 (item G: "no current R2 rule lost
# in the v2 -> v3 transfer"). Copied from the prompt files themselves, never retyped/paraphrased.
_R2_SYNTHESIS_RULES_ADDED_AFTER_51FEAC0: tuple[str, ...] = (
    # 0beed1d - ORIGIN/FOLLOW_UP narrative + anti-itemization
    "The ORIGIN announcement is the central event of this recap; every FOLLOW_UP announcement is a supporting development of that same event, never an independent story of its own - write one coherent recap of the ORIGIN event, not a list of separate news items.",
    "Merge FOLLOW_UP announcements that describe related or overlapping developments into a single synthesized point rather than giving each announcement its own separate takeaway.",
    "key_takeaways must be synthesized developments written in your own editorial words, not source headlines restated or lightly reworded - never produce one takeaway per announcement merely because it exists in the evidence.",
    "The timeline is evidence chronology only. It must not be copied into key_takeaways.",
    "key_takeaways must represent synthesized editorial progression, not one bullet per announcement.",
    "Multiple FOLLOW_UP announcements that describe the same area must be merged into one development.",
    "Prefer 2-3 meaningful developments over listing every source event.",
    "A recap with four announcements does not require four key_takeaways.",
    # 2cf8b51 - editorial boundaries: describe developments, not evidence/reports
    "key_takeaways must describe the real-world development itself, not the existence, quantity, storage, or provenance of reports/evidence.",
    "Never mention that something appears in multiple reports, stored reports, evidence, sources, or internal confirmation state.",
    "Avoid broad market, industry, or societal conclusions unless the evidence explicitly states them.",
    "Prefer concrete event-level descriptions over abstract interpretations.",
    # 9cc7f5a - uncertainty_notes provenance leakage (first rule) + qualifier preservation
    "uncertainty_notes must describe uncertainty of the real-world event itself, not uncertainty about evidence, reports, sources, or internal verification. Never mention limited evidence, stored reports, source counts, or similar provenance details.",
    "Preserve important qualifiers from the evidence when writing titles and summaries. Do not strengthen \"beta\", \"preview\", \"announced\", \"available to developers\", or similar states into stronger claims such as \"released\" or \"launched\" unless the evidence explicitly states that.",
    # bfec230 - uncertainty_notes provenance leakage (second, stricter rule)
    "uncertainty_notes must not describe evidence limitations, source count, number of reports, or how many sources support a claim. Do not write phrases such as \"based on one report\", \"only one source mentions\", \"limited evidence\", or similar provenance statements. Describe only what remains unknown about the real-world event itself.",
    # 5704b1a - epistemic strength preservation in titles/summaries
    "Titles and summaries must preserve the epistemic strength of the evidence. If the evidence represents a claim, report, estimate, survey result, or single-source statement, do not rewrite it as an independently verified fact. Keep attribution or uncertainty where required.",
)


def test_a_v1_prompt_untouched_by_versioning_migration():
    """Item A: v1 must remain exactly what it always was - this migration never reads, resolves,
    or edits v1 anywhere. "bundle" is v1's own working vocabulary throughout (the R2.5 finding
    v2 exists to fix) - proof v1's content is the original, pre-R2.5 text, not accidentally
    touched by this migration."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v1 = repo.resolve("event_recap", "1")
    assert v1.version == "1"
    assert "bundle" in v1.system.lower()


def test_b_restored_v2_matches_its_51feac0_published_baseline():
    """Item B: the restored v2 must be the ORIGINAL R2.5 content (51feac0) - none of the five
    later in-place edits' own rules may be present. Distinguishes "restored old v2" from "current
    v3" unambiguously: none of the R2 synthesis-era rules exist in v2, and v2 has exactly the
    original 8 rules, not 24."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v2 = repo.resolve("event_recap", "2")
    assert v2.version == "2"
    assert len(v2.rules) == 8
    for later_rule in _R2_SYNTHESIS_RULES_ADDED_AFTER_51FEAC0:
        assert later_rule not in v2.rules
    assert "ORIGIN" not in v2.system
    assert "FOLLOW_UP" not in v2.system


def test_c_and_g_v3_contains_every_current_r2_synthesis_rule():
    """Items C + G: v3 must contain every one of the 16 real R2 synthesis rules added across the
    five fix commits (0beed1d/2cf8b51/9cc7f5a/bfec230/5704b1a), verbatim - nothing lost in the
    v2 -> v3 transfer."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v3 = repo.resolve("event_recap", "3")
    for rule in _R2_SYNTHESIS_RULES_ADDED_AFTER_51FEAC0:
        assert rule in v3.rules


def test_d_runtime_prompt_version_constant_points_at_v3():
    """Item D: services/event_recap.py's own runtime constant must select v3, not v2."""
    assert EVENT_RECAP_PROMPT_NAME == "event_recap"
    assert EVENT_RECAP_PROMPT_VERSION == "3"


def test_e_file_prompt_repository_resolves_event_recap_v3():
    """Item E: the real FilePromptRepository (never a fake) must resolve ("event_recap", "3")
    cleanly - name/version on the returned RenderedPrompt must match the file's own declared
    name/version, and resolving via EVENT_RECAP_PROMPT_VERSION must return the identical object
    the runtime path (synthesize_event_recap) would actually use."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v3 = repo.resolve(EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION)
    assert v3.name == "event_recap"
    assert v3.version == "3"


def test_f_v3_output_schema_identical_to_the_stable_working_schema():
    """Item F: output_schema was never touched by any of the five R2 rule-only fixes - v3's
    output_schema must be byte-identical to that stable, already-shipped contract (same field
    names, types, descriptions, required list, additionalProperties)."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v3 = repo.resolve("event_recap", "3")
    assert v3.output_schema == {
        "type": "object",
        "properties": {
            "recap_title": {
                "type": "string",
                "description": "A short, factual, non-sensational title for this recap (internal review only).",
            },
            "recap_summary": {
                "type": "string",
                "description": "A concise (2-4 sentence) factual summary of the event, strictly from the evidence given.",
            },
            "key_takeaways": {
                "type": "array",
                "items": {"type": "string"},
                "description": "At most 8, fewer if evidence is thin - the most important, evidence-backed points.",
            },
            "uncertainty_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Notes on what remains single-report, unconfirmed, or genuinely unclear from the evidence given - empty if none.",
            },
        },
        "required": ["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
        "additionalProperties": False,
    }


# The ONE original v2 rule whose wording changed (0beed1d extended it to also name "ORIGIN"/
# "FOLLOW_UP" as forbidden internal vocabulary) - transcribed verbatim from prompts/event_recap/
# v3.yaml, never reconstructed by string concatenation (avoids a subtle wording-join mistake).
_INTERNAL_VOCABULARY_RULE_AFTER_ORIGIN_FOLLOW_UP_EXTENSION = (
    "Never mention this newsroom's own internal pipeline, software, or data-processing "
    "terminology in any of the four output fields (examples of what must never appear, in any "
    "language - \"bundle\", \"evidence set\", \"prompt\", \"candidate\", \"entity\", \"token\", "
    "\"parser\", \"fact verification\", or any internal status label, including \"ORIGIN\"/"
    "\"FOLLOW_UP\" themselves) - write only as a human editor describing the real-world event "
    "itself, never the process that produced this text."
)


def test_v3_rule_set_is_exactly_v2_originals_plus_r2_additions_nothing_more_nothing_less():
    """Machine-verified behavioral-equivalence proof (checkpoint item 7, multiset form - order-
    independent so it never needs to guess the real file's exact interleaving of old vs. new
    rules): v3's 24 rules must be EXACTLY the restored v2's 8 original rules (7 untouched
    verbatim, 1 - the internal-vocabulary rule - extended with the ORIGIN/FOLLOW_UP mention) plus
    the 16 real R2 rule additions - no more, no fewer, nothing silently dropped or duplicated."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v2 = repo.resolve("event_recap", "2")
    v3 = repo.resolve("event_recap", "3")

    untouched_originals = [rule for i, rule in enumerate(v2.rules) if i != 6]
    expected_pool = (
        untouched_originals
        + [_INTERNAL_VOCABULARY_RULE_AFTER_ORIGIN_FOLLOW_UP_EXTENSION]
        + list(_R2_SYNTHESIS_RULES_ADDED_AFTER_51FEAC0)
    )
    assert len(expected_pool) == 24
    assert len(v3.rules) == 24
    assert sorted(v3.rules) == sorted(expected_pool)
    # The pre-extension wording must be fully replaced in v3, never left duplicated alongside the
    # new one.
    assert v2.rules[6] not in v3.rules
    assert v3.version == "3"


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
    for path in (
        "services/event_recap.py", "scripts/_recap_r2_event_shadow.py",
        "scripts/_recap_r2_10_readiness_candidate_scanner.py",
    ):
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
# Phase R2.10 Night 2 - decimal-comma numeric normalization (real production-shadow finding)
# ---------------------------------------------------------------------------


def test_russian_decimal_comma_matches_english_decimal_point_marvell_fixture():
    """The exact real production-shadow anomaly: the English Marvell/Google event produced the
    fact "12.2" while the Russian-language event for the SAME underlying $12.2 billion figure
    produced "122" - a fabricated-looking value that appears in no evidence text at all, and one
    that silently prevented the two sources from ever being recognized as corroborating the same
    fact (_build_verified_facts() groups by exact string equality). Both must now normalize
    identically."""
    from services.event_recap import _extract_meaningful_numbers

    english = _extract_meaningful_numbers(
        "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC"
    )
    russian = _extract_meaningful_numbers(
        "Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на "
        "сумму $12,2 млрд"
    )
    assert "12.2" in english
    assert "12.2" in russian, "Russian decimal comma must normalize to the same fact as the English decimal point"
    assert "122" not in russian, "the old naive comma-strip must no longer fabricate a nonexistent value"


def test_normalize_numeric_token_locale_disambiguation_matrix():
    """Phase 2 numeric semantics audit: comma/period disambiguation must never collapse a genuine
    thousands-grouped whole number into a fabricated decimal, and must never leave a genuine
    decimal comma unconverted. `_normalize_numeric_token()` is intentionally a narrow heuristic
    (last separator = decimal when both appear; a lone comma followed by 1-2 digits = decimal;
    everything else comma-only = thousands grouping), never a general locale/NLP parser."""
    from services.event_recap import _normalize_numeric_token

    cases = {
        "12.2": "12.2",  # English decimal - already unambiguous, must stay unchanged
        "12,2": "12.2",  # Russian/EU decimal comma - the reported bug
        "1,5": "1.5",
        "0,5": "0.5",
        "1,234": "1234",  # conventional 3-digit thousands grouping - never a decimal
        "$1,299": "1299",  # a price tag, not a decimal
        "1,234.56": "1234.56",  # US thousands + decimal
        "1.234,56": "1234.56",  # EU thousands + decimal
    }
    for raw, expected in cases.items():
        assert _normalize_numeric_token(raw) == expected, f"{raw!r} -> expected {expected!r}"


def test_thousands_grouped_price_never_becomes_a_decimal():
    """A real-shaped price tag ("$1,299") must never be misread as "1.299" - the disambiguation
    heuristic must not overcorrect the original bug into a new, opposite one."""
    from services.event_recap import _extract_meaningful_numbers

    numbers = _extract_meaningful_numbers("The new flagship launches at $1,299 this fall")
    assert "1299" in numbers
    assert "1.299" not in numbers


def test_percent_and_currency_prefixed_decimal_commas_normalize_correctly():
    from services.event_recap import _extract_meaningful_numbers

    numbers = _extract_meaningful_numbers("Рост составил 1,5% при выручке в 12,2 млн рублей")
    assert "1.5" in numbers
    assert "12.2" in numbers


def test_space_separated_thousands_fractional_part_still_preserved():
    """"1 234,56" is tokenized as two separate matches by the existing (unchanged) regex - the
    single leading "1" is filtered as too short to be meaningful, exactly as before this fix; the
    fractional group "234,56" must still normalize to a genuine decimal, never "23456"."""
    from services.event_recap import _extract_meaningful_numbers

    numbers = _extract_meaningful_numbers("Цена составила 1 234,56 рублей")
    assert "234.56" in numbers
    assert "23456" not in numbers


def test_recap_event_frozen_extractor_has_the_same_unfixed_pattern_documented_not_touched():
    """Phase R2.10 Night 2 forensic: the FROZEN `services/recap_event.py::_extract_numeric_tokens()`
    duplicates the exact same pre-fix naive comma-strip behavior this test file's own RECAP-local
    fix replaces. This is deliberately NOT fixed here (frozen R1 file) - this test only documents
    and pins the known, disclosed limitation so a future checkpoint has a concrete regression
    anchor, and so nobody mistakes R1's copy as already fixed by this commit."""
    from services.recap_event import _extract_numeric_tokens

    assert _extract_numeric_tokens("$12,2 млрд") == {"122"}, (
        "if this ever changes, services/recap_event.py was modified - update this pinning test "
        "and the R2.10 report, since that file is supposed to be frozen this phase"
    )


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


# ---------------------------------------------------------------------------
# Phase R2.10 Night 2 - source identity / diversity forensic (Google News wrapper risk)
# ---------------------------------------------------------------------------


def test_frozen_count_unique_sources_can_inflate_same_real_publisher_via_wrapper():
    """Phase 3 forensic finding, REPORT ONLY: `services/recap_event.py::count_unique_sources()`
    is FROZEN (never modified here). It normalizes purely by `NewsEvent.url`'s own domain
    (`_normalize_domain()`) - it has no awareness of canonical/acquisition data at all. When the
    SAME real publisher's article reaches this newsroom twice - once via a direct URL, once via a
    Google News RSS wrapper (`news.google.com`) - the two events' domains differ
    ("cnbc.com" vs "news.google.com"), so this frozen function counts them as 2 distinct sources
    for READINESS purposes even though there is only 1 real publisher. This is a real,
    reproducible characteristic of frozen R1 code - documented here as evidence, never fixed
    (`evaluate_recap_readiness()`'s own `unique_source_count` threshold is out of scope this
    phase). `services/event_recap.py`'s own `evidence_reference_count` (see the sibling test
    below) is R2's already-existing, already-disclosed mitigation for evidence-bundle purposes -
    it does NOT retroactively correct what `count_unique_sources()` itself reports to readiness."""
    from services.recap_event import count_unique_sources

    direct = _event(title="Marvell chip deal", url="https://www.cnbc.com/2026/08/20/marvell-google.html", minutes_ago=10)
    via_google_news = _event(
        title="Marvell chip deal", url="https://news.google.com/rss/articles/CBMi...", minutes_ago=5,
    )
    assert count_unique_sources([direct, via_google_news]) == 2, (
        "documents the real inflation risk - same real publisher, counted twice, because one "
        "event arrived through a Google News wrapper URL"
    )


def test_frozen_count_unique_sources_can_also_collapse_distinct_publishers_via_wrapper():
    """The mirror-image, already-disclosed R1.3 finding (module docstring of
    load_canonical_urls_for_events()/count_unique_sources_with_canonical_urls()): two GENUINELY
    DIFFERENT real publishers, both wrapped by Google News, normalize to the identical
    "news.google.com" domain and are undercounted as ONE source. Frozen, documented, not fixed."""
    from services.recap_event import count_unique_sources

    outlet_a = _event(title="Marvell chip deal - CNBC", url="https://news.google.com/rss/articles/AAA...", minutes_ago=10)
    outlet_b = _event(title="Marvell chip deal - Reuters", url="https://news.google.com/rss/articles/BBB...", minutes_ago=5)
    assert count_unique_sources([outlet_a, outlet_b]) == 1, (
        "documents the real undercounting risk - two genuinely distinct publishers, both wrapped "
        "by Google News, collapse to a single normalized domain"
    )


def test_evidence_reference_identity_correctly_prefers_canonical_url_over_wrapper_domain():
    """R2's own `_evidence_reference_identity()` (NOT frozen, R2-owned) is the already-existing
    correction for the evidence BUNDLE (never for readiness, which stays frozen): when Article
    Acquisition has already resolved a canonical URL for a Google-News-wrapped event, that
    canonical domain is used instead of the wrapper's own domain - two wrappers pointing at the
    SAME real canonical publisher correctly collapse to ONE evidence reference."""
    from services.event_recap import _evidence_reference_identity

    wrapper_event_a = _event(title="x", url="https://news.google.com/rss/articles/AAA...", minutes_ago=10)
    wrapper_event_b = _event(title="x", url="https://news.google.com/rss/articles/BBB...", minutes_ago=5)
    identity_a = _evidence_reference_identity(wrapper_event_a, "https://www.cnbc.com/2026/08/20/marvell-google.html")
    identity_b = _evidence_reference_identity(wrapper_event_b, "https://www.cnbc.com/2026/08/20/marvell-google.html")
    assert identity_a == identity_b == "cnbc.com"


def test_evidence_reference_identity_never_collapses_to_bare_wrapper_domain_without_canonical():
    """When NO canonical URL is available yet (acquisition has not run for that event), R2's own
    correction deliberately falls back to the FULL raw event URL, never the wrapper's own domain
    alone - re-collapsing to "news.google.com" would silently reintroduce the exact ambiguity this
    correction exists to fix (module docstring's own explicit reasoning)."""
    from services.event_recap import _evidence_reference_identity

    wrapper_event = _event(title="x", url="https://news.google.com/rss/articles/AAA...", minutes_ago=10)
    identity = _evidence_reference_identity(wrapper_event, None)
    assert identity == wrapper_event.url
    assert identity != "news.google.com"


def test_evidence_reference_identity_distinguishes_genuinely_distinct_publishers():
    from services.event_recap import _evidence_reference_identity

    cnbc_event = _event(title="x", url="https://www.cnbc.com/article1", minutes_ago=10)
    reuters_event = _event(title="y", url="https://www.reuters.com/article2", minutes_ago=5)
    assert (
        _evidence_reference_identity(cnbc_event, None) != _evidence_reference_identity(reuters_event, None)
    )


# ---------------------------------------------------------------------------
# Phase R2.10 Night 2 - fact cross-source merging (Phase 6)
# ---------------------------------------------------------------------------


def test_decimal_comma_fix_enables_correct_multi_source_numeric_confirmation():
    """End-to-end proof that the Phase 1 numeric fix (see the decimal-comma tests above) actually
    reaches _build_verified_facts(): the real Marvell/Google English+Russian pair now correctly
    merges the SAME real $12.2B figure into one FACT_MULTI_SOURCE_CONFIRMED fact, instead of two
    unrelated FACT_SINGLE_SOURCE_ONLY facts (one of which - "122" - was a fabricated value present
    in no evidence text at all)."""
    events, _clusters, _summaries, facts = _summaries_and_facts([
        "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC",
        "Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на "
        "сумму $12,2 млрд",
    ])
    numeric_facts = {f.value: f for f in facts if f.fact_type == "numeric"}
    assert "12.2" in numeric_facts
    assert numeric_facts["12.2"].status == FACT_MULTI_SOURCE_CONFIRMED
    assert numeric_facts["12.2"].source_count == 2
    assert "122" not in numeric_facts


def test_entity_legal_suffix_variants_do_not_merge_known_documented_limitation():
    """Phase 6 forensic finding, REPORT ONLY / NOT FIXED (documented, not implemented tonight -
    no real production instance of this exact split was found, unlike the numeric bug; per this
    phase's own "fix only high-confidence cases" instruction, a speculative legal-suffix stripper
    was deliberately not built without concrete forensic evidence it is needed). `extract_story_
    signature()` (services/story_memory.py, FROZEN, never modified here) treats "Marvell
    Technology" and "Marvell" - and "Google LLC" and "Google" - as different entity strings.
    If two real sources described the same company using different legal-suffix forms, this
    system would currently under-detect the corroboration (two SINGLE_SOURCE_ONLY entities
    instead of one MULTI_SOURCE_CONFIRMED) - not a fabricated fact (unlike the numeric bug), just
    a missed-corroboration case. Pinned here so a future checkpoint has a concrete regression
    anchor and reproducer if a narrow, evidence-backed RECAP-local alias correction is ever
    warranted (mirroring _publisher_suffix_numbers()'s own small-explicit-list precedent, never a
    general entity-resolution engine)."""
    from services.story_memory import extract_story_signature
    from database.models.news_event import EventCategory

    full_name = extract_story_signature("Marvell Technology announces new AI chip", EventCategory.TECH)
    short_name = extract_story_signature("Marvell announces new AI chip", EventCategory.TECH)
    assert "marvell technology" in full_name.entities
    assert "marvell" in short_name.entities
    assert "marvell technology" not in short_name.entities, (
        "if this ever changes, story_memory.py's frozen entity extraction changed - update this "
        "pinning test and the R2.10 Night 2 report"
    )


# ---------------------------------------------------------------------------
# Phase R2.10 Night 2 - synthesis input invariant suite (Phase 8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesis_evidence_invariants_hold_and_build_is_reproducible(db_session):
    """A single strong invariant test covering the exact evidence that reaches Prompt v2
    (render_event_recap_bundle_text()'s own inputs), run against a real 4-announcement DB
    fixture. Builds the candidate TWICE from the same fixture and cross-checks every invariant
    below against BOTH runs, proving both correctness and reproducibility in one pass."""
    from services.recap_event import load_story_events

    story, events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "Taiwan dividend program expands eligibility criteria for AI payout",
        "Officials detail rollout timeline for Taiwan's AI dividend scheme",
    ], match_types=[NEW_STORY, STORY_UPDATE, STORY_UPDATE, STORY_UPDATE])
    event_ids = {e.id for e in events}

    for _ in range(2):
        result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
        assert result.candidate is not None
        candidate = result.candidate

        # Anchor always represented among the announcements' own member events - never an anchor
        # that R1's own clustering silently dropped or that lies outside candidate membership.
        all_member_ids = {eid for a in candidate.announcements for eid in a.member_event_ids}
        assert candidate.anchor_event_id in event_ids
        assert candidate.anchor_event_id in all_member_ids

        # No duplicate announcement cluster ids.
        cluster_ids = [a.cluster_id for a in candidate.announcements]
        assert len(cluster_ids) == len(set(cluster_ids))

        # No duplicate source ref at the candidate level.
        assert len(candidate.source_refs) == len(set(candidate.source_refs))

        # No duplicate source ref within any single announcement.
        for a in candidate.announcements:
            assert len(a.source_refs) == len(set(a.source_refs))

        # Every timeline item maps to a known announcement cluster id.
        announcement_ids = {a.cluster_id for a in candidate.announcements}
        for entry in candidate.timeline:
            assert entry.announcement_id in announcement_ids

        # Every timeline entry's supporting events exist in candidate membership.
        for entry in candidate.timeline:
            assert set(entry.supporting_event_ids) <= event_ids

        # Every fact's source_event_ids exist in candidate membership - never an unsupported event.
        for fact in candidate.verified_facts:
            assert set(fact.source_event_ids) <= event_ids

        # Every announcement's member events exist in candidate membership.
        for a in candidate.announcements:
            assert set(a.member_event_ids) <= event_ids

        # Every source ref in candidate.source_refs actually comes from some announcement's own
        # source_refs (never a ref invented at the top level).
        all_announcement_refs = {ref for a in candidate.announcements for ref in a.source_refs}
        assert set(candidate.source_refs) <= all_announcement_refs

        # Stable ordering: timeline is sorted chronologically by timestamp.
        timestamps = [entry.timestamp for entry in candidate.timeline]
        assert timestamps == sorted(timestamps)

        # Origin projection did not alter stored membership (mirrors R2.9's case4b oracle).
        confirmed = await load_story_events(db_session, story.id)
        assert {e.id for e in confirmed} == event_ids


@pytest.mark.asyncio
async def test_evidence_bundle_text_normalized_identical_across_two_builds(db_session):
    """generated_at is the only intentionally non-deterministic field on EventRecapCandidate
    itself (module docstring) - render_event_recap_bundle_text() never embeds it at all, so the
    rendered evidence TEXT sent to the prompt must be byte-for-byte identical across two builds of
    the same fixture, independent of story_title/generated_at differences."""
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    result_a = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    result_b = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW + timedelta(hours=1))
    assert result_a.candidate is not None and result_b.candidate is not None
    text_a = render_event_recap_bundle_text(result_a.candidate)
    text_b = render_event_recap_bundle_text(result_b.candidate)
    assert text_a == text_b, "evidence bundle text must not depend on `now`/generated_at"


# ---------------------------------------------------------------------------
# Phase R2.10 Night 2 - publishable invariant audit (Phase 11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishable_stays_false_across_every_reachable_r2_path(db_session):
    """Phase 11: exhaustively proves EventRecapCandidate.publishable cannot become True through
    any reachable R2 code path - deterministic build (natural READY, force_shadow), and every
    synthesis outcome (success, well-grounded, unsupported-claim-flagged, internal-vocabulary-leak-
    flagged). Structural guarantee (not just empirical): the dataclass default is `False`
    (services/event_recap.py's own `publishable: bool = False`) and the ONE `dataclasses.replace()`
    call in synthesize_event_recap() passes `publishable=False` unconditionally - no other
    constructor call for EventRecapCandidate exists anywhere in this module."""
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])

    deterministic_forced = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert deterministic_forced.candidate is not None
    assert deterministic_forced.candidate.publishable is False

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
    synthesized = await synthesize_event_recap(
        deterministic_forced.candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru",
    )
    assert synthesized.publishable is False
    assert synthesized.fact_verification.status in ("pass", "review", "block")

    unsupported_gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["The program will actually cost $999999999 in total, unlike anything reported."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    unsupported_synthesized = await synthesize_event_recap(
        deterministic_forced.candidate, unsupported_gateway, _prompt_repository(), runtime=_runtime(),
        language="ru",
    )
    assert unsupported_synthesized.fact_verification.status != "pass"
    assert unsupported_synthesized.publishable is False


# ---------------------------------------------------------------------------
# Phase R2.10 Night 2 - Telegram pure presentation prototype (Phase 18, report-only otherwise)
# ---------------------------------------------------------------------------


def _synthesized_taiwan_candidate() -> EventRecapCandidate:
    from dataclasses import replace

    candidate = _candidate_from_titles(
        [
            "Taiwan approves $314 AI dividend for every citizen",
            "Government confirms $314 per person AI dividend program in Taiwan",
        ],
        "Taiwan AI dividend program",
    )
    return replace(
        candidate,
        recap_title="Taiwan approves $314 AI dividend for every citizen",
        recap_summary="Taiwan's government confirmed a one-time $314 AI dividend paid to every citizen.",
        key_takeaways=["The dividend is funded from AI-related budget surplus.", "Payments begin next quarter."],
        uncertainty_notes=["Exact disbursement mechanism is single-source only."],
    )


def test_telegram_preview_renders_all_expected_sections():
    candidate = _synthesized_taiwan_candidate()
    text = render_event_recap_telegram_preview(candidate)
    assert text.startswith("Taiwan approves $314 AI dividend for every citizen")
    assert "AI dividend paid to every citizen" in text
    assert "Key developments:" in text
    assert "Key takeaways:" in text
    assert "AI-related budget surplus" in text
    assert "What remains uncertain:" in text
    assert "disbursement mechanism" in text
    assert "Sources:" in text


def test_telegram_preview_falls_back_to_story_title_before_synthesis():
    """Before synthesis has ever run, recap_title is None - the preview must use the real,
    deterministic story_title, never an empty/placeholder title."""
    candidate = _candidate_from_titles(
        ["Taiwan approves $314 AI dividend for every citizen", "Government confirms $314 per person AI dividend program in Taiwan"],
        "Taiwan AI dividend program",
    )
    assert candidate.recap_title is None
    text = render_event_recap_telegram_preview(candidate)
    assert text.startswith(candidate.story_title)


def test_telegram_preview_omits_empty_sections_never_pads():
    """A candidate with no uncertainty notes must never render a "no uncertainty" filler line -
    mirrors this module's own established "never pad" discipline elsewhere."""
    candidate = _candidate_from_titles(
        ["Taiwan approves $314 AI dividend for every citizen", "Government confirms $314 per person AI dividend program in Taiwan"],
        "Taiwan AI dividend program",
    )
    text = render_event_recap_telegram_preview(candidate)
    assert "What remains uncertain:" not in text


def test_telegram_preview_never_dumps_raw_urls_only_domains():
    candidate = _synthesized_taiwan_candidate()
    text = render_event_recap_telegram_preview(candidate)
    for ref in candidate.source_refs:
        assert ref not in text  # raw URLs never appear, only their normalized domains


def test_telegram_preview_raises_rather_than_silently_truncates_over_limit():
    from dataclasses import replace

    candidate = _synthesized_taiwan_candidate()
    oversized = replace(candidate, recap_summary="x" * 5000)
    with pytest.raises(EventRecapTelegramPreviewTooLongError):
        render_event_recap_telegram_preview(oversized)


def test_telegram_preview_is_deterministic():
    candidate = _synthesized_taiwan_candidate()
    assert render_event_recap_telegram_preview(candidate) == render_event_recap_telegram_preview(candidate)


# ---------------------------------------------------------------------------
# Phase F.4.9 - Russian editorial output alignment. `synthesize_event_recap()`/
# `_build_synthesis_request()` now append the same `f"Target output language: {...}"` line every
# other Capability's own `execute()` already appends (capabilities/research_capability.py,
# capabilities/copywriting_capability.py, etc.) - reusing `BusinessContext.language`/
# `settings.default_content_language` verbatim. `prompts/event_recap/v3.yaml` itself is NOT
# touched by this phase - these tests prove that directly, not by assumption.
# ---------------------------------------------------------------------------


def test_active_event_recap_prompt_version_is_still_v3():
    """Phase F.4.9 introduces no new prompt version - the language fix lives entirely in the
    Python-constructed request text, mirroring every sibling Capability's own identical
    convention, never a prompt-text edit."""
    assert EVENT_RECAP_PROMPT_VERSION == "3"


def test_event_recap_prompt_v3_file_has_no_hardcoded_language_instruction():
    """Proves the language fix is NOT baked into the immutable prompt file - v3's own `system`/
    `rules` text contains no language directive of any kind (unlike e.g. prompts/copywriting/
    v8.6.yaml's own explicit "Write... in Russian" prose) - confirms this is a pure
    Python-request-construction fix, reusing the codebase's one existing runtime/context
    mechanism, never a new immutable prompt version."""
    from pathlib import Path as _Path

    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_Path("prompts"))
    v3 = repo.resolve(EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION)
    assert v3.version == "3"
    haystack = (v3.system + " " + " ".join(v3.rules)).lower()
    assert "russian" not in haystack
    assert "target output language" not in haystack


def test_synthesis_request_includes_target_output_language_line():
    """`_build_synthesis_request()` appends the exact same convention every sibling Capability's
    own `execute()` already uses - proven directly on the constructed GenerateRequest, never
    assumed from the model's own eventual (uncontrollable) response language."""
    from services.event_recap import _build_synthesis_request

    candidate = _candidate_from_titles(
        ["Vantage Data Centers explores sale or IPO options"], "Vantage Data Centers explores strategic options",
    )
    request = _build_synthesis_request(candidate, _PROMPT, "ru")
    user_text = request.messages[1].content[0].text
    assert "Target output language: ru" in user_text


def test_synthesis_request_language_is_a_real_parameter_not_hardcoded():
    """Proves `language` is a genuine, threaded parameter - not a hardcoded "ru" string - by
    passing a different value and observing it verbatim in the constructed request, with no
    trace of "ru" anywhere the parameter itself did not put it."""
    from services.event_recap import _build_synthesis_request

    candidate = _candidate_from_titles(
        ["Vantage Data Centers explores sale or IPO options"], "Vantage Data Centers explores strategic options",
    )
    request = _build_synthesis_request(candidate, _PROMPT, "en")
    user_text = request.messages[1].content[0].text
    assert "Target output language: en" in user_text
    assert "Target output language: ru" not in user_text


@pytest.mark.asyncio
async def test_synthesize_event_recap_threads_language_into_the_real_gateway_request():
    """End-to-end proof through the real, public `synthesize_event_recap()` entry point (not just
    the private `_build_synthesis_request()` helper) - the exact request FakeLLMGateway received
    carries the language instruction, using the same fixture shape
    test_synthesis_makes_exactly_one_gateway_call() already established (still exactly one
    Gateway call - no second, translation-only call)."""
    candidate = _candidate_from_titles(
        ["Vantage Data Centers explores sale or IPO options"], "Vantage Data Centers explores strategic options",
    )
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Vantage Data Centers рассматривает продажу или IPO",
            "recap_summary": "Компания изучает стратегические варианты, включая продажу или IPO.",
            "key_takeaways": ["Vantage Data Centers рассматривает продажу или IPO."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    updated = await synthesize_event_recap(
        candidate, gateway, _prompt_repository(), runtime=_runtime(), language="ru",
    )
    assert len(gateway.received_requests) == 1
    user_text = gateway.received_requests[0].messages[1].content[0].text
    assert "Target output language: ru" in user_text
    assert updated.recap_title == "Vantage Data Centers рассматривает продажу или IPO"
    assert updated.publishable is False


# ---------------------------------------------------------------------------------------------
# Phase H.1 - _select_representative_media(): pure, offline, no DB, no LLM
# ---------------------------------------------------------------------------------------------


def _image_candidate(**overrides: object) -> EditorialImageCandidate:
    """A minimal, eligible-by-default EditorialImageCandidate factory - only the fields these
    tests actually vary need to be passed; every other field gets a plausible, harmless default."""
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(), candidate_id=f"c-{uuid.uuid4()}", rank=1, relevance_score=50,
        quality_score=80, discovery_method="open_graph_image", source_relationship=None,
        relevance_reason=None, width=1200, height=800, observed_mime="image/jpeg",
        image_format="JPEG", storage_status="stored", storage_key="images/x.jpg",
        telegram_file_id=None, editor_decision=None, source_url="https://example.com/a.jpg",
        article_url="https://example.com/article", warnings=[], is_expired=False,
        sha256=None, perceptual_hash=None, final_url=None,
    )
    defaults.update(overrides)
    return EditorialImageCandidate(**defaults)  # type: ignore[arg-type]


def test_select_representative_media_returns_none_tier_for_empty_pool() -> None:
    plan = _select_representative_media([])
    assert plan.tier == "none"
    assert plan.representative is None


def test_select_representative_media_prefers_strong_editorial_image_over_branded_logo() -> None:
    """Phase H.1 §11 (bad media filter): mirrors the REAL Twitch/Amazon Story data (Phase G.2's
    own forensic finding) - a small, `possible_branded_screenshot`-flagged candidate (quality_score
    45, 128x128) versus a large, clean editorial photo (quality_score 98, 1200x799). The strong one
    must be selected - reuses the existing rank_media_candidates()/branding-risk policy unmodified,
    never a new media-ranking rule."""
    event_a, event_b = uuid.uuid4(), uuid.uuid4()
    logo_like = _image_candidate(
        candidate_id="logo-like", quality_score=45, relevance_score=41, width=128, height=128,
        image_format="GIF", warnings=["possible_branded_screenshot"], sha256="a" * 64,
    )
    strong_photo = _image_candidate(
        candidate_id="strong-photo", quality_score=98, relevance_score=67, width=1200, height=799,
        warnings=[], sha256="b" * 64,
    )

    plan = _select_representative_media([(event_a, logo_like), (event_b, strong_photo)])

    assert plan.tier == "story_pool"
    assert plan.representative is not None
    assert plan.representative.candidate_id == "strong-photo"
    assert plan.representative.originating_event_id == event_b


def test_select_representative_media_never_selects_two_copies_of_the_same_visual() -> None:
    """Phase H.1 §13 (duplicate media test): the exact same photo (identical sha256), discovered
    independently on TWO different confirmed Story events (e.g. syndicated by two outlets) - the
    pool contains both rows, but `SelectedMediaPlan.representative` is structurally a single item,
    never a list/album (Phase H.0/H.0.2's own "не увеличивать scope до album curation" scope),
    so only one of them can ever be selected - this proves the pool never yields two separate
    primary items for one underlying visual, without rewriting any dedup logic."""
    event_first, event_second = uuid.uuid4(), uuid.uuid4()
    same_sha = "c" * 64
    first_copy = _image_candidate(
        candidate_id="copy-1", quality_score=80, relevance_score=60, sha256=same_sha,
        perceptual_hash="0000000000000000",
    )
    second_copy = _image_candidate(
        candidate_id="copy-2", quality_score=80, relevance_score=60, sha256=same_sha,
        perceptual_hash="0000000000000000",
    )

    plan = _select_representative_media([(event_first, first_copy), (event_second, second_copy)])

    assert plan.tier == "story_pool"
    assert plan.representative is not None
    # Exactly one representative item exists at all (by construction - not a list) and it is the
    # first-seen copy: the second is flagged is_duplicate_within_event=True by _compute_duplicate_
    # flags() (same sha256, first-seen-wins), which rank_media_candidates() penalizes in its
    # composite score (never eligibility itself - `eligible_for_delivery` is independent of
    # is_duplicate_within_event, only story_reuse_match/quality_score/video-rejection gate it) -
    # the penalty alone is enough to rank the unpenalized first copy strictly higher.
    assert plan.representative.candidate_id == "copy-1"
