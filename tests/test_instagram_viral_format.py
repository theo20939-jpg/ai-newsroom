"""Founder product decision (2026-09-26): VIRAL STORIES EXPAND INTO CAROUSELS - selectively. Fixtures are the REAL Phase A decisions
(the only two persisted Singles, both viral; two real non-viral NEWS_INSIGHT decisions from the offline review) and the review's own
output. No provider call."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE, viral_carousel_upgrade, viral_signals

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts/instagram_feed_product"
PERSISTED_SINGLES = {
    "deepseek": ART / "daily_media_cleanliness_20260926/live/2026-08-05_2_meme_trend/director_input.json",
    "hamster": ART / "e2e_week_2026-08-05_11/canary_run/2026-08-08_2_meme_trend/director_input.json",
}
REVIEW = ART / "viral_carousel_20260926/report.json"


def _decision(path: Path) -> dict:
    return json.loads(json.loads(path.read_text(encoding="utf-8"))["editorial_decision"])


@pytest.mark.parametrize("story", sorted(PERSISTED_SINGLES))
def test_the_persisted_viral_singles_now_upgrade_to_a_carousel(story):
    decision = _decision(PERSISTED_SINGLES[story])
    assert decision["recommended_format"] == "single" and decision["angle_intent"] == "MEME"  # what Phase A really decided
    assert viral_carousel_upgrade(decision, planned_product="TREND", executable_formats=["single", "carousel"]) == [
        "planned_product=TREND", "angle_intent=MEME"]


@pytest.mark.parametrize("intent", ["BREAKING", "IMPACT", "EXPLAINER", "COMPARISON", "HOW_TO", "PRODUCT_USE_CASE", "EVERGREEN_VALUE"])
@pytest.mark.parametrize("product", ["NEWS_INSIGHT", "AI_HACK"])
def test_a_non_viral_single_stays_single(intent, product):
    assert viral_carousel_upgrade({"recommended_format": "single", "angle_intent": intent}, planned_product=product,
                                  executable_formats=["single", "carousel"]) == []


@pytest.mark.parametrize("intent", ["MEME", "REACTION", "DEBATE"])
def test_a_viral_angle_upgrades_even_outside_the_trend_slot(intent):
    assert viral_carousel_upgrade({"recommended_format": "single", "angle_intent": intent}, planned_product="NEWS_INSIGHT",
                                  executable_formats=["single", "carousel"]) == [f"angle_intent={intent}"]


def test_the_rule_never_downgrades_and_never_forces_an_unexecutable_carousel():
    viral = {"recommended_format": "single", "angle_intent": "MEME"}
    assert viral_carousel_upgrade({**viral, "recommended_format": "reel"}, planned_product="TREND", executable_formats=["single", "carousel", "reel"]) == []
    assert viral_carousel_upgrade({**viral, "recommended_format": "carousel"}, planned_product="TREND", executable_formats=["single", "carousel"]) == []
    assert viral_carousel_upgrade(viral, planned_product="TREND", executable_formats=["single"]) == []
    assert viral_signals({"angle_intent": "IMPACT"}, planned_product=None) == []


def test_the_real_non_viral_phase_a_decisions_would_have_stayed_single():
    """The offline review asked the real Phase A about two one-beat news items; it chose carousel for both itself. Had it chosen single,
    the rule keeps it - their real intents (IMPACT, EXPLAINER) are not viral signals."""
    report = json.loads(REVIEW.read_text(encoding="utf-8"))
    decisions = [report["stays_single"], *[run["stays_single"] for run in report.get("previous_runs") or [] if "stays_single" in run]]
    assert {d["phase_a_angle_intent"] for d in decisions} == {"IMPACT", "EXPLAINER"}
    for d in decisions:
        assert viral_carousel_upgrade({"recommended_format": "single", "angle_intent": d["phase_a_angle_intent"]}, planned_product="NEWS_INSIGHT",
                                      executable_formats=["single", "carousel"]) == []


def test_the_director_receives_the_beat_retelling_note_only_when_set():
    from services.instagram_creative_director import CreativeDirectorInput, _build_user_text

    base = CreativeDirectorInput(objective="shares", format="carousel", opportunity_summary="s", allowed_evidence=["e"])
    assert "VIRAL STORY" not in _build_user_text(base)
    from dataclasses import replace

    text = _build_user_text(replace(base, viral_carousel_note=VIRAL_CAROUSEL_NOTE))
    assert "VIRAL STORY - A RETELLING IN BEATS" in text and "DISTINCT grounded beats" in text and "ONLY from the evidence" in text


def test_viral_generated_pictures_become_full_bleed_heroes_and_real_photos_are_untouched():
    from services.instagram_generated_fallback import NO_PHOTO_GENERATED, viral_generated_heroes

    inset = {"media_source": "generated", "layout": {"regions": [{"kind": "media", "content_ref": "generated", "x": 0.3, "y": 0.6, "w": 0.4, "h": 0.3}]}}
    photo = {"media_source": "source", "layout": {"regions": [{"kind": "media", "content_ref": "source"}]}}
    slides, changed = viral_generated_heroes([inset, photo])
    hero = [r for r in slides[0]["layout"]["regions"] if r["kind"] == "media"][0]
    assert changed == [0] and (hero["w"], hero["h"]) == (1.0, 1.0) and slides[0]["visual_family_reason"] == NO_PHOTO_GENERATED
    assert slides[1] == photo


def test_the_viral_brief_is_playful_but_still_illustrative_and_uses_the_directors_slide_body():
    from services.instagram_generated_fallback import generation_brief

    slide = type("Slide", (), {"slide_copy": "Хомяк пробежал 6,06 мили", "slide_body": "Mollie бегает по ночам.", "text": None, "body": None})()
    brief = generation_brief(slide, viral=True)
    assert "Mollie бегает по ночам" in brief  # a Director slide's line (slide_body) reaches the picture's brief
    assert "мем-энерги" in brief and "не документ" in brief and "скриншотов" in brief and "цитат" in brief and "постерам" in brief
    assert len(brief) <= 420


@pytest.mark.parametrize("story", sorted(PERSISTED_SINGLES))
def test_the_offline_viral_carousels_passed_the_art_gate_with_generated_heroes(story):
    report = json.loads(REVIEW.read_text(encoding="utf-8"))[story]
    assert report["result"] == "carousel" and report["art_passed"] and report["slides"] >= 4
    assert {p["treatment"] for p in report["generated_no_photo_slides"]} == {"viral_hero"}
