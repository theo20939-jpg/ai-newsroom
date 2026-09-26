"""NO SUITABLE PHOTO => GENERATED IMAGE (founder visual decision, 2026-09-26).

The priority of a slide's visual treatment:
  1. a suitable real photo / source visual;
  2. a generated editorial image;
  3. a text-led typographic composition - only when image generation is unavailable, disallowed or failed.
Fact cells, stacked fact boxes, 01/02/03 step rectangles, choice cards and dashboard-like panels are never the no-photo default.

This module is the deterministic step between the Creative Director's plan and media execution: a slide whose visual is NOT a suitable
real photo (a fact graphic, cards, typography, or an unsuitable photo demoted to a background layer) is promoted to a generated
editorial image. Its brief is compiled from the slide's OWN grounded copy only - the picture is illustrative, never evidence: no text,
no UI, no screenshots, no recognisable people or products, no new specifics (services.instagram_creative_media then adds the story's
supported facts and the negative constraints to the provider prompt). The slide renders photo-as-canvas - the image full bleed, the
exact Russian copy over its calmer end - the same composition the accepted recap uses for a real photograph.

A weekly-recap cover grid and the subscription end card keep their real story prints; a recap story whose own photo IS suitable gets
that photo as its hero instead of a generated one."""
from __future__ import annotations

from typing import Any

from services.instagram_media_first import GENERATED_SUBJECT_KEY

NO_PHOTO_GRAPHICS = ("flow_diagram", "poll_cards", "ui_frame")
# recorded on a slide THIS rule promoted (visual_family_reason): only such a slide is re-composed photo-as-canvas at render time - a slide
# the Creative Director itself planned as generated keeps its own designed layout
NO_PHOTO_GENERATED = "no_photo_generated_fallback"
_BRIEF_LIMIT = 420  # schemas.instagram_creative: generation_brief max_length

# the composition the generated picture must leave for the copy (the renderer measures the calmer end on the real pixels)
_BRIEF_TAIL = ("Иллюстративный редакционный кадр, не документ и не доказательство: без текста, букв, цифр, логотипов, интерфейсов, "
               "скриншотов, графиков и узнаваемых людей. Одна сильная сцена, глубина и свет; верхняя или нижняя треть спокойная, "
               "без деталей - там будет заголовок.")


_GENERATED_DIRECTION = ("Сгенерированный иллюстративный образ во весь кадр: одна сцена, передающая смысл слайда через предметы, пространство и "
                        "свет; никаких карточек, схем, интерфейсов и надписей; спокойная треть кадра остаётся под заголовок.")


# viral / meme-worthy stories (services.instagram_viral_format): the picture may carry irony, absurdity and meme energy - still illustrative,
# never evidence, never a fake screenshot, quote or poster imitation
_VIRAL_BRIEF_TAIL = ("Выразительная редакционная иллюстрация с иронией, абсурдом и мем-энергией в стиле KAGE - смелая сцена, не документ: "
                     "без текста, цифр, логотипов, интерфейсов, скриншотов, цитат, узнаваемых людей и подражания постерам; "
                     "треть кадра спокойная под заголовок.")
VIRAL_VISUAL_TREATMENT = ("Выразительная редакционная иллюстрация во весь кадр с визуальной иронией и мем-энергией: преувеличенная сцена-метафора, "
                          "напряжение и абсурд, но в чистом стиле KAGE; без карточек, схем, интерфейсов и надписей.")
GENERATED_VISUAL_TREATMENT = ("Редакционная сгенерированная иллюстрация во весь кадр: одна сильная сцена по смыслу истории, глубина, свет и "
                              "материал; без карточек, схем, интерфейсов и надписей.")
GENERATED_COMPOSITION = ("Вертикальный кадр с одной решающей сценой и выразительной глубиной; одна треть кадра спокойная и без деталей - "
                         "на неё ложится точный русский текст.")


def generated_plan_update(copy_text: str | None = None, *, viral: bool = False) -> dict[str, str]:
    """The plan fields the image prompt reads, rewritten when the SYSTEM (not the Director) moves a post to generated imagery: a plan
    written for fact cards or typography ('option cards', 'pseudo-interface', 'typographic 460 -> 0') would otherwise be drawn literally."""
    update = {"visual_treatment": VIRAL_VISUAL_TREATMENT if viral else GENERATED_VISUAL_TREATMENT, "composition_direction": GENERATED_COMPOSITION}
    headline = " ".join(str(copy_text or "").split())
    if headline:
        update["focal_point"] = f"Образ для мысли «{headline}»"[:199]
    return update


def _get(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _regions(slide: Any) -> list[Any]:
    layout = _get(slide, "layout")
    return list(_get(layout, "regions") or []) if layout is not None else []


def _real_photo_refs(slide: Any, suitable: set[str]) -> list[str]:
    """Suitable real photos that visibly carry this slide (a softened background layer does not count)."""
    return [str(_get(r, "content_ref")) for r in _regions(slide)
            if _get(r, "kind") == "media" and _get(r, "content_ref") in suitable and _get(r, "tone") != "muted"]


def no_photo_treatment(slide: Any, suitable: set[str], *, recap: bool) -> str | None:
    """What a slide without a suitable real photo becomes: 'real_photo' (a recap story whose own photo is suitable),
    'generated', or None (the slide already has its photo, is already generated, or is a recap cover / end card)."""
    role = str(_get(slide, "role") or "").strip().lower()
    if recap and role in ("hook", "closing"):
        return None  # the cover grid / the subscription end card: prints of the week's real photos
    if _get(slide, "media_source") == "generated":
        return None
    if _real_photo_refs(slide, suitable):
        return None
    subject = _get(slide, "media_subject")
    if recap and subject in suitable:
        return "real_photo"  # a recap story with a usable photo of its own: that photo leads, nothing is generated
    return "generated"


def generation_brief(slide: Any, *, viral: bool = False) -> str:
    """The picture's brief from the slide's own grounded copy - the idea to illustrate, never a new fact."""
    headline = " ".join(str(_get(slide, "slide_copy") or _get(slide, "text") or "").split())
    body = " ".join(str(_get(slide, "body") or _get(slide, "slide_body") or "").split())  # package dict / Director slide
    tail = _VIRAL_BRIEF_TAIL if viral else _BRIEF_TAIL
    idea = (f"Образ для мысли «{headline}»" + (f": {body}" if body else "")).rstrip(" .")
    room = _BRIEF_LIMIT - len(tail) - 2
    if len(idea) > room:
        idea = idea[: room - 1].rsplit(" ", 1)[0] + "…"
    return f"{idea}. {tail}"


def hero_layout(layout: Any, ref: str, zone: str = "bottom") -> dict[str, Any]:
    """Photo-as-canvas: `ref` full bleed, the headline and its line over the picture's calmer end (`zone`, measured on the real pixels
    by services.instagram_focal_crop.hero_copy_zone at render time) - the geometry of the accepted recap photo hero."""
    base = layout.model_dump() if hasattr(layout, "model_dump") else dict(layout or {})
    if zone == "top":
        texts = [{"y": 0.06, "h": 0.2, "w": 0.86, "content_ref": "copy", "scale_token": "HEADLINE_XL"},
                 {"y": 0.27, "h": 0.13, "w": 0.8, "content_ref": "body", "scale_token": "BODY"}]
    else:
        texts = [{"y": 0.6, "h": 0.2, "w": 0.86, "content_ref": "copy", "scale_token": "HEADLINE_XL"},
                 {"y": 0.805, "h": 0.11, "w": 0.7, "content_ref": "body", "scale_token": "BODY"}]
    return {
        "background": "ink", "palette": base.get("palette") or "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
        "density": "LOW", "media_dominance": "DOMINANT", "visual_weight": "MEDIA", "show_progress": False,
        "regions": [
            {"kind": "media", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "z": 1, "content_ref": ref, "crop_mode": "cover", "frame": "none"},
            *({"kind": "text", "x": 0.07, "z": 5, "align": "left", "valign": "top", "max_lines": 3, "tone": "primary", "on_media": True, **t}
              for t in texts),
        ],
    }


def viral_generated_heroes(slides: list[Any]) -> tuple[list[Any], list[int]]:
    """Viral / meme-worthy carousel (services.instagram_viral_format): EVERY generated picture - the Director's own too - is the slide's
    hero, full bleed with the copy over its calmer end (founder visual rule: strong hero image, expressive swipe-friendly scenes, bold type
    in clear negative space). A generated picture shrunk into a small panel or inset is exactly what a viral retelling must not do.
    Real photos and non-generated slides are untouched. Returns (slides, indices re-composed)."""
    out, changed = [], []
    for index, slide in enumerate(slides):
        if _get(slide, "media_source") != "generated" or _get(slide, "visual_family_reason") == NO_PHOTO_GENERATED:
            out.append(slide)
            continue
        update = {"layout": hero_layout(_get(slide, "layout"), GENERATED_SUBJECT_KEY), "visual_family_reason": NO_PHOTO_GENERATED}
        if isinstance(slide, dict):
            out.append({**slide, **update})
        else:
            from schemas.instagram_creative import InstagramSlideLayout

            out.append(slide.model_copy(update={**update, "layout": InstagramSlideLayout.model_validate(update["layout"])}))
        changed.append(index)
    return out, changed


def promote_no_photo_slides(slides: list[Any], *, suitable_subjects: set[str], recap: bool,
                            viral: bool = False) -> tuple[list[Any], list[dict[str, Any]]]:
    """Every slide without a suitable real photo becomes a generated editorial image (or, for a recap story with a suitable photo of its
    own, that photo as its hero). Works on the Director's pydantic slides and on a package's slide dicts alike. Deterministic, no call.
    Returns (slides, one note per promoted slide)."""
    out: list[Any] = []
    notes: list[dict[str, Any]] = []
    for index, slide in enumerate(slides):
        treatment = no_photo_treatment(slide, suitable_subjects, recap=recap)
        if treatment is None:
            out.append(slide)
            continue
        before = sorted({str(_get(r, "graphic_type") or _get(r, "kind")) for r in _regions(slide)
                         if _get(r, "kind") in ("graphic", "media")}) or ["typography"]
        if treatment == "real_photo":
            update = {"media_source": "source", "layout": hero_layout(_get(slide, "layout"), str(_get(slide, "media_subject")))}
        else:
            # the old art direction described the fact graphic (boxes, steps, cards): the generation prompt reads it as "what must be
            # visible", so the promoted slide carries the picture's own direction instead
            update = {"media_source": "generated", "generation_brief": generation_brief(slide, viral=viral),
                      "layout": hero_layout(_get(slide, "layout"), GENERATED_SUBJECT_KEY),
                      "visual_direction": _GENERATED_DIRECTION, "visual_family": "immersive_image_field", "media_function": "hero",
                      "composition": "full_bleed_media", "media_position": "full", "visual_family_reason": NO_PHOTO_GENERATED}
        if isinstance(slide, dict):
            out.append({**slide, **update})
        else:
            from schemas.instagram_creative import InstagramSlideLayout

            out.append(slide.model_copy(update={**update, "layout": InstagramSlideLayout.model_validate(update["layout"])}))
        notes.append({"slide": index, "role": _get(slide, "role"), "before": before, "treatment": treatment, **({"viral": True} if viral else {})})
    return out, notes
