"""Weekly recap product pass: deterministic FRAMES for the recap's cover and closer.

The Creative Director chooses WHICH stories frame the week (the media regions' story keys, in its order) and writes the copy; a free-form
multi-image collage is geometry it cannot place reliably (real recap v2: fragments over the headline and the logo, tiny closer crops, and a
cover that collapsed to one story's photo). For a news_recap cover (role `hook`) or closer (role `closing`) that shows three or more
different stories, the geometry is fixed here: headline and body on top, the stories as a clean photo grid (the cover's under the headline, the
closer's a subscription end card over a small stack of the week's prints).
Only x / y / w / h, frame and tilt of the media and the text boxes change - never a story key, the copy, the background or the palette."""
from __future__ import annotations

import re
from typing import Any

MIN_FRAME_STORIES = 3
MAX_FRAME_STORIES = 4
_GAP = 0.016
MIN_STORY_PHOTO_AREA = 0.35  # a recap story's single photo must stay the dominant surface


def _story_refs(layout: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for region in layout.get("regions") or []:
        ref = region.get("content_ref")
        if region.get("kind") == "media" and ref and ref not in refs:
            refs.append(ref)
    return refs[:MAX_FRAME_STORIES]


def _tile(ref: str, x: float, y: float, w: float, h: float, z: int) -> dict[str, Any]:
    return {"kind": "media", "x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4), "z": z, "content_ref": ref,
            "crop_mode": "cover", "frame": "none", "on_media": False}


def _text(ref: str, y: float, h: float, token: str, max_lines: int, tone: str) -> dict[str, Any]:
    return {"kind": "text", "x": 0.07, "y": y, "w": 0.86, "h": h, "z": 5, "content_ref": ref, "scale_token": token, "align": "left",
            "valign": "top", "max_lines": max_lines, "tone": tone, "on_media": False}


def _grid(refs: list[str], x0: float, y0: float, x1: float, y1: float) -> list[dict[str, Any]]:
    w, h = x1 - x0, y1 - y0
    if len(refs) == 3:  # one large lead tile and two stacked
        lead_w = w * 0.56
        side_w = w - lead_w - _GAP
        half = (h - _GAP) / 2
        return [_tile(refs[0], x0, y0, lead_w, h, 1), _tile(refs[1], x0 + lead_w + _GAP, y0, side_w, half, 1),
                _tile(refs[2], x0 + lead_w + _GAP, y0 + half + _GAP, side_w, half, 1)]
    tw, th = (w - _GAP) / 2, (h - _GAP) / 2
    return [_tile(ref, x0 + (i % 2) * (tw + _GAP), y0 + (i // 2) * (th + _GAP), tw, th, 1) for i, ref in enumerate(refs)]


CANVAS_ASPECT = 1080 / 1350  # canvas width / height: a width fraction times this is the same length as a height fraction


def _justified(refs: list[str], aspects: dict[str, float], x0: float, y0: float, x1: float, y1: float) -> list[dict[str, Any]]:
    """An art-directed mosaic: two rows whose tiles take the SHAPE of their own photos (a justified layout), so a wide phone shot stays
    wide and a squarer portrait stays squarer - each picture is framed as itself instead of being clipped into identical boxes. A row
    taller than its share of the area is scaled down and centred; the focal crop then trims only what is left over."""
    rows = [refs[:2], refs[2:4]] if len(refs) >= 4 else [refs[:1], refs[1:3]]
    avail_h = y1 - y0 - _GAP
    heights = []
    for row in rows:
        widths = sum(min(2.2, max(0.9, aspects.get(ref, 1.6))) for ref in row)
        heights.append(((x1 - x0 - _GAP * (len(row) - 1)) / widths) * CANVAS_ASPECT)  # the row height its photos' shapes ask for
    scale = min(1.0, avail_h / sum(heights))
    tiles, y = [], y0 + (avail_h - sum(h * scale for h in heights)) / 2
    for row, h in zip(rows, heights):
        h *= scale
        widths = [min(2.2, max(0.9, aspects.get(ref, 1.6))) * h / CANVAS_ASPECT for ref in row]
        x = x0 + ((x1 - x0) - sum(widths) - _GAP * (len(row) - 1)) / 2
        for ref, w in zip(row, widths):
            tiles.append(_tile(ref, x, y, w, h, 1))
            x += w + _GAP
        y += h + _GAP
    return tiles


# The weekly recap ends on a subscription end card (founder direction): brand copy, not a story fact - the same on every recap.
RECAP_CTA_HEADLINE = "Не пропускай главное — подписывайся на KAGE"
RECAP_CTA_BODY = "Каждую неделю — самое важное про AI, гаджеты и технологии. Коротко и без шума."


def _cta_stack(refs: list[str]) -> list[dict[str, Any]]:
    """The week's pictures as a small fanned stack of prints - 'every week, stories like these' - under the call to subscribe."""
    # one lead print in front (the collage's clear primary) and two smaller ones fanned out behind it
    # the week's lead story is the front print; the next two fan out behind it, far enough to stay recognisable
    spots = ((0.24, 0.63, 0.52, 0.28, -1.5, 3), (0.05, 0.555, 0.36, 0.22, -7.0, 1), (0.59, 0.545, 0.36, 0.22, 6.0, 2))
    return [{**_tile(ref, x, y, w, h, z), "frame": "paper", "tilt_deg": tilt} for ref, (x, y, w, h, tilt, z) in zip(refs[:3], spots)]


def recap_frame_layout(layout: dict[str, Any] | None, *, role: str, aspects: dict[str, float] | None = None,
                       slide_text: str = "") -> dict[str, Any] | None:
    """The framed layout for a recap cover (a justified mosaic of the week's stories under the copy) or closer (the subscription end
    card over a small stack of the week's prints), when the plan shows >= MIN_FRAME_STORIES different stories; else None (plan kept)."""
    if not layout or role not in ("hook", "closing"):
        return None
    refs = _story_refs(layout)
    if len(refs) < MIN_FRAME_STORIES:
        return None
    aspects = aspects or {}
    regions = [r for r in layout.get("regions") or [] if r.get("kind") == "surface"]
    if role == "hook":
        regions += [_text("copy", 0.06, 0.2, "HEADLINE_XL", 3, "primary"), _text("body", 0.27, 0.13, "BODY", 3, "muted")]
        regions += _justified(refs, aspects, 0.04, 0.445, 0.96, 0.875) if aspects else _grid(refs, 0.04, 0.445, 0.96, 0.875)
        return {**layout, "arrangement": "standard", "regions": regions}
    if not slide_text.strip().startswith(RECAP_CTA_HEADLINE):  # a closer without the end-card copy keeps a plain mosaic under its text
        regions += [_text("copy", 0.07, 0.2, "HEADLINE_XL", 2, "primary"), _text("body", 0.29, 0.16, "BODY", 4, "muted")]
        regions += _justified(refs, aspects, 0.07, 0.48, 0.93, 0.87) if aspects else _grid(refs, 0.07, 0.48, 0.93, 0.87)
        return {**layout, "arrangement": "standard", "regions": regions}
    regions += [_text("copy_lead", 0.08, 0.2, "HEADLINE_XL", 2, "primary"), _text("copy_rest", 0.29, 0.07, "HEADLINE_M", 1, "accent"),
                _text("body", 0.38, 0.12, "BODY", 3, "muted")]
    regions += _cta_stack(refs)
    return {**layout, "arrangement": "collage", "media_dominance": "SUPPORTING", "regions": regions}

def single_photo_story_layout(layout: dict[str, Any] | None, *, role: str) -> dict[str, Any] | None:
    """A recap STORY slide shows its photo once: several crops of the same image read as a cheap duplicate in a roundup (real recap v2:
    the GTA VI key art three times on one slide). Keeps the largest region of each repeated story key; None when nothing repeats."""
    if not layout or role != "story":
        return None
    regions = list(layout.get("regions") or [])
    largest: dict[str, int] = {}
    for i, r in enumerate(regions):
        ref = r.get("content_ref")
        if r.get("kind") == "media" and ref:
            if ref not in largest or r.get("w", 0) * r.get("h", 0) > regions[largest[ref]].get("w", 0) * regions[largest[ref]].get("h", 0):
                largest[ref] = i
    kept = [r for i, r in enumerate(regions) if not (r.get("kind") == "media" and r.get("content_ref") and largest.get(r["content_ref"]) != i)]
    if len(kept) == len(regions):
        return None
    photos = [r for r in kept if r.get("kind") == "media"]
    if max((m.get("w", 0) * m.get("h", 0) for m in photos), default=0) < MIN_STORY_PHOTO_AREA:
        return None  # the one photo left would be a small inset: the planned slide (rebuilt edge to edge by the renderer) reads better
    # decorative scribbles were drawn around the removed crops / the old text boxes - they are not content
    kept = [r for r in kept if not (r.get("kind") == "graphic" and str(r.get("graphic_type") or "").endswith("scribble"))]

    def clear_of_photos(x: float, y: float, w: float, h: float) -> bool:
        return all(x + w <= m["x"] or m["x"] + m["w"] <= x or y + h <= m["y"] or m["y"] + m["h"] <= y for m in photos)

    # the removed crops' space goes to the copy: a text box that stays clear of the one photo spans the full text width
    kept = [{**r, "x": 0.07, "w": 0.86} if r.get("kind") == "text" and clear_of_photos(0.07, r["y"], 0.86, r["h"]) else r for r in kept]
    media = sum(1 for r in kept if r.get("kind") == "media")
    return {**layout, "regions": kept, "arrangement": "standard" if media < 2 else layout.get("arrangement", "standard")}


_DIGIT = re.compile(r"\d")
_WORD = re.compile(r"[^\W\d_]{4,}")


def _truncated(label: str, text: str) -> bool:
    """A label word that is only the START of a word in the slide's own text ('подраздел' of 'подразделения') was cut to a length cap."""
    words = {w.lower() for w in _WORD.findall(text)}
    return any(w.lower() not in words and any(full.startswith(w.lower()) for full in words) for w in _WORD.findall(label))


_UI_MARKERS = re.compile(r"[«»@→/]|->")


def meaningful_fact_graphic(labels: list[str], slide_text: str, *, ui_paths: bool = False) -> bool:
    """A fact graphic earns its cells only with real content: most labels carry a number or a date ('30B', '1 GPU', '27 августа') or,
    for a how-to (`ui_paths`), an exact UI path the reader follows («Plugins», «@Adobe», A → B) - and no label is a truncated word.
    Topic labels, roles and categories ('Тестирование', 'Риск выявлен', 'Твоя задача') are not facts."""
    labels = [label for label in labels if label.strip()]
    if not labels or any(_truncated(label, slide_text) for label in labels):
        return False
    with_data = sum(1 for label in labels if _DIGIT.search(label))
    with_ui = sum(1 for label in labels if _UI_MARKERS.search(label))
    return with_data * 2 > len(labels) or (ui_paths and with_ui >= 1)  # a how-to path names at least one exact UI element


_STEP = re.compile(r"^\s*(?:шаг|step)\s*\d{1,2}", re.IGNORECASE)
DESIGNED_TYPOGRAPHIC = ("statement", "step_numeral", "data_point", "negative_space", "split")  # the picture-less editorial variants


def _weak_graphic(regions: list[dict[str, Any]], slide_text: str, *, ui_paths: bool) -> bool:
    graphics = [r for r in regions if r.get("kind") == "graphic" and r.get("graphic_type") in ("flow_diagram", "poll_cards")]
    if not graphics or graphics[0].get("graphic_type") == "poll_cards":  # a poll's options are the slide's own choices - kept
        return False
    labels = [label for g in graphics for label in (g.get("flow_steps") or [])]
    return not meaningful_fact_graphic(labels, slide_text, ui_paths=ui_paths)


def editorial_fallback_layout(layout: dict[str, Any] | None, *, role: str, slide_text: str, headline: str, photo: str | None,
                              ui_paths: bool = False, previous: str | None = None) -> tuple[dict[str, Any], str] | None:
    """(layout, variant) for a slide whose only visual is a WEAK fact diagram - topic labels in cells - else None (the plan is kept).
    The slide becomes a designed EDITORIAL beat instead, chosen by what it is, never by chance:
      'ambient'      - any photo of the story, suitable or not, as a quiet softened layer under display type (a hook, a recap story);
      'step_numeral' - a how-to step ('Шаг 3. ...'): the step number set large, its instruction and one line;
      'statement'    - otherwise: a display headline, its line, a KAGE violet accent bar - typography as the composition.
    No photo is a normal state: it never becomes cells, a giant stray numeral or an empty card."""
    if not layout:
        return None
    regions = list(layout.get("regions") or [])
    if not _weak_graphic(regions, slide_text, ui_paths=ui_paths):
        return None
    base = {**layout, "arrangement": "standard", "logo_position": "BOTTOM_RIGHT", "show_progress": False}
    surface = [r for r in regions if r.get("kind") == "surface"]
    if photo is not None and (role in ("hook", "story") or not ui_paths):
        return {**base, "background": "ink", "media_dominance": "SUPPORTING", "visual_weight": "TEXT", "regions": [
            {**_tile(photo, 0.0, 0.0, 1.0, 1.0, 1), "tone": "muted"},
            {**_text("copy", 0.3, 0.27, "DISPLAY", 4, "primary"), "on_media": True},
            {**_text("body", 0.6, 0.14, "BODY", 4, "primary"), "on_media": True, "w": 0.74},
        ]}, "ambient"
    return _typographic_beat(base, surface, role=role, headline=headline, previous=previous)


# One art direction, distinct beats (founder rule): the treatment follows the slide's purpose and content; the same composition never
# runs twice in a row. Nothing is invented - every variant only sets the slide's OWN copy (headline / its number / body) differently.
_BEAT_BY_ROLE = {
    "hook": "statement", "context": "negative_space", "comparison": "negative_space", "result": "negative_space",
    "evidence": "split", "step": "split", "story": "split", "takeaway": "statement", "closing": "statement", "cta": "statement",
}
_BEAT_ORDER = ("statement", "negative_space", "split")
def _leading_figure(headline: str) -> bool:
    """The headline starts with a figure and reads intact without it ('70+ | инструментов Adobe ...'); a figure in mid-sentence never
    becomes the big numeral (removing it would leave 'Рост на за неделю')."""
    from services.instagram_layout_validation import copy_parts

    parts, text = copy_parts(headline), headline.strip()
    number = parts["number"].strip()
    return bool(number) and text.startswith(number) and parts["copy_no_number"].strip() == text[len(number):].strip(" .,:;—-").strip()


def _typographic_beat(base: dict[str, Any], surface: list[dict[str, Any]], *, role: str, headline: str,
                      previous: str | None) -> tuple[dict[str, Any], str]:
    if _STEP.match(headline):
        variant = "step_numeral"          # a numbered how-to step: its number set large
    elif _leading_figure(headline):
        variant = "data_point"            # the headline OPENS with its own figure ('70+ инструментов ...'): that figure as the one data point
    else:
        variant = _BEAT_BY_ROLE.get(role, "statement")
    if variant == previous:
        variant = next(v for v in _BEAT_ORDER[_BEAT_ORDER.index(variant) + 1:] + _BEAT_ORDER if v != previous) \
            if variant in _BEAT_ORDER else next(v for v in _BEAT_ORDER if v != previous)
    text = {**base, "media_dominance": "NONE", "visual_weight": "TEXT"}
    if variant in ("step_numeral", "data_point"):
        return {**text, "regions": [
            *surface,
            {**_text("number", 0.07, 0.07, "MEGA", 1, "accent"), "w": 0.62 if variant == "data_point" else 0.5, "h": 0.3},
            _text("copy_no_number", 0.4, 0.2, "HEADLINE_XL", 3, "primary"),
            {**_text("body", 0.63, 0.18, "BODY", 5, "muted"), "w": 0.72},
        ]}, variant
    if variant == "negative_space":      # a quiet centred beat: a short accent rule, the headline centred, its line under it
        return {**text, "regions": [
            *surface,
            {"kind": "accent", "x": 0.43, "y": 0.27, "w": 0.14, "h": 0.012, "z": 2, "accent_type": "rule_h", "tone": "accent"},
            {**_text("copy", 0.31, 0.3, "HEADLINE_XL", 4, "primary"), "x": 0.1, "w": 0.8, "align": "center"},
            {**_text("body", 0.64, 0.16, "BODY", 4, "muted"), "x": 0.16, "w": 0.68, "align": "center"},
        ]}, variant
    if variant == "split":                # the headline over the slide's ground, its explanation on a KAGE violet panel below
        return {**text, "regions": [
            *surface,
            {"kind": "surface", "x": 0.0, "y": 0.56, "w": 1.0, "h": 0.44, "z": 1, "surface": "accent", "tone": "accent", "accent_type": "block"},
            {**_text("copy", 0.1, 0.38, "DISPLAY", 4, "primary"), "x": 0.07, "w": 0.86},
            {**_text("body", 0.62, 0.2, "BODY", 5, "primary"), "x": 0.07, "w": 0.74},
        ]}, variant
    return {**text, "regions": [
        *surface,
        {"kind": "accent", "x": 0.07, "y": 0.16, "w": 0.016, "h": 0.4, "z": 2, "accent_type": "rule_v", "tone": "accent"},
        {**_text("copy", 0.16, 0.34, "DISPLAY", 4, "primary"), "x": 0.12, "w": 0.81},
        {**_text("body", 0.6, 0.18, "BODY", 5, "muted"), "x": 0.12, "w": 0.7},
    ]}, "statement"


def editorial_story_layout(layout: dict[str, Any] | None, *, role: str, slide_text: str,
                           aspects: dict[str, float] | None = None) -> dict[str, Any] | None:
    """Kept for the recap's earlier callers: the recap story case of editorial_fallback_layout with the plan's own photo region."""
    del aspects
    if not layout or role != "story":
        return None
    photo = next((r.get("content_ref") for r in layout.get("regions") or [] if r.get("kind") == "media" and r.get("content_ref")), None)
    out = editorial_fallback_layout(layout, role=role, slide_text=slide_text, headline=slide_text, photo=photo)
    return out[0] if out is not None and out[1] == "ambient" else None


def with_recap_cta(carousel: Any) -> Any:
    """The recap's closing slide carries the subscription end-card copy (brand copy - no story fact, so nothing to ground)."""
    slides = list(carousel.slides)
    if not slides or slides[-1].role != "closing":
        return carousel
    slides[-1] = slides[-1].model_copy(update={"slide_copy": RECAP_CTA_HEADLINE, "slide_body": RECAP_CTA_BODY})
    return carousel.model_copy(update={"slides": slides})


def hero_story_layout(layout: dict[str, Any] | None, *, role: str, index: int, aspects: dict[str, float] | None = None,
                      zone: str | None = None) -> dict[str, Any] | None:
    """A recap story slide whose visual is a real photo (no fact graphic) is IMAGE-LED: the photo IS the canvas (full bleed), and the
    headline + its line sit over the photo's own calmer end (`zone`, chosen from the picture - services.instagram_focal_crop.
    hero_copy_zone) on a soft gradient. No text panel, no horizontal divider: the variation comes from each photograph.
    None when the slide has no photo or carries a fact graphic (editorial slides stay)."""
    del index, aspects  # the composition follows the photograph, not the slide's position
    if not layout or role != "story" or zone not in ("top", "bottom"):
        return None
    regions = list(layout.get("regions") or [])
    if any(r.get("kind") == "graphic" and r.get("graphic_type") in ("flow_diagram", "poll_cards", "ui_frame") for r in regions):
        return None
    photo = next((r.get("content_ref") for r in sorted(regions, key=lambda r: -(r.get("w", 0) * r.get("h", 0)))
                  if r.get("kind") == "media" and r.get("content_ref")), None)
    if photo is None or any(r.get("kind") == "media" and r.get("tone") == "muted" for r in regions):
        return None  # no photo - or an unsuitable one already demoted to the background layer: it never becomes the hero again
    media = {**_tile(photo, 0.0, 0.0, 1.0, 1.0, 1)}
    if zone == "top":
        texts = [{**_text("copy", 0.06, 0.2, "HEADLINE_XL", 3, "primary"), "on_media": True},
                 {**_text("body", 0.27, 0.13, "BODY", 3, "primary"), "on_media": True, "w": 0.8}]
    else:  # the copy on the bottom gradient, clear of the brand mark
        texts = [{**_text("copy", 0.6, 0.2, "HEADLINE_XL", 3, "primary"), "on_media": True},
                 {**_text("body", 0.805, 0.11, "BODY", 3, "primary"), "on_media": True, "w": 0.7}]
    return {**layout, "arrangement": "standard", "background": "ink", "media_dominance": "DOMINANT", "visual_weight": "MEDIA",
            "logo_position": "BOTTOM_RIGHT", "show_progress": False, "regions": [media, *texts]}
