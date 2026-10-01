"""One carousel, several pictures - not one picture drawn five times.

Why the saved Sonnet carousel was monotone (real 29 Sep run): the Director's carousel-wide `main_idea` ("the Claude line as a physical hierarchy
of blocks") and `visual_treatment` ("unbranded geometric model blocks") are written into EVERY slide's image prompt as "OVERALL IDEA" / "Visual
genre", and the five briefs each re-described the same physical object. Cropping, angle and layout cannot fix that: the scene concept was identical.

Two deterministic rules, no model call, no story- or motif-specific vocabulary:
  1. a slide's picture prompt carries ITS OWN beat plus a story-neutral shared look (matte editorial still life, one palette, one light) and an
     explicit list of what the carousel's OTHER pictures already show - never the carousel-wide object metaphor (`slide_scene_plan`);
  2. a physical concept that dominates the slides' scene briefs (in at least 60% of them, and at least three) stays as a small connective motif on
     the first slide that carries it; every later slide that repeats it is re-briefed from its OWN grounded copy (`diversify_slide_briefs`).
Safety text (no UI / readable text / logos / real people) is untouched - it lives in the prompt compiler and the brief tails."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from services.instagram_generated_fallback import _GENERATED_DIRECTION, generation_brief

MIN_SLIDES = 3
DOMINANCE_SHARE = 0.6
DOMINANCE_MIN = 3

# Words that describe HOW a brief is phrased (format, safety clauses, grammar, camera) - never WHAT is in the scene.
_SCAFFOLD = frozenset("""
portrait editorial still life solid ground blank unbranded branded text logo logos letter letters number numbers screen screens watermark
watermarks label labels interface interfaces ui composition scene scenes closing surface background marking markings writing word words
fake with without that this these those from into onto over under beside between behind while where which other each every very more some both
only such same also than then them they their there here have has having been being are was were will would could should must not and the for
use used using uses show shows showing shown shape shapes image images picture pictures frame view photo photograph shot style look
positioned position placed arranged arrangement visibly clearly slightly different differently clear single large larger small smaller
big bigger tall taller one two three four five six several many much most least first second third last next new old
one's another around across along above below near beside inside outside upon toward towards through
ironic playful humorous dramatic cinematic moody cold warm bright dark hard heavy thin long short brushed matte glossy simple small lone
""".split())

SHARED_LANGUAGE = (
    "Shared look for the whole carousel (look only - NOT the subject): matte editorial still-life photography, real materials and believable depth, "
    "graphite and warm paper tones with at most one restrained violet accent, soft directional window light, calm negative space."
)


def _concepts(brief: str) -> set[str]:
    """The set of content words of a scene brief, singularised (blocks -> block). Language-agnostic: a token is a run of letters of 4+ chars."""
    out: set[str] = set()
    for token in re.findall(r"[^\W\d_]{4,}", (brief or "").lower()):
        if token in _SCAFFOLD:
            continue
        if token.endswith("s") and not token.endswith("ss") and len(token) > 4:
            token = token[:-1]
        if token not in _SCAFFOLD:
            out.add(token)
    return out


def _get(slide: Any, name: str) -> str:
    raw = slide.get(name) if isinstance(slide, dict) else getattr(slide, name, "")
    return str(raw or "")


_TAIL_MARKERS = re.compile(r"\s*(?:No (?:text|labels?|logos?|letters?|numbers?|dates?|code)|Иллюстративный редакционный)", re.IGNORECASE)


def _scene_summary(brief: str) -> str:
    """What the picture SHOWS, without the brief's safety tail (which every prompt already carries once)."""
    text = _TAIL_MARKERS.split(brief.strip(), maxsplit=1)[0].strip().rstrip(".,; ")
    return text[:170]


def dominant_scene_concepts(briefs: list[str]) -> list[str]:
    """Concepts shared by at least 60% of the briefs (and at least three of them): the carousel is drawing one thing repeatedly."""
    briefs = [b for b in briefs if b and b.strip()]
    n = len(briefs)
    if n < MIN_SLIDES:
        return []
    need = max(DOMINANCE_MIN, math.ceil(DOMINANCE_SHARE * n))
    counts = Counter(token for b in briefs for token in _concepts(b))
    return sorted(token for token, c in counts.items() if c >= need)


def _generated_indices(slides: list[Any]) -> list[int]:
    return [i for i, s in enumerate(slides) if _get(s, "media_source") == "generated" and _get(s, "generation_brief").strip()]


def diversify_slide_briefs(slides: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Keep the first slide that carries a dominant concept (a connective motif); re-brief every later carrier from its own copy.
    Returns (slides, notes) - notes is empty when nothing dominated."""
    idx = _generated_indices(slides)
    dominant = dominant_scene_concepts([_get(slides[i], "generation_brief") for i in idx])
    if not dominant:
        return slides, []
    out, notes, kept = list(slides), [], False
    for i in idx:
        carried = sorted(set(dominant) & _concepts(_get(slides[i], "generation_brief")))
        if not carried:
            continue
        if not kept:
            kept = True
            notes.append({"slide": i, "action": "kept_as_connective_motif", "concepts": carried})
            continue
        avoid = ", ".join(carried)
        update = {
            "generation_brief": (f"{generation_brief(slides[i])} Главный предмет кадра выбери под смысл именно этого слайда; он не должен повторять "
                                 f"предмет соседних слайдов ({avoid})."),
            "visual_direction": _GENERATED_DIRECTION,
        }
        s = slides[i]
        out[i] = {**s, **update} if isinstance(s, dict) else s.model_copy(update=update)
        notes.append({"slide": i, "action": "rebriefed_from_own_beat", "concepts": carried})
    return out, notes


def slide_scene_plan(plan: dict[str, Any], slides: list[Any], index: int) -> dict[str, Any]:
    """The creative plan as ONE slide's picture prompt may read it: no carousel-wide object metaphor, this picture's own beat, a shared look,
    and what the other pictures already show. A carousel of fewer than three generated pictures keeps the plan as is."""
    idx = _generated_indices(slides)
    if len(idx) < MIN_SLIDES or index not in idx:
        return plan
    shown = [_scene_summary(_get(slides[i], "generation_brief")) for i in idx if i != index]
    avoid = " | ".join(o for o in shown if o and not o.startswith("Образ для мысли"))  # a beat-derived brief names no object yet
    return {
        **plan,
        "main_idea": ("One picture in a multi-picture editorial carousel. It carries ONLY the beat described in the scene above; every other picture "
                      "in the carousel carries a different beat of the same story."),
        "visual_treatment": (f"{SHARED_LANGUAGE}"
                             + (f" The carousel's other pictures already show: {avoid}." if avoid else "")
                             + " Do NOT reuse another picture's object, arrangement or metaphor; this picture has its own subject, scale and viewpoint."),
    }
