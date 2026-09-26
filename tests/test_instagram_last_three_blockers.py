"""The last three launch blockers (2026-09-26 remediation re-canary), reproduced from the real live outputs:
1. the trend-claim check read explicit NEGATIONS ('Это не Instagram-native тренд') as unsupported positive claims;
2. the pre-render contract hard-rejected a vision-unsuitable hero before the renderer's accepted fallback could run;
3. a no-photo carousel repeated one statement composition on 4 of 5 slides.
No provider, no network, no DB."""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

import services.instagram_creative_director as cd

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "artifacts/instagram_feed_product/launch_remediation_20260926"


def _trend(text: str) -> bool:
    try:
        cd.assert_trend_rationale_grounded(text, signal_type=None, provenance=None, is_platform_native=False)
        return True
    except cd.UngroundedTrendClaimError:
        return False


# --- 1. trend-claim polarity ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # the exact live Single and Reel rationales
    "Это не Instagram-native тренд и не вирусный формат. Основание для trend-подачи — абсурдный контраст внутри самой новости и узнаваемая "
    "интернет-логика «AI получил автономность, но провалил задачу», а не подтверждённая динамика Instagram.",
    "Подтверждённого Instagram-native сигнала нет, поэтому это не подача через вирусный Reels-тренд. Основа — собственная интернет-native "
    "WTF-реакция на новость ABC о неожиданном и этически проблемном поведении ИИ-агента.",
    "Нет признаков вирусного Instagram-формата.",
    "Это не является Reels-трендом.",
    "Формат не относится к Instagram-трендам.",
    "Вирусность Instagram-формата не подтверждается данными.",
    "Нет доказательств, что это вирусный формат Instagram.",
])
def test_negated_trend_statements_pass(text):
    assert _trend(text)


@pytest.mark.parametrize("text", [
    "Это вирусный Instagram-тренд.",
    "Это популярный Reels-тренд, поэтому делаем Reel.",
    "Формат набирает популярность в Reels: это вирусный тренд.",
    "Это не только вирусный формат Instagram, но и повод для реакции.",  # an intensifier asserts the trend
    "Это не просто вирусный Reels-тренд.",
    "Это вирусный Reels-тренд, и нет смысла его игнорировать.",  # a negation in another part of the sentence changes nothing
])
def test_unsupported_positive_trend_claims_still_fail(text):
    assert not _trend(text)


# --- 2. unsuitable hero -> the accepted fallback, never a dead plan ----------------------------------------------------------------------

def _replay(call: str, tmp_path: Path) -> dict:
    subprocess.run([sys.executable, str(ROOT / "scripts/_instagram_recap_plan_replay.py"), str(RUN / "recap/weekly_recap"), call,
                    str(ROOT / "artifacts/instagram_feed_product/launch_canary_20260926/recap/weekly_recap/package.json"), str(tmp_path)],
                   check=True, capture_output=True, cwd=ROOT)
    return json.loads((tmp_path / "replay.json").read_text(encoding="utf-8"))


def test_the_live_recap_plan_with_unsuitable_heroes_now_renders_and_passes_the_art_gate(tmp_path):
    result = _replay("10_director.json", tmp_path)  # the live retry plan that was rejected for 'story_2' as a hero
    assert result["pre_render"] == "PASS" and result["art_passed"] and result["slides"] == 9
    unsuitable = set(result["unsuitable"])
    for slide in result["per_slide"]:
        if slide["role"] == "story" and slide["media_subject"] in unsuitable:
            assert not slide["hero_zone_used"]  # an unsuitable photo is never the slide's hero - it is a softened background layer
        if slide["role"] in ("hook", "closing"):
            assert not set(slide["media"]) & unsuitable  # never a tile of the cover grid or a print of the end card
    treatments = {d["treatment"] for event in result["demotions"] for d in event["demotions"]}
    assert treatments == {"background_layer", "replaced_in_frame"}


def test_attempt_one_is_demoted_too_but_its_english_leak_still_goes_back_to_the_director(tmp_path):
    result = _replay("09_director.json", tmp_path)
    assert result["pre_render"].startswith("CopyLanguageLeakError") and result["demotions"]  # the language rule is untouched


def test_the_contract_accepts_an_unsuitable_image_only_as_a_background_layer():
    from schemas.instagram_creative import InstagramCarouselCreative
    from services.instagram_media_first import MediaFirstContractError, assert_media_first, demote_unsuitable_heroes

    raw = json.loads((RUN / "recap/weekly_recap/calls/10_director.json").read_text(encoding="utf-8"))["response"]["structured_output"]
    slides = list(InstagramCarouselCreative.model_validate(raw).slides)
    subjects = {f"story_{i}" for i in range(1, 8)}
    with pytest.raises(MediaFirstContractError, match="not suitable as a final visual"):
        assert_media_first(slides, available_subjects=subjects, unsuitable_subjects={"story_2", "story_3"}, generated_media_available=False)
    demoted, notes = demote_unsuitable_heroes(slides, {"story_2", "story_3"}, tuple(sorted(subjects)))
    assert_media_first(demoted, available_subjects=subjects, unsuitable_subjects={"story_2", "story_3"}, generated_media_available=False)
    layer = next(r for r in demoted[1].layout.regions if r.kind == "media")
    assert (layer.content_ref, layer.tone, layer.w * layer.h) == ("story_2", "muted", 1.0) and notes


# --- 3. no-photo carousel beats ------------------------------------------------------------------------------------------------------

def _variants(post: str) -> list[str]:
    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_format_director import ContentFormat
    from services.instagram_platform_renderer import render_instagram_carousel

    data = json.loads((RUN / "daily" / post / "package.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    return [r.evidence.notes.get("editorial_variant") or "plan" for r in render_instagram_carousel(InstagramContentPackage(**data), subject_assets={})]


def test_the_deepseek_carousel_is_no_longer_four_identical_statements():
    variants = _variants("2026-08-05_2_meme_trend")
    assert variants.count("statement") <= 2 and all(a != b for a, b in zip(variants, variants[1:]))  # distinct beats, never back to back


def test_the_adobe_carousel_keeps_its_steps_and_no_card_survives_without_generation():
    variants = _variants("2026-08-06_1_ai_hack")
    # founder decision 2026-09-26: with no generated image the UI-path boxes and choice cards become text-led beats too (no "plan" cards)
    assert variants.count("step_numeral") == 2 and variants.count("plan") == 0
    assert variants[0] == "data_point" and all(a != b for a, b in zip(variants, variants[1:]))


def test_a_leading_figure_stays_whole_and_a_mid_sentence_figure_is_never_cut_out():
    from services.instagram_layout_validation import copy_parts
    from services.instagram_recap_frames import _leading_figure

    assert copy_parts("70+ инструментов Adobe — прямо в ChatGPT")["number"] == "70+"
    assert _leading_figure("70+ инструментов Adobe — прямо в ChatGPT") and _leading_figure("30B параметров на одной GPU")
    assert not _leading_figure("Рост на 10% за неделю") and not _leading_figure("460 целей. 0 взломов. ИИ всё делал сам.")
