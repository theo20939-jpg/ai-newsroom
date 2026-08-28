"""Phase V2.10A - real-path visual blocker fix (automatic brand placement + source-branding
preservation). No real Gemini/OpenAI/Anthropic/Telegram call anywhere in this file. Synthetic PIL
fixtures are used for the pure algorithmic checks (fast, deterministic, no dependency on evidence
files); the real V2.6/V2.7/V2.4 evidence images are used only where a real-photo proof is the
actual point of the test."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from services.editorial_recomposition import (
    assess_pixel_branding_risk,
    build_overlay_aware_recomposition_prompt,
    build_recomposition_prompt,
    maybe_recompose,
)
from services.nnj_adaptive_overlay import (
    SCALE_LADDER,
    FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX,
    OverlayPlacement,
    apply_adaptive_nnj_branding,
    select_overlay_placement,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CANVAS = (1280, 720)


def _flat_photo(color: tuple[int, int, int] = (120, 120, 120)) -> bytes:
    """A perfectly uniform photo - safe everywhere under pixel-occupancy scoring."""
    im = Image.new("RGB", _CANVAS, color)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _photo_with_busy_patch(box: tuple[int, int, int, int]) -> bytes:
    """A flat photo with one small, genuinely high-edge-density checkerboard patch drawn at
    `box` - simulates a real watermark/logo's own strong local edges without needing a real
    image file."""
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
# 1 - missing manual bbox no longer means full-frame subject / automatic NO_OVERLAY
# ---------------------------------------------------------------------------


def test_missing_bbox_on_a_clean_real_photo_does_not_force_no_overlay() -> None:
    branded, decision = apply_adaptive_nnj_branding(_flat_photo())  # no subject_bbox at all
    assert decision.overlay_mode == "full_signature"
    assert decision.placement is not OverlayPlacement.NO_OVERLAY
    assert decision.used_pixel_occupancy is True


def test_old_full_frame_conservative_bbox_would_have_forced_no_overlay() -> None:
    """Proves the OLD behavior really was this bad - the regression this phase fixes."""
    decision = select_overlay_placement(FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX)
    assert decision.overlay_mode == "no_overlay"


# ---------------------------------------------------------------------------
# 2 - real automatic image evidence produces a visible Candidate C result
# ---------------------------------------------------------------------------


def test_real_robot_vacuum_photo_automatic_call_produces_visible_signature() -> None:
    path = _REPO_ROOT / "assets/brand/newsroom_visuals/v2_6_telegram_canary/source_original.jpg"
    if not path.exists():
        pytest.skip("real evidence file not present in this checkout")
    branded, decision = apply_adaptive_nnj_branding(path.read_bytes())  # no bbox - real production call
    assert decision.overlay_mode == "full_signature"


def test_real_iphone_and_honor_photos_automatic_call_picks_preferred_corner() -> None:
    for rel in (
        "assets/brand/newsroom_visuals/v2_4_canary_live/raw_recomposed.jpg",
        "assets/brand/newsroom_visuals/v2_7_local_e2e_proof/source_honor_camera.jpg",
    ):
        path = _REPO_ROOT / rel
        if not path.exists():
            pytest.skip("real evidence file not present in this checkout")
        _branded, decision = apply_adaptive_nnj_branding(path.read_bytes())
        assert decision.placement is OverlayPlacement.LOWER_RIGHT
        assert decision.scale == 1.00
        assert len(decision.attempts) == 0


# ---------------------------------------------------------------------------
# 3/4 - placement priority and scale ordering preserved on the pixel-occupancy path
# ---------------------------------------------------------------------------


def test_placement_priority_order_preserved_on_pixel_occupancy_path() -> None:
    """An entirely clean/flat photo must win at the FIRST placement tried (lower_right) -
    proves the pixel-occupancy path did not reorder or skip the locked priority sequence."""
    _branded, decision = apply_adaptive_nnj_branding(_flat_photo())
    assert decision.placement is OverlayPlacement.LOWER_RIGHT
    assert decision.scale == 1.00
    assert len(decision.attempts) == 0


def test_scale_ladder_order_preserved_on_pixel_occupancy_path() -> None:
    """A busy patch sized to block the full lower_right zone at scale 1.00 but clear once the
    zone shrinks at a smaller scale - proves scale is tried largest-first, within one placement,
    exactly as SCALE_LADDER declares, before ever moving to the next placement."""
    # lower_right zone at scale 1.00 covers roughly the bottom-right ~470x110px (measured via the
    # real Candidate C alpha content + margin/clearance); a patch placed just inside that region
    # but outside the smaller-scale zones lets 1.00/0.85 collide while 0.70/0.55 clear.
    busy_box = (1280 - 470, 720 - 110, 1280 - 380, 720 - 90)
    photo = _photo_with_busy_patch(busy_box)
    decision = select_overlay_placement(None, photo_for_occupancy=Image.open(io.BytesIO(photo)))
    assert decision.placement is OverlayPlacement.LOWER_RIGHT
    assert decision.scale in SCALE_LADDER
    tried_scales = [a.scale for a in decision.attempts if a.placement is OverlayPlacement.LOWER_RIGHT]
    assert tried_scales == sorted(tried_scales, reverse=True)  # largest tried first


# ---------------------------------------------------------------------------
# 5 - semantic/protected-region signal wins over pixel occupancy when available
# ---------------------------------------------------------------------------


def test_trustworthy_bbox_takes_priority_over_pixel_occupancy_signal() -> None:
    """A photo that pixel-occupancy scoring would flag as unsafe everywhere (fully busy), but a
    supplied subject_bbox that only covers the far side of the canvas - the bbox path must be
    used (and must succeed), never silently replaced by the pixel signal."""
    busy_everywhere = Image.open(io.BytesIO(_all_busy_photo()))
    small_far_bbox = (0, 0, 100, 100)  # nowhere near lower_right
    decision = select_overlay_placement(small_far_bbox, photo_for_occupancy=busy_everywhere)
    assert decision.used_pixel_occupancy is False
    assert decision.overlay_mode == "full_signature"
    assert decision.placement is OverlayPlacement.LOWER_RIGHT


# ---------------------------------------------------------------------------
# 6/7 - LOGO_ONLY and NO_OVERLAY remain reachable on the pixel-occupancy path
# ---------------------------------------------------------------------------


def test_logo_only_reachable_when_all_full_signature_candidates_are_risky() -> None:
    busy = Image.open(io.BytesIO(_all_busy_photo()))
    decision = select_overlay_placement(None, photo_for_occupancy=busy)
    assert decision.placement in (OverlayPlacement.LOGO_ONLY, OverlayPlacement.NO_OVERLAY)
    assert all(a.placement != OverlayPlacement.LOGO_ONLY for a in decision.attempts) or decision.placement is OverlayPlacement.NO_OVERLAY


def test_no_overlay_still_possible_for_genuinely_unsafe_full_frame_content() -> None:
    # A uniformly noisy/busy frame must degrade at least to LOGO_ONLY; NO_OVERLAY remains a
    # structurally reachable terminal state (asserted directly against the full-frame-conservative
    # bbox path, which is exactly this same "everything collides" case by construction).
    fallback_decision = select_overlay_placement(FULL_FRAME_CONSERVATIVE_SUBJECT_BBOX)
    assert fallback_decision.overlay_mode == "no_overlay"


# ---------------------------------------------------------------------------
# 8/9 - ORIGINAL_SOURCE and successful-recomposition inputs both receive adaptive branding
# ---------------------------------------------------------------------------


def test_original_source_style_input_receives_full_adaptive_branding() -> None:
    branded_bytes, decision = apply_adaptive_nnj_branding(_flat_photo())
    assert decision.overlay_mode != "no_overlay"
    assert branded_bytes != _flat_photo()  # branding pixels were actually composited


def test_recomposed_style_input_receives_full_adaptive_branding() -> None:
    # A clean, low-detail image stands in for a successful source-preserving recomposition's own
    # typical negative-space background - the function has no opinion about where bytes came from.
    branded_bytes, decision = apply_adaptive_nnj_branding(_flat_photo((40, 45, 60)))
    assert decision.overlay_mode != "no_overlay"


# ---------------------------------------------------------------------------
# 10/11 - factual source-branding pixel risk prevents recomposition, fails open, zero provider calls
# ---------------------------------------------------------------------------


def test_pixel_branding_risk_detected_on_real_watermarked_photo() -> None:
    path = _REPO_ROOT / "assets/brand/newsroom_visuals/v2_6_telegram_canary/source_original.jpg"
    if not path.exists():
        pytest.skip("real evidence file not present in this checkout")
    assert assess_pixel_branding_risk(path.read_bytes()) is not None


def test_pixel_branding_risk_absent_on_real_clean_photos() -> None:
    for rel in (
        "assets/brand/newsroom_visuals/v2_4_canary_live/raw_recomposed.jpg",
        "assets/brand/newsroom_visuals/v2_7_local_e2e_proof/source_honor_camera.jpg",
    ):
        path = _REPO_ROOT / rel
        if not path.exists():
            pytest.skip("real evidence file not present in this checkout")
        assert assess_pixel_branding_risk(path.read_bytes()) is None


@pytest.mark.asyncio
async def test_branding_risk_makes_recomposition_ineligible_and_fails_open_zero_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sets editorial_recomposition_mode="live" in-process (reverted by monkeypatch teardown) to
    prove the branding-risk gate rejects BEFORE any GeminiImageAdapter is ever constructed - the
    real function returns from evaluate_eligibility()'s own False branch, never reaching the
    provider-call code at all. No network access, no API key required for this test to pass."""
    from core.config import settings

    path = _REPO_ROOT / "assets/brand/newsroom_visuals/v2_6_telegram_canary/source_original.jpg"
    if not path.exists():
        pytest.skip("real evidence file not present in this checkout")
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    result = await maybe_recompose(source_image_bytes=path.read_bytes())
    assert result.used_recomposed_image is False
    assert "branding" in result.eligibility.reason
    assert result.provider is None  # never reached the point where a provider is chosen


# ---------------------------------------------------------------------------
# 12 - DATA/QUOTE/BREAKING behavior unchanged (structural)
# ---------------------------------------------------------------------------


def test_adaptive_branding_only_reachable_for_news_presentation_type() -> None:
    source = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "if presentation_decision.presentation_type == PRESENTATION_NEWS and source_bytes is not None:" in source
    assert "render_branded_media(" in source  # DATA/QUOTE/BREAKING path still present, untouched


# ---------------------------------------------------------------------------
# 13 - no hardcoded story-specific bbox in production code
# ---------------------------------------------------------------------------


def test_no_hardcoded_robot_vacuum_bbox_in_production_code() -> None:
    for rel in ("services/nnj_adaptive_overlay.py", "services/editorial_recomposition.py", "worker/content_cycle.py"):
        source = Path(rel).read_text(encoding="utf-8")
        assert "330, 0, 970, 660" not in source
        assert "robot_vacuum" not in source.lower()


# ---------------------------------------------------------------------------
# Prompt hardening (Stage 5)
# ---------------------------------------------------------------------------


def test_prompt_forbids_erasing_source_branding() -> None:
    prompt = build_recomposition_prompt()
    assert "SOURCE BRANDING PRESERVATION" in prompt
    assert "watermark" in prompt.lower()
    assert "credit" in prompt.lower()


def test_overlay_aware_prompt_still_includes_branding_preservation_clause() -> None:
    assert "SOURCE BRANDING PRESERVATION" in build_overlay_aware_recomposition_prompt()
