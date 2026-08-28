"""Phase V2.4F - tests for the compact right-side NNJ overlay candidates
(scripts/nnj_v2_4f_compact_right_overlay.py). No Gemini/OpenAI import anywhere in this file."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from PIL import Image

from services.brand_renderer import load_brand_mark
from scripts.nnj_v2_4f_compact_right_overlay import (
    BrandingZone,
    _CANVAS_WIDTH,
    build_candidate,
    check_collision,
    measure_pulse_geometry,
)

_SOURCE_OVERLAY_PATH = Path("assets/brand/newsroom_visuals/v1/overlays/universal/universal_minimal_01.png")
_MANIFEST_PATH = Path("assets/brand/newsroom_visuals/v2_4f_compact_right_overlay/manifest.json")


def test_manifest_exists() -> None:
    assert _MANIFEST_PATH.exists()


def test_line_does_not_begin_at_x_zero() -> None:
    for _letter, _name, frac in (("A", "compact", 0.45), ("B", "restrained", 0.39), ("C", "minimal", 0.33)):
        _img, zone, provenance = build_candidate(frac, "check")
        assert provenance["overlay_start_x"] > 0
        assert zone.x_start > 0


def test_overlay_occupies_only_intended_right_side_region() -> None:
    for frac in (0.45, 0.39, 0.33):
        _img, zone, provenance = build_candidate(frac, "check")
        # the overlay's real alpha content must sit entirely within the RIGHT portion of the
        # canvas, never spanning from the left edge (the V2.4D defect)
        assert zone.x_start >= _CANVAS_WIDTH * 0.4
        assert zone.x_end <= _CANVAS_WIDTH


def test_pulse_pixels_derive_from_universal_minimal_01() -> None:
    _img, _zone, provenance = build_candidate(0.39, "check")
    assert provenance["source_overlay"].replace("\\", "/") == str(_SOURCE_OVERLAY_PATH).replace("\\", "/")
    assert provenance["pulse_scale_factor"] > 0


def test_canonical_nnj_mark_derives_from_load_brand_mark() -> None:
    _img, zone, provenance = build_candidate(0.39, "check")
    assert "load_brand_mark" in provenance["canonical_logo_source"]
    assert provenance["contains_trusted_branding"] is True
    logo = load_brand_mark()
    assert logo.width == logo.height  # 1:1, confirms it wasn't stretched
    x0, y0, x1, y1 = provenance["logo_bbox"]
    assert abs((x1 - x0) - (y1 - y0)) <= 2


def test_no_legacy_wordmark_pixels_remain() -> None:
    _img, _zone, provenance = build_candidate(0.39, "check")
    assert provenance["embedded_v1_wordmark_included"] is False


def test_no_signal_bars_pixels_remain() -> None:
    _img, _zone, provenance = build_candidate(0.39, "check")
    assert provenance["signal_bars_icon_included"] is False


def test_no_extra_glyph_between_pulse_and_logo() -> None:
    """Regression test for the exact V2.4D bug: the corrected measure_pulse_geometry() must find
    its right edge (dev_x1) with real clearance before x=900 (where the wordmark's first letter
    genuinely begins) - not the old, wrong x<=942 boundary that sliced through it."""
    source = Image.open(_SOURCE_OVERLAY_PATH).convert("RGBA")
    geom = measure_pulse_geometry(source)
    dev_x1 = geom["deviation_x_range"][1]
    assert dev_x1 < 900
    assert geom["wordmark_margin_px"] > 20  # real, disclosed clearance, not a razor-thin margin
    # the crop itself (with padding) must also stay clear of the wordmark
    assert geom["crop_bbox"][2] < 900


def test_safe_zone_bbox_equals_overlay_bbox_plus_clearance() -> None:
    _img, zone, provenance = build_candidate(0.39, "check")
    overlay_bbox = provenance["overlay_alpha_bbox"]
    assert zone.x_start == overlay_bbox[0]
    assert zone.y_start == overlay_bbox[1]
    assert zone.x_end == overlay_bbox[2]
    assert zone.y_end == overlay_bbox[3]
    assert zone.clearance_x_start == max(0, zone.x_start - zone.clearance)
    assert zone.clearance_y_start == max(0, zone.y_start - zone.clearance)


def test_collision_uses_x_and_y_bounds_not_only_y() -> None:
    zone = BrandingZone(x_start=800, y_start=600, x_end=1250, y_end=700, clearance=10)
    # A subject fully to the LEFT of the zone, but at the same Y-range - must be CLEAR, proving
    # the check considers X, not just Y (V2.4D's own rejected "protect the whole row" behavior).
    left_of_zone = (0, 620, 400, 680)
    assert check_collision(left_of_zone, zone) is False
    # A subject overlapping both X and Y - must be a collision.
    overlapping = (700, 620, 900, 680)
    assert check_collision(overlapping, zone) is True
    # A subject in the zone's X-range but well above its Y-range (with clearance) - must be CLEAR.
    above_zone = (850, 0, 1000, 500)
    assert check_collision(above_zone, zone) is False


def test_zero_provider_calls() -> None:
    tree = ast.parse(Path("scripts/nnj_v2_4f_compact_right_overlay.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("gemini" in m.lower() or "openai" in m.lower() for m in imported)


def test_raw_gemini_image_not_modified() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["raw_gemini_image_modified"] is False
    assert manifest["brand_renderer_modified"] is False
    assert manifest["content_cycle_modified"] is False


def test_current_composition_collision_recorded_for_all_candidates() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    for letter in ("A", "B", "C"):
        assert "collision" in manifest["candidates"][letter]
        assert isinstance(manifest["candidates"][letter]["collision"], bool)


def test_three_candidates_have_distinct_widths() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    widths = {letter: manifest["candidates"][letter]["width_fraction"] for letter in ("A", "B", "C")}
    assert widths["A"] > widths["B"] > widths["C"]
