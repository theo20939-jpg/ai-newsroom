"""Content, hooks & virality pass (prompt v10.7): a slide is a HEADLINE plus, when the story needs it, an explanatory BODY.

Founder review of the completed iteration-6 set: the slides looked good but said almost nothing ("Он сменил критерий", "Сначала задача.
Потом модель.", "И ещё: пульс и кислород."). Root cause: the prompt capped every slide at one short line and pushed all explanation into the
caption, and there was no field for explanatory text. These tests pin the new contract end to end, zero provider calls."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml
from PIL import Image

import services.instagram_creative_director as cd
from schemas.instagram_creative import InstagramCarouselSlideCreative, InstagramSlideLayout
from services import instagram_creative_media as media
from services.instagram_body_copy import attach_body_region
from services.instagram_carousel_layouts import HOOK_HEADLINE_FLOOR_FRAC, render_carousel_slide
from services.instagram_layout_validation import compose_slide_text, copy_parts, validate_layout
from services.instagram_media_first import MediaFirstContractError, assert_information_density, find_thin_slides, has_concrete_anchor
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

ROOT = Path(__file__).resolve().parent.parent
SPEC = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)


def _region(kind, x, y, w, h, **kw):
    return {"kind": kind, "x": x, "y": y, "w": w, "h": h, "z": kw.pop("z", 1), **kw}


# the real iteration-6r NEWS_RECAP "Claude Code" slide: a declared side column on paper beside a generated image
SIDE_COLUMN = {
    "background": "paper", "density": "MEDIUM", "media_dominance": "BALANCED", "visual_weight": "MIXED", "show_progress": False,
    "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="paper"),
        _region("media", 0.46, 0.0, 0.54, 1.0, content_ref="generated", crop_mode="cover", frame="none"),
        _region("text", 0.07, 0.18, 0.33, 0.2, z=2, content_ref="copy", scale_token="HEADLINE_L", align="left", valign="top", tone="primary",
                on_media=False),
        _region("accent", 0.07, 0.14, 0.11, 0.02, z=2, accent_type="rule_h", tone="accent"),
    ],
}
# a text_top band directly on top of a large image band: no free space under the headline
BAND = {
    "background": "ink", "density": "MEDIUM", "media_dominance": "DOMINANT", "visual_weight": "MIXED", "show_progress": False,
    "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="ink"),
        _region("text", 0.07, 0.12, 0.86, 0.18, z=2, content_ref="copy", scale_token="HEADLINE_XL", align="left", valign="top", tone="primary",
                on_media=False),
        _region("media", 0.0, 0.32, 1.0, 0.68, content_ref="generated", crop_mode="cover", frame="none"),
    ],
}
BODY = "Это формат инструкций для ИИ-агентов, который предложила OpenAI. Anthropic поддержала стандарт конкурента."


def test_copy_parts_splits_headline_and_body_and_derives_everything_else_from_the_headline_only():
    parts = copy_parts(compose_slide_text("Шаг 2. Собери чек-лист", "Попроси уложить вывод в 3 пункта."))
    assert parts["copy"] == "Шаг 2. Собери чек-лист" and parts["number"] == "2" and parts["copy_no_number"] == "Собери чек-лист"
    assert parts["body"] == "Попроси уложить вывод в 3 пункта."
    assert copy_parts("$149 — и титан?")["body"] == "" and compose_slide_text("Заголовок", None) == "Заголовок"


def test_body_goes_under_the_headline_in_the_same_column():
    layout, how = attach_body_region(SIDE_COLUMN, compose_slide_text("Claude Code теперь понимает AGENTS.md", BODY))
    body = next(r for r in layout["regions"] if r.get("content_ref") == "body")
    headline = next(r for r in layout["regions"] if r.get("content_ref") == "copy")
    assert how == "below_headline" and body["x"] == headline["x"] and body["w"] == headline["w"]
    assert body["y"] >= headline["y"] + headline["h"] and body["y"] + body["h"] <= 0.93 and body["scale_token"] == "BODY"
    assert attach_body_region(SIDE_COLUMN, "Без тела") == (SIDE_COLUMN, None)  # no body: the plan is untouched


def test_no_room_under_the_headline_moves_the_image_band_down_but_keeps_it_large():
    layout, how = attach_body_region(BAND, compose_slide_text("Права в Apple Wallet: скоро ещё три штата", "Функция только что заработала в "
                                                                "Вирджинии и Оклахоме. С новыми штатами их будет почти 20."))
    media_region = next(r for r in layout["regions"] if r["kind"] == "media")
    assert how == "media_moved_down" and media_region["h"] >= 0.34 and media_region["y"] + media_region["h"] == pytest.approx(1.0)
    assert validate_layout(InstagramSlideLayout.model_validate(layout), slide_copy=compose_slide_text("Права", "Функция заработала."),
                           resolvable_subjects={"generated"}).accepted


def test_a_body_without_a_text_region_is_never_silently_dropped():
    validated = validate_layout(InstagramSlideLayout.model_validate(SIDE_COLUMN), slide_copy=compose_slide_text("Claude Code", BODY),
                                resolvable_subjects={"generated"})
    assert not validated.accepted and "copy_not_fully_presented" in validated.rejection_codes


def test_a_rendered_slide_shows_the_body_under_a_display_size_headline():
    img = Image.new("RGB", (1024, 1536), (120, 110, 100))
    result = render_carousel_slide(spec=SPEC, role="story", index=6, total=8, slide_copy="Claude Code теперь понимает AGENTS.md", slide_body=BODY,
                                   source_evidence=None, package_identity="p", media_image=img, media_mode="GENERATED", layout_plan=SIDE_COLUMN,
                                   subject_assets={"generated": (img, "id")})
    metrics = {m["ref"]: m for m in result.notes["text_metrics"]}
    assert "body" in metrics and not result.text_clipped and result.notes["fallback_role_layout_used"] is False
    # a narrow declared column below the hook display floor is rebuilt when that makes the headline larger (real iteration-6r recap:
    # this exact column rendered its headline at 67px and read as a caption)
    assert result.notes["media_scale_reason"] == "headline_below_floor" and result.notes["headline_px_before"] == 67
    assert metrics["copy"]["font_px"] > 67 and HOOK_HEADLINE_FLOOR_FRAC * SPEC.width > 67


@pytest.mark.parametrize("headline", ["Он сменил критерий", "Сначала задача. Потом модель.", "Считал не интеллект. Считал задачу.",
                                      "И ещё: пульс и кислород."])
def test_the_founders_empty_examples_are_thin_without_a_body(headline):
    slides = [{"slide_copy": "$149 — и титан?"}, {"slide_copy": headline}]
    assert len(find_thin_slides(slides)) == 1
    with pytest.raises(MediaFirstContractError, match="make sense without the caption"):
        assert_information_density(slides)
    slides[1]["slide_body"] = "Главным критерием он выбрал стоимость выполненной задачи, а не рейтинг."
    assert find_thin_slides(slides) == []


def test_hook_needs_a_concrete_anchor_or_a_body_and_a_step_label_is_not_one():
    assert find_thin_slides([{"slide_copy": "Длинный текст. Чек-лист короткий."}, {"slide_copy": "x", "slide_body": "один два три четыре пять шесть"}])
    assert has_concrete_anchor("Уровень GPT-5.6 Sol — за 1% цены") and has_concrete_anchor("$149 — и титан?")
    assert not has_concrete_anchor("Шаг 1. Оставь только решения")
    # a full, anchored statement may stand without a body
    assert find_thin_slides([{"slide_copy": "$149"}, {"slide_copy": "OpenAI запустила GPT-6 Sol и Luna, и это уже вторая модель за месяц"}]) == []


def test_schema_carries_body_and_the_guards_read_it():
    slide = InstagramCarouselSlideCreative(role="story", slide_copy="Заголовок", slide_body="Тело", visual_direction="v")
    assert slide.slide_body == "Тело"
    source = inspect.getsource(cd._validate_carousel_output)
    for guard in ("text_fields", "_enforce_output_policy", "assert_no_meta_language", "assert_no_unsupported_clickbait"):
        assert guard in source
    assert source.count("slide_body") >= 4  # fact safety, output policy, meta-language and clickbait all read the body


def test_v10_7_is_active_and_is_exactly_what_its_generator_builds():
    import scripts._instagram_make_prompt_v10_7 as gen

    assert cd.CAROUSEL_PROMPT_VERSION == "10.9" and "10.7" in cd.BODY_COPY_CAROUSEL_VERSIONS and "10.7" in cd._EVIDENCE_HANDLE_CAROUSEL_VERSIONS
    committed = yaml.safe_load((ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.7.yaml").read_text(encoding="utf-8"))
    assert committed == gen.build()
    text = "\n".join(committed["rules"])
    assert "Instagram copy is SHORT" not in text and "2 to 7 words" not in text  # the caps that produced empty slides are gone
    schema = committed["output_schema"]
    assert "editorial_angle" in schema["required"] and "slide_body" in schema["properties"]["slides"]["items"]["required"]


def test_image_prompt_forbids_pseudo_writing_and_false_specificity():
    prompt = media.compile_instagram_generation_prompt(plan={}, opportunity_summary="s", evidence=["e"], content_format="carousel",
                                                       slide={"generation_brief": "a hand holding a phone above three state-shaped cards"})
    assert "no handwriting" in prompt and "no recognisable map or state outlines" in prompt
