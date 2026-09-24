"""KAGE weekly news recap (services/instagram_weekly_recap.py): production Story identity, confirmed membership, fragments of one event
consolidated with Story Memory's own confirmed-match rule (never a title-similarity rule of its own), "what defined the week"
selection, no quotas, no fixed length, no repeat of a daily story or premise. Headlines are real items from the 5-11 Aug 2026 window."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.instagram_weekly_recap import MIN_ITEMS, RecapStory, consolidate, select_weekly_recap_items

T0 = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)


def _story(sid: str, *titles: str, sources=("Engadget",), days: float = 0.0, category: str = "GADGETS") -> RecapStory:
    return RecapStory(story_id=sid, titles=titles, sources=frozenset(sources), first_seen=T0 + timedelta(days=days), category=category)


FOLD_A = "Samsung confirms Galaxy Z Fold 8’s record-breaking sales numbers as pre-order deals are ending"
FOLD_B = "Samsung confirms Galaxy Z Fold 8’s record-breaking pre-order numbers"


def test_two_fragments_of_one_event_are_consolidated_by_story_memory_evidence():
    a = _story("a", FOLD_A, sources=("9to5Google",))
    b = _story("b", FOLD_B, sources=("CNET",), days=0.5)
    c = _story("c", "Pixel Watch 5 specs leak reveals what’s new: ‘Accelerated’ chip, 2nd-gen Active Band", sources=("ZDNET",), days=0.2)
    items = consolidate([a, b, c])
    merged = [i for i in items if {"a", "b"} <= i.story_ids]
    assert merged and merged[0].coverage == 2
    assert not any({"a", "c"} <= i.story_ids for i in items)


def test_fragments_far_apart_in_time_stay_separate():
    a = _story("a", FOLD_A, sources=("9to5Google",))
    b = _story("b", FOLD_B, sources=("CNET",), days=6)
    assert len(consolidate([a, b])) == 2


def _items(*specs):
    return consolidate([_story(sid, title, sources=sources) for sid, title, sources in specs])


_OUTLETS = [("The Verge AI", "Engadget", "CNET", "TechCrunch AI", "9to5Mac", "3DNews", "vc.ru"),
            ("9to5Google", "Engadget", "ZDNET", "The Verge AI", "3DNews"),
            ("9to5Mac", "Engadget", "Rozetked", "CNET", "vc.ru"),
            ("Techmeme", "TechCrunch AI", "Engadget", "The Guardian Technology", "WIRED AI", "3DNews")]


def test_the_recap_picks_widely_carried_user_facing_stories_and_nothing_to_fill_slots():
    items = _items(
        ("s1", "OpenAI is giving ChatGPT free users unlimited text chats", _OUTLETS[0]),
        ("s2", "Google Assistant will vanish from Android phones and connected devices in September", _OUTLETS[1]),
        ("s3", "Telegram briefly pulled from the App Store over child sexual abuse material availability", _OUTLETS[2]),
        ("s4", "eBay reports Q2 revenue up 15% YoY to $3.13B, vs. $3.02B est.", _OUTLETS[3]),  # business: half weight
        ("s5", "Some tiny model update nobody covered", ("Lobsters",)),
    )
    picks = select_weekly_recap_items(items)
    headlines = [p.item.headline for p in picks]
    assert len(picks) >= MIN_ITEMS and not any("nobody covered" in h for h in headlines)
    if any("eBay" in h for h in headlines):
        assert "eBay" in headlines[-1]  # widest-carried business news still ranks below user-facing stories
    assert all(p.why for p in picks)


def test_a_daily_story_or_its_premise_is_not_repeated_but_a_broader_event_can_be():
    items = _items(
        ("gym", "AI agent hacks gym to get its owner spot in pilates class", _OUTLETS[0]),
        ("astra", "OpenAI slows down Astra development due to cybersecurity concerns", _OUTLETS[3]),
        ("s2", "Google Assistant will vanish from Android phones and connected devices in September", _OUTLETS[1]),
        ("s3", "Telegram briefly pulled from the App Store over child sexual abuse material availability", _OUTLETS[2]),
        ("gym2", "An OpenClaw agent reportedly hacked a gym's booking system and kicked someone off a waiting list",
         ("Engadget", "BBC Technology", "TechCrunch AI", "vc.ru")),
    )
    picks = select_weekly_recap_items(items, daily_story_ids={"gym"},
                                      daily_titles=["An OpenClaw agent reportedly hacked a gym's booking system"])
    ids = set().union(*(p.item.story_ids for p in picks))
    assert "gym" not in ids and "gym2" not in ids  # the same premise (another copy) is not repeated
    assert "astra" in ids  # the broader AI-safety story of the week is a different story


def test_no_recap_without_a_real_set():
    items = _items(("s1", "OpenAI is giving ChatGPT free users unlimited text chats", _OUTLETS[0]))
    assert select_weekly_recap_items(items) == []
