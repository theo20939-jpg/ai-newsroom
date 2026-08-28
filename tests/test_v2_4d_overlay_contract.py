"""Phase V2.4D - tests for the AUTHORITATIVE canonical 16:9 overlay contract
(services/nnj_overlay_contract.py + scripts/nnj_v2_4d_canonical_16x9_overlay.py). No Gemini/OpenAI
import anywhere in this file."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from PIL import Image

from services.brand_renderer import load_brand_mark
from services.editorial_recomposition import build_recomposition_prompt
from services.nnj_overlay_contract import (
    CANONICAL_OVERLAY_WHITE_16X9_MANIFEST_PATH,
    CANONICAL_OVERLAY_WHITE_16X9_PATH,
    build_overlay_aware_prompt_clause,
    check_collision,
    load_safe_zone_geometry,
)

_MANIFEST = json.loads(CANONICAL_OVERLAY_WHITE_16X9_MANIFEST_PATH.read_text(encoding="utf-8"))
_PHASE_MANIFEST_PATH = CANONICAL_OVERLAY_WHITE_16X9_MANIFEST_PATH.parent / "manifest.json"
_PHASE_MANIFEST = json.loads(_PHASE_MANIFEST_PATH.read_text(encoding="utf-8"))
_SOURCE_OVERLAY_PATH = Path("assets/brand/newsroom_visuals/v1/overlays/universal/universal_minimal_01.png")


def test_derivative_and_manifest_exist() -> None:
    assert CANONICAL_OVERLAY_WHITE_16X9_PATH.exists()
    assert CANONICAL_OVERLAY_WHITE_16X9_MANIFEST_PATH.exists()


def test_canonical_canvas_is_1280x720() -> None:
    safe_zone = load_safe_zone_geometry()
    assert safe_zone.canvas_width == 1280
    assert safe_zone.canvas_height == 720
    derivative = Image.open(CANONICAL_OVERLAY_WHITE_16X9_PATH)
    assert derivative.size == (1280, 720)


def test_protected_band_is_14_percent() -> None:
    safe_zone = load_safe_zone_geometry()
    assert abs(safe_zone.protected_fraction - 0.14) < 1e-9


def test_protected_y_start_is_619() -> None:
    safe_zone = load_safe_zone_geometry()
    assert abs(safe_zone.protected_y_start - 619) <= 2


def test_line_y_is_666() -> None:
    safe_zone = load_safe_zone_geometry()
    assert abs(safe_zone.line_y - 666) <= 2


def test_pulse_does_not_extend_materially_above_87_5_percent() -> None:
    """The pulse's own top edge (its bbox y0) must sit close to the intended ~87.5% design
    height (y~630) - definitively NOT anywhere near V2.4C's rejected y~379."""
    safe_zone = load_safe_zone_geometry()
    pulse_top_y = safe_zone.pulse_bbox[1]
    assert 615 <= pulse_top_y <= 645  # a few px tolerance around the 630 target (crop padding)
    assert pulse_top_y > 500  # unambiguously nowhere near the rejected V2.4C zone (~379)


def test_pulse_shape_originates_from_universal_minimal_01() -> None:
    assert _MANIFEST["source_overlay"].replace("\\", "/") == str(_SOURCE_OVERLAY_PATH).replace("\\", "/")
    assert "pulse_source_measurement" in _MANIFEST
    measurement = _MANIFEST["pulse_source_measurement"]
    # a real, measured peak/trough pair, not invented (peak strictly above baseline, trough
    # strictly below - the real ECG shape's own defining property)
    assert measurement["peak_y"] < measurement["baseline_y0"]
    assert measurement["trough_y"] > measurement["baseline_y1"]
    assert _MANIFEST["pulse_scale_factor"] > 0


def test_no_untrusted_v1_wordmark_retained() -> None:
    assert _MANIFEST["embedded_v1_wordmark_included"] is False


def test_canonical_nnj_logo_used() -> None:
    assert _MANIFEST["contains_trusted_branding"] is True
    assert "load_brand_mark" in _MANIFEST["canonical_logo_source"]
    safe_zone = load_safe_zone_geometry()
    derivative = Image.open(CANONICAL_OVERLAY_WHITE_16X9_PATH).convert("RGBA")
    x0, y0, x1, y1 = safe_zone.logo_bbox
    logo_region_alpha = derivative.crop((x0, y0, x1, y1)).split()[-1]
    assert logo_region_alpha.getbbox() is not None  # not empty

    logo = load_brand_mark()
    assert logo.width == logo.height  # 1:1, confirms it wasn't stretched when placed
    bbox_w, bbox_h = x1 - x0, y1 - y0
    assert abs(bbox_w - bbox_h) <= 2


def test_signal_bars_icon_absent() -> None:
    assert _MANIFEST["signal_bars_icon_included"] is False
    # No 'icon_bbox' field at all in this phase's schema (unlike V2.4C's rejected derivative).
    assert "icon_bbox" not in _MANIFEST


def test_manifest_is_single_source_of_truth() -> None:
    """Reloading via the public loader must reproduce the exact same values already recorded in
    the raw JSON - proving there is no second, drifted copy of these numbers anywhere."""
    safe_zone = load_safe_zone_geometry()
    assert safe_zone.canvas_width == _MANIFEST["canvas_width"]
    assert safe_zone.protected_y_start == _MANIFEST["protected_y_start"]
    assert safe_zone.line_y == _MANIFEST["line_y"]
    assert tuple(safe_zone.pulse_bbox) == tuple(_MANIFEST["pulse_bbox"])


def test_prompt_clause_derives_protected_region_from_manifest() -> None:
    safe_zone = load_safe_zone_geometry()
    clause = build_overlay_aware_prompt_clause(safe_zone)
    expected_pct = round(safe_zone.protected_fraction * 100)
    assert f"lower {expected_pct}%" in clause
    assert expected_pct == 14


def test_factual_fidelity_rules_remain_intact() -> None:
    # Phase V2.10I: stale-assertion fix, disclosed. The literal phrase "change hardware design"
    # this test originally asserted was superseded by Phase V2.5-V2.7's own prompt-tightening
    # work (already-approved current contract, predating this phase) with the more specific
    # "changing product geometry; changing camera/sensor/button/port geometry" - a stricter,
    # not weaker, version of the same rule. Test-only update; the product prompt itself is
    # unchanged by this phase.
    base_prompt = build_recomposition_prompt()
    assert "FORBIDDEN" in base_prompt
    assert "changing product geometry" in base_prompt
    assert "changing camera/sensor/button/port geometry" in base_prompt
    assert "SOURCE FIDELITY" in base_prompt


def test_hand_or_product_removal_never_instructed() -> None:
    safe_zone = load_safe_zone_geometry()
    clause = build_overlay_aware_prompt_clause(safe_zone)
    assert "not delete real foreground elements" in clause.lower()
    assert "reposition or slightly scale the complete factual subject group" in clause.lower()


def test_collision_marks_current_intersecting_subject_correctly() -> None:
    collision = _PHASE_MANIFEST["collision_validation"]
    assert collision["current_composition_collision"] is True


def test_synthetic_clear_layout_passes() -> None:
    collision = _PHASE_MANIFEST["collision_validation"]
    assert collision["layout_proof_collision"] is False


def test_collision_geometry_primitive_directly() -> None:
    safe_zone = load_safe_zone_geometry()
    intersecting = (100, safe_zone.protected_y_start + 5, 200, safe_zone.protected_y_end - 5)
    assert check_collision(intersecting, safe_zone) is True
    clear = (100, 0, 200, max(0, safe_zone.clearance_y_start - 10))
    assert check_collision(clear, safe_zone) is False


def test_zero_provider_calls_in_derivative_script() -> None:
    tree = ast.parse(Path("scripts/nnj_v2_4d_canonical_16x9_overlay.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("gemini" in m.lower() or "openai" in m.lower() for m in imported)


def test_zero_provider_calls_in_contract_module() -> None:
    tree = ast.parse(Path("services/nnj_overlay_contract.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("gemini" in m.lower() or "openai" in m.lower() for m in imported)


def test_brand_renderer_and_content_cycle_not_modified() -> None:
    assert _PHASE_MANIFEST["brand_renderer_modified"] is False
    assert _PHASE_MANIFEST["content_cycle_modified"] is False
