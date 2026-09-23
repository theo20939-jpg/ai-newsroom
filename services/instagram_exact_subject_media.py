"""Exact subject beats a generated stand-in (product polish, after the v10.9 run).

When a slide says it is ABOUT a real subject (media_subject = a listed key, media_function hero / evidence_photo / detail) and the pipeline
holds an isolated product shot of exactly that subject, the slide shows the real thing instead of a generated approximation - a generated
picture must never stand in for the industrial design of a named gadget. Real v10.9 TREND: every slide named the vivo Watch 6 as its
subject, but the official product photo had been mislabelled a flat card, so five slides about the watch showed abstract materials.

Deterministic and conservative: the FIRST photo slide about the subject shows the whole product (object_contain), the first 'detail' slide
after it may show a closer crop of the same photo; every other slide keeps its planned visual. No model call, and the swapped slides need
no paid generation.
"""
from __future__ import annotations

from typing import Any

from PIL import Image

from services.instagram_asset_profile import profile_asset

WHOLE_FUNCTIONS = ("hero", "evidence_photo")
PHOTO_FUNCTIONS = ("hero", "evidence_photo", "detail")


def exact_subject_keys(images: list[tuple[str, Image.Image]], *, exclude: frozenset[str] | set[str] = frozenset()) -> set[str]:
    """Subject keys whose own image is an isolated, suitable product shot (never one the vision check rejected)."""
    keys = set()
    for key, image in images:
        if key in exclude:
            continue
        profile = profile_asset(image.convert("RGBA" if image.mode == "RGBA" else "RGB"), subject_key=key)
        if profile.suitable_for_final_visual and profile.hero_ready:
            keys.add(key)
    return keys


def _swap(slide: dict[str, Any], key: str, crop_mode: str) -> dict[str, Any]:
    layout = dict(slide.get("layout") or {})
    regions = []
    for region in layout.get("regions") or []:
        region = dict(region)
        if region.get("kind") == "media" and region.get("content_ref") == "generated":
            region.update({"content_ref": key, "crop_mode": crop_mode})
            if crop_mode == "object_cover":  # the detail view leans into the product's face, not the same framing as the whole shot
                region.update({"focus_x": 0.42, "focus_y": 0.45})
        regions.append(region)
    layout["regions"] = regions
    return {**slide, "media_source": "source", "layout": layout}


def prefer_exact_subject_slides(slides: list[dict[str, Any]], exact_keys: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(slides, notes). Plain-dict form, used by the live path and by zero-cost re-renders alike."""
    out = [dict(s) for s in slides]
    notes: list[dict[str, Any]] = []
    already = {r.get("content_ref") for s in out for r in (s.get("layout") or {}).get("regions") or [] if r.get("kind") == "media"}
    for key in sorted(exact_keys - already):
        about = [i for i, s in enumerate(out) if s.get("media_subject") == key and s.get("media_source") == "generated"
                 and s.get("media_function") in PHOTO_FUNCTIONS and any(
                     r.get("kind") == "media" and r.get("content_ref") == "generated" for r in (s.get("layout") or {}).get("regions") or [])]
        if not about:
            continue
        whole = next((i for i in about if out[i].get("media_function") in WHOLE_FUNCTIONS), about[0])
        out[whole] = _swap(out[whole], key, "object_contain")
        notes.append({"slide": whole, "subject": key, "treatment": "exact_product_whole"})
        detail = next((i for i in about if i > whole and out[i].get("media_function") == "detail"), None)
        if detail is not None:
            out[detail] = _swap(out[detail], key, "object_cover")
            notes.append({"slide": detail, "subject": key, "treatment": "exact_product_detail_crop"})
    return out, notes


def prefer_exact_subject_media(carousel: Any, exact_keys: set[str]) -> tuple[Any, list[dict[str, Any]]]:
    """The same rule on a validated InstagramCarouselCreative."""
    if not exact_keys:
        return carousel, []
    slides = [s.model_dump() for s in carousel.slides]
    new_slides, notes = prefer_exact_subject_slides(slides, exact_keys)
    if not notes:
        return carousel, []
    return carousel.model_copy(update={"slides": [type(carousel.slides[0]).model_validate(s) for s in new_slides]}), notes
