"""Autonomous Product Quality Loop, iteration 6: defects read off the real iteration-5 pixels.

- a narrow side column held a long Russian word at ~71px and left most of the column empty (8 of 20 real slides);
- a `standard` slide pasted the SAME generated photo twice, escaping the one-media adapter with a 50px headline;
- the TREND closer's copy "От $149. Остальное — детали." rendered as "От $." once the numeral was set in type;
- the image prompt handed the model "a large red 149 anchors the left side", and the picture came back with a painted "49"."""
from __future__ import annotations

from PIL import Image

from services import instagram_creative_media as media
from services.instagram_carousel_layouts import HOOK_HEADLINE_FLOOR_FRAC, render_carousel_slide
from services.instagram_layout_validation import copy_parts
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

SPEC = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)


def _region(kind, x, y, w, h, **kw):
    return {"kind": kind, "x": x, "y": y, "w": w, "h": h, "z": kw.pop("z", 1), **kw}


def _render(layout, copy, index=3, total=4):
    img = Image.new("RGB", (1024, 1280), (150, 140, 130))
    return render_carousel_slide(spec=SPEC, role="takeaway", index=index, total=total, slide_copy=copy, source_evidence=None, package_identity="p",
                                 media_image=img, media_mode="GENERATED", layout_plan=layout, subject_assets={"generated": (img, "id")})


def _headline_px(result):
    return max(m["font_px"] for m in result.notes["text_metrics"] if m["ref"] in ("copy", "copy_lead", "copy_no_number"))


# the EXACT real iteration-5 NEWS_INSIGHT closer: short copy, one long word, image on the right
REAL_INSIGHT_CLOSER = {
    "background": "soft", "density": "LOW", "media_dominance": "BALANCED", "visual_weight": "MIXED", "show_progress": False,
    "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="soft", frame="none"),
        _region("text", 0.07, 0.19, 0.4, 0.16, z=3, content_ref="copy", scale_token="HEADLINE_XL", align="left", valign="top", max_lines=2,
                tone="primary", on_media=False),
        _region("accent", 0.07, 0.41, 0.16, 0.025, z=3, accent_type="rule_h", tone="accent", on_media=False),
        _region("media", 0.5, 0.08, 0.46, 0.82, z=2, content_ref="generated", surface="media_ground", crop_mode="cover", focus_x=0.58,
                focus_y=0.52, frame="none", on_media=False),
    ],
}

# the EXACT real iteration-5 TREND slide 3: one generated photo, then a tilted small copy of the SAME photo
REAL_TREND_DUPLICATE = {
    "background": "paper", "density": "LOW", "media_dominance": "BALANCED", "visual_weight": "MIXED", "show_progress": False,
    "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="paper"),
        _region("media", 0.46, 0.08, 0.49, 0.58, content_ref="generated", crop_mode="cover", frame="none"),
        _region("media", 0.64, 0.68, 0.25, 0.22, z=2, content_ref="generated", crop_mode="cover", frame="paper", tilt_deg=-4),
        _region("text", 0.06, 0.18, 0.34, 0.24, z=3, content_ref="copy", scale_token="HEADLINE_M", align="left", valign="top", tone="primary",
                on_media=False),
        _region("accent", 0.06, 0.14, 0.14, 0.02, z=3, accent_type="rule_h", tone="accent"),
    ],
}


def test_a_side_column_that_cannot_hold_display_type_yields_to_the_full_width_band():
    result = _render(REAL_INSIGHT_CLOSER, "Выбор начинается с задачи.")
    assert result.notes["media_scale_orientation"] in ("text_top", "text_bottom")
    assert _headline_px(result) >= HOOK_HEADLINE_FLOOR_FRAC * SPEC.width


def test_a_side_column_that_does_hold_display_type_is_kept():
    result = _render(REAL_INSIGHT_CLOSER, "Итог: ясно")
    assert result.notes["media_scale_orientation"] == "side_right"
    assert _headline_px(result) >= HOOK_HEADLINE_FLOOR_FRAC * SPEC.width


def test_the_same_asset_pasted_twice_on_a_standard_slide_is_one_picture_and_gets_scaled():
    result = _render(REAL_TREND_DUPLICATE, "Ещё два акцента: версии и датчики", index=2)
    assert result.notes.get("media_scale_adapted") is True
    assert len(result.notes.get("media_regions") or []) == 1
    assert _headline_px(result) >= HOOK_HEADLINE_FLOOR_FRAC * SPEC.width


def test_the_currency_travels_with_its_amount_and_a_content_free_fragment_is_dropped():
    parts = copy_parts("От $149. Остальное — детали.")
    assert parts["number"] == "$149"
    assert parts["copy_no_number"] == "Остальное — детали"
    assert "$" not in parts["copy_no_number"]
    kept = copy_parts("Вместо 20 минут — 30 секунд")  # the residue carries meaning: only the numeral goes
    assert kept["number"] == "20" and kept["copy_no_number"] == "Вместо минут — 30 секунд"
    assert copy_parts("Цена 99 ₽")["number"] == "99 ₽"
    assert copy_parts("Рост 40%")["number"] == "40%"


def test_the_image_prompt_never_asks_for_the_numeral_the_renderer_sets_in_type():
    slide = {
        "slide_copy": "От $149. Остальное — детали.", "visual_family": "dark_type_number_statement", "media_function": "result",
        "generation_brief": "Close-up of a smartwatch-like object bleeding off the right edge. Leave the left quiet for a large price numeral.",
        "story_anchor": "The stated starting price of $149 is the final focal fact beside the watch object.",
        "visual_direction": "A generated final frame shows the watch cropped across the right edge, while a large red 149 anchors the left side.",
    }
    prompt = media.compile_instagram_generation_prompt(plan={}, opportunity_summary="Часы от $149", evidence=["Цена от $149"], content_format="carousel", slide=slide)
    scene = prompt.split("SPECIFIC SCENE TO DEPICT", 1)[1].split("Slide purpose", 1)[0]
    assert "149" not in scene
    assert media._TYPESET_MASK in scene
    assert "WHAT MUST BE PHYSICALLY VISIBLE" in prompt and "typography the application adds" in prompt


def test_single_digit_scene_counts_are_not_masked():
    assert media._mask_typeset("three cards and 3 straps", "3") == "three cards and 3 straps"
    assert media._mask_typeset("a price tag of 1490 next to 149", "149") == f"a price tag of 1490 next to {media._TYPESET_MASK}"


# the EXACT real iteration-6 AI_HACK slide 3: a small headline box on a large framed image, rejected (text_region_too_small)
REAL_AI_HACK_STEP = {
    "background": "graphite", "density": "HIGH", "media_dominance": "DOMINANT", "visual_weight": "MEDIA", "show_progress": True,
    "palette": "neo", "logo_position": "BOTTOM_LEFT", "arrangement": "standard",
    "regions": [
        _region("surface", 0, 0, 1, 1, z=0, surface="graphite"),
        _region("media", 0.05, 0.08, 0.9, 0.84, content_ref="generated", crop_mode="cover", focus_x=0.56, focus_y=0.5, frame="paper",
                on_media=False, tilt_deg=0),
        _region("text", 0.09, 0.14, 0.4, 0.16, z=2, content_ref="copy", scale_token="HEADLINE_L", align="left", valign="top", max_lines=2,
                tone="primary", on_media=True),
        _region("text", 0.84, 0.84, 0.08, 0.08, z=2, content_ref="number", scale_token="NUMERAL", align="right", valign="bottom", max_lines=1,
                tone="accent", on_media=True),
    ],
}


def test_rejected_plan_is_rescued_by_a_band_when_the_default_orientation_fails():
    # the default rescue collides with the BOTTOM_LEFT logo; a full-width band must still compete instead of the small fallback
    result = _render(REAL_AI_HACK_STEP, "Шаг 2. Собери чек-лист", index=2)
    assert not result.notes.get("media_preserving_fallback_used")
    assert result.notes.get("media_scale_rescued_rejected_plan") == ["text_region_too_small"]
    assert _headline_px(result) >= HOOK_HEADLINE_FLOOR_FRAC * SPEC.width
