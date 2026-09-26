"""Founder review 2026-09-26 - VIRAL EDITORIAL QUALITY: KAGE-first selection, hook, humour, voice, slide redundancy and people in generated
pictures. Fixtures are real headlines from the production pool and the real saved outputs; no provider call."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.instagram_feed_product import FeedCandidate, FeedFormat, event_oddity, kage_core, read_candidate, read_with_evidence
from services.instagram_viral_format import (
    VIRAL_CAROUSEL_NOTE,
    generated_person_risks,
    named_people,
    viral_carousel_upgrade,
    viral_copy_findings,
)

ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "artifacts/instagram_feed_product/viral_editorial_quality_20260926/offline/replay.json"


def _read(title: str, source: str = "Know Your Meme", summary: str = ""):
    return read_candidate(FeedCandidate(id="x", title=title, summary=summary, source_name=source, source_type="RSS"))


# --- selection: KAGE relevance first, virality never compensates -------------------------------------------------------------------------

@pytest.mark.parametrize("title,source", [
    ("IShowSpeed's 'Ronaldo Day' Clip Becomes A Powerful Brainrot Meme", "Know Your Meme"),
    ("2020 Karen Video About 'Playing Games' Becomes A Meme With Difficult Game Enjoyers On TikTok", "Know Your Meme"),
    ("Why Ed Miliband has embraced his ‘awkward dad’ image in viral TikTok video", "The Guardian Technology"),
])
def test_viral_stories_whose_technology_is_incidental_never_reach_the_viral_slot(title, source):
    read = _read(title, source, summary="streamer and YouTuber on YouTube, a viral clip online")
    assert read.format is FeedFormat.REJECT and "technology is incidental" in read.reason


@pytest.mark.parametrize("title,source", [
    ("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night", "Hacker News Front Page"),
    ("460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина", "Habr: Artificial Intelligence"),
    ("$580M undersea cable rerouted to avoid the grave of Dobby the House Elf", "Hacker News Front Page"),
    ("Спутникопад Starlink превратили в глобальный барометр — они помогают изучать атмосферу Земли", "3DNews"),
])
def test_strange_events_with_a_tech_core_stay_strong_viral_candidates(title, source):
    read = _read(title, source)
    assert read.format is FeedFormat.MEME_TREND and read.strong


def test_distribution_words_are_not_an_event_and_creator_words_are_not_a_tech_core():
    assert not event_oddity("IShowSpeed clip becomes a brainrot meme and goes viral")
    assert event_oddity("Physicist rigged his hamster's wheel")
    assert kage_core("streamer's clip on YouTube and TikTok goes viral online") == []
    assert "gadget" in kage_core("new phone glitch") and "ai" in kage_core("ChatGPT agent deleted a database")


def test_a_tech_story_that_only_spread_needs_its_body_to_show_a_strange_event():
    candidate = FeedCandidate(id="x", title="Google's new app feature becomes a meme", source_name="Verge", source_type="RSS")
    first = read_candidate(candidate)
    assert first.format is FeedFormat.MEME_TREND and not first.strong
    assert not read_with_evidence(candidate, first, "The app feature spread widely on social media and many users shared it.").strong
    assert read_with_evidence(candidate, first, "The app accidentally turned every photo into a hamster, a bizarre glitch.").strong


def test_a_viral_single_with_too_few_distinct_facts_is_not_stretched_into_a_carousel():
    decision = {"recommended_format": "single", "angle_intent": "MEME"}
    thin = ["A short title only", "SOURCE MEDIA: 1200x630 source image available", "The one real fact of the story, stated in full here."]
    rich = [*thin, "A second distinct fact with its own concrete detail for a slide.", "A third distinct fact that adds another beat to it."]
    assert viral_carousel_upgrade(decision, planned_product="TREND", executable_formats=["single", "carousel"], evidence=thin) == []
    assert viral_carousel_upgrade(decision, planned_product="TREND", executable_formats=["single", "carousel"], evidence=rich)


# --- people in generated pictures ---------------------------------------------------------------------------------------------------------

def test_named_people_are_read_from_role_and_name_and_organisations_are_not_people():
    assert named_people(["based on a viral clip of streamer and YouTuber IShowSpeed", "with NHL player Cole Caufield."]) == {
        "IShowSpeed", "Cole Caufield"}
    assert named_people(["Thijs de Buck, an MRI physicist based in Utrecht"]) == {"Thijs de Buck"}
    assert named_people(["Эту сессию восстановили исследователи из Unit 42, подразделения Palo Alto Networks."]) == set()


def test_a_generated_lookalike_or_reenactment_is_a_risk_and_anonymous_hands_or_a_simile_are_not():
    evidence = ["Thijs de Buck, an MRI physicist based in Utrecht, built a tracker."]
    slide = lambda brief: {"media_source": "generated", "generation_brief": brief}  # noqa: E731
    assert generated_person_risks([slide("A young man attaching a sensor to a wheel")], evidence)
    assert generated_person_risks([slide("Thijs de Buck smiling at his desk")], evidence)
    assert not generated_person_risks([slide("Portrait close-up of human hands attaching a blank sensor to a wheel")], evidence)
    assert not generated_person_risks([slide("A hamster posed like an athlete beside a stopwatch")], evidence)
    assert not generated_person_risks([{"media_source": "source", "generation_brief": "a man"}], evidence)  # real photos are not affected
    assert not generated_person_risks([slide("A young man attaching a sensor")], ["No person is named here."])


def test_every_generated_picture_prompt_forbids_named_people_lookalikes_and_reenactments():
    from services.instagram_creative_media import compile_instagram_generation_prompt

    for slide in (None, {"slide_copy": "x", "generation_brief": "a wheel"}):
        prompt = compile_instagram_generation_prompt(plan={"main_idea": "x"}, opportunity_summary="s", evidence=["e"],
                                                     content_format="carousel" if slide else "single", slide=slide)
        assert "Never depict, imitate or re-create a specific real person named in the story" in prompt


# --- hook, humour, voice, redundancy (the failed IShowSpeed plan) --------------------------------------------------------------------------

def _slides(*pairs, refs=None):
    refs = refs or [f"E{i}" for i in range(len(pairs))]
    return [{"slide_copy": h, "slide_body": b, "source_evidence": r, "role": "story"} for (h, b), r in zip(pairs, refs)]


def test_a_distribution_hook_is_rejected_and_an_event_hook_is_not():
    evidence = ["The clip went viral in 2026 and was popularized as a meme that September."]
    assert any("hook describes how the story spread" in p for p in viral_copy_findings(
        _slides(("Ролик 2024-го стал brainrot-мемом", "Клип попал в хоккейную ленту в 2026 году.")), evidence))
    assert not any("hook" in p for p in viral_copy_findings(
        _slides(("ИИ получил 460 целей. Не взломал ни одну.", "Всё остальное агент делал сам.")), ["460 targets, zero systems breached"]))


def test_the_internet_as_an_actor_and_an_unsupported_again_are_rejected_unless_the_evidence_says_so():
    slides = _slides(("Хоккейный клип", "А потом интернет оставил только контраст."), ("Второй кадр", "Фрагмент снова разошёлся."))
    silent = viral_copy_findings(slides, ["The clip comes from a 2024 video."])
    assert any("abstract commentary" in p for p in silent) and any("unsupported implication" in p for p in silent)
    said = viral_copy_findings(slides, ["Internet users shared it again after the clip came back online."])
    assert not any("abstract commentary" in p or "unsupported implication" in p for p in said)


def test_an_incomplete_construction_is_rejected():
    assert any("'между' needs two terms" in p for p in viral_copy_findings(_slides(("Мемом стал не Ronaldo Day, а сбой между ним", "x y z.")), []))
    assert not any("между" in p for p in viral_copy_findings(_slides(("Контраст между песней и падением", "x y z.")), []))


def test_two_adjacent_slides_on_the_same_evidence_with_nothing_new_make_the_same_point():
    same = _slides(("Сначала был клип", "Он пел Happy day, Ronaldo day."), ("Потом контраст", "Песня и столкновение."),
                   ("Сбой между песней и столкновением", "Ronaldo Day и падение."), refs=["E1", "E5", "E5"])
    # thesis-level rule (2026-09-26): judged on the slides' claims, not on the shared evidence id
    assert any(p.startswith("slides 2 and 3: the second slide restates the first slide's thesis") for p in viral_copy_findings(same, []))
    new = _slides(("Потом контраст", "Песня и столкновение."), ("6,06 мили", "Трекер записал 4 часа 37 минут."), refs=["E5", "E5"])
    assert not any("slides 1 and 2" in p for p in viral_copy_findings(new, []))


def test_the_note_carries_the_hook_humour_structure_and_people_rules():
    note = VIRAL_CAROUSEL_NOTE
    assert "STRANGEST CONCRETE FACT" in note and "never how the story spread" in note
    assert "find the joke already present in the facts" in note and "no 'the internet decided'" in note
    assert "as many slides as there are DISTINCT grounded beats" in note and "NEVER shows a real person named in the story" in note


# --- the zero-cost replay of the real outputs ---------------------------------------------------------------------------------------------

def test_the_failed_canary_is_rejected_by_selection_and_would_be_blocked_by_the_director_and_the_gate():
    b = json.loads(REPLAY.read_text(encoding="utf-8"))["B_ishowspeed"]
    assert b["planner_read_now"]["format"] == "reject"
    # a generated likeness of a named real person is a HARD failure (founder decision 2026-09-26: never laundered through the copy retry)
    assert b["director_validation_now"].startswith("CreativeFactSafetyError") and len(b["generated_person_risks"]) == 3
    assert not b["art_gate_now"]["art_passed"]
    joined = " ".join(b["all_viral_copy_findings"])
    # slides 3/4 were flagged by the evidence-id overlap rule, which the thesis-level rule (2026-09-26) replaced: they reword the same
    # contrast with synonyms (фраза/песня, столкновение/фейл), which a lexical thesis comparison does not see - disclosed, not claimed
    for expected in ("hook describes how the story spread", "abstract commentary", "unsupported implication", "'между' needs two terms"):
        assert expected in joined


@pytest.mark.parametrize("key", ["C_deepseek", "C_hamster"])
def test_the_accepted_viral_carousels_stay_eligible_and_pass(key):
    c = json.loads(REPLAY.read_text(encoding="utf-8"))[key]
    assert c["planner_read_now"]["format"] == "meme_trend" and c["planner_read_now"]["strong"]
    assert c["director_validation_now"] == "PASS" and c["art_gate_now"] == {"art_passed": True, "blocking": []}


def test_an_ordinary_non_viral_kage_story_is_unaffected():
    d = json.loads(REPLAY.read_text(encoding="utf-8"))["D_adobe_ai_hack"]
    assert d["planner_read_now"]["format"] == "ai_hack" and not d["viral_rules_apply"] and d["art_gate_now"]["art_passed"]
