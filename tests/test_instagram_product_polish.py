"""Product polish after the v10.9 run - zero provider calls.

Founder review of the real v10.9 pixels: a carousel about the vivo Watch 6 never showed the watch; some cards looked fitted rather than
typeset; the Russian was slightly broken. These tests pin the general fixes (no story-specific rules):
  - an isolated product shot on a uniform ground is a product, not a 'flat text card';
  - a slide ABOUT a real subject shows the exact product photo instead of a generated stand-in, and a rebuild never cuts it in half;
  - card composition: long labels fit their cards, multi-word names and clitics keep their line, a long body gets a band, a narrow
    headline box takes the free width beside it, graphic slides give headline + body a real band;
  - the hook-only planning fields no longer fail a whole post (the v10.9 contract regression)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import services.instagram_creative_director as cd
from services.instagram_asset_profile import profile_asset
from services.instagram_body_copy import widen_headline_into_free_space
from services.instagram_carousel_layouts import _body_lines, _headline_px, render_carousel_slide
from services.instagram_exact_subject_media import exact_subject_keys, prefer_exact_subject_slides
from services.instagram_typography import wrap_units
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

ROOT = Path(__file__).resolve().parent.parent
V109 = ROOT / "tests" / "fixtures" / "instagram_v109_validation"
SPEC = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)


def _v109(name: str) -> dict:
    return json.loads((V109 / f"{name}.json").read_text(encoding="utf-8"))


def _product_shot() -> Image.Image:
    """A dark round 'watch' with a strap on a black studio ground: few colours, one solid isolated object (like the real product photo)."""
    img = Image.new("RGB", (800, 780), (6, 6, 8))
    d = ImageDraw.Draw(img)
    d.rectangle([300, 90, 500, 690], fill=(60, 60, 66))
    d.ellipse([190, 170, 610, 590], fill=(120, 120, 128))
    d.ellipse([230, 210, 570, 550], fill=(45, 45, 52))
    d.line([(400, 380), (480, 300)], fill=(240, 150, 30), width=10)
    return img


def _text_card() -> Image.Image:
    """A flat social card: thin strokes of 'text' on a uniform light ground."""
    img = Image.new("RGB", (800, 450), (245, 245, 245))
    d = ImageDraw.Draw(img)
    for row in range(6):
        d.line([(60, 60 + row * 60), (740, 60 + row * 60)], fill=(30, 30, 30), width=4)
    return img


def test_an_isolated_product_shot_is_a_product_not_a_flat_card():
    product = profile_asset(_product_shot(), subject_key="source")
    assert product.dominant_colours_90 <= 12  # the old rule alone called this a 'flat text card'
    assert product.hero_ready and product.object_fill >= 0.45 and product.suitable_for_final_visual
    card = profile_asset(_text_card(), subject_key="card")
    assert not card.suitable_for_final_visual  # thin strokes fill little of their box: still a card


def test_a_slide_about_the_real_product_shows_the_exact_photo_not_a_generated_stand_in():
    slides = _v109("trend_generative")["paid_output"]["slides"]
    assert all(s["media_source"] == "generated" and s["media_subject"] == "source" for s in slides)  # the real v10.9 plan
    keys = exact_subject_keys([("source", _product_shot())])
    swapped, notes = prefer_exact_subject_slides(slides, keys)
    assert [n["treatment"] for n in notes] == ["exact_product_whole", "exact_product_detail_crop"]
    whole = next(r for r in swapped[0]["layout"]["regions"] if r["kind"] == "media")
    assert swapped[0]["media_source"] == "source" and whole["content_ref"] == "source" and whole["crop_mode"] == "object_contain"
    assert all(s["media_source"] == "generated" for s in swapped[2:])  # the rest keeps its planned visual
    assert prefer_exact_subject_slides(slides, set())[1] == []
    assert exact_subject_keys([("source", _product_shot())], exclude={"source"}) == set()  # a vision rejection always wins


def test_a_rebuilt_layout_never_cuts_the_exact_product_in_half():
    slide = prefer_exact_subject_slides(_v109("trend_generative")["paid_output"]["slides"], {"source"})[0][0]
    result = render_carousel_slide(spec=SPEC, role=slide["role"], index=0, total=4, slide_copy="Титан, сапфир, eSIM — от $149",
                                   slide_body="Это стартовая цена новых vivo Watch 6.", source_evidence=None, package_identity="p",
                                   media_mode="SOURCE", layout_plan=slide["layout"], subject_assets={"source": (_product_shot(), "id")})
    region = result.notes["media_regions"][0]
    assert result.notes["media_scale_adapted"]  # the layout WAS rebuilt around the headline...
    assert region["subject"] == "source" and region["treatment"] == "object_contained"  # ...and the whole product is still shown


def test_the_v10_9_hook_field_regression_no_longer_fails_a_post():
    data = _v109("trend_generative")
    assert "hook_emotion belongs to the hook slide only" in data["acceptance_error_at_run"]
    director_input = cd.CreativeDirectorInput(objective="reach", format="carousel", opportunity_summary="s", locale="ru", media_first=True,
                                              allowed_evidence=list(data["evidence_handles"].values()), available_media_subjects=("source",))
    outcome = cd._validate_carousel_output(data["paid_output"], None, director_input=director_input, archetype="trend_generative")
    assert all(s.hook_emotion is None and s.hook_mechanic is None for s in outcome.carousel.slides[1:])
    assert outcome.carousel.slides[0].hook_emotion is not None


@pytest.mark.parametrize(("text", "unit"), [("Права переезжают в Apple Wallet", "в Apple Wallet"), ("Luna — 1% цены GPT-5.6 Sol", "GPT-5.6 Sol"),
                                             ("Claude Code теперь понимает AGENTS.md", "Claude Code"), ("Ты бы взял такие за $149?", "Ты бы"),
                                             ("Где же подвох?", "Где же")])
def test_names_and_particles_keep_their_line(text, unit):
    assert unit in wrap_units(text)


def test_a_long_body_gets_a_band_not_a_narrow_column():
    slide = _v109("news_insight")["paid_output"]["slides"][1]
    img = Image.new("RGB", (1024, 1536), (180, 150, 120))
    result = render_carousel_slide(spec=SPEC, role=slide["role"], index=1, total=4, slide_copy="Умнее — не значит выгоднее",
                                   slide_body="Рейтинг интеллекта показывает, насколько модель сильна. Но не показывает, сколько ты заплатишь за результат.",
                                   source_evidence=None, package_identity="p", media_mode="GENERATED", layout_plan=slide["layout"],
                                   subject_assets={"generated": (img, "id")})
    assert _body_lines(result) <= 4 and not result.text_clipped  # was 8 lines of fine print in a 0.34-wide column


def test_graphic_slides_give_headline_and_body_a_real_band():
    slide = _v109("ai_hack")["paid_output"]["slides"][1]
    result = render_carousel_slide(spec=SPEC, role=slide["role"], index=1, total=5, slide_copy="Шаг 1. Оставь только решения",
                                   slide_body="Вставь текст и попроси: «Выдели только принятые решения, без описания проблемы».",
                                   source_evidence=None, package_identity="p", media_mode="GRAPHIC", layout_plan=slide["layout"], subject_assets={})
    assert _headline_px(result) >= 100 and not result.text_clipped  # was 75px squeezed against the body


def test_a_narrow_headline_box_takes_the_free_width_beside_it():
    layout = {"regions": [{"kind": "text", "content_ref": "copy", "x": 0.06, "y": 0.08, "w": 0.52, "h": 0.16},
                          {"kind": "graphic", "graphic_type": "flow_diagram", "x": 0.06, "y": 0.53, "w": 0.86, "h": 0.27}]}
    widened, changed = widen_headline_into_free_space(layout)
    assert changed and widened["regions"][0]["w"] > 0.8
    blocked = {"regions": [*layout["regions"], {"kind": "media", "content_ref": "generated", "x": 0.6, "y": 0.0, "w": 0.4, "h": 1.0}]}
    assert widen_headline_into_free_space(blocked)[1] is False  # an image beside it keeps the column
