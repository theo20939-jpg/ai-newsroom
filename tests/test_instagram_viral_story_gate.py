"""VIRAL STORY STRENGTH + ACTUALITY gate (founder task 2026-09-26): the viral slot takes a story that is already strong and current - it
never picks the best of a weak batch. Fixtures describe CHARACTERISTICS (a DeepSeek-like AI hack, a Hamster-like absurd tracker, a
GTA-like niche mod), never a story-specific blacklist. Deterministic - no provider call."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.instagram_feed_product import FeedCandidate, FeedFormat, FeedRead, plan_daily_slots
from services.instagram_viral_nomination import nominate_viral_events, nominated_reads
from services.instagram_viral_story_gate import (
    ClusterMember,
    assess_actuality,
    assess_viral_story,
    best_viral_story,
    cluster_signals,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _candidate(title: str, summary: str = "", *, id: str = "c", source: str = "Example Tech", hours_old: float = 2,
               **signals) -> FeedCandidate:
    return FeedCandidate(id=id, title=title, summary=summary, source_name=source, source_type="RSS",
                         published_at=NOW - timedelta(hours=hours_old), **signals)


DEEPSEEK_LIKE = _candidate(
    "AI agent built on DeepSeek hacked 460 servers with zero human operators",
    "Security researchers published the analysis on 25 September: the bot scanned, exploited and reported on its own.", id="deepseek")
HAMSTER_LIKE = _candidate(
    "Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night",
    "He built a speed and distance tracker for the wheel. One recent activity showed 6.06 miles in 4 hours and 37 minutes.",
    id="hamster", source="Hacker News Front Page", on_hacker_news=True)
GTA_LIKE = _candidate(
    "Спустя 18 лет моддер реализовал в GTA IV полноценное сглаживание",
    "Мод добавляет DLSS и DLAA, для работы нужен Fusion Fix. Автор выложил сборку на GitHub.", id="gta", source="3DNews")


def test_deepseek_like_fixture_stays_strong_with_a_single_source():
    verdict = assess_viral_story(DEEPSEEK_LIKE, now=NOW)
    assert verdict.strength == "STRONG" and verdict.broad_interest == "BROAD"
    assert verdict.actuality.status == "CURRENT" and verdict.momentum == "NONE"
    assert verdict.eligible, verdict.reason  # one source is enough for an exceptionally strong, explicitly current event


def test_hamster_like_fixture_stays_strong():
    verdict = assess_viral_story(HAMSTER_LIKE, now=NOW)
    assert verdict.strength == "STRONG"
    assert {"absurd_measurable_outcome", "unlikely_pairing"} <= set(verdict.mechanisms)
    assert verdict.eligible, verdict.reason


def test_gta_like_niche_mod_does_not_win_even_with_momentum():
    quiet = assess_viral_story(GTA_LIKE, now=NOW)
    loud = assess_viral_story(_candidate(GTA_LIKE.title, GTA_LIKE.summary, independent_sources=9, story_events_24h=12,
                                         on_hacker_news=True, forwards=500), now=NOW)
    assert quiet.kage_core  # KAGE-relevant gaming technology ...
    assert quiet.good_kage_news  # ... and usable as ordinary news
    for verdict in (quiet, loud):
        assert not verdict.eligible and verdict.failed_gate == "3_broad_interest"
    assert best_viral_story([(GTA_LIKE, quiet)]) is None


def test_recent_but_weak_story_does_not_qualify():
    verdict = assess_viral_story(_candidate("Samsung adds a new battery toggle to its Settings app", "The option rolls out today.",
                                            hours_old=0.5), now=NOW)
    assert verdict.actuality.status == "CURRENT"
    assert not verdict.eligible and verdict.failed_gate == "4_inherent_virality"


def test_strong_tech_relevance_alone_does_not_qualify():
    verdict = assess_viral_story(_candidate("OpenAI releases a new ChatGPT model for enterprise customers",
                                            "The model is available today in the business plan."), now=NOW)
    assert verdict.kage_core and verdict.broad_interest == "BROAD"
    assert not verdict.eligible and verdict.failed_gate == "4_inherent_virality"


def test_viral_terminology_alone_does_not_qualify():
    verdict = assess_viral_story(_candidate("ChatGPT meme goes viral as TikTok users share the trend",
                                            "The internet reacts: users noticed the brainrot clip and it became a meme today."), now=NOW)
    assert not verdict.eligible
    assert verdict.failed_gate in ("1_kage_relevance", "3_broad_interest", "4_inherent_virality")
    assert "viral" not in verdict.hook.lower() and "meme" not in verdict.hook.lower()  # the hook is judged without distribution words


def test_niche_subject_fails_broad_interest_for_a_tech_story():
    verdict = assess_viral_story(_candidate("Nvidia driver v580.12 fixes a DLSS bug in three games",
                                            "The hotfix ships today for GeForce cards."), now=NOW)
    assert verdict.kage_core  # clearly KAGE tech ...
    assert not verdict.eligible and verdict.failed_gate == "3_broad_interest"  # ... but a reader must already follow the niche


def test_strong_inherent_event_qualifies_with_one_source():
    verdict = assess_viral_story(_candidate("AI coding agent deleted a company's production database, then lied about it",
                                            "The incident happened yesterday; the founder posted the logs."), now=NOW)
    assert verdict.strength == "STRONG" and verdict.momentum == "NONE"
    assert verdict.eligible, verdict.reason


def test_momentum_strengthens_but_cannot_rescue_a_moderate_story():
    moderate = _candidate("Codex suffers a full outage", "Developers could not use the service today.", independent_sources=8,
                          story_events_24h=10, on_hacker_news=True)
    verdict = assess_viral_story(moderate, now=NOW)
    assert verdict.momentum == "STRONG" and verdict.strength == "MODERATE"
    assert not verdict.eligible and verdict.failed_gate == "4_inherent_virality"
    assert verdict.good_kage_news

    # between two strong stories, momentum decides the order
    quiet = _candidate(DEEPSEEK_LIKE.title, DEEPSEEK_LIKE.summary, id="quiet")
    loud = _candidate(DEEPSEEK_LIKE.title, DEEPSEEK_LIKE.summary, id="loud", independent_sources=6, on_hacker_news=True)
    pairs = [(c, assess_viral_story(c, now=NOW)) for c in (quiet, loud)]
    assert all(v.eligible for _c, v in pairs)
    assert best_viral_story(pairs)[0].id == "loud"


def test_strong_but_undated_single_source_needs_corroboration():
    undated = _candidate("AI chatbot hacked a hospital database and deleted patient files", "Staff discovered the damage.")
    alone = assess_viral_story(undated, now=NOW)
    assert alone.actuality.status == "UNCERTAIN"  # the article timestamp is not the event's
    assert not alone.eligible and alone.failed_gate == "5_momentum"
    corroborated = _candidate(undated.title, undated.summary, independent_sources=3, story_first_seen=NOW - timedelta(hours=10))
    assert assess_viral_story(corroborated, now=NOW).eligible


def test_fresh_article_about_an_old_event_is_rejected():
    resurfaced = assess_viral_story(_candidate("AI robot that escaped its lab resurfaces online",
                                               "The old video from 3 years ago shows the robot rolling out of the building."), now=NOW)
    old_cluster = assess_viral_story(_candidate(DEEPSEEK_LIKE.title, "A new article on the hack.", story_first_seen=NOW - timedelta(days=30)),
                                     now=NOW)
    stale = assess_viral_story(_candidate(DEEPSEEK_LIKE.title, "Researchers published the analysis on 20 September.",
                                          independent_sources=6), now=NOW)
    assert resurfaced.failed_gate == "2_event_actuality" and resurfaced.actuality.status == "OLD"
    assert old_cluster.failed_gate == "2_event_actuality"
    # 6 days old: not current, and momentum does not lift it back - still good KAGE news
    assert stale.actuality.status == "RECENT" and stale.failed_gate == "2_event_actuality" and stale.good_kage_news


def test_article_time_is_never_assumed_to_be_event_time():
    actuality = assess_actuality("Robot vacuum maps a house", "", published_at=NOW - timedelta(minutes=5), story_first_seen=None,
                                 independent_sources=1, now=NOW)
    assert actuality.status == "UNCERTAIN"


def test_creator_content_without_a_tech_core_fails_relevance():
    verdict = assess_viral_story(_candidate("Famous streamer's birthday stream becomes a meme",
                                            "Fans clipped the moment and it went viral on YouTube."), now=NOW)
    assert not verdict.eligible and verdict.failed_gate == "1_kage_relevance"


def test_empty_viral_slot_is_valid():
    weak = [_candidate("Codex suffers a full outage", "Developers could not use the service today.", id="a"), GTA_LIKE]
    assert best_viral_story([(c, assess_viral_story(c, now=NOW)) for c in weak]) is None
    read = FeedRead(format=FeedFormat.MEME_TREND, strong=True, kinds=("oddity",), reason="", rank=1.0)
    # a strong legacy MEME_TREND read is no fallback: only nominated events feed the viral slot
    nominated = nominated_reads(nominate_viral_events(weak, now=NOW), 3)
    plans = plan_daily_slots([(c, read) for c in weak], viral_nominations=nominated)
    assert nominated == [] and all(plan.format is not FeedFormat.MEME_TREND for plan in plans)  # no best-of-a-weak-batch
    nominated = nominated_reads(nominate_viral_events([HAMSTER_LIKE, *weak], now=NOW), 3)
    plans = plan_daily_slots([(c, read) for c in weak], viral_nominations=nominated)
    [viral] = [plan for plan in plans if plan.format is FeedFormat.MEME_TREND]
    assert [c.id for c, _r in viral.shortlist] == ["hamster"]


def test_cluster_signals_count_outlets_of_this_event_only():
    def member(title: str, source: str, hours: float) -> ClusterMember:
        return ClusterMember(title=title, source_id=source, source_name=source, seen_at=NOW - timedelta(hours=hours),
                             collected_at=NOW - timedelta(hours=hours))

    event = "Rogue AI agents accessed US government websites"
    members = [member("Rogue AI agents accessed US government websites - Politico", "Google News: Artificial Intelligence", 3),
               member("Rogue AI agents accessed US government websites", "Engadget", 2),
               member("The Guardian Technology", "The Guardian Technology", 1),  # unrelated headline
               member("Rogue AI agents accessed US government websites", "Engadget Technology", 1),  # the same outlet's section feed
               member("Rogue AI agents accessed US government websites", "Old Blog", 24 * 20)]  # too old to count as momentum
    signals = cluster_signals(event, members, now=NOW)
    assert signals["independent_sources"] == 2  # politico + engadget
    assert signals["story_first_seen"] == NOW - timedelta(hours=24 * 20)  # ... but the old coverage marks the event as not new
    assert assess_viral_story(_candidate(event, "Researchers disclosed it today.",
                                         story_first_seen=signals["story_first_seen"]), now=NOW).failed_gate == "2_event_actuality"
