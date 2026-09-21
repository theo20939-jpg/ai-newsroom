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
MAX_GENERATED_SLIDES_PER_POST = 6
MIN_GENERATION_BRIEF_CHARS = 24
MAX_HOOK_CHARS = 120
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


def has_substantive_graphic(slide: Any) -> bool:
    return any(_get(r, "kind") == "graphic" and _get(r, "graphic_type") in SUBSTANTIVE_GRAPHICS for r in _regions(slide))


def _only_small_fragment(slide: Any, ref: str) -> bool:
    layout = _get(slide, "layout")
    arrangement = _get(layout, "arrangement") if layout is not None else None
    for r in _regions(slide):
        if _get(r, "kind") == "media" and _get(r, "content_ref") == ref:
            if arrangement != "collage" or float(_get(r, "w")) * float(_get(r, "h")) > _UNSUITABLE_MAX_AREA:
                return False
    return True


def assert_media_first(slides: list[Any], *, available_subjects: set[str], unsuitable_subjects: set[str]) -> None:
    """Raise MediaFirstContractError unless every slide has a meaningful visual idea that its own layout actually executes."""
    generated = 0
    for index, slide in enumerate(slides):
        source = _get(slide, "media_source")
        where = f"slide {index}"
        if source not in ("source", "generated", "graphic"):
            raise MediaFirstContractError(f"{where}: media_source must be source, generated or graphic (typographic-only slides are not allowed)")
        refs = media_refs(slide)
        if source == "generated":
            generated += 1
            if len(str(_get(slide, "generation_brief") or "").strip()) < MIN_GENERATION_BRIEF_CHARS:
                raise MediaFirstContractError(f"{where}: a generated slide needs a concrete generation_brief")
            if GENERATED_SUBJECT_KEY not in refs:
                raise MediaFirstContractError(f"{where}: a generated slide's layout must contain a media region with content_ref '{GENERATED_SUBJECT_KEY}'")
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
    r"^компания\s+\S+\s+представил", r"^новая модель получила", r"^\d+\s+функци\w+\s+нового", r"^главные\s+(истории|новости)", r"^вот что произошло",
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
