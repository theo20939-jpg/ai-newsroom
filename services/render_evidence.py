"""DESIGN-SPEC-ENFORCEMENT-1 §3/§4: RenderEvidence - a structured, renderer-truthful metadata
contract describing what the deterministic renderer *actually did*, so the Art Director's
SPEC_MATCH dimension can verify the FINAL render against an ACTIVE Design Spec's declarative
layout/typography parameters field-by-field, instead of only checking the `presentation_mode`
invariant (`services/telegram_art_director_spec_evaluation.py::_evaluate_spec_match`).

DESIGN PRINCIPLE (spec §4 - "renderer is the source of truth"): every field below is derived by
*replaying the renderer's own deterministic decision helpers*
(`services/brand_renderer.py` / `services/nnj_master_news_overlay.py` - the same pure functions,
the same locked constants), never by asking an LLM to estimate a value the renderer already knows.
When a legacy render genuinely cannot expose a field, that ONE field is `NOT_MEASURED` (a distinct
sentinel, never confused with "measured as absent / zero / false") - it contributes nothing to
SPEC_MATCH, and never makes the whole dimension NOT_APPLICABLE.

This module performs NO pixel inspection and NO Design Spec comparison - it only produces the
evidence. `services/telegram_art_director_spec_evaluation.py` consumes it. Vision/OCR
(`services/telegram_art_director_vision.py`) still independently owns visual collision, perceived
clipping, metric ambiguity and model-drawn fake branding (spec §13).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class _NotMeasured:
    """Singleton sentinel: this render cannot truthfully expose this field yet (spec §4). Distinct
    from `None` / `0` / `False` - a spec check skips a NOT_MEASURED field entirely rather than
    treating it as a measured value."""

    _instance: "_NotMeasured | None" = None

    def __new__(cls) -> "_NotMeasured":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "NOT_MEASURED"

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return False


NOT_MEASURED = _NotMeasured()


class SourceTreatment(str, Enum):
    """Mirrors schemas/declarative_visual_parameters.py::SourceImageTreatment value-for-value so a
    spec's declared `source_image_treatment` compares directly against evidence."""

    PRESERVE = "preserve"
    RECOMPOSE = "recompose"
    CROP = "crop"


class ScrimState(str, Enum):
    """Mirrors schemas/declarative_visual_parameters.py::ScrimTreatment."""

    NONE = "none"
    LIGHT = "light"
    STRONG = "strong"


@dataclass(frozen=True)
class RenderEvidence:
    """Only fields the renderer can truthfully produce for a given render. A field the renderer
    does not decide for this presentation type, or a legacy render that cannot yet expose it,
    stays `NOT_MEASURED`."""

    presentation_type: str
    renderer_variant: str
    renderer_version: str | None = None

    canvas_width: int | _NotMeasured = NOT_MEASURED
    canvas_height: int | _NotMeasured = NOT_MEASURED

    # The safe edge inset the renderer actually used, as a fraction of canvas width. A spec's
    # `safe_margin_frac` is treated as a FLOOR - the render must keep AT LEAST this much margin, so
    # a larger actual inset (e.g. QUOTE's 0.053 vs the spec's 0.019) is safer, not a violation.
    safe_margin_frac: float | _NotMeasured = NOT_MEASURED

    # Exactly one canonical NNJ mark is the contract; >1 is a hard failure.
    logo_count: int | _NotMeasured = NOT_MEASURED
    # PlacementZone.value ("lower_right" | "lower_left" | "upper_right" | "upper_left") - the corner
    # the renderer's own deterministic scorer chose for the brand mark / signature.
    logo_zone: str | _NotMeasured = NOT_MEASURED
    # The corner the primary compositional accent (independent pulse line / stat block) landed in.
    # NOT_MEASURED when the renderer fuses the accent into the single brand-mark signature and
    # never makes a separate placement decision (the MASTER NEWS production path).
    placement_zone: str | _NotMeasured = NOT_MEASURED

    scrim_applied: bool | _NotMeasured = NOT_MEASURED
    scrim_treatment: str | _NotMeasured = NOT_MEASURED  # ScrimState.value

    source_image_treatment: str | _NotMeasured = NOT_MEASURED  # SourceTreatment.value
    source_preserved: bool | _NotMeasured = NOT_MEASURED

    presentation_mode: str | _NotMeasured = NOT_MEASURED

    primary_font_size: int | _NotMeasured = NOT_MEASURED
    secondary_font_size: int | _NotMeasured = NOT_MEASURED
    actual_line_count: int | _NotMeasured = NOT_MEASURED

    text_clipped: bool | _NotMeasured = NOT_MEASURED

    # DESIGN-SPEC-ENFORCEMENT-1 addendum §3: fields the renderer POSITIVELY determined do not apply
    # to THIS render (e.g. `primary_font_size` in MINIMAL_SOURCE_PRESERVING - no stat typography is
    # rendered at all; `scrim_treatment` for QUOTE - the portrait is inset into a designed card, not
    # composited under a source-legibility scrim). Distinct from a NOT_MEASURED value that IS
    # applicable but the legacy renderer cannot expose (e.g. NEWS `placement_zone`) - the latter
    # makes SPEC_MATCH PARTIAL_EVIDENCE, the former does not.
    not_applicable_fields: frozenset[str] = frozenset()

    # Free-form notes about WHY a field is NOT_MEASURED / not applicable - for logs / console / the
    # phase report, never read by the deterministic comparator.
    notes: dict[str, str] = field(default_factory=dict)

    def measured(self, name: str) -> bool:
        return not isinstance(getattr(self, name, NOT_MEASURED), _NotMeasured)


# --------------------------------------------------------------------------------------------------
# Derivers - each replays the renderer's own deterministic helpers. Imports are lazy so this module
# has no import-time coupling to the renderer stack (and no circular import via
# telegram_art_director_spec_evaluation).
# --------------------------------------------------------------------------------------------------


def _zone(placement: Any) -> str | _NotMeasured:
    """ComponentPlacement / PlacementZone -> the four-corner string the spec vocabulary uses, or
    NOT_MEASURED for OMITTED / anything unrecognised."""
    val = getattr(placement, "value", placement)
    if val in ("lower_right", "lower_left", "upper_right", "upper_left"):
        return str(val)
    return NOT_MEASURED


def _canvas_crop_treatment(src_w: int, src_h: int, canvas_w: int, canvas_h: int) -> tuple[str, bool]:
    """`_fit_photo_to_canvas()` center-crops-to-fill: pixels are dropped only when the source
    aspect ratio differs from the target. Returns (SourceTreatment.value, source_preserved)."""
    src_ar = (src_w / src_h) if src_h else 0.0
    canvas_ar = (canvas_w / canvas_h) if canvas_h else 0.0
    cropped = abs(src_ar - canvas_ar) > 0.01
    return (SourceTreatment.CROP.value if cropped else SourceTreatment.PRESERVE.value, not cropped)


def derive_master_news_render_evidence(
    source_image_bytes: bytes,
    *,
    presentation_type: str = "NEWS",
    subject_bbox: tuple[int, int, int, int] | None = None,
) -> RenderEvidence:
    """NEWS production path (`worker/content_cycle.py` -> `apply_master_news_branding()`), also the
    grouped-carousel branding path. Replays that function's own steps: fit the source to the
    1280x720 canvas (`_fit_photo_to_canvas`), then `select_master_news_branding()` for the real
    single-brand-mark decision + corner. The upper mark and lower signature are mutually exclusive
    by construction (VISUAL-SINGLE-BRAND-MARK-1 §6), so `logo_count` is 0 or 1. The pulse waveform
    is drawn as part of that one lower signature at the same corner - there is no independent
    pulse-placement decision to measure, so `placement_zone` is NOT_MEASURED. No headline text is
    baked by this contract -> the font / line fields stay NOT_MEASURED."""
    from PIL import Image

    from services.nnj_master_news_overlay import (
        _CANVAS_H,
        _CANVAS_W,
        _SAFE_INSET_FRAC,
        ComponentPlacement,
        _fit_photo_to_canvas,
        select_master_news_branding,
    )

    with Image.open(io.BytesIO(source_image_bytes)) as im:
        src_w, src_h = im.width, im.height
        photo_fit = _fit_photo_to_canvas(im.convert("RGBA"), (_CANVAS_W, _CANVAS_H))
        decision = select_master_news_branding(photo_fit, subject_bbox=subject_bbox)

    treatment, preserved = _canvas_crop_treatment(src_w, src_h, _CANVAS_W, _CANVAS_H)

    lower = decision.lower_signature.placement
    upper = decision.upper_mark.placement
    placed = [p for p in (lower, upper) if p is not ComponentPlacement.OMITTED]
    chosen = placed[0] if placed else None

    return RenderEvidence(
        presentation_type=presentation_type,
        renderer_variant="nnj_master_news_overlay.apply_master_news_branding",
        renderer_version="master_news_v1",
        canvas_width=_CANVAS_W,
        canvas_height=_CANVAS_H,
        safe_margin_frac=round(float(_SAFE_INSET_FRAC), 5),
        logo_count=len(placed),
        logo_zone=_zone(chosen),
        # DESIGN-SPEC-ENFORCEMENT-1 addendum §1: `placement_zone` is a REAL, unresolved
        # measurement gap, NOT "not applicable". The founder telegram_news v1 spec declares
        # placement_zone=lower_left (the pulse accent bottom-left) - that describes the retired
        # two-corner render_news_hero() hero layout. The production MASTER NEWS path fuses the
        # pulse into the ONE lower brand-mark signature at the signature's own corner
        # (lower_right-preferred) and `MasterNewsBrandingDecision` exposes NO independent
        # accent-placement decision to read. So the spec field cannot be verified here -> SPEC_MATCH
        # becomes PARTIAL_EVIDENCE, and this drift is a candidate for the same narrow future
        # renderer correction as the BREAKING band. It is deliberately left OUT of
        # not_applicable_fields so it surfaces to the Founder rather than being silently dropped.
        placement_zone=NOT_MEASURED,
        scrim_applied=False,
        scrim_treatment=ScrimState.NONE.value,
        source_image_treatment=treatment,
        source_preserved=preserved,
        presentation_mode=NOT_MEASURED,
        text_clipped=False,
        # MASTER NEWS bakes no headline text -> the spec's font/line params genuinely do not apply.
        not_applicable_fields=frozenset({"primary_font_size", "secondary_font_size", "actual_line_count"}),
        notes={
            "placement_zone": (
                "MEASUREMENT GAP: MASTER NEWS fuses the pulse into the single lower brand-mark "
                "signature; no independent accent-placement decision exists to read. The founder "
                "placement_zone=lower_left describes the retired two-corner render_news_hero layout."
            ),
            "primary_font_size": "NOT APPLICABLE: MASTER NEWS contract bakes no headline text",
            "actual_line_count": "NOT APPLICABLE: MASTER NEWS contract bakes no headline text",
        },
    )


def derive_breaking_render_evidence(source_image_bytes: bytes | None) -> RenderEvidence:
    """BREAKING production path (`render_branded_media` -> `render_breaking_frame`), corrected in
    VISUAL-RENDERER-RECONCILIATION-1: the retired ~22% dark-gradient lower-third band + baked
    "BREAKING" wordmark + red accent rule are GONE. BREAKING now composites the source at its
    NATIVE size (no fit / crop -> `source_image_treatment=preserve`) with the exact MASTER NEWS
    single lower signature (`select_master_news_branding()` on the native photo - one thin line +
    pulse + exactly one canonical NNJ mark, adaptive safe-corner placement, single-brand-mark
    invariant). This deriver REPLAYS that same helper.

    `scrim_treatment` is now genuinely `none` - the corrected renderer composites no band/scrim of
    any kind over the source. `placement_zone` is NOT_MEASURED but APPLICABLE (the founder
    telegram_breaking v1 declares placement_zone=lower_left, wrongly derived from the retired two-
    corner render_news_hero note - the same discrepancy as NEWS): the fused NEWS-family signature
    exposes no independent accent placement, so BREAKING SPEC_MATCH is PARTIAL_EVIDENCE with that
    one field named, pending the founder-review `telegram_breaking v2` correction. font/line
    params do not apply (BREAKING bakes no editorial typography)."""
    from PIL import Image

    from services.brand_renderer import _CARD_HEIGHT, _CARD_WIDTH
    from services.nnj_master_news_overlay import _SAFE_INSET_FRAC, ComponentPlacement, select_master_news_branding

    if source_image_bytes is not None:
        with Image.open(io.BytesIO(source_image_bytes)) as im:
            canvas_w, canvas_h = im.width, im.height
            decision = select_master_news_branding(im.convert("RGBA"))
        placed = [
            p for p in (decision.lower_signature.placement, decision.upper_mark.placement)
            if p is not ComponentPlacement.OMITTED
        ]
        logo_count = len(placed)
        logo_zone = _zone(placed[0]) if placed else NOT_MEASURED
        src_present = True
    else:
        canvas_w, canvas_h = _CARD_WIDTH, _CARD_HEIGHT
        logo_count, logo_zone, src_present = 1, "lower_right", False

    notes = {
        "placement_zone": (
            "MEASUREMENT GAP: BREAKING now uses the MASTER NEWS fused lower signature (line + pulse "
            "+ one mark); no independent accent-placement decision exists to read. The founder "
            "telegram_breaking v1 placement_zone=lower_left is the same wrongly-derived parameter as "
            "NEWS - see the telegram_breaking v2 candidate proposal."
        ),
        "primary_font_size": "NOT APPLICABLE: BREAKING bakes no editorial typography (band + wordmark removed)",
        "actual_line_count": "NOT APPLICABLE: BREAKING bakes no editorial typography",
    }
    if not src_present:
        notes["source_image_treatment"] = "no source photo supplied - BREAKING rendered its minimal solid card + one mark; nothing to preserve or destroy"

    return RenderEvidence(
        presentation_type="BREAKING",
        renderer_variant="brand_renderer.render_breaking_frame -> nnj_master_news_overlay.select_master_news_branding",
        renderer_version="pulse-breaking-v2",
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        safe_margin_frac=round(float(_SAFE_INSET_FRAC), 5),
        logo_count=logo_count,
        logo_zone=logo_zone,
        placement_zone=NOT_MEASURED,
        scrim_applied=False,
        scrim_treatment=ScrimState.NONE.value,
        source_image_treatment=SourceTreatment.PRESERVE.value,
        source_preserved=True,
        presentation_mode=NOT_MEASURED,
        text_clipped=False,
        not_applicable_fields=frozenset({"primary_font_size", "secondary_font_size", "actual_line_count"}),
        notes=notes,
    )


def _derive_data_hero_evidence(data_candidate: Any) -> RenderEvidence:
    """FOUNDER-VISUAL-BOARD-ALIGNMENT-1: renderer-truthful evidence for
    `brand_renderer.render_data_hero_card` (board format 3). Replays the two deterministic
    font/wrap decisions the renderer makes and reads back the same locked constants."""
    from PIL import Image, ImageDraw

    from services.data_source_classification import DataPresentationMode

    from services.brand_renderer import (
        _CANVAS_H,
        _CANVAS_W,
        _HERO_LABEL_FONT_MAX,
        _HERO_LABEL_FONT_MIN,
        _HERO_LABEL_MAX_LINES,
        _HERO_MARGIN,
        _HERO_VALUE_FONT_MAX,
        _HERO_VALUE_FONT_MIN,
        _fit_single_line,
        _fit_wrapped_block,
    )

    draw = ImageDraw.Draw(Image.new("RGB", (_CANVAS_W, _CANVAS_H)))
    inner_w = _CANVAS_W - _HERO_MARGIN * 2
    value_font, value_size = _fit_single_line(
        draw, data_candidate.value, font_max=_HERO_VALUE_FONT_MAX,
        font_min=_HERO_VALUE_FONT_MIN, max_width=inner_w,
    )
    label_lines: list[str] = []
    if str(getattr(data_candidate, "label", "")).strip():
        label_lines, _lf, _ls = _fit_wrapped_block(
            draw, str(data_candidate.label).strip().upper(), font_max=_HERO_LABEL_FONT_MAX,
            font_min=_HERO_LABEL_FONT_MIN, max_width=inner_w, max_lines=_HERO_LABEL_MAX_LINES,
        )
    size_attr = getattr(value_font, "size", value_size)
    primary_font_size = int(size_attr) if isinstance(size_attr, (int, float)) else int(value_size)

    return RenderEvidence(
        presentation_type="DATA",
        renderer_variant="brand_renderer.render_data_hero_card",
        renderer_version="pulse-data-hero-v1",
        canvas_width=_CANVAS_W,
        canvas_height=_CANVAS_H,
        safe_margin_frac=round(_HERO_MARGIN / _CANVAS_W, 5),
        logo_count=1,
        logo_zone="lower_right",
        # The dominant metric block is the primary compositional accent - it sits in the upper-left.
        placement_zone="upper_left",
        scrim_applied=False,
        scrim_treatment=ScrimState.NONE.value,
        # The hero card is a NEW generated artifact, not a transform of a source photo - there is
        # no source to preserve, recompose or crop. Distinct from a measurement gap.
        source_image_treatment=NOT_MEASURED,
        source_preserved=NOT_MEASURED,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD.value,
        primary_font_size=primary_font_size,
        actual_line_count=len(label_lines),
        text_clipped=False,
        not_applicable_fields=frozenset({"secondary_font_size", "source_image_treatment", "source_preserved"}),
        notes={
            "source_image_treatment": "NOT APPLICABLE: generated hero-metric card - no source photo is used",
            "renderer": "render_data_hero_card: primary value font-fit + label wrapped <= 2 lines, deterministic",
        },
    )


def derive_data_render_evidence(
    source_image_bytes: bytes,
    data_candidate: Any,
    *,
    presentation_mode: Any = None,
) -> RenderEvidence:
    """DATA production path (`render_branded_media` -> `render_data_card`). Replays, in the exact
    order `render_data_card` runs them:
      1. `_fit_photo_to_canvas` (center-crop-to-fill) -> canvas + whether a crop occurred;
      2. `_select_data_signature` (the real bottom-corner scorer) or, when it returns None, the
         guaranteed lower-right fallback signature (which draws on an opaque scrim);
      3. for `MINIMAL_SOURCE_PRESERVING`: STOP - the stat block is skipped entirely, so
         `actual_line_count=0` and `primary_font_size` stays NOT_MEASURED (no stat typography was
         rendered - "42 stays 42");
      4. otherwise `_measure_data_stat_block` (real chosen stat font + wrapped label lines) then
         `_select_data_block_placement` - and if THAT returns None the stat block is not drawn
         after all, so again `actual_line_count=0` / font NOT_MEASURED.
    `data_candidate` is the same `DataCandidate` the render used (its value/label text drives the
    font-fit + wrap), so the measured values are exactly what the render produced."""
    from PIL import Image, ImageDraw

    from services.brand_renderer import (
        _DATA_BLOCK_MARGIN,
        _DATA_BLOCK_WIDTH_FRAC,
        _DATA_STAT_FONT_MAX,
        _DATA_STAT_FONT_MIN,
        _build_data_signature_fallback,
        _data_signature_geometry,
        _measure_data_stat_block,
        _select_data_block_placement,
        _select_data_signature,
    )
    from services.data_source_classification import DataPresentationMode
    from services.nnj_master_news_overlay import (
        _CANVAS_H,
        _CANVAS_W,
        _SAFE_INSET_FRAC,
        _SCORE_PAD_PX_FRAC,
        _fit_photo_to_canvas,
    )

    mode = presentation_mode if isinstance(presentation_mode, DataPresentationMode) else None
    mode_value: str | _NotMeasured = mode.value if mode is not None else NOT_MEASURED

    # FOUNDER-VISUAL-BOARD-ALIGNMENT-1: FULL_DATA_CARD now renders the generated hero-metric card
    # (`brand_renderer.render_data_hero_card`) - a source-free graphite panel, so none of the
    # photo-fit / bottom-signature / corner-stat replay below applies. Replay the hero renderer's
    # own two deterministic decisions instead: the fitted primary-value font size and the wrapped
    # label line count.
    if mode is DataPresentationMode.FULL_DATA_CARD:
        return _derive_data_hero_evidence(data_candidate)

    with Image.open(io.BytesIO(source_image_bytes)) as im:
        src_w, src_h = im.width, im.height
        canvas = _fit_photo_to_canvas(im.convert("RGBA"), (_CANVAS_W, _CANVAS_H))

    canvas_w, canvas_h = canvas.size
    treatment, preserved = _canvas_crop_treatment(src_w, src_h, canvas_w, canvas_h)

    inset = max(1, round(_SAFE_INSET_FRAC * canvas_w))
    pad = max(1, round(_SCORE_PAD_PX_FRAC * canvas_w))

    signature_plan = _select_data_signature(canvas, inset=inset, pad=pad)
    notes: dict[str, str] = {"_data_stat_font_range": f"{_DATA_STAT_FONT_MIN}-{_DATA_STAT_FONT_MAX}"}
    if signature_plan is not None:
        logo_zone = _zone(signature_plan.placement)
        mark_box, pulse_box, line_box = _data_signature_geometry(
            canvas.size, signature_plan.placement, inset, signature_plan.line_len,
        )
        signature_box: tuple[int, int, int, int] | None = (
            min(mark_box[0], pulse_box[0], line_box[0]), min(mark_box[1], pulse_box[1], line_box[1]),
            max(mark_box[2], pulse_box[2], line_box[2]), max(mark_box[3], pulse_box[3], line_box[3]),
        )
        scrim_applied = False
        scrim_value: str | _NotMeasured = ScrimState.NONE.value
    else:
        # Every bottom corner failed the scored search -> the guaranteed fallback signature, which
        # draws its mark on an opaque scrim (`_SIGNATURE_FALLBACK_SCRIM_FILL`), always lower-right.
        logo_zone = "lower_right"
        _fallback_img, fallback_box = _build_data_signature_fallback(canvas.size, inset=inset)
        signature_box = (int(fallback_box[0]), int(fallback_box[1]), int(fallback_box[2]), int(fallback_box[3]))
        scrim_applied = True
        scrim_value = ScrimState.STRONG.value
        notes["scrim_treatment"] = "no bottom corner passed the scored signature search; the guaranteed lower-right fallback signature draws on an opaque scrim"

    primary_font_size: int | _NotMeasured = NOT_MEASURED
    line_count: int | _NotMeasured = NOT_MEASURED
    stat_block_rendered = False

    if mode is DataPresentationMode.MINIMAL_SOURCE_PRESERVING:
        line_count = 0
        notes["primary_font_size"] = "NOT APPLICABLE: MINIMAL_SOURCE_PRESERVING skips the stat block entirely - no stat typography rendered ('42 stays 42')"
    else:
        block_w = max(160, round(_DATA_BLOCK_WIDTH_FRAC * canvas_w))
        inner_max_width = max(1, block_w - _DATA_BLOCK_MARGIN * 2)
        draw = ImageDraw.Draw(canvas)
        _primary, stat_font, _bbox, label_lines, _lf, _llh, text_height = _measure_data_stat_block(
            draw, data_candidate, max_width=inner_max_width,
        )
        block_h = round(text_height) + _DATA_BLOCK_MARGIN * 2
        placement_result = _select_data_block_placement(
            canvas, block_w=block_w, block_h=block_h, inset=inset, pad=pad, avoid_box=signature_box,
        )
        if placement_result is None:
            # No safe corner -> render_data_card draws no stat text at all (never a forced overlay).
            line_count = 0
            notes["primary_font_size"] = "NOT APPLICABLE: no safe corner for the stat block; render_data_card drew no stat text"
        else:
            stat_block_rendered = True
            size = getattr(stat_font, "size", None)
            primary_font_size = int(size) if isinstance(size, (int, float)) else NOT_MEASURED
            line_count = len(label_lines)

    # `primary_font_size` is a genuine spec field only when a stat block was actually rendered.
    # `secondary_font_size` is never a distinct spec-governed size in render_data_card (the label
    # font is derived from the stat font fit) -> always not applicable.
    not_applicable = {"secondary_font_size"}
    if not stat_block_rendered:
        not_applicable.add("primary_font_size")

    return RenderEvidence(
        presentation_type="DATA",
        renderer_variant="brand_renderer.render_data_card",
        renderer_version="pulse-data-v1",
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        safe_margin_frac=round(float(_SAFE_INSET_FRAC), 5),
        logo_count=1,
        logo_zone=logo_zone,
        placement_zone=logo_zone,
        scrim_applied=scrim_applied,
        scrim_treatment=scrim_value,
        source_image_treatment=treatment,
        source_preserved=preserved,
        presentation_mode=mode_value,
        primary_font_size=primary_font_size,
        actual_line_count=line_count,
        text_clipped=False,
        not_applicable_fields=frozenset(not_applicable),
        notes=notes,
    )


_QUOTE_TEXT_PANEL_FEATHER_PX = 40  # render_quote_card(): overlay rect extends 40px past the portrait's left edge


def derive_quote_render_evidence(portrait_bytes: bytes | None) -> RenderEvidence:
    """QUOTE production path (`render_branded_media` -> `render_quote_card`). The portrait is
    resized to the card height at its OWN aspect and pasted on the right (no crop) - the card is a
    fixed 1200x675 with a fixed `margin = 64` (-> safe_margin_frac 0.053, comfortably above the
    spec's 0.019 floor). The mark is bottom-right (`_paste_svg_mark`, same margin).

    `primary_font_size` / `actual_line_count` -> not applicable: the quote body is rendered
    Telegram-native-style (fixed `_font(42)`), and telegram_quote v1 declares no font range / no
    max_line_count.

    DESIGN-SPEC-ENFORCEMENT-1 addendum §1 - `scrim_treatment` -> not applicable, WITH forensic
    evidence rather than a bare NOT_MEASURED: `render_quote_card` starts the card as a solid black
    1200x675, pastes the portrait flush to the RIGHT, then draws a near-opaque (alpha 235/255)
    black rectangle over the LEFT text region that extends only `_QUOTE_TEXT_PANEL_FEATHER_PX`
    (=40px) past the portrait's left edge. That rectangle is the card's own text panel on its own
    black ground; the only part touching the source portrait is that 40px anti-hard-edge feather
    (measured below as a single-digit % of the portrait width). Unlike the BREAKING band (22% of
    the frame, 82% opacity, over the whole photo), this is NOT a source-legibility scrim - there is
    no scrim decision over the source to verify. A regression test pins this geometry."""
    from services.brand_renderer import _CARD_HEIGHT, _CARD_WIDTH

    quote_margin_px = 64  # render_quote_card()'s own fixed `margin = 64`
    notes = {
        "primary_font_size": "NOT APPLICABLE: quote body is Telegram-native fixed _font(42); telegram_quote v1 declares no font range",
        "actual_line_count": "NOT APPLICABLE: telegram_quote v1 declares no max_line_count",
    }
    if portrait_bytes is not None:
        from PIL import Image

        with Image.open(io.BytesIO(portrait_bytes)) as pim:
            portrait_w = round(_CARD_HEIGHT * pim.width / pim.height) if pim.height else _CARD_WIDTH
        feather_frac = _QUOTE_TEXT_PANEL_FEATHER_PX / portrait_w if portrait_w else 1.0
        notes["scrim_treatment"] = (
            f"NOT APPLICABLE: the dark left panel is the card's own text ground; it overlaps the "
            f"portrait by only {_QUOTE_TEXT_PANEL_FEATHER_PX}px "
            f"({feather_frac:.1%} of the {portrait_w}px portrait width) as an edge feather, not a "
            f"source-legibility scrim. (cf. BREAKING band: 22% of frame, 82% opacity, whole photo.)"
        )
    else:
        notes["scrim_treatment"] = "NOT APPLICABLE: no portrait supplied - fully generated card, no source to scrim"
        notes["source_image_treatment"] = "no portrait supplied - fully generated card; nothing to preserve or destroy"

    return RenderEvidence(
        presentation_type="QUOTE",
        renderer_variant="brand_renderer.render_quote_card",
        renderer_version="pulse-quote-v1",
        canvas_width=_CARD_WIDTH,
        canvas_height=_CARD_HEIGHT,
        safe_margin_frac=round(quote_margin_px / _CARD_WIDTH, 5),
        logo_count=1,
        logo_zone="lower_right",
        placement_zone=NOT_MEASURED,
        scrim_applied=portrait_bytes is not None,
        scrim_treatment=NOT_MEASURED,
        source_image_treatment=SourceTreatment.PRESERVE.value,
        source_preserved=True,
        presentation_mode=NOT_MEASURED,
        primary_font_size=NOT_MEASURED,
        actual_line_count=NOT_MEASURED,
        text_clipped=False,
        not_applicable_fields=frozenset(
            {"scrim_treatment", "placement_zone", "primary_font_size", "secondary_font_size", "actual_line_count"}
        ),
        notes=notes,
    )


__all__ = [
    "NOT_MEASURED",
    "RenderEvidence",
    "ScrimState",
    "SourceTreatment",
    "derive_breaking_render_evidence",
    "derive_data_render_evidence",
    "derive_master_news_render_evidence",
    "derive_quote_render_evidence",
]
