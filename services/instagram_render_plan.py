"""Interpret Phase B creative plans as renderable primitives, with auditable evidence."""
from __future__ import annotations

from typing import Any

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

    generated = media.get("strategy") == "generated_media"
    if fmt == "single":
        if generated:  # no suitable photo => the generated editorial image is the hero, full bleed
            family = "editorial_hero"
            primitives = ["full_bleed_image", "controlled_focal_crop", "readability_gradient", "overlap_typography", "brand_anchor"]
            source_treatment = "full_bleed_hero"
            typography = "image_anchored_display"
        elif media.get("strategy") == "typographic" or plan_strategy == "typographic" or "typograph" in signals or "типограф" in signals:
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
        # Phase B.4.4: one composition dispatch, light surfaces, no media-darkening primitives. The
        # per-slide decision lives in services/instagram_carousel_layouts.py; this record only
        # states the family so evidence stays truthful (no predicted-vs-executed media primitive).
        s = slide or {}
        role = str(s.get("role") or "detail")
        family = "carousel_composition"
        primitives = ["progress_marker", "brand_anchor"]
        source_treatment = "generic_composition"
        typography = "display" if role.strip().lower() in {"hook", "problem", "takeaway", "cta"} else "supporting_editorial"
    elif fmt == "reel":
        if generated:  # a generated cover picture: full bleed under the hook, not a screenshot recomposition
            family = "reel_generated_hero"
            primitives = ["full_bleed_image", "grid_band_veil", "display_copy", "brand_anchor"]
            source_treatment = "full_bleed_hero"
            typography = "center_safe_display"
        elif has_source:
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
