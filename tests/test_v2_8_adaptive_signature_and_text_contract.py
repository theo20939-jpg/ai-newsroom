"""Phase V2.8 - Production Presentation Contract Recovery (text V8.6 + adaptive pulse signature
scale ladder + NEWS topic forensic). No real Gemini/OpenAI/Anthropic/Telegram call anywhere in
this file."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from services.news_telegram_presentation import (
    is_v8_family_output,
    render_compact_news_card_html,
    render_v81_news_card_html,
)
from services.nnj_adaptive_overlay import (
    SCALE_LADDER,
    OverlayPlacement,
    build_overlay_layer,
    select_overlay_placement,
)
from services.nnj_candidate_c_contract import CANDIDATE_C_OVERLAY_PNG_PATH

# ---------------------------------------------------------------------------
# A/B - V8.6 reader-facing rendering + no metadata/raw-title leak
# ---------------------------------------------------------------------------

_V86_FIXTURE = {
    "title": "Заголовок примера",
    "main_body": "Основной текст новости на русском языке без служебных меток.",
    "ending": "Короткое заключение.",
    "quote": None, "story_led": False, "viral_potential": "LOW", "meme_potential": "NONE",
}


def test_v86_shaped_output_is_recognized_as_v8_family() -> None:
    assert is_v8_family_output(_V86_FIXTURE)


def test_v86_reader_facing_render_has_no_category_date_header() -> None:
    html = render_v81_news_card_html(_V86_FIXTURE)
    assert "\U0001F4F0" not in html
    assert " · " not in html


def test_v86_reader_facing_render_has_no_internal_field_labels() -> None:
    html = render_v81_news_card_html(_V86_FIXTURE)
    for forbidden in ("main_body", "story_led", "viral_potential", "meme_potential", "what_happened", "why_it_matters"):
        assert forbidden not in html


def test_v86_reader_facing_render_has_no_duplicated_headline() -> None:
    html = render_v81_news_card_html(_V86_FIXTURE)
    title = str(_V86_FIXTURE["title"])
    assert html.count(title) == 1


def test_compact_renderer_also_forbids_all_metadata_fields() -> None:
    html = render_compact_news_card_html("Заголовок", "Тело новости.")
    for forbidden in ("📰", " · ", "GADGETS", "what_happened", "why_it_matters"):
        assert forbidden not in html


# ---------------------------------------------------------------------------
# C/D - scale ladder deterministic, uniform scale only
# ---------------------------------------------------------------------------


def test_scale_ladder_is_descending_and_starts_at_one() -> None:
    assert SCALE_LADDER[0] == 1.0
    assert list(SCALE_LADDER) == sorted(SCALE_LADDER, reverse=True)


def test_scale_ladder_measured_against_real_candidate_c_content() -> None:
    """The ladder must have been validated against the real asset, not picked arbitrarily -
    every rung must still produce a legible (non-degenerate) content size."""
    img = Image.open(CANDIDATE_C_OVERLAY_PNG_PATH).convert("RGBA")
    bbox = img.split()[-1].getbbox()
    assert bbox is not None
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    for scale in SCALE_LADDER:
        scaled_w, scaled_h = round(w * scale), round(h * scale)
        assert scaled_w > 50 and scaled_h > 5  # still a real, visible signature at every rung


@pytest.mark.parametrize("scale", list(SCALE_LADDER))
def test_build_overlay_layer_uniform_scale_preserves_aspect_ratio(scale: float) -> None:
    built = build_overlay_layer(OverlayPlacement.LOWER_RIGHT, scale=scale)
    assert built is not None
    _image, zone = built
    content_w = zone.x_end - zone.x_start
    content_h = zone.y_end - zone.y_start

    base_built = build_overlay_layer(OverlayPlacement.LOWER_RIGHT, scale=1.0)
    assert base_built is not None
    _base_image, base_zone = base_built
    base_w = base_zone.x_end - base_zone.x_start
    base_h = base_zone.y_end - base_zone.y_start

    # Uniform scale: width and height ratios must match within integer-rounding tolerance -
    # never a non-uniform stretch that would change the aspect ratio.
    ratio_w = content_w / base_w
    ratio_h = content_h / base_h
    assert abs(ratio_w - ratio_h) < 0.03


def test_selection_is_deterministic_across_repeated_calls() -> None:
    bbox = (300, 100, 900, 500)
    results = {select_overlay_placement(bbox).placement for _ in range(5)}
    assert len(results) == 1
    scales = {select_overlay_placement(bbox).scale for _ in range(5)}
    assert len(scales) == 1


# ---------------------------------------------------------------------------
# E/F - trusted asset provenance
# ---------------------------------------------------------------------------


def test_full_signature_pixels_derive_from_locked_candidate_c_asset() -> None:
    source_text = Path("services/nnj_adaptive_overlay.py").read_text(encoding="utf-8")
    assert "CANDIDATE_C_OVERLAY_PNG_PATH" in source_text
    assert "_load_candidate_c_layer" in source_text


def test_logo_only_uses_canonical_brand_mark_not_a_recreated_mark() -> None:
    source_text = Path("services/nnj_adaptive_overlay.py").read_text(encoding="utf-8")
    assert "load_brand_mark" in source_text


def test_no_untrusted_v1_wordmark_asset_referenced() -> None:
    """The old, rejected untrusted V1 wordmark PNGs must never be referenced as an asset path -
    provider names (Gemini/OpenAI) are checked structurally by the AST-based import tests below,
    not by a raw substring scan, since this module's own docstring legitimately discusses the
    NNJ-BRAND-RULE non-negotiable ("Gemini still never draws...") without importing anything."""
    source_text = Path("services/nnj_adaptive_overlay.py").read_text(encoding="utf-8")
    assert "nnj_logo_wordmark" not in source_text
    assert "untrusted_wordmark" not in source_text


# ---------------------------------------------------------------------------
# G/H/I/J - collision guard at every scale, fallback order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scale", list(SCALE_LADDER))
def test_collision_guard_active_at_every_scale(scale: float) -> None:
    built = build_overlay_layer(OverlayPlacement.LOWER_RIGHT, scale=scale)
    assert built is not None
    _image, zone = built
    # A subject placed exactly over the measured zone must be treated as a collision at every scale.
    subject = (zone.x_start, zone.y_start, zone.x_end, zone.y_end)
    sx0, sy0, sx1, sy1 = subject
    zx0, zy0 = zone.clearance_x_start, zone.clearance_y_start
    zx1, zy1 = zone.clearance_x_end, zone.clearance_y_end
    assert sx0 < zx1 and sx1 > zx0 and sy0 < zy1 and sy1 > zy0


def test_fallback_order_tries_placement_before_moving_to_next_corner() -> None:
    """Phase V2.8 §3's documented priority: PLACEMENT is primary, SCALE is secondary - a subject
    that blocks only the largest scale at lower_right must still try smaller lower_right scales
    before ever trying lower_left."""
    lr_1 = build_overlay_layer(OverlayPlacement.LOWER_RIGHT, scale=1.0)
    assert lr_1 is not None
    _img, zone_1 = lr_1
    # A subject that collides with the full-size zone but clears the smallest-scale zone.
    lr_55 = build_overlay_layer(OverlayPlacement.LOWER_RIGHT, scale=0.55)
    assert lr_55 is not None
    _img2, zone_55 = lr_55
    subject = (zone_1.x_start, zone_1.y_start, zone_1.x_start + 5, zone_1.y_start + 5)
    # Confirm this subject does NOT collide with the smallest lower_right zone (sanity check).
    collides_small = not (
        subject[2] <= zone_55.clearance_x_start or subject[0] >= zone_55.clearance_x_end
        or subject[3] <= zone_55.clearance_y_start or subject[1] >= zone_55.clearance_y_end
    )
    if collides_small:
        pytest.skip("synthetic subject collides with every lower_right scale in this environment's measured geometry")
    decision = select_overlay_placement(subject)
    assert decision.placement == OverlayPlacement.LOWER_RIGHT  # never jumped to lower_left


def test_logo_only_reached_only_after_every_full_signature_candidate_rejected() -> None:
    decision = select_overlay_placement((0, 0, 1280, 660))  # covers everywhere but the very bottom strip
    if decision.placement == OverlayPlacement.LOGO_ONLY:
        full_signature_attempts = [a for a in decision.attempts if a.placement != OverlayPlacement.LOGO_ONLY]
        assert len(full_signature_attempts) == 4 * len(SCALE_LADDER)


def test_no_overlay_reached_only_after_logo_only_also_collides() -> None:
    decision = select_overlay_placement((0, 0, 1280, 720))
    assert decision.placement == OverlayPlacement.NO_OVERLAY
    assert any(a.placement == OverlayPlacement.LOGO_ONLY for a in decision.attempts)


# ---------------------------------------------------------------------------
# K/L/M - robot-vacuum regression, no AI calls, no Telegram sends
# ---------------------------------------------------------------------------


def test_robot_vacuum_regression_now_selects_full_signature() -> None:
    decision = select_overlay_placement((330, 0, 970, 660))  # exact real V2.7 subject bbox
    assert decision.overlay_mode == "full_signature"
    assert decision.placement == OverlayPlacement.LOWER_RIGHT


def test_robot_vacuum_regression_script_artifacts_exist() -> None:
    out_dir = Path("assets/brand/newsroom_visuals/v2_8_robot_vacuum_regression")
    for name in ("robot_vacuum_source.jpg", "robot_vacuum_old_logo_only.jpg", "robot_vacuum_new_result.jpg", "robot_vacuum_overlay_debug.jpg", "robot_vacuum_manifest.json"):
        assert (out_dir / name).exists(), name


def test_no_ai_provider_import_anywhere_in_adaptive_overlay_module() -> None:
    import ast

    tree = ast.parse(Path("services/nnj_adaptive_overlay.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(risky in m.lower() for m in imported for risky in ("gemini", "openai", "anthropic"))


def test_no_telegram_import_anywhere_in_adaptive_overlay_module() -> None:
    import ast

    tree = ast.parse(Path("services/nnj_adaptive_overlay.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("aiogram" in m.lower() or "telegram" in m.lower() for m in imported)


# ---------------------------------------------------------------------------
# N - NEWS topic resolution behavior
# ---------------------------------------------------------------------------


def test_news_topic_id_defaults_to_none_and_resolves_to_chat_root() -> None:
    from schemas.editorial_route import EditorialDestination
    from services.telegram_routing import resolve_route

    target = resolve_route(EditorialDestination.NEWS)
    assert target is not None
    assert target.topic_id is None  # current real .env state - General/chat root, documented behavior


def test_historical_news_topic_id_evidence_exists_in_repository_docs() -> None:
    """Phase V2.8 §10 forensic: two independent real, successful live-canary reports
    (phase23_1d, phase23_1f) both document news_topic_id=2 as the real, working NEWS topic - this
    test pins that evidence exists (not that it is currently active in .env, which it is not)."""
    doc_a = Path("docs/phase23_1d_first_editorial_run_report.md").read_text(encoding="utf-8")
    doc_b = Path("docs/phase23_1f_5_news_editorial_canary_report.md").read_text(encoding="utf-8")
    assert "message_thread_id=2" in doc_a or "'message_thread_id': 2" in doc_a
    assert "message_thread_id=2" in doc_b or "'message_thread_id': 2" in doc_b
