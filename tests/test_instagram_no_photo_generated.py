"""Founder visual decision (2026-09-26): NO SUITABLE PHOTO => GENERATED IMAGE - never fact cells / step rectangles / choice cards.
Priority: suitable real photo -> generated editorial image -> text-led typography only when generation is unavailable or failed.
Fixtures are the accepted persisted packages and the generated images already paid for in the offline review - no provider call here."""
from __future__ import annotations

import copy
import dataclasses
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from services.instagram_generated_fallback import (
    GENERATED_VISUAL_TREATMENT,
    NO_PHOTO_GENERATED,
    generation_brief,
    no_photo_treatment,
    promote_no_photo_slides,
)

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "artifacts/instagram_feed_product/daily_media_cleanliness_20260926"
GENERATED = ROOT / "artifacts/instagram_feed_product/no_photo_generated_20260926/generated"
RECAP_SUITABLE = {"story_1", "story_4", "story_5", "story_6", "story_7"}


def _plan(post: str) -> dict:
    return json.loads((REVIEW / post / "package.json").read_text(encoding="utf-8"))["media_plan"]


def _package(post: str):
    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_format_director import ContentFormat

    data = json.loads((REVIEW / post / "package.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    return InstagramContentPackage(**data)


# --- which slides get a generated image ------------------------------------------------------------------------------------------------

def test_every_adobe_no_photo_card_slide_is_promoted_to_a_generated_image():
    slides, notes = promote_no_photo_slides(copy.deepcopy(_plan("preserved/carousel_adobe")["slides"]), suitable_subjects=set(), recap=False)
    assert [(n["slide"], n["treatment"]) for n in notes] == [(i, "generated") for i in range(6)]
    assert {g for n in notes for g in n["before"]} == {"flow_diagram", "poll_cards"}
    for slide in slides:
        regions = slide["layout"]["regions"]
        assert slide["media_source"] == "generated" and slide["visual_family_reason"] == NO_PHOTO_GENERATED
        assert not any(r["kind"] == "graphic" for r in regions)  # no cards, cells or step rectangles left
        assert [r["content_ref"] for r in regions if r["kind"] == "media"] == ["generated"]


def test_the_recap_generates_only_the_stories_without_a_suitable_photo_and_keeps_its_cover_and_end_card():
    before = _plan("preserved/weekly_recap")["slides"]
    slides, notes = promote_no_photo_slides(copy.deepcopy(before), suitable_subjects=RECAP_SUITABLE, recap=True)
    assert [(n["slide"], before[n["slide"]]["media_subject"], n["treatment"]) for n in notes] == [
        (1, "story_2", "generated"), (4, "story_3", "generated")]  # Assistant and Meta: their photos were judged unsuitable
    for i in (0, 2, 3, 5, 6, 7, 8):  # the cover grid, the real-photo stories and the subscription end card are untouched
        assert slides[i] == before[i]


def test_a_recap_story_with_a_suitable_photo_of_its_own_uses_that_photo_not_a_generated_one():
    slide = {"role": "story", "media_subject": "story_4", "media_source": "graphic",
             "layout": {"regions": [{"kind": "graphic", "graphic_type": "flow_diagram"}]}}
    assert no_photo_treatment(slide, RECAP_SUITABLE, recap=True) == "real_photo"
    promoted, _ = promote_no_photo_slides([slide], suitable_subjects=RECAP_SUITABLE, recap=True)
    assert [r["content_ref"] for r in promoted[0]["layout"]["regions"] if r["kind"] == "media"] == ["story_4"]


def test_a_slide_that_already_has_its_photo_or_was_planned_generated_is_left_alone():
    photo = {"role": "step", "layout": {"regions": [{"kind": "media", "content_ref": "source"}]}}
    planned = {"role": "step", "media_source": "generated", "layout": {"regions": [{"kind": "media", "content_ref": "generated"}]}}
    softened = {"role": "hook", "layout": {"regions": [{"kind": "media", "content_ref": "source", "tone": "muted", "w": 1, "h": 1}]}}
    assert no_photo_treatment(photo, {"source"}, recap=False) is None
    assert no_photo_treatment(planned, {"source"}, recap=False) is None
    assert no_photo_treatment(softened, set(), recap=False) == "generated"  # an unsuitable photo as a blurred layer is not a photo


def test_the_brief_is_built_from_the_slides_own_copy_and_forbids_evidence_imitation():
    brief = generation_brief({"slide_copy": "Meta принесла Muse", "body": "В семействе — Muse Spark, Muse Glimmer и Muse Code."})
    assert "«Meta принесла Muse»" in brief and "Muse Code" in brief and len(brief) <= 420
    assert "не документ" in brief and "без текста" in brief and "логотипов" in brief and "узнаваемых людей" in brief
    assert ".." not in brief


# --- SINGLE / REEL --------------------------------------------------------------------------------------------------------------------

def test_single_reel_plan_prefers_a_generated_image_and_typography_only_without_generation():
    from schemas.instagram_creative import InstagramSingleCreative
    from services.instagram_automatic_trigger import _demote_source_plan

    raw = json.loads((REVIEW / "live/2026-08-05_2_meme_trend/calls/03_director.json").read_text(encoding="utf-8"))["response"]["structured_output"]
    creative = InstagramSingleCreative.model_validate(raw)
    typographic = creative.creative_execution_plan.media_strategy
    generated, changed = _demote_source_plan(creative, generation=True)
    plan = generated.creative_execution_plan
    assert changed and plan.media_strategy == "generated_media" and plan.visual_treatment == GENERATED_VISUAL_TREATMENT
    assert creative.on_image_copy.split()[1] in plan.focal_point  # the picture's focus is the post's own copy
    assert generated.on_image_copy == creative.on_image_copy  # no copy touched
    without, changed = _demote_source_plan(creative, generation=False)
    assert without.creative_execution_plan.media_strategy == typographic and not changed  # already typographic: nothing to do


def test_the_director_is_told_to_plan_a_generated_image_when_generation_is_available(monkeypatch):
    from core.config import settings
    from services.instagram_automatic_trigger import _daily_media_note

    rejected = {"suitable": False, "checks": [{"image_kind": "article_or_news_card"}]}
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "live")
    assert "media_strategy 'generated_media'" in _daily_media_note(rejected)
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "off")
    assert "media_strategy 'typographic'" in _daily_media_note(rejected)


def test_every_generated_picture_prompt_refuses_ai_art_cliches_and_brand_symbol_imitation():
    from services.instagram_creative_media import compile_instagram_generation_prompt

    post = compile_instagram_generation_prompt(plan={"main_idea": "x", "focal_point": "the post's own focus"}, opportunity_summary="s",
                                               evidence=["e"], content_format="reel")  # SINGLE / REEL: the plan-level prompt
    slide = compile_instagram_generation_prompt(plan={"main_idea": "x"}, opportunity_summary="s", evidence=["e"], content_format="carousel",
                                                slide={"slide_copy": "Meta принесла Muse", "generation_brief": generation_brief({"slide_copy": "Meta"})})
    for prompt in (post, slide):
        assert "anonymous robot" in prompt and "brand-coloured dots" in prompt
    assert "FOCAL SUBJECT\nthe post's own focus" in post and "NO OUTDATED NNJ/NINJA BRANDING" in post  # the Director's own plan still leads


def _generated(name: str) -> Image.Image:
    path = GENERATED / name
    if not path.exists():
        pytest.skip(f"offline review picture {name} not present")
    return Image.open(path).convert("RGB")


def _generated_package(post: str, ref: str = "generated:images/test.png"):
    pkg = _package(post)
    media_plan = {**pkg.media_plan, "creative_execution_plan": {**pkg.media_plan["creative_execution_plan"], "media_strategy": "generated_media"},
                  "media_execution": {"strategy": "generated_media", "status": "generated_media", "assets": [{"asset_key": "primary", "media_mode": "GENERATED"}]}}
    return dataclasses.replace(pkg, source_image_ref=ref, media_candidate_id=None, media_plan=media_plan)


def test_a_generated_single_renders_full_bleed_and_passes_the_gate_even_though_the_source_was_rejected():
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_platform_renderer import render_instagram_feed_image

    pkg = _generated_package("live/2026-08-05_2_meme_trend")
    render = render_instagram_feed_image(pkg, source_image=_generated("single.png"))
    art = validate_instagram_art(pkg, [render])
    assert render.evidence.source_image_treatment != "none" and render.evidence.notes["layout_variant"] == "news_full_bleed"
    assert art.passed, art.blocking_issues
    missing = render_instagram_feed_image(pkg, source_image=None)
    assert any(i.startswith("generated_image_not_rendered") for i in validate_instagram_art(pkg, [missing]).blocking_issues)


def test_a_generated_reel_cover_keeps_its_hook_at_display_size_inside_the_grid_band():
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_platform_renderer import render_instagram_reel_cover

    pkg = _generated_package("live_reel_final/2026-08-10_2_meme_trend")
    render = render_instagram_reel_cover(pkg, source_image=_generated("reel.png"))
    top, bottom = render.evidence.notes["grid_safe_band"]
    boxes = [t.box for t in render.evidence.text_regions]
    assert render.evidence.notes["layout_variant"] == "reel_generated_hero" and render.evidence.source_image_treatment != "none"
    assert all(top <= b[1] and b[3] <= bottom for b in boxes) and min(b[3] - b[1] for b in boxes) >= 45 and not render.evidence.text_clipped
    assert validate_instagram_art(pkg, [render]).passed


def test_promoted_recap_slides_render_the_generated_picture_as_the_canvas_and_pass_the_gate():
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_creative_media import derive_image_identity
    from services.instagram_platform_renderer import render_instagram_carousel

    pkg = _package("preserved/weekly_recap")
    slides, _ = promote_no_photo_slides(copy.deepcopy(pkg.media_plan["slides"]), suitable_subjects=RECAP_SUITABLE, recap=True)
    pictures = {1: _generated("weekly_recap_slide_2.png"), 4: _generated("weekly_recap_slide_5.png")}
    stories = {}
    for path in sorted((REVIEW / "preserved/weekly_recap/story_media").glob("*.img")):
        image = Image.open(BytesIO(path.read_bytes())).convert("RGB")
        stories[path.stem] = (image, derive_image_identity(image))
    after = dataclasses.replace(pkg, media_plan={**pkg.media_plan, "slides": slides})
    renders = render_instagram_carousel(after, subject_assets=stories,
                                        slide_subject_assets={i: {"generated": (im, derive_image_identity(im))} for i, im in pictures.items()})
    for i in pictures:
        notes = renders[i].evidence.notes
        assert [m["subject"] for m in notes.get("media_regions") or []] == ["generated"] and not notes.get("editorial_variant")
    assert validate_instagram_art(after, renders).passed


# --- generation unavailable: text-led, still never cards --------------------------------------------------------------------------------

def test_without_generation_no_fact_card_survives_as_the_no_photo_visual():
    from services.instagram_platform_renderer import render_instagram_carousel

    renders = render_instagram_carousel(_package("preserved/carousel_adobe"), subject_assets={})
    assert all(r.evidence.notes.get("editorial_variant") for r in renders)  # every no-photo card became a designed typographic beat
