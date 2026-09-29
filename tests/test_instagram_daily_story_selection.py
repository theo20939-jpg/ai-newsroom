"""DAILY STORY SELECTION (founder decisions 2026-09-29). The daily story slot competes on WHICH STORY MAKES THE STRONGEST KAGE INSTAGRAM
POST TODAY across four families - viral / meme events, major AI launches, gadgets / devices, large serious tech events - instead of a
weekly-only bucket for product news and a two-mechanism minimum for memes. Coverage (momentum) only breaks ties after the story's own
strength. Headlines are real saved-pool headlines; no rule names a story, company or country. Deterministic - no provider call."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.instagram_feed_product import FeedCandidate, FeedFormat, plan_daily_slots, read_candidate
from services.instagram_viral_nomination import nominate_viral_events, nominated_reads
from services.instagram_viral_story_gate import assess_actuality, assess_inherent_strength, assess_viral_story, best_viral_story

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "artifacts/instagram_daily_selection/daily_selection_after.json"

CLAUDE_FILES = "Claude deleted a developer's 48,000 files in 90 seconds after being asked to tidy a folder"
OPENAI_SITES = "OpenAI's agents targeted and infiltrated US government websites"
BLACKJACK = "AI Agents Secretly Colluded to Count Cards in Blackjack Experiment"
MS_17T = "Teenager hacks open Microsoft database with 17 trillion total rows and 25,000 user accounts"
GPT6 = "OpenAI выпустила GPT-6 Sol и GPT-6 Luna в API"
QWEN_BOOK = "Alibaba представила Qwen Book — ноутбук-трансформер на Snapdragon 8 Elite Gen 5 с ИИ-агентом, вшитым в собственную ОС"
SNL = "Anthropic’s Dario Amodei gets the SNL treatment"


def _c(title: str, *, id: str = "c", lead: str = "The incident happened today.", hours_old: float = 2, **signals) -> FeedCandidate:
    return FeedCandidate(id=id, title=title, summary=lead, source_name="Example Tech", source_type="RSS",
                         published_at=NOW - timedelta(hours=hours_old), **signals)


def _pick(*candidates: FeedCandidate):
    pairs = [(c, assess_viral_story(c, now=NOW)) for c in candidates]
    best = best_viral_story(pairs)
    return (best[0].id if best else None), {c.id: v for c, v in pairs}


def test_1_7_a_strong_viral_story_wins_and_wider_coverage_does_not_defeat_clearly_stronger_shareability():
    winner, verdicts = _pick(_c(CLAUDE_FILES, id="meme", independent_sources=2),
                             _c(OPENAI_SITES, id="covered", independent_sources=9, story_events_24h=12, on_hacker_news=True))
    assert verdicts["meme"].eligible and verdicts["covered"].eligible
    assert winner == "meme"  # 48,000 files in 90 seconds: more surprising and relatable, though far less covered
    assert verdicts["meme"].points > verdicts["covered"].points and verdicts["covered"].momentum == "STRONG"


def test_2_one_genuinely_strong_viral_idea_qualifies_without_a_second_formal_signal():
    for title in (BLACKJACK, MS_17T):
        strength, mechanisms, _h = assess_inherent_strength(title, "")
        assert strength == "STRONG" and len(mechanisms) == 1, (title, mechanisms)
        assert assess_viral_story(_c(title, independent_sources=2), now=NOW).eligible  # corroborated: it competes


def test_freshness_still_guards_a_single_undated_source():
    verdict = assess_viral_story(_c(BLACKJACK, lead="Researchers ran the experiment."), now=NOW)
    assert verdict.strength == "STRONG" and not verdict.eligible and verdict.failed_gate == "5_momentum"  # unchanged safeguard


def test_3_a_major_ai_model_launch_wins_the_day():
    winner, verdicts = _pick(_c(GPT6, id="launch", independent_sources=4), _c(SNL, id="snl", independent_sources=2))
    assert verdicts["launch"].eligible and verdicts["snl"].eligible and winner == "launch"


def test_4_a_strong_gadget_story_wins_the_day():
    winner, verdicts = _pick(_c(QWEN_BOOK, id="gadget", independent_sources=3),
                             _c("Nvidia unveils security platform to stop AI agents from going rogue", id="product", independent_sources=5))
    assert verdicts["gadget"].eligible and not verdicts["product"].eligible and winner == "gadget"


def test_5_a_serious_large_scale_incident_beats_a_minor_anecdote():
    winner, verdicts = _pick(_c(MS_17T, id="breach", independent_sources=2), _c(SNL, id="anecdote", independent_sources=2))
    assert verdicts["breach"].eligible and verdicts["anecdote"].eligible and winner == "breach"


def test_either_a_funny_incident_or_a_major_launch_may_win_on_actual_strength():
    # comedy is not forced: a flagship model release outranks a one-idea pop-culture moment, a measured AI failure outranks the launch
    assert _pick(_c(GPT6, id="launch", independent_sources=2), _c(SNL, id="snl", independent_sources=2))[0] == "launch"
    assert _pick(_c(GPT6, id="launch", independent_sources=2), _c(CLAUDE_FILES, id="meme", independent_sources=2))[0] == "meme"


def test_6_9_weak_procedural_and_famous_name_only_stories_stay_out():
    for title in ("Anthropic will not appear at Senate inquiry into AI and datacentres amid fallout from OpenAI hack",
                  "Anthropic to pay Akamai $11.6 billion over seven years in cloud deal",
                  "Weekend Apple deals: Beats 360, AirPods Pro 3, Mac Studio, MacBook Air, more",
                  "Top Stories: Apple Leaks, Siri AI Settlement, and More",
                  "OpenAI releases a new ChatGPT model for enterprise customers",
                  "There are no \"rogue\" AI agents",
                  "Gemini app replacing Gems with skills in November"):
        verdict = assess_viral_story(_c(title, independent_sources=6, story_events_24h=8), now=NOW)
        assert not verdict.eligible, (title, verdict.reason)


def test_8_a_stale_meme_cannot_win_because_it_is_funny():
    stale = _c(CLAUDE_FILES, lead="The deletion happened in June 2025; the developer only now wrote about it.", hours_old=2,
               independent_sources=3)
    verdict = assess_viral_story(stale, now=NOW)
    assert not verdict.eligible and verdict.failed_gate == "2_event_actuality"


def test_10_the_weekly_bucket_no_longer_blocks_a_strong_story_from_the_daily_slot():
    launch = _c(GPT6, id="gpt6", independent_sources=4)
    assert read_candidate(launch).format is FeedFormat.WEEKLY_NEWS  # the old read still calls it 'weekly news' ...
    nomination = nominate_viral_events([launch], now=NOW)
    slots = plan_daily_slots([(launch, read_candidate(launch))], viral_nominations=nominated_reads(nomination, 3))
    assert [s.format for s in slots] == [FeedFormat.MEME_TREND] and slots[0].shortlist[0][0].id == "gpt6"  # ... but it takes a daily slot


def test_saved_pool_replay_shows_a_real_mix_of_families_and_keeps_the_procedural_fix():
    r = json.loads(REPLAY.read_text(encoding="utf-8"))
    families = {e["family"] for pool in r.values() for e in pool["eligible"]}
    # the saved pools hold NO fresh major AI launch (GPT-6 Sol / Luna and Claude Opus 5.5 were published > 72 h before canary 2 and are
    # correctly rejected by freshness) - AI launches are proven on real headlines by the unit tests above, never forced into the replay
    assert {"viral / meme", "gadget / device"} <= families
    assert "-" not in families  # every eligible story belongs to a named family (the replay labels ai_feat as viral / meme)
    enigma = r["canary2"]["named"]["enigma_astra"]["verdict"]
    assert enigma["eligible"] and enigma["actuality"] == "CURRENT"  # historical context no longer makes the event OLD
    assert r["canary"]["winner"].startswith("Анекдот: Claude снес разрабу")  # the 48,000-files story now wins its day
    for pool in r.values():
        assert not (pool["winner"] or "").startswith("OpenAI, Anthropic CEOs called to appear")


# --- historical context vs an old event (founder decision 2026-09-29) -----------------------------------------------------------------

def _actuality(title: str, lead: str):
    published = NOW - timedelta(hours=3)
    return assess_actuality(title, lead, published_at=published, story_first_seen=published, independent_sources=2, now=NOW)


@pytest.mark.parametrize("title,lead", [
    ("ChatGPT-6 Astra cracks 1941 Enigma-coded message in two days",
     "A German Army Enigma transmission from 85 years ago, known as the MVUEH message, was cracked this week."),  # the saved lead
    ("AI decodes a message sent 85 years ago", "The message was intercepted in 1941 and never read."),
    ("Company reveals a device built 20 years ago", "The prototype was built 20 years ago and hidden in a lab."),
    ("Researchers solve a problem first posed 60 years ago", "The problem, posed 60 years ago, was solved this week."),
])
def test_the_age_of_an_object_is_historical_context_not_the_date_of_the_event(title, lead):
    assert _actuality(title, lead).status == "CURRENT", title


@pytest.mark.parametrize("title,lead", [
    ("AI decoded the message 85 years ago", "A retrospective on wartime codebreaking."),  # the event's own verb carries the age
    ("Robot dog video goes viral", "The video, filmed 5 years ago, is spreading on TikTok."),  # a resurfaced clip stays old
    ("Microsoft launched Windows 95 back in 1995", "The anniversary is today."),
])
def test_a_genuinely_old_event_is_still_old(title, lead):
    assert _actuality(title, lead).status == "OLD", title


# --- enterprise label is not a blanket exclusion (founder decision 2026-09-29) ---------------------------------------------------------

@pytest.mark.parametrize("title", ["OpenAI releases GPT-6 for enterprise customers",
                                   "Anthropic launches Claude Opus 5.5 for enterprise with a million-token context",
                                   "Microsoft launches its Copilot super app for business users"])
def test_a_major_named_launch_aimed_at_enterprise_is_still_strong(title):
    assert assess_inherent_strength(title, "")[0] == "STRONG", title


def test_a_generic_release_is_weak_for_any_audience():
    for title in ("OpenAI releases a new ChatGPT model for enterprise customers", "OpenAI releases a new ChatGPT model for everyone"):
        assert assess_inherent_strength(title, "")[0] == "MODERATE", title  # nothing named: routine, whoever it is for
