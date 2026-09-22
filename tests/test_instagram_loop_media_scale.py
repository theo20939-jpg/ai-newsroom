"""Autonomous Product Quality Loop, iteration 1: media scale + headline floor (services.instagram_media_scale_adapter,
services.instagram_carousel_layouts._try_declared) and prompt v10.4."""
from __future__ import annotations

import random
from pathlib import Path

import yaml
from PIL import Image

from schemas.instagram_creative import InstagramSlideLayout
from services.instagram_carousel_layouts import HEADLINE_FLOOR_FRAC, render_carousel_slide
from services.instagram_layout_validation import validate_layout
from services.instagram_media_scale_adapter import MIN_MEDIA_AREA, adapt_media_scale
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

SPEC = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
PROMPTS = Path(__file__).resolve().parent.parent / "prompts" / "instagram_creative_director_carousel"


def _region(kind, x, y, w, h, **kw):
    base = {"kind": kind, "x": x, "y": y, "w": w, "h": h, "z": kw.pop("z", 1)}
    return {**base, **kw}


def _busy(seed=1, size=(1024, 1280)):
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    return img


def _plain(colour=(120, 110, 100)):
    return Image.new("RGB", (1024, 1280), colour)


# the EXACT real iteration-0 AI_HACK hook geometry: a framed 0.34 x 0.62 inset beside a 0.43-wide text column
REAL_AI_HACK_HOOK = {
    "background": "ink", "density": "LOW", "media_dominance": "BALANCED", "visual_weight": "MIXED", "show_progress": True,
    "palette": "neo", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="ink"),
        _region("media", 0.57, 0.13, 0.34, 0.62, content_ref="generated", crop_mode="cover", focus_x=0.58, focus_y=0.5, frame="paper"),
        _region("accent", 0.08, 0.17, 0.12, 0.025, z=2, accent_type="rule_h", tone="accent"),
        _region("text", 0.08, 0.23, 0.43, 0.25, z=2, content_ref="copy", scale_token="HEADLINE_XL", align="left", valign="top", max_lines=3,
                tone="primary", on_media=False),
    ],
}
REAL_AI_HACK_COPY = "Тебе нужен не длинный текст, а понятное решение."


def _render(layout, copy, *, mode="GENERATED", image=None, key="generated"):
    img = image if image is not None else _plain()
    return render_carousel_slide(spec=SPEC, role="hook", index=0, total=4, slide_copy=copy, source_evidence=None, package_identity="p",
                                 media_image=img, media_mode=mode, layout_plan=layout, subject_assets={key: (img, "id")})


def _headline_px(result):
    return max(m["font_px"] for m in result.notes["text_metrics"] if m["ref"] in ("copy", "copy_lead", "copy_no_number"))


def test_the_real_small_inset_is_re_laid_edge_to_edge_and_the_headline_grows():
    plan = InstagramSlideLayout.model_validate(REAL_AI_HACK_HOOK)
    before = render_carousel_slide(spec=SPEC, role="hook", index=0, total=4, slide_copy=REAL_AI_HACK_COPY, source_evidence=None,
                                   package_identity="p", media_image=_plain(), media_mode=None, layout_plan=REAL_AI_HACK_HOOK,
                                   subject_assets={"generated": (_plain(), "id")})
    after = _render(REAL_AI_HACK_HOOK, REAL_AI_HACK_COPY)
    assert after.notes["media_scale_adapted"] is True and "media_scale_adapted" in after.notes["layout_adaptations"]
    assert after.notes["media_canvas_coverage"] >= MIN_MEDIA_AREA > before.notes["media_canvas_coverage"]
    assert _headline_px(after) >= 1.8 * _headline_px(before)
    assert after.notes["visual_preserved"] is True and after.notes["overlay_operations_executed"] == 0
    adaptation = adapt_media_scale(plan, slide_copy=REAL_AI_HACK_COPY)
    media = next(r for r in adaptation.layout.regions if r.kind == "media")
    assert media.frame == "none" and media.crop_mode == "cover"
    assert validate_layout(adaptation.layout, slide_copy=REAL_AI_HACK_COPY, resolvable_subjects={"generated"}).accepted


def test_a_non_media_slide_is_never_rescaled():
    after = _render(REAL_AI_HACK_HOOK, REAL_AI_HACK_COPY, mode=None)
    assert not after.notes.get("media_scale_adapted")


def test_short_copy_beside_the_image_gets_a_full_height_side_panel():
    plan = InstagramSlideLayout.model_validate(REAL_AI_HACK_HOOK)
    adaptation = adapt_media_scale(plan, slide_copy="Титан и сапфир")
    assert adaptation.orientation == "side_right"
    media = next(r for r in adaptation.layout.regions if r.kind == "media")
    assert media.y == 0 and media.h == 1 and media.x + media.w == 1


def test_large_media_collage_hero_object_and_graphic_slides_are_untouched():
    big = {**REAL_AI_HACK_HOOK, "regions": [
        REAL_AI_HACK_HOOK["regions"][0],
        _region("media", 0, 0.4, 1, 0.6, content_ref="generated", crop_mode="cover"),
        _region("text", 0.08, 0.08, 0.84, 0.28, z=2, content_ref="copy", scale_token="HEADLINE_XL", on_media=False),
    ]}
    assert adapt_media_scale(InstagramSlideLayout.model_validate(big), slide_copy=REAL_AI_HACK_COPY) is None
    collage = {**REAL_AI_HACK_HOOK, "arrangement": "collage"}
    assert adapt_media_scale(InstagramSlideLayout.model_validate(collage), slide_copy=REAL_AI_HACK_COPY) is None
    staged = {**REAL_AI_HACK_HOOK, "arrangement": "stage", "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="media_ground", content_ref="generated"),
        _region("media", 0.5, 0.2, 0.4, 0.6, content_ref="generated", crop_mode="object_contain"),
        REAL_AI_HACK_HOOK["regions"][3],
    ]}
    assert adapt_media_scale(InstagramSlideLayout.model_validate(staged), slide_copy=REAL_AI_HACK_COPY) is None
    graphic = {**REAL_AI_HACK_HOOK, "regions": [*REAL_AI_HACK_HOOK["regions"], _region("graphic", 0.08, 0.55, 0.4, 0.2, graphic_type="ui_frame")]}
    assert adapt_media_scale(InstagramSlideLayout.model_validate(graphic), slide_copy=REAL_AI_HACK_COPY) is None


def test_an_object_on_a_plain_surface_is_not_treated_as_a_staged_hero():
    """real TREND_GENERATIVE iteration-0 shape: object_contain on a graphite surface (no media_ground) rendered as a visible inset box"""
    plan = {**REAL_AI_HACK_HOOK, "arrangement": "stage", "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="graphite"),
        _region("media", 0.5, 0.18, 0.46, 0.7, content_ref="generated", crop_mode="object_contain"),
        REAL_AI_HACK_HOOK["regions"][3],
    ]}
    adaptation = adapt_media_scale(InstagramSlideLayout.model_validate(plan), slide_copy="Титан и сапфир — а старт от $149")
    assert adaptation is not None and adaptation.layout.arrangement == "standard"


def test_a_rejected_media_first_plan_is_rebuilt_edge_to_edge_instead_of_the_small_fallback():
    rejected = {**REAL_AI_HACK_HOOK, "regions": [
        REAL_AI_HACK_HOOK["regions"][0],
        _region("media", 0.1, 0.1, 0.8, 0.6, content_ref="generated", crop_mode="cover"),
        _region("text", 0.1, 0.05, 0.7, 0.12, z=2, content_ref="copy", scale_token="HEADLINE_XL", on_media=False),  # overlaps the media
    ]}
    assert not validate_layout(InstagramSlideLayout.model_validate(rejected), slide_copy="И ещё две версии корпуса.",
                               resolvable_subjects={"generated"}).accepted
    result = _render(rejected, "И ещё две версии корпуса.")
    assert result.notes["media_scale_adapted"] is True and result.notes["media_scale_rescued_rejected_plan"]
    assert result.notes["media_preserving_fallback_used"] is False and result.notes["visual_preserved"] is True


def test_a_headline_squeezed_below_display_size_gets_a_solid_band_and_grows():
    """real NEWS_INSIGHT iteration-0 hook shape (rendered at 39px): immersive image, a small on-media box for a 47-character line"""
    immersive = {**REAL_AI_HACK_HOOK, "regions": [
        _region("media", 0, 0, 1, 1, content_ref="source", crop_mode="cover"),
        _region("text", 0.35, 0.1, 0.57, 0.12, z=2, content_ref="copy", scale_token="HEADLINE_XL", on_media=True),
    ]}
    img = _plain((20, 20, 24))
    result = _render(immersive, "Самая дорогая модель — уже не план по умолчанию.", mode="SOURCE", image=img, key="source")
    assert result.notes["media_scale_reason"] == "headline_below_floor"
    assert result.notes["headline_px_before"] < HEADLINE_FLOOR_FRAC * SPEC.width <= _headline_px(result)


def test_prompt_v10_4_changes_exactly_the_three_copy_and_scale_rules():
    v103 = yaml.safe_load((PROMPTS / "v10.3.yaml").read_text(encoding="utf-8"))
    v104 = yaml.safe_load((PROMPTS / "v10.4.yaml").read_text(encoding="utf-8"))
    assert v104["version"] == "10.4" and v104["output_schema"] == v103["output_schema"] and v104["system"] == v103["system"]
    changed = [b for a, b in zip(v103["rules"], v104["rules"]) if a != b]
    assert len(v103["rules"]) == len(v104["rules"]) and len(changed) == 3
    joined = " ".join(changed)
    assert "2 to 7 words" in joined and "at least half of the canvas" in joined and "about 70 characters" not in joined


# ------------------------------------------------------------------------------------------ iteration 2 (real iteration-1 findings)


def test_a_rejected_staged_object_plan_is_rebuilt_not_sent_to_the_small_caption_fallback():
    """real NEWS_RECAP 'Watch 6' slide: object_contain on a media_ground stage, rejected for text_over_media"""
    staged = {**REAL_AI_HACK_HOOK, "arrangement": "stage", "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="media_ground", content_ref="generated"),
        _region("media", 0.32, -0.08, 0.76, 0.9, content_ref="generated", crop_mode="object_contain"),
        _region("text", 0.07, 0.13, 0.48, 0.18, z=2, content_ref="copy", scale_token="HEADLINE_L", on_media=False),
    ]}
    result = _render(staged, "Watch 6: титан, сапфир, eSIM")
    assert result.notes["media_scale_adapted"] is True and result.notes["media_preserving_fallback_used"] is False


def test_an_unbreakable_name_in_a_side_column_moves_to_a_full_width_band():
    """real NEWS_RECAP slide: 'AliceAI-Foundation' cannot break, so the side column rendered it at 43px"""
    result = render_carousel_slide(spec=SPEC, role="story", index=5, total=8, slide_copy="Яндекс открыл AliceAI-Foundation", source_evidence=None,
                                   package_identity="p", media_image=_plain(), media_mode="GENERATED", layout_plan=REAL_AI_HACK_HOOK,
                                   subject_assets={"generated": (_plain(), "id")})
    assert result.notes["media_scale_orientation"] in ("text_top", "text_bottom")
    assert _headline_px(result) >= HEADLINE_FLOOR_FRAC * SPEC.width


def test_the_hook_has_a_higher_floor_than_later_slides():
    from services.instagram_carousel_layouts import HOOK_HEADLINE_FLOOR_FRAC, _headline_floor
    assert _headline_floor(SPEC, 0) == HOOK_HEADLINE_FLOOR_FRAC * SPEC.width > _headline_floor(SPEC, 3) == HEADLINE_FLOOR_FRAC * SPEC.width


def test_prompt_v10_5_changes_only_the_hook_rule():
    v104 = yaml.safe_load((PROMPTS / "v10.4.yaml").read_text(encoding="utf-8"))
    v105 = yaml.safe_load((PROMPTS / "v10.5.yaml").read_text(encoding="utf-8"))
    changed = [(a, b) for a, b in zip(v104["rules"], v105["rules"]) if a != b]
    assert v105["version"] == "10.5" and v105["output_schema"] == v104["output_schema"] and len(changed) == 1
    old, new = changed[0]
    assert new.startswith("HOOK CONTRACT (slide 1).") and new.startswith(old[:200]) and "NEVER reuse, translate or paraphrase" in new
