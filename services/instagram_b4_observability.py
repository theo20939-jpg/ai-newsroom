"""Phase B.4.2 section 12: audit record for one generated carousel. Diagnostic metadata only -
stored in `media_plan["b4_observability"]`, never rendered into any post copy, never containing a
secret. Every value is read from what actually happened (render evidence / resolver identities),
not from what the plan requested."""
from __future__ import annotations

from typing import Any, Sequence

from services.instagram_layout_signature import infer_family


def build_b4_observability(
    *, carousel: Any, prompt_version: str, renders: Sequence[Any], art: Any,
    slide_identities: dict[int, str], deliberate_fallback_subjects: Sequence[str] = (),
    model_emitted_archetype: str | None = None, archetype_correction_required: bool = False,
) -> dict[str, Any]:
    slides = []
    for index, (slide, render) in enumerate(zip(carousel.slides, renders)):
        notes = render.evidence.notes
        chosen_family = getattr(slide, "visual_family", None)
        layout_model = getattr(slide, "layout", None)
        executed_family = (
            infer_family(layout_model.model_dump()) if notes.get("layout_plan_applied") and layout_model is not None else "legacy_role_fallback"
        )
        slides.append({
            "visual_family_chosen": chosen_family,
            "visual_family_executed": executed_family,
            "visual_family_matches": bool(chosen_family) and chosen_family == executed_family,
            "index": index,
            "media_subject": slide.media_subject,
            "resolved_asset_identity": slide_identities.get(index),
            "layout_variant": notes.get("layout_variant"),
            "layout_plan_applied": bool(notes.get("layout_plan_applied")),
            "layout_plan_rejected": notes.get("layout_plan_rejected"),
            "layout_signature": notes.get("layout_signature"),
            "layout_adaptations": notes.get("layout_adaptations") or [],
            "media_function": getattr(slide, "media_function", None),
            "media_regions": notes.get("media_regions") or [],
            "unresolved_media_regions": notes.get("unresolved_media_regions") or [],
            "overlay_operations_executed": int(notes.get("overlay_operations_executed") or 0),
            "source_media_pixels_unaltered": notes.get("source_media_pixels_unaltered"),
            "graphic_fallback_used": bool(notes.get("graphic_fallback_used")),
            "composition_adapted_for_text_fit": bool(notes.get("composition_adapted_for_text_fit")),
            "calm_zone_requested": notes.get("calm_zone_requested"),
            "calm_zone_executed": notes.get("calm_zone_executed"),
            "calm_zone_adapted": bool(notes.get("calm_zone_adapted")),
            "collage_geometry_adapted": notes.get("collage_geometry_adapted"),
            "collage_adaptation_reasons": notes.get("collage_adaptation_reasons"),
            "requested_media_regions": notes.get("requested_media_regions"),
            "executed_media_regions": notes.get("executed_media_regions"),
            "max_region_displacement": notes.get("max_region_displacement"),
            "max_scale_change": notes.get("max_scale_change"),
            "structured_composition_present": bool(notes.get("structured_composition_present")),
            "structured_composition_executed": bool(notes.get("structured_composition_executed")),
            "role_fallback_used": bool(notes.get("fallback_role_layout_used")),
        })
    return {
        "content_archetype": carousel.content_archetype,
        "model_emitted_archetype": model_emitted_archetype,
        "archetype_correction_required": archetype_correction_required,
        "prompt_version": prompt_version,
        "slide_count": len(carousel.slides),
        "overlay_operations_executed_total": sum(s["overlay_operations_executed"] for s in slides),
        "structured_composition_present": any(s["structured_composition_present"] for s in slides),
        "structured_composition_executed": any(s["structured_composition_executed"] for s in slides),
        "role_fallback_used": any(s["role_fallback_used"] for s in slides),
        "slides": slides,
        "deliberate_fallback_subjects": list(deliberate_fallback_subjects),
        "art_validation_passed": bool(art.passed),
        "art_blocking_issues": list(getattr(art, "blocking_issues", []) or []),
        "art_warnings": list(getattr(art, "warnings", []) or []),
    }
