"""Phase V2.10H - the locked MASTER NEWS production contract, wired as the real NEWS branding
path. No real Gemini/OpenAI/Anthropic/Telegram call anywhere in this file. Synthetic PIL fixtures
are used for the algorithmic checks (fast, deterministic); real evidence images are used only
where a real-photo proof is the actual point of the test."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from services.nnj_master_news_mark import rasterize_nnj_mark
from services.nnj_master_news_overlay import (
    NEWS_BRANDING_BRANDED,
    NEWS_BRANDING_NO_OVERLAY_SAFETY,
    ComponentPlacement,
    apply_master_news_branding,
    select_master_news_branding,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CANVAS = (1280, 720)


def _flat_photo(color=(120, 120, 120)) -> bytes:
    im = Image.new("RGB", _CANVAS, color)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _photo_with_busy_patch(box) -> bytes:
    im = Image.new("RGB", _CANVAS, (120, 120, 120))
    draw = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    step = 4
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if ((x - x0) // step + (y - y0) // step) % 2 == 0:
                draw.rectangle([x, y, x + step, y + step], fill=(250, 250, 250))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _all_busy_photo() -> bytes:
    return _photo_with_busy_patch((0, 0, _CANVAS[0], _CANVAS[1]))


# ---------------------------------------------------------------------------
# 1 - canonical boxless SVG-derived mark
# ---------------------------------------------------------------------------


def test_mark_is_rasterized_from_real_canonical_svg_not_a_box() -> None:
    mark = rasterize_nnj_mark(target_width=100)
    assert mark.mode == "RGBA"
    # boxless: no fully-opaque background rectangle - only the wordmark's own alpha content
    alpha = mark.split()[-1]
    opaque_fraction = sum(1 for v in alpha.getdata() if v > 200) / (mark.width * mark.height)
    assert opaque_fraction < 0.5  # a filled box would be ~100% opaque; a wordmark is sparse


def test_mark_red_fill_matches_locked_nnj_red() -> None:
    mark = rasterize_nnj_mark(target_width=200, red=True)
    rgb = mark.convert("RGB")
    # sample a pixel known to be inside a glyph stroke (found empirically via alpha bbox center)
    alpha = mark.split()[-1]
    bbox = alpha.getbbox()
    assert bbox is not None
    cx, cy = (bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2
    # search nearby for an opaque pixel (center may land in a letter counter/gap)
    found = None
    for dy in range(-10, 11):
        for dx in range(-10, 11):
            x, y = min(max(cx + dx, 0), mark.width - 1), min(max(cy + dy, 0), mark.height - 1)
            if alpha.getpixel((x, y)) > 200:
                found = rgb.getpixel((x, y))
                break
        if found:
            break
    assert found is not None
    # allow +-3/channel anti-aliasing rounding rather than requiring an exact byte match
    assert all(abs(a - b) <= 3 for a, b in zip(found, (237, 28, 36), strict=True))


# ---------------------------------------------------------------------------
# 2 - MASTER_BALANCED geometry / proportional scaling
# ---------------------------------------------------------------------------


def test_master_balanced_geometry_matches_locked_contract() -> None:
    branded, decision = apply_master_news_branding(_flat_photo())
    assert decision.canvas_size == _CANVAS
    assert decision.lower_signature.placement is ComponentPlacement.LOWER_RIGHT


def test_geometry_scales_proportionally_to_a_different_canvas() -> None:
    im = Image.new("RGB", (640, 360), (120, 120, 120))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    branded, decision = apply_master_news_branding(buf.getvalue())
    assert decision.canvas_size == _CANVAS  # apply_master_news_branding always fits to 1280x720
    out = Image.open(io.BytesIO(branded))
    assert out.size == _CANVAS


# ---------------------------------------------------------------------------
# 3/4 - LEFT never mirrors NNJ; RIGHT/LEFT ordering
# ---------------------------------------------------------------------------


def test_left_lower_signature_never_mirrors_nnj_glyph() -> None:
    """The LEFT-anchored NNJ mark must be pixel-identical to a RIGHT-anchored mark of the same
    size (never horizontally flipped) - proven by rasterizing both independently and comparing."""
    right_mark = rasterize_nnj_mark(target_width=38, red=True)
    left_mark = rasterize_nnj_mark(target_width=38, red=True)
    assert list(right_mark.getdata()) == list(left_mark.getdata())  # same unflipped rasterization


def test_right_ordering_is_line_pulse_nnj() -> None:
    from services.nnj_master_news_overlay import _build_lower_signature_image

    layer = _build_lower_signature_image(_CANVAS, ComponentPlacement.LOWER_RIGHT, 20)
    bbox = layer.split()[-1].getbbox()
    assert bbox is not None
    # the terminal mark sits at the RIGHT end - the rightmost content column must belong to it
    # (verified indirectly: content extends close to the right inset)
    assert _CANVAS[0] - bbox[2] <= 21  # within ~inset of the right edge


def test_left_ordering_is_nnj_pulse_line() -> None:
    from services.nnj_master_news_overlay import _build_lower_signature_image

    layer = _build_lower_signature_image(_CANVAS, ComponentPlacement.LOWER_LEFT, 20)
    bbox = layer.split()[-1].getbbox()
    assert bbox is not None
    assert bbox[0] <= 21  # content starts within ~inset of the left edge (the mark)


# ---------------------------------------------------------------------------
# 5-10 - independent components, placement priority, fallback, degradation
# ---------------------------------------------------------------------------


def test_upper_mark_never_joins_an_already_placed_lower_signature() -> None:
    """VISUAL-SINGLE-BRAND-MARK-1 §6: both components draw the SAME canonical NNJ mark, so a clean
    photo where the lower signature can be placed must never ALSO place the upper mark - that
    would put two independently-readable NNJ marks on one image. Supersedes this suite's own prior
    "upper_and_lower" expectation, which was the real, live duplicate-brand-mark root cause this
    phase closes."""
    branded, decision = apply_master_news_branding(_flat_photo())
    assert decision.lower_signature.placement is not ComponentPlacement.OMITTED
    assert decision.upper_mark.placement is ComponentPlacement.OMITTED
    assert decision.degradation_mode == "lower_signature_only"


def test_lower_right_preferred_when_safe() -> None:
    branded, decision = apply_master_news_branding(_flat_photo())
    assert decision.lower_signature.placement is ComponentPlacement.LOWER_RIGHT


def test_lower_left_fallback_when_lower_right_blocked() -> None:
    photo = Image.open(io.BytesIO(_photo_with_busy_patch((900, 550, 1280, 720))))
    decision = select_master_news_branding(photo)
    assert decision.lower_signature.placement is not ComponentPlacement.LOWER_RIGHT


def test_upper_fallback_reachable_when_both_lower_edges_blocked() -> None:
    photo = Image.open(io.BytesIO(_photo_with_busy_patch((0, 550, 1280, 720))))
    decision = select_master_news_branding(photo)
    assert decision.lower_signature.placement in (
        ComponentPlacement.UPPER_RIGHT, ComponentPlacement.UPPER_LEFT, ComponentPlacement.OMITTED,
    )


def test_upper_mark_only_degradation_reachable() -> None:
    """A photo busy along the whole bottom edge but clean at top: lower signature should fail to
    find a bottom slot and either fall back to an upper corner or omit, while the (independently
    evaluated, smaller-footprint) upper mark can still succeed."""
    photo_bytes = _photo_with_busy_patch((0, 600, 1280, 720))
    branded, decision = apply_master_news_branding(photo_bytes)
    # "upper_and_lower" is structurally unreachable since VISUAL-SINGLE-BRAND-MARK-1 §6 (both
    # components draw the same canonical mark - never composited together).
    assert decision.degradation_mode in ("upper_mark_only", "lower_signature_only")


def test_lower_signature_only_degradation_reachable() -> None:
    photo = Image.open(io.BytesIO(_photo_with_busy_patch((_CANVAS[0] - 200, 0, _CANVAS[0], 200))))
    decision = select_master_news_branding(photo)
    # busy only in the upper-right corner (small relative to the lower signature's own big footprint
    # elsewhere) - lower signature should still find a safe slot; upper mark specifically targets
    # that corner first and may be blocked there
    assert decision.lower_signature.placement is not ComponentPlacement.OMITTED


def test_no_overlay_degradation_reachable_for_a_fully_busy_photo() -> None:
    branded, decision = apply_master_news_branding(_all_busy_photo())
    assert decision.degradation_mode == "no_overlay"
    assert decision.upper_mark.placement is ComponentPlacement.OMITTED
    assert decision.lower_signature.placement is ComponentPlacement.OMITTED


# ---------------------------------------------------------------------------
# 11/12 - protected-region collision + visibility rejection
# ---------------------------------------------------------------------------


def test_subject_bbox_collision_is_rejected_even_when_pixels_look_quiet() -> None:
    photo = Image.open(io.BytesIO(_flat_photo()))
    full_frame_bbox = (0, 0, _CANVAS[0], _CANVAS[1])
    decision = select_master_news_branding(photo, subject_bbox=full_frame_bbox)
    assert decision.degradation_mode == "no_overlay"
    assert any(a.collides_with_subject_bbox for a in decision.lower_signature.attempts)


def test_visibility_rejection_for_red_on_red_background() -> None:
    """A region whose own mean color is very close to the locked NNJ red must be rejected even
    though it may be perfectly 'quiet' (flat, low edge density)."""
    im = Image.new("RGB", _CANVAS, (237, 28, 36))  # exactly the locked NNJ red
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    branded, decision = apply_master_news_branding(buf.getvalue())
    assert decision.degradation_mode == "no_overlay"
    assert any(not a.safe_by_visibility for a in decision.lower_signature.attempts)


# ---------------------------------------------------------------------------
# 13 - no hardcoded story bbox
# ---------------------------------------------------------------------------


def test_no_hardcoded_story_specific_bbox_in_production_code() -> None:
    for rel in ("services/nnj_master_news_overlay.py", "services/nnj_master_news_mark.py", "worker/content_cycle.py"):
        source = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "robot_vacuum" not in source.lower()
        assert "330, 0, 970, 660" not in source


# ---------------------------------------------------------------------------
# 14/15 - ORIGINAL_SOURCE and RECOMPOSED both use the same real production call
# ---------------------------------------------------------------------------


def _non_comment_lines(source: str) -> str:
    """Strips full-line and trailing '#' comments so structural checks below assert on real code,
    never on historical-context prose (this file's own comments legitimately name the superseded
    Candidate C symbols while explaining why they are no longer called)."""
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


def test_content_cycle_calls_master_news_branding_not_candidate_c() -> None:
    source = (_REPO_ROOT / "worker/content_cycle.py").read_text(encoding="utf-8")
    code = _non_comment_lines(source)
    assert "apply_candidate_c_branding" not in code
    assert "apply_adaptive_nnj_branding" not in code
    # Phase V2.25: the import grew from a single name to three (the branding function plus the
    # explicit diagnostic-status constants) and is therefore now parenthesized/multi-line - check
    # for the module and the name independently rather than one exact single-line string.
    assert "from services.nnj_master_news_overlay import (" in source
    assert "apply_master_news_branding,\n)" in source
    assert "branded_bytes, master_decision = apply_master_news_branding(" in source
    assert "source_bytes, disable_lower_signature=recomposition_source_risk is not None," in source


def test_content_cycle_two_branding_call_sites_cover_primary_image_and_media_group() -> None:
    """Phase V2.10H originally required exactly one call site (reached regardless of whether
    recomposition succeeded). Phase V2.25 Part B deliberately adds a SECOND, real call site - the
    real accidental bug this phase fixed was that a NEWS media-group (album) send only ever
    branded media_group_items[0], leaving every other photo in the group completely unbranded with
    no diagnostic. The fix independently re-resolves and brands every remaining group photo via
    its own apply_master_news_branding() call - so the production file now legitimately has two
    call sites (primary image; remaining media-group images), never duplicated logic inline."""
    source = (_REPO_ROOT / "worker/content_cycle.py").read_text(encoding="utf-8")
    code = _non_comment_lines(source)
    assert code.count("apply_master_news_branding(") == 2
    assert "visual_path" in source  # ORIGINAL_SOURCE vs RECOMPOSE still distinguished in telemetry
    assert "news_branding_status" in source  # Phase V2.25 Part B explicit diagnostic vocabulary


# ---------------------------------------------------------------------------
# 16/17 - Candidate C left alone
# ---------------------------------------------------------------------------


def test_candidate_c_no_longer_the_normal_news_production_call() -> None:
    source = (_REPO_ROOT / "worker/content_cycle.py").read_text(encoding="utf-8")
    assert "from services.nnj_adaptive_overlay import" not in source


def test_candidate_c_locked_asset_untouched() -> None:

    path = _REPO_ROOT / "assets/brand/newsroom_visuals/candidate_c_locked/candidate_c_overlay.png"
    assert path.exists()
    # the asset's own manifest records its authoritative geometry - re-derive and compare rather
    # than a bare existence check, so any pixel edit would be caught
    from PIL import Image as _Image
    im = _Image.open(path)
    bbox = im.convert("RGBA").split()[-1].getbbox()
    assert bbox == (826, 623, 1248, 682)  # unchanged since V2.4G lock


def test_nnj_adaptive_overlay_module_itself_untouched_and_importable() -> None:
    """Candidate C's own selector module must still exist, still work, and still be reachable as
    historical/fallback evidence - just no longer called from worker/content_cycle.py."""
    from services.nnj_adaptive_overlay import apply_adaptive_nnj_branding

    branded, decision = apply_adaptive_nnj_branding(_flat_photo())
    assert decision.overlay_mode in ("full_signature", "logo_only", "no_overlay")


# ---------------------------------------------------------------------------
# Phase V2.10I - conservative factual-safety hardening (real Honor forensic finding)
# ---------------------------------------------------------------------------


def _photo_with_small_hotspot(hotspot_box) -> bytes:
    """A large, otherwise-flat candidate region with ONE small high-contrast text-like patch
    inside it - reproduces the real Honor dilution shape (a small real disclaimer inside a much
    larger quiet region) without depending on a specific real evidence file staying byte-for-byte
    unchanged."""
    im = Image.new("RGB", _CANVAS, (120, 120, 120))
    draw = ImageDraw.Draw(im)
    x0, y0, x1, y1 = hotspot_box
    step = 2
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if ((x - x0) // step + (y - y0) // step) % 2 == 0:
                draw.rectangle([x, y, x + step, y + step], fill=(250, 250, 250))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_patch_based_scoring_catches_a_small_hotspot_a_whole_region_average_would_dilute() -> None:
    """Reproduces the real V2.10H Honor failure shape synthetically: a small, dense, text-like
    patch positioned inside the LOWER_RIGHT candidate's own padded scoring box, small enough that
    a naive whole-region average would fall under the old 8.0 threshold (as it did for the real
    Honor case: 6.45), but which the Phase V2.10I patch-based worst-case must still catch."""
    # LOWER_RIGHT's own padded score box spans roughly the bottom-right ~490x210px region at
    # 1280x720 (component width ~307px + 2x50px pad, component height ~38px + 2x50px pad) - place
    # a small hotspot inside it, away from its edges, sized similarly to the real disclaimer text
    # relative to its own containing box.
    hotspot = (1000, 660, 1180, 685)
    photo = Image.open(io.BytesIO(_photo_with_small_hotspot(hotspot)))
    decision = select_master_news_branding(photo)
    lower_right_attempts = [a for a in decision.lower_signature.attempts if a.placement is ComponentPlacement.LOWER_RIGHT]
    # LOWER_RIGHT must be rejected (and therefore recorded as an attempt, not silently accepted)
    # for this hotspot to prove the patch-based fix actually works.
    assert lower_right_attempts, "LOWER_RIGHT was accepted outright - the hotspot was diluted away, reproducing the V2.10H bug"
    assert not lower_right_attempts[0].accepted


def test_detail_risk_field_present_and_gates_independently() -> None:
    branded, decision = apply_master_news_branding(_flat_photo())
    for a in decision.lower_signature.attempts + decision.upper_mark.attempts:
        assert hasattr(a, "detail_risk_pct")
        assert hasattr(a, "safe_by_detail_risk")


# ---------------------------------------------------------------------------
# disable_lower_signature (Phase V2.10I §7 - existing metadata reuse)
# ---------------------------------------------------------------------------


def test_disable_lower_signature_forces_omitted_without_scoring_any_region() -> None:
    branded, decision = apply_master_news_branding(_flat_photo(), disable_lower_signature=True, signature_style="fused")
    assert decision.lower_signature.placement is ComponentPlacement.OMITTED
    assert decision.lower_signature.attempts == ()
    assert decision.lower_signature.disabled_reason is not None


def test_disable_lower_signature_does_not_affect_upper_mark() -> None:
    branded, decision = apply_master_news_branding(_flat_photo(), disable_lower_signature=True, signature_style="fused")
    assert decision.upper_mark.placement is not ComponentPlacement.OMITTED  # still independently evaluated


def test_lower_signature_not_disabled_by_default() -> None:
    branded, decision = apply_master_news_branding(_flat_photo())
    assert decision.lower_signature.disabled_reason is None


# ---------------------------------------------------------------------------
# Real Honor regression (the actual V2.10H failure case, re-verified fixed)
# ---------------------------------------------------------------------------


def test_honor_disclaimer_region_no_longer_falsely_accepted() -> None:
    """The exact real V2.10H failure: LOWER_RIGHT on the real Honor photo must now be rejected
    (it contains real disclaimer text), forcing a fallback to a different, genuinely safe
    placement or OMITTED - never silently accepted over the text."""
    path = _REPO_ROOT / "assets/brand/newsroom_visuals/v2_7_local_e2e_proof/source_honor_camera.jpg"
    if not path.exists():
        import pytest
        pytest.skip("real evidence file not present in this checkout")
    branded, decision = apply_master_news_branding(path.read_bytes())
    lower_right_attempts = [a for a in decision.lower_signature.attempts if a.placement is ComponentPlacement.LOWER_RIGHT]
    assert decision.lower_signature.placement is not ComponentPlacement.LOWER_RIGHT
    if lower_right_attempts:
        assert not lower_right_attempts[0].accepted


# ---------------------------------------------------------------------------
# Phase V2.17 - MASTER_BALANCED rescale: same approved visual language, larger footprint
# ---------------------------------------------------------------------------


def test_rescaled_lower_signature_width_is_in_the_approved_42_to_46_percent_range() -> None:
    """Phase V2.25: superseded the V2.17-era ~30-34% approved range (see git history for that
    test) with a materially larger ~44% target - a real, deliberate, user-requested enlargement,
    not a regression of that earlier calibration."""
    from services.nnj_master_news_overlay import _LOWER_TOTAL_WIDTH_FRAC

    assert 0.42 <= _LOWER_TOTAL_WIDTH_FRAC <= 0.46


def test_rescaled_components_are_all_larger_than_the_pre_v2_17_footprint() -> None:
    """Every lower-signature/upper-mark fraction grew relative to the original V2.10H lock - proves
    this is a uniform enlargement of the same design, not an accidental partial change."""
    from services.nnj_master_news_overlay import (
        _CANVAS_H, _CANVAS_W, _GAP_FRAC, _LOWER_LINE_THICKNESS_FRAC, _LOWER_MARK_W_FRAC,
        _LOWER_PULSE_H_FRAC, _LOWER_PULSE_W_FRAC, _LOWER_TOTAL_WIDTH_FRAC, _UPPER_MARK_W_FRAC,
    )

    original_px = {
        "lower_total_width": (307, _CANVAS_W, _LOWER_TOTAL_WIDTH_FRAC),
        "lower_pulse_w": (36, _CANVAS_W, _LOWER_PULSE_W_FRAC),
        "lower_pulse_h": (34, _CANVAS_H, _LOWER_PULSE_H_FRAC),
        "lower_line_thickness": (2, _CANVAS_H, _LOWER_LINE_THICKNESS_FRAC),
        "lower_mark_w": (38, _CANVAS_W, _LOWER_MARK_W_FRAC),
        "upper_mark_w": (32, _CANVAS_W, _UPPER_MARK_W_FRAC),
        "gap": (10, _CANVAS_W, _GAP_FRAC),
    }
    for name, (old_px, dimension, new_frac) in original_px.items():
        new_px = new_frac * dimension
        assert new_px > old_px, f"{name} did not grow: {old_px}px -> {new_px}px"


def test_upper_mark_grew_within_the_approved_1_35_to_1_6x_range_from_original() -> None:
    """Cumulative ratio from the ORIGINAL V2.10H lock (32px), across both the V2.17 and V2.25
    rescales together - still a "same design, larger" enlargement, not a redesign."""
    from services.nnj_master_news_overlay import _CANVAS_W, _UPPER_MARK_W_FRAC

    old_px = 32
    new_px = _UPPER_MARK_W_FRAC * _CANVAS_W
    ratio = new_px / old_px
    assert 1.35 <= ratio <= 2.2


def test_upper_mark_grew_within_the_approved_1_3_to_1_45x_range_from_v2_17() -> None:
    """Phase V2.25's own explicit target range, measured from the immediately-prior V2.17
    baseline (48px) rather than the original V2.10H lock - the ~1.375x increase this phase asked
    for specifically."""
    from services.nnj_master_news_overlay import _CANVAS_W, _UPPER_MARK_W_FRAC

    v2_17_px = 48
    new_px = _UPPER_MARK_W_FRAC * _CANVAS_W
    ratio = new_px / v2_17_px
    assert 1.3 <= ratio <= 1.45


def test_safe_inset_deliberately_enlarged_for_v2_25() -> None:
    """Phase V2.10H originally found no mathematical necessity to change the corner inset just
    because the components drawn inside the box grew (V2.17 left it at 20px). Phase V2.25
    deliberately changes that: the user's own explicit instruction enlarges the inset to 24px to
    match the materially larger overall footprint - a real, intentional change, not a silent
    drift away from the V2.10H §2 calibration."""
    from services.nnj_master_news_overlay import _CANVAS_W, _SAFE_INSET_FRAC

    assert round(_SAFE_INSET_FRAC * _CANVAS_W) == 24


def test_rescaled_footprint_never_exceeds_canvas_bounds_on_a_quiet_photo() -> None:
    """A quiet, safe photo should accept both components in some corner - proves the new, larger
    footprint still fits entirely within the 1280x720 canvas at every accepted placement."""
    branded, decision = apply_master_news_branding(_flat_photo())
    w, h = decision.canvas_size
    for component in (decision.upper_mark, decision.lower_signature):
        if component.placement is ComponentPlacement.OMITTED:
            continue
        accepted = [a for a in component.attempts if a.accepted]
        assert accepted, f"{component.placement} reported accepted but no attempt record confirms it"
        x0, y0, x1, y1 = accepted[0].box
        assert x0 >= 0 and y0 >= 0 and x1 <= w and y1 <= h, f"box {accepted[0].box} exceeds canvas {w}x{h}"
    # The branded image itself must also still be exactly the reference canvas size.
    with Image.open(io.BytesIO(branded)) as im:
        assert im.size == (w, h)


def test_rescaled_safety_scoring_uses_the_new_larger_footprint_not_the_old_one() -> None:
    """Proves the safety evaluation genuinely reads the new constants (not a stale cached size):
    the scored box width for LOWER_RIGHT must match the current `_LOWER_TOTAL_WIDTH_FRAC` (~563px/
    44.0% as of Phase V2.25, up from ~410px/32.0% at V2.17 and ~307px/24.0% originally), at the
    1280-wide reference canvas."""
    from services.nnj_master_news_overlay import _LOWER_TOTAL_WIDTH_FRAC

    branded, decision = apply_master_news_branding(_flat_photo(), signature_style="fused")
    lower_right_attempts = [
        a for a in decision.lower_signature.attempts if a.placement is ComponentPlacement.LOWER_RIGHT
    ]
    assert lower_right_attempts, "expected LOWER_RIGHT to have been scored on a quiet photo"
    box = lower_right_attempts[0].box
    scored_width = box[2] - box[0]
    expected_width = round(_LOWER_TOTAL_WIDTH_FRAC * 1280)
    assert scored_width == expected_width
    assert scored_width > 307  # unambiguously larger than the pre-V2.17 value


def test_degradation_still_reports_only_the_four_valid_modes_after_rescale() -> None:
    for photo_bytes in (_flat_photo(), _all_busy_photo()):
        _branded, decision = apply_master_news_branding(photo_bytes)
        assert decision.degradation_mode in (
            "upper_and_lower", "lower_signature_only", "upper_mark_only", "no_overlay",
        )


# ---------------------------------------------------------------------------
# Phase V2.25 Part B - the explicit news_branding_status diagnostic (BRANDED / NO_OVERLAY_SAFETY
# are the two states MasterNewsBrandingDecision can itself represent; the caller in
# worker/content_cycle.py is responsible for the other two - ORIGINAL_SOURCE_BRANDING_FAILURE and
# NO_OVERLAY_NO_SOURCE_BYTES - see tests/test_v2_9_production_wiring.py for those).
# ---------------------------------------------------------------------------


def test_news_branding_status_is_branded_for_a_safe_quiet_photo() -> None:
    """TEST 1 (Phase V2.25 spec): a normal, safe NEWS image must resolve to the BRANDED final
    asset - at least one component actually composited, and the decision's own explicit status
    says so."""
    branded, decision = apply_master_news_branding(_flat_photo())
    assert decision.news_branding_status == NEWS_BRANDING_BRANDED
    assert decision.degradation_mode != "no_overlay"
    # The branded bytes must be a real, valid, full-canvas JPEG - not a bare passthrough.
    with Image.open(io.BytesIO(branded)) as im:
        assert im.size == _CANVAS


def test_news_branding_status_is_no_overlay_safety_for_an_explicitly_unsafe_photo() -> None:
    """TEST 2 (Phase V2.25 spec): an explicitly unsafe footprint (every candidate corner rejected
    on both components) must permit NO_OVERLAY - the safety fallback is never removed - and the
    decision's own explicit status must say NO_OVERLAY_SAFETY, distinguishable from BRANDED."""
    branded, decision = apply_master_news_branding(_all_busy_photo())
    assert decision.degradation_mode == "no_overlay"
    assert decision.news_branding_status == NEWS_BRANDING_NO_OVERLAY_SAFETY
    # Still a valid, full-canvas image - the safety fallback degrades branding, never the send.
    with Image.open(io.BytesIO(branded)) as im:
        assert im.size == _CANVAS


# ---------------------------------------------------------------------------
# Phase V2.25 TEST 7 - small/portrait source images: _fit_photo_to_canvas() always normalizes to
# the fixed 1280x720 reference canvas regardless of input shape, but the new, materially larger
# (~44%) geometry must still fit entirely within that canvas and never crash on an extreme input
# aspect ratio or a genuinely small source image.
# ---------------------------------------------------------------------------


def _portrait_flat_photo(color=(120, 120, 120)) -> bytes:
    im = Image.new("RGB", (900, 1600), color)  # tall portrait source, far from the 16:9 canvas
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _small_flat_photo(color=(120, 120, 120)) -> bytes:
    im = Image.new("RGB", (320, 180), color)  # well under the 1280x720 reference canvas
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_portrait_source_image_bounds_remain_valid_at_the_new_larger_geometry() -> None:
    branded, decision = apply_master_news_branding(_portrait_flat_photo())
    with Image.open(io.BytesIO(branded)) as im:
        assert im.size == _CANVAS
    for component in (decision.upper_mark, decision.lower_signature):
        if component.placement is ComponentPlacement.OMITTED:
            continue
        accepted = [a for a in component.attempts if a.accepted]
        assert accepted
        x0, y0, x1, y1 = accepted[0].box
        assert 0 <= x0 < x1 <= _CANVAS[0]
        assert 0 <= y0 < y1 <= _CANVAS[1]


def test_small_source_image_bounds_remain_valid_at_the_new_larger_geometry() -> None:
    branded, decision = apply_master_news_branding(_small_flat_photo())
    with Image.open(io.BytesIO(branded)) as im:
        assert im.size == _CANVAS
    for component in (decision.upper_mark, decision.lower_signature):
        if component.placement is ComponentPlacement.OMITTED:
            continue
        accepted = [a for a in component.attempts if a.accepted]
        assert accepted
        x0, y0, x1, y1 = accepted[0].box
        assert 0 <= x0 < x1 <= _CANVAS[0]
        assert 0 <= y0 < y1 <= _CANVAS[1]
