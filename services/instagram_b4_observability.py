"""Phase B.4.2 section 12: audit record for one generated carousel. Diagnostic metadata only -
stored in `media_plan["b4_observability"]`, never rendered into any post copy, never containing a
secret. Every value is read from what actually happened (render evidence / resolver identities),
not from what the plan requested."""
from __future__ import annotations

from typing import Any, Sequence


def build_b4_observability(
    *, carousel: Any, prompt_version: str, renders: Sequence[Any], art: Any,
    slide_identities: dict[int, str], deliberate_fallback_subjects: Sequence[str] = (),
) -> dict[str, Any]:
    slides = []
    for index, (slide, render) in enumerate(zip(carousel.slides, renders)):
        notes = render.evidence.notes
        slides.append({
            "index": index,
            "media_subject": slide.media_subject,
            "resolved_asset_identity": slide_identities.get(index),
            "overlay_mode": slide.overlay_mode,
            "structured_composition_present": bool(notes.get("structured_composition_present")),
            "structured_composition_executed": bool(notes.get("structured_composition_executed")),
            "role_fallback_used": bool(notes.get("fallback_role_layout_used")),
        })
    return {
        "content_archetype": carousel.content_archetype,
        "prompt_version": prompt_version,
        "slide_count": len(carousel.slides),
        "structured_composition_present": any(s["structured_composition_present"] for s in slides),
        "structured_composition_executed": any(s["structured_composition_executed"] for s in slides),
        "role_fallback_used": any(s["role_fallback_used"] for s in slides),
        "slides": slides,
        "deliberate_fallback_subjects": list(deliberate_fallback_subjects),
        "art_validation_passed": bool(art.passed),
        "art_blocking_issues": list(getattr(art, "blocking_issues", []) or []),
    }
