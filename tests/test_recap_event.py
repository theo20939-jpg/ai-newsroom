"""NINJA PULSE RECAP Phase R1 - offline fixture matrix (spec's own 8 named cases A-H) plus targeted
correctness tests for the async DB-touching pieces. Pure-function cases (A-H) build plain
NewsEvent objects directly in memory - deterministic, fake, fully offline (no DB, no network, no
LLM), per the spec's own explicit "tests themselves must remain deterministic/fake/offline"
instruction. The clustering similarity scores below are hand-verified against
`_announcement_similarity()`'s real 0.4/0.6 entity/title weighting and the 0.75 threshold - see the
inline `# sim=` comments at each event for the worked arithmetic."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.recap_event import (
    ACTIVE,
    COOLING,
    DISCOVERED,
    READY,
    _extract_numeric_tokens,
    _has_conflicting_distinctive_facts,
    build_recap_event_snapshot,
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    has_primary_source_unknown,
    load_story_events,
)
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    extract_story_signature,
)

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _event(
    *, title: str, url: str, minutes_ago: float, source_id: uuid.UUID | None = None
) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        title=title,
        category=EventCategory.TECH,
        url=url,
        published_at=_NOW - timedelta(minutes=minutes_ago),
        collected_at=_NOW - timedelta(minutes=minutes_ago),
        hash=f"h-{uuid.uuid4()}",
    )


# ---------------------------------------------------------------------------
# A. single article -> DISCOVERED / not ready
# ---------------------------------------------------------------------------


def test_case_a_single_article_is_discovered_and_not_ready():
    events = [
        _event(
            title="Apple unveils iPhone X",
            url="https://techcrunch.com/a",
            minutes_ago=5,
        )
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 1
    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[0].published_at,
        now=_NOW,
        research_complete=False,
        unresolved_conflict_count=0,
        story_integrity_eligible=True,
    )
    assert result.ready is False
    assert result.state == DISCOVERED


# ---------------------------------------------------------------------------
# B. three duplicate articles about one announcement -> one cluster, not ready
# ---------------------------------------------------------------------------


def test_case_b_three_duplicate_announcements_form_one_cluster_not_ready():
    events = [
        _event(
            title="OpenAI unveils new device",
            url="https://theverge.com/b1",
            minutes_ago=30,
        ),
        # sim vs anchor: entity jaccard=1.0 (both {"openai"}), token dice=2*3/(4+4)=0.75
        # -> combined = 0.4*1.0 + 0.6*0.75 = 0.85 >= 0.75 threshold => merges
        _event(
            title="OpenAI shows new device",
            url="https://techcrunch.com/b2",
            minutes_ago=25,
        ),
        _event(
            title="OpenAI reveals new device",
            url="https://engadget.com/b3",
            minutes_ago=20,
        ),
    ]
    clusters = cluster_announcements(events)
    assert len(clusters) == 1
    assert len(clusters[0].event_ids) == 3

    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[-1].published_at,
        now=_NOW,
        research_complete=False,
        unresolved_conflict_count=0,
        story_integrity_eligible=True,
    )
    assert result.ready is False
    assert any("announcement_count" in reason for reason in result.reasons)


# ---------------------------------------------------------------------------
# C/D/E/G share one 6-event, 4-announcement developing-launch fixture; only cooling/research/
# conflict signals differ. Clustering itself hand-verified inline (see B's comment style above).
# ---------------------------------------------------------------------------


def _developing_launch_events(*, last_minutes_ago: float) -> list[NewsEvent]:
    return [
        _event(
            title="Apple unveils iPhone X",
            url="https://techcrunch.com/c1",
            minutes_ago=last_minutes_ago + 50,
        ),
        # cluster2 anchor: entity jaccard=1.0, token dice=2*2/7=0.571 -> combined=0.4+0.343=0.743 < 0.75 => new cluster
        _event(
            title="Apple announces iPhone X pricing",
            url="https://theverge.com/c2",
            minutes_ago=last_minutes_ago + 40,
        ),
        # cluster3: distinct "Watch Ultra" topic, combined well below 0.75 vs both prior anchors => new cluster
        _event(
            title="Apple reveals Watch Ultra 3",
            url="https://engadget.com/c3",
            minutes_ago=last_minutes_ago + 30,
        ),
        # cluster4: distinct "Apple Intelligence" topic => new cluster
        _event(
            title="Apple introduces Apple Intelligence upgrade",
            url="https://arstechnica.com/c4",
            minutes_ago=last_minutes_ago + 20,
        ),
        # merges into cluster1: entity jaccard=1.0, token dice=2*2/6=0.667 -> combined=0.4+0.4=0.8 >= 0.75
        _event(
            title="Apple demos iPhone X",
            url="https://9to5mac.com/c5",
            minutes_ago=last_minutes_ago + 10,
        ),
        # merges into cluster2: entity jaccard=1.0, token dice=2*4/9=0.889 -> combined=0.4+0.533=0.933 >= 0.75
        _event(
            title="Apple announces iPhone X pricing details",
            url="https://macrumors.com/c6",
            minutes_ago=last_minutes_ago,
        ),
    ]


def test_case_c_developing_launch_is_active_before_cooling():
    events = _developing_launch_events(
        last_minutes_ago=5
    )  # freshest event 5 minutes ago - well inside cooling window
    clusters = cluster_announcements(events)
    assert (
        len(clusters) == 4
    )  # exactly the 4 distinct announcements, despite 6 total events
    assert len(events) == 6

    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[-1].published_at,
        now=_NOW,
        research_complete=False,
        unresolved_conflict_count=0,
        story_integrity_eligible=True,
    )
    assert result.ready is False
    assert result.state == ACTIVE


def test_case_d_cooled_with_research_complete_is_ready():
    events = _developing_launch_events(
        last_minutes_ago=120
    )  # freshest event 120 minutes ago - past the 90m cooling window
    clusters = cluster_announcements(events)

    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[-1].published_at,
        now=_NOW,
        research_complete=True,
        unresolved_conflict_count=0,
        story_integrity_eligible=True,
    )
    assert result.ready is True
    assert result.state == READY


def test_two_to_three_announcement_clusters_remain_not_ready_under_the_raised_default():
    """Phase R1.1: recap_min_announcement_count was raised 2 -> 4 (spec's own "two distinct
    announcements are insufficient maturity" correction) - a cooled, research-complete story with
    only 3 announcement clusters must now fail the readiness gate on that basis alone, where it
    would have passed under R1's original default of 2."""
    from core.config import settings

    assert (
        settings.recap_min_announcement_count == 4
    )  # the new default itself, not hardcoded here

    events = [
        _event(
            title="Apple unveils iPhone X",
            url="https://techcrunch.com/t1",
            minutes_ago=140,
        ),
        _event(
            title="Apple announces iPhone X pricing",
            url="https://theverge.com/t2",
            minutes_ago=130,
        ),
        _event(
            title="Apple reveals Watch Ultra 3",
            url="https://engadget.com/t3",
            minutes_ago=120,
        ),
    ]
    clusters = cluster_announcements(events)
    assert (
        len(clusters) == 3
    )  # three genuinely distinct announcements - would have passed the old min=2

    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[-1].published_at,
        now=_NOW,
        research_complete=True,
        unresolved_conflict_count=0,
        story_integrity_eligible=True,
    )
    assert result.ready is False
    assert any("announcement_count" in reason for reason in result.reasons)


def test_case_e_unresolved_conflict_blocks_readiness():
    events = _developing_launch_events(last_minutes_ago=120)
    clusters = cluster_announcements(events)

    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[-1].published_at,
        now=_NOW,
        research_complete=True,
        unresolved_conflict_count=1,
        story_integrity_eligible=True,
    )
    assert result.ready is False
    assert (
        result.state == COOLING
    )  # cooled, but still gated - not the still-developing ACTIVE state
    assert any("unresolved" in reason for reason in result.reasons)


def test_case_g_long_running_story_produces_multiple_clusters():
    events = _developing_launch_events(last_minutes_ago=5)
    clusters = cluster_announcements(events)
    assert len(clusters) >= 3  # genuinely different developments, not one blob
    headlines = {c.headline for c in clusters}
    assert len(headlines) == len(
        clusters
    )  # every cluster keeps its own distinct anchor headline


# ---------------------------------------------------------------------------
# F. many duplicate/supporting-source events must NOT falsely inflate announcement_count
# ---------------------------------------------------------------------------


def test_case_f_high_event_count_does_not_inflate_announcement_count():
    events = [
        _event(
            title="Google launches Gemini update",
            url="https://techcrunch.com/f1",
            minutes_ago=60,
        ),
        _event(
            title="Google unveils Gemini update",
            url="https://theverge.com/f2",
            minutes_ago=50,
        ),
        _event(
            title="Google reveals Gemini update",
            url="https://engadget.com/f3",
            minutes_ago=40,
        ),
        _event(
            title="Google shows Gemini update",
            url="https://arstechnica.com/f4",
            minutes_ago=30,
        ),
        _event(
            title="Google announces Gemini update",
            url="https://9to5google.com/f5",
            minutes_ago=20,
        ),
        _event(
            title="Google demos Gemini update",
            url="https://macrumors.com/f6",
            minutes_ago=10,
        ),
    ]
    clusters = cluster_announcements(events)
    assert len(events) == 6
    assert (
        len(clusters) <= 2
    )  # near-duplicate coverage of one announcement, not six distinct developments


# ---------------------------------------------------------------------------
# H. weak/noisy story -> not recap-ready
# ---------------------------------------------------------------------------


def test_case_h_weak_noisy_story_is_not_recap_ready():
    events = [
        _event(
            title="Startup teases mystery product",
            url="https://obscureblog.example/h1",
            minutes_ago=10,
        ),
        _event(
            title="Startup teases mystery product",
            url="https://obscureblog.example/h1b",
            minutes_ago=5,
        ),
    ]
    clusters = cluster_announcements(events)
    result = evaluate_recap_readiness(
        event_count=len(events),
        announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events),
        last_event_at=events[-1].published_at,
        now=_NOW,
        research_complete=False,
        unresolved_conflict_count=0,
        story_integrity_eligible=True,
    )
    assert result.ready is False
    assert result.state == DISCOVERED


# ---------------------------------------------------------------------------
# Source counting / primary-source signal
# ---------------------------------------------------------------------------


def test_unique_source_count_dedupes_by_normalized_domain():
    events = [
        _event(title="A", url="https://www.techcrunch.com/x", minutes_ago=1),
        _event(
            title="B", url="https://techcrunch.com/y", minutes_ago=2
        ),  # same domain, www. stripped
        _event(title="C", url="https://theverge.com/z", minutes_ago=3),
    ]
    assert count_unique_sources(events) == 2


def test_unique_source_count_falls_back_to_source_id_when_url_missing():
    source_a, source_b = uuid.uuid4(), uuid.uuid4()
    events = [
        _event(title="A", url=None, minutes_ago=1, source_id=source_a),
        _event(title="B", url=None, minutes_ago=2, source_id=source_a),
        _event(title="C", url=None, minutes_ago=3, source_id=source_b),
    ]
    assert count_unique_sources(events) == 2


def test_has_primary_source_is_always_unknown_in_r1():
    assert has_primary_source_unknown() is None


# ---------------------------------------------------------------------------
# load_story_events() - the confirmed-membership match_type filter (real forensic finding)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_story_events_excludes_related_and_uncertain_matches(db_session):
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(
        name="Test",
        type=SourceType.RSS,
        url="https://example.com/feed.xml",
        active=True,
    )
    db_session.add(source)
    await db_session.flush()

    def make_event(title: str) -> NewsEvent:
        e = NewsEvent(
            source_id=source.id,
            title=title,
            category=EventCategory.TECH,
            url="https://example.com/" + title,
            hash=f"h-{uuid.uuid4()}",
        )
        db_session.add(e)
        return e

    origin = make_event("Origin event")
    confirmed_update = make_event("Confirmed update event")
    confirmed_duplicate = make_event("Confirmed duplicate event")
    related = make_event("Related but different event")
    uncertain = make_event("Uncertain match event")
    await db_session.flush()

    story = Story(
        title=origin.title,
        category=EventCategory.TECH,
        entities=[],
        keywords=[],
        topic_bucket="other",
        first_event_id=origin.id,
        event_count=3,
    )
    db_session.add(story)
    await db_session.flush()

    db_session.add_all(
        [
            NewsEventStoryLink(
                news_event_id=origin.id,
                story_id=story.id,
                match_type=NEW_STORY,
                match_score=1.0,
            ),
            NewsEventStoryLink(
                news_event_id=confirmed_update.id,
                story_id=story.id,
                match_type=STORY_UPDATE,
                match_score=0.8,
            ),
            NewsEventStoryLink(
                news_event_id=confirmed_duplicate.id,
                story_id=story.id,
                match_type=SUPPORTING_SOURCE,
                match_score=0.7,
            ),
            NewsEventStoryLink(
                news_event_id=related.id,
                story_id=story.id,
                match_type=RELATED_STORY,
                match_score=0.3,
            ),
            NewsEventStoryLink(
                news_event_id=uncertain.id,
                story_id=story.id,
                match_type=UNCERTAIN_MATCH,
                match_score=0.5,
            ),
        ]
    )
    await db_session.flush()

    loaded = await load_story_events(db_session, story.id)
    loaded_ids = {e.id for e in loaded}

    assert loaded_ids == {origin.id, confirmed_update.id, confirmed_duplicate.id}
    assert related.id not in loaded_ids
    assert uncertain.id not in loaded_ids


@pytest.mark.asyncio
async def test_build_recap_event_snapshot_end_to_end(db_session):
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(
        name="Test",
        type=SourceType.RSS,
        url="https://example.com/feed.xml",
        active=True,
    )
    db_session.add(source)
    await db_session.flush()

    origin = NewsEvent(
        source_id=source.id,
        title="Apple unveils iPhone X",
        category=EventCategory.TECH,
        url="https://techcrunch.com/e1",
        hash=f"h-{uuid.uuid4()}",
    )
    db_session.add(origin)
    await db_session.flush()

    story = Story(
        title=origin.title,
        category=EventCategory.TECH,
        entities=["apple"],
        keywords=[],
        topic_bucket="product",
        first_event_id=origin.id,
        event_count=1,
    )
    db_session.add(story)
    await db_session.flush()

    db_session.add(
        NewsEventStoryLink(
            news_event_id=origin.id,
            story_id=story.id,
            match_type=NEW_STORY,
            match_score=1.0,
        )
    )
    await db_session.flush()

    snapshot = await build_recap_event_snapshot(db_session, story, now=_NOW)
    assert snapshot.story_id == story.id
    assert snapshot.event_count == 1
    assert snapshot.state == DISCOVERED
    assert snapshot.has_primary_source is None


@pytest.mark.asyncio
async def test_build_recap_event_snapshot_fails_closed_when_declared_anchor_missing_from_confirmed_members(db_session):
    """Phase R1.5A.2 item 14/L: real production forensic finding - a Story's declared
    `first_event_id` can point to an event whose own link row never reached confirmed-membership
    status (e.g. still UNCERTAIN_MATCH), while OTHER events are confirmed members. The old contract
    silently substituted `events[0]` (the chronologically-earliest CONFIRMED member) as a stand-in
    anchor and ran full integrity evaluation against it - letting a Story become "eligible" without
    ever verifying its own true declared origin. Fixed to fail closed: `story_integrity_eligible`
    must be False, with no substitute anchor ever chosen, whenever the declared anchor is absent from
    confirmed membership."""
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name="Test", type=SourceType.RSS, url="https://example.com/feed2.xml", active=True)
    db_session.add(source)
    await db_session.flush()

    missing_anchor = NewsEvent(
        source_id=source.id, title="Original story-originating article",
        category=EventCategory.TECH, url="https://example.com/original", hash=f"h-{uuid.uuid4()}",
    )
    confirmed_a = NewsEvent(
        source_id=source.id, title="Follow-up coverage of the same story",
        category=EventCategory.TECH, url="https://example.com/followup-a", hash=f"h-{uuid.uuid4()}",
    )
    confirmed_b = NewsEvent(
        source_id=source.id, title="More follow-up coverage of the same story",
        category=EventCategory.TECH, url="https://example.com/followup-b", hash=f"h-{uuid.uuid4()}",
    )
    db_session.add_all([missing_anchor, confirmed_a, confirmed_b])
    await db_session.flush()

    story = Story(
        title=missing_anchor.title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="product", first_event_id=missing_anchor.id, event_count=3,
    )
    db_session.add(story)
    await db_session.flush()

    db_session.add_all([
        NewsEventStoryLink(
            news_event_id=missing_anchor.id, story_id=story.id, match_type=UNCERTAIN_MATCH, match_score=0.4,
        ),
        NewsEventStoryLink(
            news_event_id=confirmed_a.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.9,
        ),
        NewsEventStoryLink(
            news_event_id=confirmed_b.id, story_id=story.id, match_type=SUPPORTING_SOURCE, match_score=0.85,
        ),
    ])
    await db_session.flush()

    snapshot = await build_recap_event_snapshot(db_session, story, now=_NOW, research_complete=True)
    assert snapshot.story_integrity_eligible is False
    assert any("first_event_id" in r and "confirmed" in r for r in snapshot.story_integrity_reasons)
    assert snapshot.state != READY


# ---------------------------------------------------------------------------
# Phase R1.3 §2/§13: Story.event_count vs actual confirmed-member count (real R1.2 mismatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_declared_event_count_does_not_override_actual_confirmed_member_count(db_session):
    """R1.2 production replay found repeated real mismatches (6->5, 11->10, 8->7, 5->4, 4->3)
    between Story.event_count and the actual confirmed-member NewsEventStoryLink count. This proves
    the fix directly: a Story whose OWN declared event_count says 8 but which only has 4 real
    confirmed-member links must report event_count=4 (the authoritative signal), never 8 - and
    Story.event_count is never written to or repaired."""
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name="Test", type=SourceType.RSS, url="https://example.com/feed.xml", active=True)
    db_session.add(source)
    await db_session.flush()

    origin = NewsEvent(
        source_id=source.id, title="Apple unveils iPhone X", category=EventCategory.TECH,
        url="https://techcrunch.com/mismatch1", hash=f"h-{uuid.uuid4()}",
    )
    db_session.add(origin)
    await db_session.flush()

    # Story.event_count is deliberately set to 8 (a stale/inflated declared value) even though only
    # 4 confirmed-member NewsEventStoryLink rows will actually be created below - reproducing the
    # exact real mismatch shape R1.2 found in production.
    story = Story(
        title=origin.title, category=EventCategory.TECH, entities=["apple"], keywords=[],
        topic_bucket="product", first_event_id=origin.id, event_count=8,
    )
    db_session.add(story)
    await db_session.flush()

    confirmed_titles = [
        "Apple unveils iPhone X",
        "Apple announces iPhone X pricing",
        "Apple demos iPhone X",
        "Apple confirms iPhone X pricing details",
    ]
    events = [origin]
    for title in confirmed_titles[1:]:
        e = NewsEvent(
            source_id=source.id, title=title, category=EventCategory.TECH,
            url=f"https://example.com/{uuid.uuid4()}", hash=f"h-{uuid.uuid4()}",
        )
        db_session.add(e)
        events.append(e)
    await db_session.flush()

    db_session.add_all([
        NewsEventStoryLink(news_event_id=events[0].id, story_id=story.id, match_type=NEW_STORY, match_score=1.0),
        NewsEventStoryLink(news_event_id=events[1].id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.8),
        NewsEventStoryLink(news_event_id=events[2].id, story_id=story.id, match_type=SUPPORTING_SOURCE, match_score=0.7),
        NewsEventStoryLink(news_event_id=events[3].id, story_id=story.id, match_type=SEMANTIC_DUPLICATE, match_score=0.9),
    ])
    await db_session.flush()

    snapshot = await build_recap_event_snapshot(db_session, story, now=_NOW, research_complete=True)

    assert story.event_count == 8  # never repaired/mutated in the DB
    assert snapshot.declared_event_count == 8  # diagnostic-only, verbatim copy
    assert snapshot.event_count == 4  # the authoritative recap metric - confirmed-member count only


# ---------------------------------------------------------------------------
# Phase R1.3 §12: readiness is unconditionally gated by story_integrity_eligible
# ---------------------------------------------------------------------------


def test_readiness_never_ready_when_story_integrity_ineligible():
    events = _developing_launch_events(last_minutes_ago=120)
    clusters = cluster_announcements(events)

    result = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events), last_event_at=events[-1].published_at,
        now=_NOW, research_complete=True, unresolved_conflict_count=0,
        story_integrity_eligible=False, story_integrity_reasons=["anchor_coherent_ratio 0.00 < required 0.5"],
    )
    assert result.ready is False
    assert result.state != READY
    assert any("anchor_coherent_ratio" in reason for reason in result.reasons)


# ---------------------------------------------------------------------------
# Phase R1.4 §15 (mandatory): 4 publications of ONE announcement must never satisfy
# recap_min_announcement_count - the central safety property this checkpoint establishes.
# ---------------------------------------------------------------------------


def test_four_publications_of_one_announcement_pass_integrity_but_fail_announcement_count():
    """Integrity PASS (these 4 events plausibly describe one real-world announcement) must NOT be
    conflated with announcement maturity: 4 real publications of the SAME Taiwan dividend
    announcement must never reach recap_min_announcement_count=4 clusters, so READY must be False.
    This is the exact safety property that stops "many duplicate reports" from masquerading as
    "many distinct developments."

    Phase R1.4.2: the corrected, safe clustering algorithm (temporal distinctive evidence
    restricted to the cluster's stable reference - spec §6's mandatory anti-chain fix) produces 2
    clusters for these exact real titles, not the 1 an earlier, less conservative design produced
    (see tests/test_recap_announcement_identity.py::
    test_case_d_four_taiwan_dividend_variants_safely_split_not_forced_merge for the full,
    disclosed real-number explanation) - this test asserts the actual SAFETY PROPERTY (announcement
    maturity stays well below the readiness floor), not a specific cluster count, so it remains
    valid regardless of exactly how many clusters the safe algorithm produces for this fixture."""
    from core.config import settings

    assert settings.recap_min_announcement_count == 4

    events = [
        _event(title="Taiwan will pay every citizen about $314 as part of new AI dividend", url="https://a.example/1", minutes_ago=6),
        _event(title="Taiwan will pay every citizen $314 under new AI dividend program", url="https://b.example/2", minutes_ago=4),
        _event(title="Taiwan to pay all citizens dividends worth $314 from AI fund", url="https://c.example/3", minutes_ago=2),
        _event(title="Taiwan approves $314 AI dividend payment for every citizen", url="https://d.example/4", minutes_ago=0),
    ]

    integrity = evaluate_recap_story_integrity(events[0], events)
    assert integrity.eligible is True

    clusters = cluster_announcements(events)
    assert len(clusters) < settings.recap_min_announcement_count  # duplicate coverage of ONE announcement, never enough distinct clusters

    result = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events), last_event_at=events[-1].published_at,
        now=_NOW, research_complete=True, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )
    assert result.ready is False
    assert any("announcement_count" in reason for reason in result.reasons)


def test_four_publisher_suffixed_reports_of_one_taiwan_announcement_do_not_inflate_announcement_count():
    """Phase R1.5B.1 §19: the exact safety property publisher-suffix sanitization must preserve -
    multiple source reports of ONE real announcement must not inflate announcement_count to >=4
    merely because each publisher (Ведомости/Хабр/Эксперт/CNews.ru) appears as a different
    extracted entity. Real production Taiwan titles, verbatim (from the R1.5B.1 checkpoint
    message) - 3 of the 4 collapse into one cluster once publisher noise is removed, the 4th stays
    separate on its own genuine merits (materially weaker overlap, omits the $314 figure) - well
    below the recap_min_announcement_count=4 floor either way."""
    from core.config import settings

    assert settings.recap_min_announcement_count == 4

    events = [
        _event(
            title="Тайвань выплатит каждому гражданину страны около $314 «дивидендов от ИИ» - Ведомости",
            url="https://a.example/1", minutes_ago=300,
        ),
        _event(
            title="Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
            url="https://b.example/2", minutes_ago=225,
        ),
        _event(
            title="Тайвань выплатит каждому гражданину «дивиденды от ИИ» в $314 - Эксперт",
            url="https://c.example/3", minutes_ago=105,
        ),
        _event(
            title="Тайвань выплатит всем своим гражданам «дивиденды» от мирового бума ИИ - CNews.ru",
            url="https://d.example/4", minutes_ago=0,
        ),
    ]

    integrity = evaluate_recap_story_integrity(events[0], events)

    clusters = cluster_announcements(events)
    assert len(clusters) < settings.recap_min_announcement_count

    result = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events), last_event_at=events[-1].published_at,
        now=_NOW, research_complete=True, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )
    assert any("announcement_count" in reason for reason in result.reasons)


def test_four_genuine_announcements_in_one_live_event_produce_announcement_count_four():
    """Phase R1.4.1 §14 (mandatory): the anti-chaining fix must not collapse legitimate recap
    structure - a real developing launch with 4 genuinely distinct announcements (unveil, pricing,
    availability, a second product) must still pass integrity AND produce announcement_count=4,
    clearing recap_min_announcement_count=4. Cooling/research may still independently gate READY -
    this fixture keeps research_complete=True and events far enough in the past to isolate the
    announcement-count safety property specifically."""
    from core.config import settings

    assert settings.recap_min_announcement_count == 4

    events = [
        _event(title="Apple unveils Product X", url="https://a.example/1", minutes_ago=100),
        _event(title="Apple announces Product X price $999", url="https://b.example/2", minutes_ago=97),
        _event(title="Apple announces Product X availability September 18", url="https://c.example/3", minutes_ago=94),
        _event(title="Apple unveils Watch Y", url="https://d.example/4", minutes_ago=91),
    ]

    integrity = evaluate_recap_story_integrity(events[0], events)
    assert integrity.eligible is True

    clusters = cluster_announcements(events)
    assert len(clusters) == 4  # 4 genuinely separate announcements, not collapsed

    result = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters),
        unique_source_count=count_unique_sources(events), last_event_at=events[-1].published_at,
        now=_NOW, research_complete=True, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )
    assert not any("announcement_count" in reason for reason in result.reasons)


# ---------------------------------------------------------------------------
# R2.10G3-0: _extract_numeric_tokens() decimal-comma bug (real forensic finding, R2.11
# announcement-identity checkpoint, re-verified live against this exact unmodified function before
# this phase's own fix). Blindly stripping every comma treats a Russian-locale decimal comma
# identically to English thousands-grouping - "$12,2 млрд" (twelve-point-two) and "$12.2 billion"
# (the same real figure) produced two DIFFERENT numeric-identity strings ("122" vs "12.2"),
# registering a spurious conflict in _has_conflicting_distinctive_facts() for two reports of the
# exact same number. services/event_recap.py::_normalize_numeric_token() already solved this
# correctly (Phase R2.10 Night 2) - this test matrix pins the SAME contract now applied locally
# inside services/recap_event.py (duplicated, not imported - a real circular-import constraint:
# services/event_recap.py already imports FROM services/recap_event.py, so the reverse import is
# not possible; this mirrors this codebase's own established per-module-private-helper convention,
# e.g. _normalize_domain() being duplicated between the same two files for the same reason).
# ---------------------------------------------------------------------------


def test_dot_decimal_unchanged() -> None:
    """Test A."""
    assert _extract_numeric_tokens("Deal valued at $12.2 billion") == {"12.2"}


def test_comma_decimal_normalizes_to_dot() -> None:
    """Test B."""
    assert _extract_numeric_tokens("Сделка на $12,2 млрд") == {"12.2"}


def test_dot_and_comma_decimal_are_the_same_identity() -> None:
    """Test C."""
    assert _extract_numeric_tokens("$12.2 billion") == _extract_numeric_tokens("$12,2 млрд") == {"12.2"}


def test_different_decimal_values_remain_distinct() -> None:
    """Test D."""
    assert _extract_numeric_tokens("$12.2 billion") != _extract_numeric_tokens("$12.3 billion")
    assert _extract_numeric_tokens("$12,2 млрд") != _extract_numeric_tokens("$12,3 млрд")


def test_integer_vs_decimal_remain_distinct() -> None:
    """Test E: the historical bug's own signature - "12,2" must never collapse to bare "122"."""
    assert _extract_numeric_tokens("$12,2 млрд") != {"122"}
    assert "122" not in _extract_numeric_tokens("$12,2 млрд")


def test_marvell_en_ru_pair_no_longer_falsely_conflicts() -> None:
    """Test F: the exact real R2.11 fixture. Real production titles - EN and RU reports of the
    identical $12.2B figure must no longer register as a numeric conflict once notation-only
    differences are normalized away. Only the numeric-notation artifact is exercised here (both
    titles carry the identical distinctive entity "Google"/"Marvell" via extract_story_signature,
    with no other asymmetric entity introduced) - isolating the fix's own effect from the entity
    check that _has_conflicting_distinctive_facts() ALSO performs."""
    title_en = "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC"
    title_ru = "Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на сумму $12,2 млрд"
    en_tokens = _extract_numeric_tokens(title_en)
    ru_tokens = _extract_numeric_tokens(title_ru)
    assert "12.2" in en_tokens and "12.2" in ru_tokens, (
        f"expected the same real $12.2B figure on both sides, got EN={en_tokens} RU={ru_tokens}"
    )
    assert "122" not in ru_tokens, "the historical bug's own signature must not reappear"


def test_58m_shares_vs_12_2b_still_conflicts() -> None:
    """Test G: the fix must not turn every numeric fact into an equivalence class - a genuinely
    different distinguishing number (58 vs 12.2) must still register as a real conflict."""
    sig_a = extract_story_signature(
        "Marvell and Google expand their chip development deal, with Marvell granting Google a warrant to buy up to 58M+ shares",
        EventCategory.TECH,
    )
    sig_b = extract_story_signature(
        "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC",
        EventCategory.TECH,
    )
    assert _has_conflicting_distinctive_facts(
        sig_a, "Marvell and Google expand their chip development deal, with Marvell granting Google a warrant to buy up to 58M+ shares",
        sig_b, "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC",
    ) is True


def test_vk_apple_conflict_result_unchanged_by_numeric_fix() -> None:
    """Test H: the VK/Apple R2.11 fixture has no numbers on either side at all - this fix must not
    change its outcome, since that risk (verb/action blindness) is explicitly a SEPARATE, still-
    unresolved defect this phase does not touch."""
    a = "VK подала в суд на Apple и потребовала вернуть свои приложения в App Store"
    b = "VK подала иск против Apple в российский суд из-за удаления её приложений из App Store"
    sig_a, sig_b = extract_story_signature(a, EventCategory.TECH), extract_story_signature(b, EventCategory.TECH)
    assert _extract_numeric_tokens(a) == _extract_numeric_tokens(b) == set()
    assert _has_conflicting_distinctive_facts(sig_a, a, sig_b, b) is False


def test_apple_sues_settles_samsung_still_shows_no_conflict() -> None:
    """Critical product invariant (must remain true after this fix - R2.11's own adversarial
    fixture): _has_conflicting_distinctive_facts() still cannot distinguish "sues" from "settles"
    for the identical two entities with zero numbers on either side. This fix corrects numeric
    notation only - it does not and cannot solve verb/action blindness. Documented here as a
    regression guard against anyone mistaking this fix for a solution to that separate, still-open
    R2.11 finding."""
    a = "Apple sues Samsung over patent infringement claims"
    b = "Apple settles patent dispute with Samsung amicably"
    sig_a, sig_b = extract_story_signature(a, EventCategory.TECH), extract_story_signature(b, EventCategory.TECH)
    assert _has_conflicting_distinctive_facts(sig_a, a, sig_b, b) is False
    assert set(sig_a.entities) == set(sig_b.entities)


def test_numeric_token_extraction_is_deterministic() -> None:
    """Test I."""
    title = "Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC"
    assert _extract_numeric_tokens(title) == _extract_numeric_tokens(title)


def test_thousands_grouping_still_stripped_not_treated_as_decimal() -> None:
    """§10/§11: a lone comma followed by exactly 3 digits is conventional thousands grouping, not
    a decimal separator - "$1,299" must normalize to "1299", never "1.299". Mirrors services/
    event_recap.py::_normalize_numeric_token()'s own documented contract exactly."""
    assert _extract_numeric_tokens("Priced at $1,299 for the base model") == {"1299"}


def test_us_thousands_then_decimal_and_eu_thousands_then_decimal_both_handled() -> None:
    """§10: "1,234.56" (US: thousands-comma, decimal-dot) and "1.234,56" (EU: thousands-dot,
    decimal-comma) - whichever separator occurs LAST is the decimal separator, mirroring
    services/event_recap.py::_normalize_numeric_token()'s own documented contract exactly."""
    assert _extract_numeric_tokens("Revenue of $1,234.56 million reported") == {"1234.56"}
    assert _extract_numeric_tokens("Выручка составила $1.234,56 млн") == {"1234.56"}
