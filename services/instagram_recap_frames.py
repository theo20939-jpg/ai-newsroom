"""Weekly recap product pass: deterministic FRAMES for the recap's cover and closer.

The Creative Director chooses WHICH stories frame the week (the media regions' story keys, in its order) and writes the copy; a free-form
multi-image collage is geometry it cannot place reliably (real recap v2: fragments over the headline and the logo, tiny closer crops, and a
cover that collapsed to one story's photo). For a news_recap cover (role `hook`) or closer (role `closing`) that shows three or more
different stories, the geometry is fixed here: headline and body on top, the stories as a clean photo grid (cover) or strip (closer).
Only x / y / w / h, frame and tilt of the media and the text boxes change - never a story key, the copy, the background or the palette."""
from __future__ import annotations

from typing import Any

MIN_FRAME_STORIES = 3
MAX_FRAME_STORIES = 4
_GAP = 0.016


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


def _strip(refs: list[str], x0: float, y0: float, x1: float, h: float) -> list[dict[str, Any]]:
    tw = (x1 - x0 - _GAP * (len(refs) - 1)) / len(refs)
    return [_tile(ref, x0 + i * (tw + _GAP), y0, tw, h, 1) for i, ref in enumerate(refs)]


def recap_frame_layout(layout: dict[str, Any] | None, *, role: str) -> dict[str, Any] | None:
    """The framed layout for a recap cover / closer that shows >= MIN_FRAME_STORIES different stories, else None (the plan is kept)."""
    if not layout or role not in ("hook", "closing"):
        return None
    refs = _story_refs(layout)
    if len(refs) < MIN_FRAME_STORIES:
        return None
    regions = [r for r in layout.get("regions") or [] if r.get("kind") == "surface"]
    if role == "hook":
        regions += [_text("copy", 0.06, 0.2, "HEADLINE_XL", 3, "primary"), _text("body", 0.27, 0.13, "BODY", 3, "muted")]
        regions += _grid(refs, 0.04, 0.42, 0.96, 0.87)  # clear of the brand mark in the bottom corner
    else:
        regions += [_text("copy", 0.07, 0.2, "HEADLINE_XL", 2, "primary"), _text("body", 0.29, 0.16, "BODY", 4, "muted")]
        regions += _strip(refs, 0.07, 0.5, 0.93, 0.3)
    return {**layout, "arrangement": "standard", "regions": regions}


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
    media = sum(1 for r in kept if r.get("kind") == "media")
    return {**layout, "regions": kept, "arrangement": "standard" if media < 2 else layout.get("arrangement", "standard")}
