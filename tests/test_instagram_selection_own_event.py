"""SELECTION QUALITY - OWN-EVENT READING + PROCEDURAL / BRAND-NAME TRAP (founder selection review 2026-09-29, after canary 10).

Canary 10's viral slot chose 'OpenAI, Anthropic CEOs called to appear at Australian AI probe' - a CEO declining one Senate hearing. Both
viral mechanisms and the broad-interest anchor came from a DIFFERENT event the article only referred to ('amid fallout from OpenAI hack',
'in the wake of the revelation that OpenAI agents had breached ...'), and a famous company's name alone made it 'broad'. Now a story is
read on its OWN event, and a procedural headline needs a real-world consequence. Characteristics, never topic names - no rule mentions
Anthropic, Australia, a Senate or a hearing as a topic. Deterministic - no provider call."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.instagram_feed_product import FeedCandidate
from services.instagram_viral_story_gate import assess_broad_interest, assess_inherent_strength, assess_viral_story, own_event_text

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "artifacts/instagram_selection_remediation/selection_replay.json"


def _c(title: str, summary: str = "", **signals) -> FeedCandidate:
    return FeedCandidate(id="c", title=title, summary=summary, source_name="Example Tech", source_type="RSS",
                         published_at=NOW - timedelta(hours=2), **signals)


CANARY10_TITLE = "Anthropic will not appear at Senate inquiry into AI and datacentres amid fallout from OpenAI hack"
CANARY10_LEAD = ("Company behind Claude chatbot expected to attend separate Australian government hearing on AI next week. The chief executive "
                 "of Anthropic will turn down an invitation to appear at a Senate committee hearing on AI this week, in the wake of the revelation "
                 "that OpenAI agents had breached Australian government websites.")


def test_canary10_negative_fixture_is_valid_news_but_not_a_viral_slot_story():
    before_mechanisms = ["unexpected_ai_behaviour", "security_surprise"]  # what the canary credited (from the background clause)
    strength, mechanisms, _hook = assess_inherent_strength(CANARY10_TITLE, CANARY10_LEAD)
    assert strength == "NONE" and not set(mechanisms) & set(before_mechanisms)
    broad, reason = assess_broad_interest(CANARY10_TITLE, CANARY10_LEAD)
    assert broad == "NARROW" and "procedural event" in reason
    verdict = assess_viral_story(_c(CANARY10_TITLE, CANARY10_LEAD, independent_sources=5, story_events_24h=6), now=NOW)
    assert not verdict.eligible and verdict.failed_gate == "3_broad_interest"
    assert verdict.good_kage_news  # still valid, current KAGE news - usable when requested, just not auto-chosen for the viral slot


def test_background_clauses_are_removed_and_the_events_own_words_stay():
    assert own_event_text("X will not appear at the inquiry amid fallout from a hack") == "X will not appear at the inquiry"
    assert own_event_text("Y cancels event in the wake of the revelation that bots breached sites. Z confirmed it.") == \
        "Y cancels event . Z confirmed it."
    assert own_event_text("Компания отменила конференцию на фоне утечки данных") == "Компания отменила конференцию"
    assert own_event_text("AI agent built on DeepSeek hacked 460 servers") == "AI agent built on DeepSeek hacked 460 servers"


@pytest.mark.parametrize("title", [
    "Google, Microsoft CEOs called to appear at German parliament AI hearing amid fallout from chatbot hack",
    "Meta executive declines to testify before EU committee in the wake of the revelation that bots infiltrated election sites",
    "Руководителя Apple вызвали на слушания в парламенте на фоне взлома правительственных сайтов ИИ-агентами",
])
def test_the_lesson_generalises_to_other_companies_countries_and_languages(title):
    verdict = assess_viral_story(_c(title, independent_sources=5, story_events_24h=6), now=NOW)
    assert not verdict.eligible and verdict.failed_gate in ("3_broad_interest", "4_inherent_virality"), (title, verdict.reason)


@pytest.mark.parametrize("title", [
    "EU bans ChatGPT over privacy breach affecting millions of users",
    "Senate committee votes to ban TikTok for 150 million US users",
    "FTC sued Apple over App Store monopoly",
])
def test_a_procedural_or_regulatory_event_with_a_real_consequence_stays_broad(title):
    broad, reason = assess_broad_interest(title, "")
    assert broad == "BROAD", reason  # no anti-politics / anti-regulation shortcut: a real consequence keeps it


@pytest.mark.parametrize("title,lead", [
    ("AI agent built on DeepSeek hacked 460 servers with zero human operators",
     "Security researchers published the analysis on 25 September: the bot scanned, exploited and reported on its own."),
    ("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night",
     "He built a speed and distance tracker for the wheel. One recent activity showed 6.06 miles in 4 hours and 37 minutes."),
])
def test_genuinely_viral_own_event_stories_keep_their_strength(title, lead):
    strength, _m, _h = assess_inherent_strength(title, lead)
    assert strength == "STRONG"


def test_an_ai_event_is_not_mistaken_for_procedure():
    broad, reason = assess_broad_interest("OpenAI pauses training of latest models after AI agents probed U.S. government sites", "")
    assert broad == "BROAD", reason  # 'after <event>' is part of this story (its cause), not a background attribution


def test_saved_pool_replay_changes_only_the_procedural_winner_and_keeps_every_other_winner():
    r = json.loads(REPLAY.read_text(encoding="utf-8"))
    for pool in ("canary9", "canary10"):
        assert r[pool]["before_winner"].startswith("OpenAI, Anthropic CEOs called to appear")
        assert r[pool]["after_winner"] == "OpenAI agents tried to ‘bruteforce’ a UN website"
        assert r[pool]["procedural_story_after"]["failed_gate"] == "3_broad_interest"
    for pool in ("canary", "canary2", "canary3", "canary4", "canary5", "canary6", "canary7", "canary8"):
        assert r[pool]["after_winner"] == r[pool]["before_winner"], pool
