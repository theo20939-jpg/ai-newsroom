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


def meaningful_fact_graphic(labels: list[str], slide_text: str) -> bool:
    """A recap fact graphic earns its cells only with real data - most labels carry a number or a date ('30B', '1 GPU', '27 августа') -
    and no label is a truncated word. Topic labels, roles and categories ('Тестирование', 'Риск выявлен') are not facts."""
    labels = [label for label in labels if label.strip()]
    if not labels or any(_truncated(label, slide_text) for label in labels):
        return False
    return sum(1 for label in labels if _DIGIT.search(label)) * 2 > len(labels)


def editorial_story_layout(layout: dict[str, Any] | None, *, role: str, slide_text: str,
                           aspects: dict[str, float] | None = None) -> dict[str, Any] | None:
    """A recap story slide whose only graphic is a set of weak fact cells becomes an EDITORIAL slide instead: a large headline, its line
    of context and - when the plan carries one - the story's own photo as a modest supporting picture (never a forced hero). None when
    the slide has no such graphic or its cells hold real data. Without any photo the planned graphic is kept (a slide needs a visual)."""
    if not layout or role != "story":
        return None
    regions = list(layout.get("regions") or [])
    graphics = [r for r in regions if r.get("kind") == "graphic" and r.get("graphic_type") in ("flow_diagram", "poll_cards")]
    if not graphics:
        return None
    labels = [label for g in graphics for label in (g.get("flow_steps") or [])]
    if graphics[0].get("graphic_type") == "poll_cards":
        labels = [part.strip() for part in re.split(r"[|/,;]", slide_text.split(":", 1)[-1]) if part.strip()]
    if meaningful_fact_graphic(labels, slide_text):
        return None
    photo = next((r.get("content_ref") for r in regions if r.get("kind") == "media" and r.get("content_ref")), None)
    if photo is None:
        return None
    surface = [r for r in regions if r.get("kind") == "surface"]
    # headline and its line read as one block at the top; the supporting photo sits below it, on the side away from the brand mark
    photo_x = 0.34 if layout.get("logo_position", "BOTTOM_RIGHT") == "BOTTOM_LEFT" else 0.08
    return {**layout, "arrangement": "standard", "media_dominance": "SUPPORTING", "visual_weight": "MIXED", "regions": [
        *surface,
        _text("copy", 0.09, 0.2, "HEADLINE_XL", 3, "primary"),
        _text("body", 0.3, 0.13, "BODY", 4, "muted"),
        # the supporting photo keeps its own shape (a 16:9 stage shot is not squeezed into a squarer slot)
        {**_tile(photo, photo_x, 0.5, 0.58, min(0.36, max(0.2, 0.58 * CANVAS_ASPECT / (aspects or {}).get(photo, 1.6))), 1), "frame": "paper"},
    ]}


def with_recap_cta(carousel: Any) -> Any:
    """The recap's closing slide carries the subscription end-card copy (brand copy - no story fact, so nothing to ground)."""
    slides = list(carousel.slides)
    if not slides or slides[-1].role != "closing":
        return carousel
    slides[-1] = slides[-1].model_copy(update={"slide_copy": RECAP_CTA_HEADLINE, "slide_body": RECAP_CTA_BODY})
    return carousel.model_copy(update={"slides": slides})
