"""Phase B.5R.2: hero-object and internet-culture-collage fidelity closure. Primitive-level tests run on git-tracked assets (and
pure arithmetic); plan-level tests need the local copy of the stored Newsroom media and skip cleanly when it is absent."""
from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest
from PIL import Image

from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion
from scripts import _instagram_phase_b5r1_assets as assets
from scripts import _instagram_phase_b5r1_render as render
from scripts import _instagram_phase_b5r2_families as fam
from services import instagram_design_tokens as tok
from services.instagram_declarative_layout import PALETTES, _fit_object, _object_bbox, _torn_mask, render_declared_slide
from services.instagram_layout_signature import geometry_distance, structure_profile
from services.instagram_layout_validation import validate_layout

_STORE = "hero_moon_on_black" in assets.available_ids() and "imm_lunar_lander" in assets.available_ids()
needs_store = pytest.mark.skipif(not _STORE, reason="local copy of stored Newsroom media not present")
_SPEC = fam.SPEC
_LOGO = Image.open(assets._REPO / "assets" / "brand" / "nnj_logo.png")  # a real, tracked RGBA asset (rounded red square)


def _run(layout: dict, copy: str, images: dict[str, Image.Image]):
    subjects = {k: (v, f"test:{k}") for k, v in images.items()}
    validated = validate_layout(InstagramSlideLayout.model_validate(layout), slide_copy=copy, resolvable_subjects=set(subjects))
    if not validated.accepted or validated.layout is None:
        return validated, None
    return validated, render_declared_slide(spec=_SPEC, layout=validated.layout, slide_copy=copy, index=0, total=1, subject_assets=subjects,
                                            progress_hidden=validated.progress_hidden)


def _stage(region, *, background="ink", mode="object_contain", extra=None, text=(0.06, 0.05, 0.45, 0.12)):
    regions = [fam._m(*region, "obj", crop_mode=mode, focus_x=0.5, focus_y=0.5), fam._t(*text, ref="copy", token="HEADLINE_M")]
    return fam._layout(regions + (extra or []), background=background, arrangement="stage")


# ------------------------------------------------------------------------------------------ hero primitives


def test_object_extent_not_the_photo_frame_drives_staging() -> None:
    alpha_bbox = _LOGO.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    assert _object_bbox(_LOGO) == alpha_bbox
    ground = Image.new("RGB", (1000, 800), (247, 247, 247))
    ground.paste((30, 30, 34), (300, 100, 500, 700))  # a uniform ground with a 200x600 object
    assert _object_bbox(ground) == (300, 100, 500, 700)
    scene = Image.effect_noise((200, 200), 60).convert("RGB")  # no uniform ground: the whole frame is the "object"
    assert _object_bbox(scene) == (0, 0, 200, 200)
    layer, box = _fit_object(ground, 500, 500, 0.5, 0.5, contain=True)
    assert (box[3] - box[1]) == pytest.approx(500, abs=2)  # the OBJECT (600 tall) fills the region height, not the photo (800)


def test_object_can_dominate_and_outweigh_supporting_type() -> None:
    layout = _stage((0.25, 0.35, 0.70, 0.60))
    _v, result = _run(layout, "Заголовок", {"obj": _LOGO})
    assert result is not None
    n = result.notes
    assert n["object_bbox_canvas_coverage"] >= 0.25 and n["object_bbox_canvas_coverage"] >= 3 * n["text_canvas_coverage"]
    assert n["object_bounding_boxes"] and all(0 <= v <= 1 for box in n["object_bounding_boxes"] for v in box)


def test_bounded_edge_bleed_works_and_is_rejected_beyond_its_bound() -> None:
    ok = _stage((0.30, 0.30, 0.95, 0.80))  # bleeds right (+0.25) and bottom (+0.10): allowed on a stage
    validated, result = _run(ok, "Заголовок", {"obj": _LOGO})
    assert result is not None
    assert result.notes["object_bounding_boxes"][0][2] == pytest.approx(1.0, abs=0.01)  # the object is cropped by the canvas edge
    too_far = _stage((0.30, 0.30, 1.45, 0.80))
    validated, result = _run(too_far, "Заголовок", {"obj": _LOGO})
    assert result is None and "out_of_bounds" in validated.rejection_codes
    standard = {**ok, "arrangement": "standard"}
    validated, result = _run(standard, "Заголовок", {"obj": _LOGO})
    assert result is None and "out_of_bounds" in validated.rejection_codes  # bleed exists only on a declared stage/collage


def test_dark_and_light_ground_staging_both_work_without_overlay() -> None:
    dark = _run(_stage((0.25, 0.25, 0.60, 0.60), background="ink"), "Заголовок", {"obj": _LOGO})[1]
    light = _run(_stage((0.25, 0.25, 0.60, 0.60), background="paper"), "Заголовок", {"obj": _LOGO})[1]
    assert dark is not None and light is not None
    assert dark.image.getpixel((1050, 700)) == tok.INK and light.image.getpixel((1050, 700)) == tok.PAPER  # ground untouched by the object
    assert dark.notes["source_media_pixels_unaltered"] is True and light.notes["source_media_pixels_unaltered"] is True


def test_the_same_asset_stages_into_materially_different_valid_geometries() -> None:
    layouts = [_stage((0.30, 0.30, 0.95, 0.80)), _stage((-0.30, 0.10, 0.90, 0.70), text=(0.62, 0.05, 0.32, 0.10)), _stage((0.10, -0.10, 0.60, 1.20), text=(0.74, 0.05, 0.22, 0.10))]
    renders = [_run(lay, "Заголовок", {"obj": _LOGO})[1] for lay in layouts]
    assert all(r is not None for r in renders)
    assert len({r.image.tobytes() for r in renders}) == 3
    for a, b in itertools.combinations(layouts, 2):
        assert geometry_distance(a, b) >= 0.3


def test_unsafe_text_object_collision_is_rejected_not_hidden() -> None:
    layout = fam._layout([fam._m(0.10, 0.10, 0.80, 0.60, "obj", crop_mode="object_contain"), fam._t(0.20, 0.30, 0.50, 0.15, ref="copy", token="HEADLINE_L")],
                         background="ink", arrangement="stage")
    validated, result = _run(layout, "Заголовок", {"obj": _LOGO})
    assert result is None and "text_over_media" in validated.rejection_codes


@needs_store
def test_hero_reconstructions_have_dominant_objects_dark_and_light_grounds_and_distinct_arrangements() -> None:
    plans = fam.hero_plans()
    assert len(plans) >= 4
    dark = light = 0
    for plan in plans:
        validated, result, code = render.render_plan(plan)
        assert result is not None, (plan["name"], code)
        n = result.notes
        assert not result.text_clipped and n["source_media_pixels_unaltered"] in (True, None)
        assert n["object_bbox_canvas_coverage"] >= 0.30, plan["name"]
        headline = max(n["text_metrics"], key=lambda m: m["font_px"])
        assert n["object_bbox_canvas_coverage"] >= 1.5 * headline["block_h_frac"] * headline["block_w_frac"], plan["name"]
        dark += plan["layout"]["background"] == "ink"
        light += plan["layout"]["background"] != "ink"
        assert plan["layout"]["arrangement"] == "stage"
    assert dark >= 2 and light >= 2
    for a, b in itertools.combinations(plans, 2):
        assert geometry_distance(a["layout"], b["layout"]) >= 0.5, (a["label"], b["label"])


# ------------------------------------------------------------------------------------------ collage primitives


def test_torn_edge_is_deterministic_jagged_and_bounded() -> None:
    a, b = _torn_mask(400, 300, 12), _torn_mask(400, 300, 12)
    assert a.tobytes() == b.tobytes()
    full = Image.new("L", (400, 300), 255)
    assert a.tobytes() != full.tobytes()  # the edge is not a straight rectangle
    assert a.getpixel((200, 150)) == 255 and a.getbbox() is not None
    assert a.getbbox()[0] <= 14 and a.getbbox()[1] <= 14  # displaced by at most the amplitude


def test_die_cut_outline_is_drawn_around_a_real_alpha_cutout_only() -> None:
    plain = fam._layout([fam._m(0.10, 0.10, 0.50, 0.40, "obj", crop_mode="cutout_contain", z=1), fam._t(0.06, 0.62, 0.7, 0.15, ref="copy", token="HEADLINE_M", z=2)],
                        background="ink", arrangement="collage")
    cut = fam._layout([fam._m(0.10, 0.10, 0.50, 0.40, "obj", crop_mode="cutout_contain", frame="die_cut", z=1), fam._t(0.06, 0.62, 0.7, 0.15, ref="copy", token="HEADLINE_M", z=2)],
                      background="ink", arrangement="collage")
    a = _run(plain, "Заголовок", {"obj": _LOGO})[1]
    b = _run(cut, "Заголовок", {"obj": _LOGO})[1]
    assert a is not None and b is not None
    from services.instagram_kage_brand import LIGHT as paper  # the KAGE mat colour

    light_px = lambda im: sum(1 for px in im.crop((80, 100, 700, 700)).getdata() if px == paper)  # noqa: E731
    assert light_px(a.image) == 0 and light_px(b.image) > 500  # the white sticker outline exists only with die_cut


def test_highlight_and_burst_devices_use_bounded_family_accents() -> None:
    layout = fam._layout([
        fam._r("graphic", 0.10, 0.10, 0.50, 0.10, graphic_type="highlight", tone="accent", z=1),
        fam._r("graphic", 0.65, 0.10, 0.25, 0.18, graphic_type="burst", tone="accent2", tilt_deg=8.0, z=1),
        fam._t(0.06, 0.40, 0.7, 0.2, ref="copy", token="HEADLINE_L", tone="accent", z=2),
    ], background="ink", palette="culture", arrangement="collage")
    result = _run(layout, "Заголовок", {})[1]
    assert result is not None
    accent, accent2 = PALETTES["culture"]
    assert result.image.getpixel((round(0.35 * _SPEC.width), round(0.15 * _SPEC.height))) == accent
    assert result.image.getpixel((round(0.775 * _SPEC.width), round(0.19 * _SPEC.height))) == accent2
    assert accent in {px for px in result.image.crop((60, 540, 900, 800)).getdata()}  # coloured type
    with pytest.raises(ValueError):
        LayoutRegion.model_validate({**fam._r("graphic", 0.1, 0.1, 0.2, 0.2, graphic_type="burst"), "tilt_deg": 13.0})
    with pytest.raises(ValueError):
        LayoutRegion.model_validate({**fam._r("graphic", 0.1, 0.1, 0.2, 0.2, graphic_type="burst"), "tone": "#ff00ff"})


def test_collage_with_torn_fragments_is_deterministic_and_z_order_decides_the_stack() -> None:
    def build(order):
        z1, z2, z3 = order
        return fam._layout([
            fam._m(0.04, 0.05, 0.70, 0.40, "a", frame="torn", tilt_deg=-4.0, z=z1),
            fam._m(0.40, 0.25, 0.42, 0.30, "b", frame="torn", tilt_deg=5.0, z=z2),
            fam._m(0.10, 0.40, 0.24, 0.17, "c", frame="paper", tilt_deg=3.0, z=z3),
            fam._t(0.06, 0.72, 0.7, 0.16, ref="copy", token="HEADLINE_XL", z=6),
        ], background="ink", palette="culture", arrangement="collage")
    images = {"a": assets.resolve("repo_yellow_kiosk"), "b": assets.resolve("repo_ev_infographic"), "c": assets.resolve("repo_keyboard_app")}
    one = _run(build((1, 2, 3)), "Хуже не бывает", images)[1]
    again = _run(build((1, 2, 3)), "Хуже не бывает", images)[1]
    swapped = _run(build((2, 1, 3)), "Хуже не бывает", images)[1]
    assert one is not None and again is not None and swapped is not None
    assert one.image.tobytes() == again.image.tobytes() and one.image.tobytes() != swapped.image.tobytes()
    assert one.notes["rotation_count"] >= 3


@needs_store
def test_collage_reconstructions_are_layered_hierarchical_and_not_a_grid() -> None:
    plans = fam.collage_plans()
    assert len(plans) >= 4
    dark = sum(p["layout"]["background"] == "ink" for p in plans)
    assert dark >= 2 and len(plans) - dark >= 1
    for plan in plans:
        validated, result, code = render.render_plan(plan)
        assert result is not None, (plan["name"], code)
        areas = sorted((r["w"] * r["h"] for r in plan["layout"]["regions"] if r["kind"] == "media"), reverse=True)
        assert len(areas) >= 3 and areas[0] >= 1.5 * areas[1] and areas[0] >= 2.5 * areas[-1]
        n = result.notes
        assert n["rotation_count"] >= 2 and n["layer_count"] >= 7 and not result.text_clipped
        assert n["negative_space"] <= 0.40, plan["name"]  # collages are carried by fragments, not by empty canvas
        media = [r for r in plan["layout"]["regions"] if r["kind"] == "media"]
        assert any(r["frame"] in ("torn", "die_cut") for r in media) and any(r["graphic_type"] in ("burst", "highlight") for r in plan["layout"]["regions"] if r["kind"] == "graphic")
        assert len({r["z"] for r in media}) == len(media)
    for a, b in itertools.combinations(plans, 2):
        assert geometry_distance(a["layout"], b["layout"]) >= 0.5, (a["label"], b["label"])
        assert a["layout"]["background"] != b["layout"]["background"] or a["layout"]["palette"] != b["layout"]["palette"] or structure_profile(a["layout"]) != structure_profile(b["layout"])


@needs_store
def test_hero_and_collage_differ_structurally_and_the_same_plan_and_assets_render_identically() -> None:
    for h, c in itertools.product(fam.hero_plans(), fam.collage_plans()):
        assert geometry_distance(h["layout"], c["layout"]) >= 0.5
        p1, p2 = structure_profile(h["layout"]), structure_profile(c["layout"])
        assert sum(p1[k] != p2[k] for k in p1) >= 2
    plan = fam.collage_plans()[0]
    a, b = render.render_plan(plan)[1], render.render_plan(plan)[1]
    assert a is not None and b is not None and a.image.tobytes() == b.image.tobytes()


# ------------------------------------------------------------------------------------------ shared guarantees


def test_no_overlay_primitives_in_the_renderer_stack_and_canonical_logo_only() -> None:
    forbidden = {"apply_bottom_readability_gradient", "apply_top_readability_gradient", "build_dimmed_source_field", "GaussianBlur", "ImageFilter"}
    for module in ("services/instagram_declarative_layout.py", "services/instagram_layout_validation.py", "services/instagram_quiet_zones.py"):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden:
                seen.add(node.id)
            if isinstance(node, ast.ImportFrom):
                seen |= {a.name for a in node.names if a.name in forbidden}
            if isinstance(node, ast.Attribute) and node.attr in ("alpha_composite", "filter"):
                seen.add(node.attr)
        assert not seen, (module, seen)
    layout = fam._layout([fam._t(0.07, 0.10, 0.80, 0.30, ref="copy", token="DISPLAY")], background="ink", logo="BOTTOM_LEFT")
    result = _run(layout, "Заголовок", {})[1]
    assert result is not None and result.visible_brand_mark_count == 1 and result.notes["logo_position"] == "BOTTOM_LEFT"


def test_cyrillic_extreme_type_stays_unclipped() -> None:
    layout = fam._layout([fam._t(0.06, 0.10, 0.50, 0.14, ref="copy_lead", token="MEGA", max_lines=1), fam._t(0.06, 0.28, 0.40, 0.05, ref="copy_rest", token="CAPTION", max_lines=2)], background="ink")
    result = _run(layout, "Ну и ну. Короткое пояснение", {})[1]
    assert result is not None and not result.text_clipped
    sizes = {m["ref"]: m["font_px"] for m in result.notes["text_metrics"]}
    assert sizes["copy_lead"] / sizes["copy_rest"] >= 4


@needs_store
def test_immersive_family_is_preserved_byte_for_byte_when_the_b5r1_render_is_present() -> None:
    reference_dir = assets._REPO / "artifacts" / "instagram_phase_b5r1" / "renderer_examples"
    if not reference_dir.exists():
        pytest.skip("accepted B.5R.1 immersive renders not present locally")
    for plan in fam.immersive_plans():
        result = render.render_plan(plan)[1]
        ref = reference_dir / f"immersive_image_field_{plan['label']}.png"
        assert result is not None and ref.exists()
        assert Image.open(ref).convert("RGB").tobytes() == result.image.convert("RGB").tobytes(), plan["label"]
