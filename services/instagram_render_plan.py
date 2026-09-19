"""Interpret Phase B creative plans as renderable primitives, with auditable evidence."""
from __future__ import annotations

from typing import Any

from services.instagram_carousel_layouts import select_media_primitive, select_slide_layout
from services.instagram_content_package import InstagramContentPackage


def _plan(package: InstagramContentPackage) -> dict[str, Any]:
    value = package.media_plan.get("creative_execution_plan")
    return value if isinstance(value, dict) else {}


def _text(plan: dict[str, Any]) -> str:
    return " ".join(str(plan.get(key) or "") for key in (
        "main_idea", "focal_point", "composition_direction", "visual_treatment",
        "source_vs_ai_decision", "avoid_repetition",
    )).lower()


def interpret_render_plan(
    package: InstagramContentPackage, *, slide: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate the existing plan into a small, deterministic set of compositional primitives."""
    plan = _plan(package)
    if not plan:
        return {
            "creative_plan": {},
            "render_interpretation": "",
            "used_primitives": ["legacy_layout"],
            "source_media_treatment": "legacy_selection",
            "typography_treatment": "legacy_hierarchy",
            "render_plan_applied": False,
            "audience_label": None,
        }
    signals = _text(plan)
    media = package.media_plan.get("media_execution") or {}
    plan_strategy = str(plan.get("media_strategy") or "")
    has_source = bool(package.source_image_ref or media.get("strategy") == "source" or plan_strategy == "source_media")
    fmt = package.content_format.value

    if fmt == "single":
        if media.get("strategy") == "typographic" or plan_strategy == "typographic" or "typograph" in signals or "типограф" in signals:
            family = "typographic_focal"
            primitives = ["field_background", "background_typography", "display_copy", "brand_anchor"]
            source_treatment = "none"
            typography = "display_symbol_plus_supporting_copy"
        elif has_source and any(word in signals for word in ("full", "hero", "cinematic", "полный", "герой", "кино")):
            family = "editorial_hero"
            primitives = ["full_bleed_image", "controlled_focal_crop", "readability_gradient", "overlap_typography", "brand_anchor"]
            source_treatment = "full_bleed_hero"
            typography = "image_anchored_display"
        elif has_source:
            family = "editorial_split"
            primitives = ["oversized_image_crop", "layered_panel", "display_copy", "brand_anchor"]
            source_treatment = "oversized_crop"
            typography = "display_plus_supporting"
        else:
            family = "typographic_focal"
            primitives = ["field_background", "background_typography", "display_copy", "brand_anchor"]
            source_treatment = "none"
            typography = "display_symbol_plus_supporting_copy"
    elif fmt == "carousel":
        # Phase B.3.1: `source_media_treatment`/`used_primitives` are no longer this function's OWN
        # independent, role-keyed guess - they are the exact SAME decision
        # `render_carousel_slide()` will make, computed here BEFORE rendering so the art validator
        # can later confirm the two agree (instagram_art_validator.py's own new check). Two parallel
        # classifiers that only coincidentally shared some family names was the root cause found in
        # the Phase B.3 forensic trace; this makes it one real decision, read from two places.
        s = slide or {}
        role = str(s.get("role") or "detail")
        index = int(s.get("index") or 0)
        slide_copy = str(s.get("text") or "")
        media_need = s.get("media_need")
        layout = select_slide_layout(role=role, index=index, slide_copy=slide_copy)
        primitive = select_media_primitive(layout=layout, media_need=media_need, has_media=has_source)
        family = layout
        primitives = ["progress_marker", "brand_anchor", primitive.value]
        source_treatment = primitive.value
        typography = "display" if role.strip().lower() in {"hook", "problem", "takeaway", "cta"} else "supporting_editorial"
    elif fmt == "reel":
        if has_source:
            family = "reel_recomposed_source"
            primitives = ["blurred_source_field", "masked_source_crop", "solid_copy_panel", "display_copy", "brand_anchor"]
            source_treatment = "masked_detail_crop"
            typography = "center_safe_display"
        else:
            family = "reel_typographic"
            primitives = ["field_background", "motion_cue", "display_copy", "brand_anchor"]
            source_treatment = "none"
            typography = "center_safe_display"
    else:
        family = "unsupported"
        primitives = []
        source_treatment = "none"
        typography = "none"

    return {
        "creative_plan": {
            "main_idea": plan.get("main_idea"),
            "focal_point": plan.get("focal_point"),
            "composition_direction": plan.get("composition_direction"),
            "visual_treatment": plan.get("visual_treatment"),
        },
        "render_interpretation": family,
        "used_primitives": primitives,
        "source_media_treatment": source_treatment,
        "typography_treatment": typography,
        "render_plan_applied": True,
        "audience_label": None,
    }
