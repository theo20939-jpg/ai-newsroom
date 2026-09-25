"""Phase B.6: MEDIA-FIRST contract for Instagram carousels.

A finished slide is never a plain surface plus text plus logo. Every slide names WHERE its visual idea comes from (`media_source`):
  source     - a listed real asset that is genuinely suitable as a final visual (a photo / object / illustration, not an article card)
  generated  - a contextual image generated from the slide's `generation_brief` (its layout consumes the reserved subject key `generated`)
  graphic    - a SUBSTANTIVE graphic composition: an interface frame, a flow diagram or a poll. A rule, a scribble or a numeral is not.
TYPOGRAPHIC is never a final media source for a carousel. Everything here is deterministic: no model call, no OCR.
"""
from __future__ import annotations

import re
from typing import Any

GENERATED_SUBJECT_KEY = "generated"
SUBSTANTIVE_GRAPHICS = frozenset({"ui_frame", "flow_diagram", "poll_cards"})
# What services/instagram_declarative_layout.py actually draws into meaningful pixels without a generated image. `ui_frame` draws ONLY
# an empty window chrome (rounded box, title bar, three dots) - it is a frame AROUND a real UI image, never content on its own.
EXECUTABLE_VISUAL_PRIMITIVES = (
    "source media: a listed SOURCE_SUITABLE subject (media region with its key)",
    "flow_diagram with 2-4 short flow_steps (a sequence, a menu path, a before/after)",
    "poll_cards with 2-4 short options written in the slide copy (a checklist, choices, config keys and values, a list of uses)",
    "text: headline, body, a big step number, code or config quoted as text",
    "ui_frame ONLY around a listed real UI screenshot subject placed inside it - never an empty frame",
)
# Visual repetition (2026-09-25): a supported primitive used on many slides is a DESIGN-QUALITY question for founder review, never by itself
# an invalid render plan (the fixed 60% share hard-rejected both 7/7-covered recap plans of the micro-canary). Only a mechanically
# duplicated composition - the same layout, primitive, asset and graphic content - on almost every slide is still rejected.
REPETITION_WARNING_SHARE = 0.6  # diagnostic only: one generic primitive on 5+ slides AND over this share of the carousel
DEGENERATE_MIN_SLIDES = 5
GENERIC_PRIMITIVES = frozenset({"flow_diagram", "poll_cards"})
MAX_GENERATED_SLIDES_PER_POST = 6
MIN_GENERATION_BRIEF_CHARS = 24
MAX_HOOK_CHARS = 120
MIN_STORY_ANCHOR_CHARS = 12
MIN_VISUAL_DIRECTION_CHARS = 60  # a generated slide's visual_direction must answer: what is visible, the story-specific subject, the relationship/action, why it supports the slide
# Generic AI-art defaults (Phase B.6.1). A term is forbidden in a generated slide's plan UNLESS the supplied story evidence itself uses it (the story is literally about it).
GENERIC_AI_ART_TERMS = (
    "glowing cube", "floating cube", "floating sphere", "glowing sphere", "random geometry", "floating geometry", "ai brain", "glowing brain", "robot", "hologram",
    "cyberpunk", "monolith", "neon circuit", "neon grid", "glowing core", "digital brain", "мозг", "робот", "голограмм", "киберпанк", "монолит",
)
_UNSUITABLE_MAX_AREA = 0.10  # an unsuitable source (article card / flat graphic) may only be a small supporting collage fragment


class MediaFirstContractError(ValueError):
    """The plan leaves a slide without a meaningful visual, or uses a media source the contract forbids."""


class UnsupportedClickbaitError(ValueError):
    """Bold framing that the supplied evidence does not literally support."""


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _regions(slide: Any) -> list[Any]:
    layout = _get(slide, "layout")
    return list(_get(layout, "regions") or []) if layout is not None else []


def media_refs(slide: Any) -> list[str]:
    return [str(_get(r, "content_ref")) for r in _regions(slide) if _get(r, "kind") == "media" and _get(r, "content_ref")]


def _flow_steps_valid(steps: Any) -> bool:
    return isinstance(steps, (list, tuple)) and 2 <= len(steps) <= 4 and all(isinstance(s, str) and 1 <= len(s.strip()) <= 22 for s in steps)


def has_substantive_graphic(slide: Any) -> bool:
    """Phase B.6.2: a flow_diagram is substantive only with valid structured flow_steps (2-4 short node labels) - free-form
    visual_direction prose is a legacy render-time fallback (services/instagram_declarative_layout.py), never a way to pass this
    generation-time content check, so a broken flow_diagram plan is rejected here rather than silently rendering text-only."""
    for r in _regions(slide):
        if _get(r, "kind") != "graphic":
            continue
        graphic_type = _get(r, "graphic_type")
        if graphic_type == "flow_diagram":
            if _flow_steps_valid(_get(r, "flow_steps")):
                return True
        elif graphic_type in SUBSTANTIVE_GRAPHICS:
            return True
    return False


def _only_small_fragment(slide: Any, ref: str) -> bool:
    layout = _get(slide, "layout")
    arrangement = _get(layout, "arrangement") if layout is not None else None
    for r in _regions(slide):
        if _get(r, "kind") == "media" and _get(r, "content_ref") == ref:
            if arrangement != "collage" or float(_get(r, "w")) * float(_get(r, "h")) > _UNSUITABLE_MAX_AREA:
                return False
    return True


def find_generic_ai_art(text: str, evidence: list[str]) -> list[str]:
    """Phase B.7: GENERIC_AI_ART_TERMS only - each hit is excused when the slide's OWN evidence is literally about that
    object. There is no separate unescaped "vague phrase" denylist any more: it was redundant with MIN_VISUAL_DIRECTION_CHARS
    (a genuinely lazy one-liner can no longer reach that length) and, having no evidence escape hatch, it false-positived on
    real grounded prose ("two abstract AI model cores" for a real two-model release). Grounding is now asserted structurally
    via the slide's own `source_evidence` handle (assert_media_first below), not by guessing from word choice."""
    lowered = str(text or "").lower()
    blob = " ".join(evidence).lower()
    return [t for t in GENERIC_AI_ART_TERMS if t in lowered and t not in blob]


def assert_hook_contract(slides: list[Any], *, require_mechanic: bool = False) -> None:
    """Phase B.6.1/B.6.2: the first slide is the hook and states its ONE intended reader reaction (hook_emotion) and, from v10.2,
    HOW it creates that reaction (hook_mechanic); every other slide has neither. The model declares both; whether the copy
    actually cashes the mechanic out is founder review, never a regex - see hook_review.json for both fields side by side."""
    from schemas.instagram_creative import HOOK_EMOTIONS, HOOK_MECHANICS

    first = slides[0]
    if str(_get(first, "role")) != "hook":
        raise MediaFirstContractError("slide 0 must be the hook")
    if not str(_get(first, "slide_copy") or "").strip():
        raise MediaFirstContractError("the hook slide has no copy")
    if _get(first, "hook_emotion") not in HOOK_EMOTIONS:
        raise MediaFirstContractError("the hook slide must state hook_emotion (one of the bounded reactions)")
    if require_mechanic and _get(first, "hook_mechanic") not in HOOK_MECHANICS:
        raise MediaFirstContractError("the hook slide must state hook_mechanic (one of the bounded mechanics)")
    for index, slide in enumerate(slides[1:], start=1):
        if _get(slide, "hook_emotion") is not None:
            raise MediaFirstContractError(f"slide {index}: hook_emotion belongs to the hook slide only")
        if _get(slide, "hook_mechanic") is not None:
            raise MediaFirstContractError(f"slide {index}: hook_mechanic belongs to the hook slide only")


def assert_media_first(
    slides: list[Any], *, available_subjects: set[str], unsuitable_subjects: set[str], evidence: list[str] | None = None,
    generated_media_available: bool = True,
) -> None:
    """Raise MediaFirstContractError unless every slide has a meaningful visual idea that its own layout actually executes.

    `evidence` (the whole post's evidence) is accepted for caller-signature compatibility but no longer consulted (Phase B.7):
    a generated slide's grounding is now checked against its OWN resolved `source_evidence` handle, not the post-wide blob."""
    generated = 0
    for index, slide in enumerate(slides):
        regions = _regions(slide)
        media_refs_on_slide = {_get(r, "content_ref") for r in regions if _get(r, "kind") == "media"}
        fillable = set(available_subjects) - set(unsuitable_subjects) | ({GENERATED_SUBJECT_KEY} if generated_media_available else set())
        if any(_get(r, "kind") == "graphic" and _get(r, "graphic_type") == "ui_frame" for r in regions) and not (media_refs_on_slide & fillable):
            raise MediaFirstContractError(
                f"slide {index}: ui_frame renders only an empty window frame and this slide has no real UI image inside it - use "
                "flow_diagram (2-4 flow_steps), poll_cards (2-4 options in the copy), a listed source subject, or text")
        source = _get(slide, "media_source")
        where = f"slide {index}"
        if source not in ("source", "generated", "graphic"):
            raise MediaFirstContractError(f"{where}: media_source must be source, generated or graphic (typographic-only slides are not allowed)")
        refs = media_refs(slide)
        if source == "generated" and not generated_media_available:
            # the runtime capability boundary (settings.instagram_image_generation_mode): a generated slide could never be rendered
            raise MediaFirstContractError(f"{where}: image generation is off for this run - use media_source 'source' (a listed suitable "
                                          f"subject) or 'graphic' (ui_frame, poll_cards or flow_diagram with flow_steps), never 'generated'")
        if source == "generated":
            generated += 1
            if len(str(_get(slide, "generation_brief") or "").strip()) < MIN_GENERATION_BRIEF_CHARS:
                raise MediaFirstContractError(f"{where}: a generated slide needs a concrete generation_brief")
            if GENERATED_SUBJECT_KEY not in refs:
                raise MediaFirstContractError(f"{where}: a generated slide's layout must contain a media region with content_ref '{GENERATED_SUBJECT_KEY}'")
            if len(str(_get(slide, "story_anchor") or "").strip()) < MIN_STORY_ANCHOR_CHARS:
                raise MediaFirstContractError(f"{where}: a generated slide needs a story_anchor - the concrete story-specific thing that makes the image belong to THIS story")
            if len(str(_get(slide, "visual_direction") or "").strip()) < MIN_VISUAL_DIRECTION_CHARS:
                raise MediaFirstContractError(f"{where}: a generated slide's visual_direction must say what is visible, the story-specific subject, the relationship shown and why it supports the slide")
            # Phase B.7: grounding is structural, not lexical - a generated slide must cite the evidence handle its image is
            # FOR (services.instagram_creative_director resolves it to the exact canonical sentence before this runs), and
            # only THAT sentence - never the whole post's evidence - excuses a GENERIC_AI_ART_TERMS hit.
            slide_evidence_text = str(_get(slide, "source_evidence") or "").strip()
            if not slide_evidence_text:
                raise MediaFirstContractError(f"{where}: a generated slide needs source_evidence (a cited evidence handle) so its image is grounded in that slide's own evidence")
            generic = find_generic_ai_art(
                " ".join(str(_get(slide, k) or "") for k in ("generation_brief", "story_anchor", "visual_direction")), [slide_evidence_text])
            if generic:
                raise MediaFirstContractError(f"{where}: generic AI-art default in a generated visual plan: {generic}")
        elif source == "source":
            real = [r for r in refs if r in available_subjects]
            if not real:
                raise MediaFirstContractError(f"{where}: a source slide's layout must use a listed real subject key")
            for ref in real:
                if ref in unsuitable_subjects and not _only_small_fragment(slide, ref):
                    raise MediaFirstContractError(
                        f"{where}: '{ref}' is not suitable as a final visual (flat article / text card); generate a contextual visual, "
                        "or use it only as a small collage fragment"
                    )
        elif not has_substantive_graphic(slide):
            raise MediaFirstContractError(f"{where}: a graphic slide needs a substantive graphic (ui_frame, flow_diagram or poll_cards), not a rule or a numeral")
        stray = [r for r in refs if r != GENERATED_SUBJECT_KEY and r not in available_subjects]
        if stray:
            raise MediaFirstContractError(f"{where}: media region uses an unlisted subject {stray}")
    if generated > MAX_GENERATED_SLIDES_PER_POST:
        raise MediaFirstContractError(f"{generated} generated slides exceed the per-post bound {MAX_GENERATED_SLIDES_PER_POST}")
    degenerate = visual_repetition_report(slides)["degenerate_composition"]
    if degenerate:
        raise MediaFirstContractError(
            f"slides {degenerate['slides']} repeat one identical composition (same layout, primitive, asset and graphic content) - "
            "each slide must show its own content")


def _main_generic(slide: Any) -> str | None:
    regions = _regions(slide)
    if any(_get(r, "kind") == "media" for r in regions):
        return None
    return next((_get(r, "graphic_type") for r in regions if _get(r, "kind") == "graphic" and _get(r, "graphic_type") in GENERIC_PRIMITIVES), None)


def _layout_signature(slide: Any) -> tuple:
    """Geometry + region kinds + primitive + asset: what the eye sees as 'the same layout', ignoring the words on it."""
    return tuple(sorted(
        (str(_get(r, "kind")), str(_get(r, "graphic_type")), str(_get(r, "content_ref")),
         *(round(float(_get(r, k) or 0), 2) for k in ("x", "y", "w", "h")))
        for r in _regions(slide)))


def _composition_signature(slide: Any) -> tuple:
    """The layout signature plus the graphic's own content (flow steps; a poll's options live in the slide copy)."""
    steps = tuple(tuple(_get(r, "flow_steps") or ()) for r in _regions(slide) if _get(r, "flow_steps"))
    poll_copy = str(_get(slide, "slide_copy") or "").strip() if _main_generic(slide) == "poll_cards" else ""
    return (_layout_signature(slide), steps, poll_copy)


def visual_repetition_report(slides: list[Any]) -> dict[str, Any]:
    """Deterministic repetition diagnostics for founder review: primitive distribution, source-asset reuse (across slides and within one
    slide), layout-signature repetition and the one degenerate case the contract still rejects. Advisory except `degenerate_composition`."""
    n = len(slides)
    primitives: dict[str, int] = {}
    asset_slides: dict[str, list[int]] = {}
    asset_within_slide: list[dict[str, Any]] = []
    layouts: dict[tuple, list[int]] = {}
    compositions: dict[tuple, list[int]] = {}
    for index, slide in enumerate(slides):
        main = _main_generic(slide) or ("source_media" if media_refs(slide) else str(_get(slide, "media_source") or "text"))
        primitives[main] = primitives.get(main, 0) + 1
        refs = [r for r in media_refs(slide) if r != GENERATED_SUBJECT_KEY]
        for ref in sorted(set(refs)):
            asset_slides.setdefault(ref, []).append(index)
            if refs.count(ref) > 1:
                asset_within_slide.append({"slide": index, "asset": ref, "uses": refs.count(ref)})
        layouts.setdefault(_layout_signature(slide), []).append(index)
        compositions.setdefault(_composition_signature(slide), []).append(index)
    dominant = max(primitives.items(), key=lambda kv: kv[1]) if primitives else (None, 0)
    repeated_layouts = sorted((v for v in layouts.values() if len(v) > 1), key=len, reverse=True)
    most_composition = max(compositions.values(), key=len) if compositions else []
    degenerate = (n >= DEGENERATE_MIN_SLIDES and len(most_composition) >= max(DEGENERATE_MIN_SLIDES, n - 1))
    warnings = []
    if dominant[0] in GENERIC_PRIMITIVES and dominant[1] >= 5 and dominant[1] > REPETITION_WARNING_SHARE * n:
        warnings.append(f"{dominant[0]} carries {dominant[1]} of {n} slides")
    if repeated_layouts and len(repeated_layouts[0]) >= max(3, n // 2 + 1):
        warnings.append(f"one layout signature on slides {repeated_layouts[0]}")
    warnings += [f"asset '{a}' reused on slides {s}" for a, s in asset_slides.items() if len(s) >= 3]
    warnings += [f"asset '{w['asset']}' used {w['uses']}x on slide {w['slide']}" for w in asset_within_slide]
    return {
        "slide_count": n, "primitive_distribution": primitives,
        "source_asset_reuse": {a: s for a, s in asset_slides.items()}, "asset_reuse_within_slide": asset_within_slide,
        "layout_signature_repetition": [v for v in repeated_layouts],
        "design_repetition_warning": bool(warnings), "warnings": warnings,
        "degenerate_composition": {"slides": most_composition} if degenerate else None,
    }


def slide_has_visual(*, notes: dict[str, Any], planned_slide: dict[str, Any] | None, source_image_treatment: str | None = None) -> bool:
    """True when the RENDERED slide carries an executed non-text visual: a real media region, a legacy media treatment, or a substantive graphic in an executed declarative plan."""
    if notes.get("media_regions"):
        return True
    if source_image_treatment and source_image_treatment != "none":
        return True
    if notes.get("layout_plan_applied") and planned_slide is not None and has_substantive_graphic(planned_slide):
        return not any(str(r).startswith("flow_diagram_without_sequence") for r in (notes.get("unresolved_media_regions") or []))
    return False


_CLICKBAIT = (r"ты обязан", r"все делают неправильно", r"это уничтожит", r"интернет умер", r"всё изменилось", r"все изменилось")
_WEAK_HOOK_OPENERS = (
    r"^неделя,\s+когда", r"^эта неделя", r"^компания\s+\S+\s+представил", r"^новая модель получила", r"^\d+\s+функци\w+\s+нового", r"^главные\s+(истории|новости)", r"^вот что произошло",
)


def find_unsupported_clickbait(copy_fields: dict[str, str], evidence: list[str]) -> list[str]:
    blob = " ".join(evidence).lower()
    hits: list[str] = []
    for name, text in copy_fields.items():
        lowered = str(text or "").lower()
        for pattern in _CLICKBAIT:
            if re.search(pattern, lowered) and not re.search(pattern, blob):
                hits.append(f"{name}: {pattern}")
    return hits


def assert_no_unsupported_clickbait(copy_fields: dict[str, str], evidence: list[str]) -> None:
    hits = find_unsupported_clickbait(copy_fields, evidence)
    if hits:
        raise UnsupportedClickbaitError(f"clickbait framing without literal evidence support: {hits}")


def weak_hook_patterns(hook_copy: str) -> list[str]:
    """Advisory: the generic openers the KAGE hook policy avoids. Reported for review, never a hard failure."""
    lowered = str(hook_copy or "").strip().lower()
    return [pattern for pattern in _WEAK_HOOK_OPENERS if re.search(pattern, lowered)]


def assert_hook_is_short(hook_copy: str) -> None:
    if len(str(hook_copy or "").strip()) > MAX_HOOK_CHARS:
        raise MediaFirstContractError(f"hook copy is {len(str(hook_copy).strip())} chars; the Instagram hook is one strong line (<= {MAX_HOOK_CHARS})")


# Content pass (prompt v10.7). A slide must communicate something concrete on its own: the founder's rejected examples ("Он сменил критерий",
# "Сначала задача. Потом модель.", "И ещё: пульс и кислород.") are clean phrases that say almost nothing without the caption. Deterministic
# floor only - whether the copy is actually INTERESTING is editorial review, never a regex.
MIN_BODY_WORDS = 6
SELF_SUFFICIENT_HEADLINE_WORDS = 9
_STEP_LABEL = re.compile(r"^\s*(?:шаг|step)\s*\d{1,2}\s*[.:—\-]?\s*", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"[\w$€£₽%]+", text or "")


def has_concrete_anchor(text: str) -> bool:
    """A number/price/percentage or a Latin-script name (products, companies, models) that the reader can hold on to. A step label's
    numeral is structure, not content."""
    body = _STEP_LABEL.sub("", text or "")
    return bool(re.search(r"\d", body) or re.search(r"[$€£₽]", body) or re.search(r"\b[A-Za-z][A-Za-z0-9.\-]+", body))


def find_thin_slides(slides: list[Any]) -> list[str]:
    """Slides that carry no concrete information of their own. The hook needs a concrete anchor or explanatory body; every other slide
    needs an explanatory body of MIN_BODY_WORDS words unless its headline is itself a full, anchored statement."""
    thin: list[str] = []
    for index, slide in enumerate(slides):
        headline = str(_get(slide, "slide_copy") or "")
        body_words = len(_words(str(_get(slide, "slide_body") or "")))
        if index == 0:
            if not has_concrete_anchor(headline) and body_words < MIN_BODY_WORDS:
                thin.append(f"slide {index} (hook) names no concrete fact, number or name and has no explanatory body: {headline!r}")
            continue
        if body_words >= MIN_BODY_WORDS:
            continue
        if has_concrete_anchor(headline) and len(_words(_STEP_LABEL.sub("", headline))) >= SELF_SUFFICIENT_HEADLINE_WORDS:
            continue
        thin.append(f"slide {index} has no explanatory body (>= {MIN_BODY_WORDS} words) and its headline alone is not a full concrete statement: {headline!r}")
    return thin


def assert_information_density(slides: list[Any]) -> None:
    thin = find_thin_slides(slides)
    if thin:
        raise MediaFirstContractError("informationally empty slides - the carousel must make sense without the caption: " + "; ".join(thin))
