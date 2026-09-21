"""Phase B.5R.1: high-fidelity family reconstruction with REAL media. Tests that need the local copy of the stored
Newsroom images (git-excluded, see scripts/_instagram_phase_b5r1_assets.py) skip cleanly when it is absent; tests
on git-tracked repository assets always run."""
from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion
from scripts import _instagram_phase_b5r1_assets as assets
from scripts import _instagram_phase_b5r1_families as fam
from scripts import _instagram_phase_b5r1_render as render
from services import instagram_design_tokens as tok
from services.instagram_declarative_layout import DeclaredRenderRejected, _fit_cutout, render_declared_slide
from services.instagram_image_handling import fit_image_cover
from services.instagram_layout_signature import geometry_distance, structure_profile
from services.instagram_layout_validation import LOGO_ZONES, validate_layout
from services.instagram_quiet_zones import measure_zone, select_text_zone

_STORE = "imm_lunar_lander" in assets.available_ids()
needs_store = pytest.mark.skipif(not _STORE, reason="local copy of stored Newsroom media not present")
_SPEC = fam.SPEC
_INK = tok.INK


def _validate_and_render(layout: dict, copy: str, images: dict[str, Image.Image]):
    subjects = {k: (v, f"test:{k}") for k, v in images.items()}
    model = InstagramSlideLayout.model_validate(layout)
    validated = validate_layout(model, slide_copy=copy, resolvable_subjects=set(subjects))
    if not validated.accepted or validated.layout is None:
        return validated, None
    return validated, render_declared_slide(spec=_SPEC, layout=validated.layout, slide_copy=copy, index=0, total=1,
                                            subject_assets=subjects, progress_hidden=validated.progress_hidden)


def _tracked(*ids: str) -> dict[str, Image.Image]:
    out = {}
    for i in ids:
        img = assets.resolve(i)
        assert img is not None, i
        out[i] = img
    return out


# ------------------------------------------------------------------------------------------ registry / real media


def test_registry_is_real_existing_media_only() -> None:
    known = {assets.IMM, assets.HERO, assets.COL}
    assert len(assets.ASSETS) >= 30
    for a in assets.ASSETS:
        assert a.source_type in ("repository", "newsroom_storage")
        assert a.subject and a.why and a.families and set(a.families) <= known and a.key
        assert not any(w in a.asset_id for w in ("placeholder", "synthetic", "fake"))
        if a.source_type == "repository":
            img = assets.resolve(a.asset_id)
            assert img is not None and min(img.size) >= 300, a.asset_id


def test_no_plan_uses_synthetic_or_unregistered_subjects() -> None:
    for plan in fam.hero_plans() + fam.collage_plans():
        assert set(plan["assets"]) <= set(assets.BY_ID)
        media_refs = {r["content_ref"] for r in plan["layout"]["regions"] if r["kind"] == "media"}
        assert media_refs <= set(plan["assets"])
        assert all(r.get("graphic_type") != "ui_frame" for r in plan["layout"]["regions"])  # no drawn stand-in objects


# ------------------------------------------------------------------------------------------ quiet-zone measurement


def test_quiet_zone_measurement_is_deterministic_on_real_media() -> None:
    img = fam.fitted_for_canvas("repo_portrait", 0.5, 0.5)
    a, b = select_text_zone(img), select_text_zone(img)
    assert [r.as_dict() for r in a.reports] == [r.as_dict() for r in b.reports] and a.why == b.why
    assert (a.selected.name if a.selected else None) == (b.selected.name if b.selected else None)


def test_quiet_zone_accepts_calm_dark_and_rejects_busy_pixels() -> None:
    calm = Image.new("RGB", (400, 300), (12, 12, 16))
    assert measure_zone(calm, (0, 0, 400, 300)).quiet and measure_zone(calm, (0, 0, 400, 300)).text_colour == "light"
    busy = Image.new("RGB", (400, 300), (110, 110, 110))
    for x in range(0, 400, 16):
        busy.paste((240, 240, 240), (x, 0, x + 8, 300))
    assert not measure_zone(busy, (0, 0, 400, 300)).quiet
    mid = Image.new("RGB", (400, 300), (120, 120, 120))  # a flat mid-grey supports neither text colour at 4.5:1
    assert not measure_zone(mid, (0, 0, 400, 300)).quiet


def test_unsuitable_image_fails_immersive_eligibility_and_is_not_forced() -> None:
    for fx in (0.1, 0.5, 0.9):
        assert not fam.immersive_eligibility("repo_yellow_kiosk", fx, 0.5).eligible
    assert fam.plan_immersive("repo_yellow_kiosk", focus_x=0.5, focus_y=0.5, copy="Заголовок. Пояснение", lead_token="DISPLAY",
                              rest_token="CAPTION", name="x", label="X") is None


def test_text_on_bright_media_is_refused_and_never_rescued_with_a_layer() -> None:
    plan = next(p for p in fam.hero_plans() if p["label"] == "X")
    validated, result, code = render.render_plan(plan)
    assert result is None and code == "text_on_media_unreadable"
    from services.instagram_carousel_layouts import _try_declared

    outcome = _try_declared(spec=_SPEC, layout_plan=plan["layout"], slide_copy=plan["copy"], index=0, total=1,
                            subject_assets={"repo_orange_phone": (assets.resolve("repo_orange_phone"), "x")}, visual_direction=None)
    assert outcome == (None, ["text_on_media_unreadable"])


# ------------------------------------------------------------------------------------------ immersive


@needs_store
def test_immersive_reconstructions_are_full_frame_with_measured_text_zones() -> None:
    plans = fam.immersive_plans()
    assert len(plans) >= 3
    for plan in plans:
        validated, result, code = render.render_plan(plan)
        assert result is not None, (plan["name"], code)
        media = [r for r in plan["layout"]["regions"] if r["kind"] == "media"]
        assert len(media) == 1 and media[0]["w"] == 1.0 and media[0]["h"] == 1.0
        assert result.notes["media_canvas_coverage"] >= 0.999
        assert result.notes["source_media_pixels_unaltered"] is True
        sel = plan["selection"].selected
        assert sel is not None and sel.quiet and sel.text_colour in ("light", "dark")
        assert result.notes["text_zone_reports"] and all(z["quiet"] for z in result.notes["text_zone_reports"])
        assert not result.text_clipped


@needs_store
def test_immersive_plans_have_materially_different_geometry_and_text_positions() -> None:
    plans = fam.immersive_plans()
    for a, b in itertools.combinations(plans, 2):
        assert geometry_distance(a["layout"], b["layout"]) >= 0.3, (a["label"], b["label"])
    assert len({p["selection"].selected.name for p in plans}) == len(plans)  # a different text zone per reconstruction


def test_immersive_source_pixels_stay_intact_outside_text_accent_and_logo() -> None:
    plan = fam.plan_immersive("repo_portrait", focus_x=0.5, focus_y=0.5, copy="Заголовок. Пояснение", lead_token="HEADLINE_XL",
                              rest_token="CAPTION", name="portrait", label="P")
    assert plan is not None
    validated, result = _validate_and_render(plan["layout"], plan["copy"], {"repo_portrait": assets.resolve("repo_portrait")})
    assert result is not None
    expected = fit_image_cover(assets.resolve("repo_portrait").convert("RGB"), width=_SPEC.width, height=_SPEC.height, focus_x=0.5, focus_y=0.5).image
    lower = (0, int(_SPEC.height * 0.55), int(_SPEC.width * 0.80), _SPEC.height)  # away from the top text, accent and bottom-right logo
    diff = ImageChops.difference(result.image.convert("RGB").crop(lower), expected.convert("RGB").crop(lower))
    assert diff.getbbox() is None, "source pixels must be identical except crop/scale (no darken, tint, blur or gradient)"


# ------------------------------------------------------------------------------------------ dark surface / overlay


def test_dark_surface_renders_without_overlay_or_source_alteration() -> None:
    layout = fam._layout([fam._t(0.07, 0.10, 0.80, 0.30, ref="copy", token="DISPLAY", max_lines=3)], background="ink")
    _validated, result = _validate_and_render(layout, "Два слова в заголовке", {})
    assert result is not None
    gray = result.image.convert("L")
    assert gray.getpixel((1000, 700)) < 20 and gray.getpixel((60, 1250)) < 20


def test_no_overlay_primitives_exist_in_the_renderer_stack() -> None:
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


# ------------------------------------------------------------------------------------------ hero object stage


@needs_store
def test_hero_objects_dominate_the_canvas_and_are_real_isolated_media() -> None:
    for plan in fam.hero_plans():
        if plan["label"] == "X":
            continue
        validated, result, code = render.render_plan(plan)
        assert result is not None, (plan["name"], code)
        n = result.notes
        assert n["object_bbox_canvas_coverage"] >= 0.30, plan["name"]
        assert n["object_bbox_canvas_coverage"] >= 2 * n["text_canvas_coverage"]
        assert n["source_media_pixels_unaltered"] is True
        assert not result.text_clipped


def test_media_ground_needs_a_genuinely_uniform_asset() -> None:
    layout = fam._layout([fam._ground("repo_yellow_kiosk"), fam._t(0.07, 0.1, 0.8, 0.2, ref="copy", token="HEADLINE_L")], background="paper", arrangement="stage")
    with pytest.raises(DeclaredRenderRejected) as info:
        _validate_and_render(layout, "Заголовок", _tracked("repo_yellow_kiosk"))
    assert info.value.code == "media_ground_not_uniform"
    ok = fam._layout([fam._ground("repo_orange_phone"), fam._m(0.1, 0.3, 0.8, 0.7, "repo_orange_phone"), fam._t(0.07, 0.05, 0.8, 0.2, ref="copy", token="HEADLINE_L")],
                     background="paper", arrangement="stage")
    _v, result = _validate_and_render(ok, "Заголовок", _tracked("repo_orange_phone"))
    assert result is not None and result.notes["source_media_pixels_unaltered"] in (True, None)


def test_object_staging_accepts_real_transparent_media_and_keeps_pixels() -> None:
    logo = Image.open(assets._REPO / "assets" / "brand" / "nnj_logo.png")  # a real, tracked RGBA asset
    assert logo.mode == "RGBA" and logo.getchannel("A").getextrema()[0] == 0
    layout = fam._layout([fam._m(0.10, 0.10, 0.50, 0.30, "logo", crop_mode="cutout_contain"), fam._t(0.07, 0.55, 0.8, 0.2, ref="copy", token="HEADLINE_L")],
                         background="ink", arrangement="stage")
    _v, result = _validate_and_render(layout, "Заголовок", {"logo": logo})
    assert result is not None and result.notes["source_media_pixels_unaltered"] is True
    layer = _fit_cutout(logo, round(0.50 * _SPEC.width), round(0.30 * _SPEC.height), 0.5, 0.5, contain=True)
    x0, y0 = round(0.10 * _SPEC.width), round(0.10 * _SPEC.height)
    alpha = layer.getchannel("A")
    solid = next((x, y) for y in range(0, layer.height, 7) for x in range(0, layer.width, 7) if alpha.getpixel((x, y)) == 255)
    clear = next((x, y) for y in range(0, layer.height, 7) for x in range(0, layer.width, 7) if alpha.getpixel((x, y)) == 0)
    assert result.image.getpixel((x0 + solid[0], y0 + solid[1])) == layer.getpixel(solid)[:3]
    assert result.image.getpixel((x0 + clear[0], y0 + clear[1])) == _INK  # transparency shows the ground, no matte box
    assert result.notes["object_canvas_coverage"] < result.notes["media_canvas_coverage"]


@needs_store
def test_real_transparent_newsroom_cutout_is_supported() -> None:
    img = assets.resolve("col_portrait_cutout")
    assert img is not None and img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250


# ------------------------------------------------------------------------------------------ collage


def _tracked_collage(tilt=(-4.0, 3.0, 5.0)) -> tuple[dict, dict[str, Image.Image]]:
    layout = fam._layout([
        fam._m(0.04, 0.05, 0.70, 0.40, "repo_yellow_kiosk", tilt_deg=tilt[0], z=1),
        fam._m(0.50, 0.30, 0.42, 0.30, "repo_ev_infographic", frame="paper", tilt_deg=tilt[1], z=2),
        fam._m(0.10, 0.42, 0.24, 0.17, "repo_keyboard_app", frame="paper", tilt_deg=tilt[2], z=3),
        fam._r("graphic", 0.40, 0.62, 0.16, 0.10, graphic_type="arrow_scribble", tone="accent", z=4),
        fam._t(0.06, 0.72, 0.70, 0.16, ref="copy", token="HEADLINE_XL", z=5),
    ], background="ink", palette="culture", arrangement="collage", density="HIGH")
    return layout, _tracked("repo_yellow_kiosk", "repo_ev_infographic", "repo_keyboard_app")


def test_collage_supports_three_uneven_overlapping_layered_fragments() -> None:
    layout, images = _tracked_collage()
    validated, result = _validate_and_render(layout, "Хуже не бывает", images)
    assert result is not None and not result.text_clipped
    medias = [r for r in validated.layout.regions if r.kind == "media"]
    assert len(medias) == 3 and len({round(m.w * m.h, 3) for m in medias}) == 3
    overlaps = [max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x)) * max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y)) for a, b in itertools.combinations(medias, 2)]
    assert any(o > 0 for o in overlaps)
    assert [r.z for r in validated.layout.regions] == sorted(r.z for r in validated.layout.regions)  # explicit z order wins
    assert result.notes["rotation_count"] >= 3 and result.notes["layer_count"] >= 5


def test_collage_hierarchy_is_enforced_flat_equal_cards_are_rejected() -> None:
    flat = fam._layout([
        fam._m(0.04, 0.05, 0.30, 0.25, "repo_yellow_kiosk"), fam._m(0.36, 0.05, 0.30, 0.25, "repo_ev_infographic"),
        fam._m(0.68, 0.05, 0.28, 0.25, "repo_keyboard_app"), fam._t(0.06, 0.5, 0.7, 0.2, ref="copy", token="HEADLINE_L"),
    ], background="ink", arrangement="collage")
    validated, result = _validate_and_render(flat, "Заголовок", _tracked("repo_yellow_kiosk", "repo_ev_infographic", "repo_keyboard_app"))
    assert result is None and "collage_hierarchy_flat" in validated.rejection_codes


def test_media_overlap_is_only_legal_in_the_collage_arrangement() -> None:
    layout, images = _tracked_collage()
    layout = {**layout, "arrangement": "standard"}
    validated, result = _validate_and_render(layout, "Заголовок", images)
    assert result is None and "media_regions_collide" in validated.rejection_codes


def test_rotations_are_bounded_and_the_same_plan_and_assets_give_identical_pixels() -> None:
    with pytest.raises(ValueError):
        LayoutRegion.model_validate({**fam._m(0.1, 0.1, 0.4, 0.3, "x"), "tilt_deg": 25.0})
    layout, images = _tracked_collage()
    a = _validate_and_render(layout, "Хуже не бывает", images)[1]
    b = _validate_and_render(layout, "Хуже не бывает", images)[1]
    assert a is not None and b is not None and a.image.tobytes() == b.image.tobytes()
    other = _validate_and_render(_tracked_collage(tilt=(-4.0, 3.0, 6.0))[0], "Хуже не бывает", images)[1]
    assert other is not None and other.image.tobytes() != a.image.tobytes()


@needs_store
def test_real_media_collage_reconstructions_render_with_hierarchy_and_no_grid() -> None:
    for plan in fam.collage_plans():
        validated, result, code = render.render_plan(plan)
        assert result is not None, (plan["name"], code)
        areas = sorted((r["w"] * r["h"] for r in plan["layout"]["regions"] if r["kind"] == "media"), reverse=True)
        assert len(areas) >= 3 and areas[0] >= 1.5 * areas[1] and areas[0] >= 2.5 * areas[-1]
        assert result.notes["rotation_count"] >= 3 and not result.text_clipped


# ------------------------------------------------------------------------------------------ families / geometry


def test_same_family_plans_have_materially_different_geometry() -> None:
    for family_plans in (fam.hero_plans(), fam.collage_plans()):
        plans = [p for p in family_plans if p["label"] != "X"]
        for a, b in itertools.combinations(plans, 2):
            assert geometry_distance(a["layout"], b["layout"]) >= 0.5, (a["name"], b["name"])


def test_different_families_differ_in_structure_not_just_in_images() -> None:
    hero = [p for p in fam.hero_plans() if p["label"] != "X"]
    collage = fam.collage_plans()
    for h, c in itertools.product(hero, collage):
        p1, p2 = structure_profile(h["layout"]), structure_profile(c["layout"])
        assert sum(p1[k] != p2[k] for k in p1) >= 2, (h["name"], c["name"])
        assert geometry_distance(h["layout"], c["layout"]) >= 0.5


@needs_store
def test_immersive_differs_structurally_from_the_other_families() -> None:
    for imm, other in itertools.product(fam.immersive_plans(), fam.collage_plans() + [p for p in fam.hero_plans() if p["label"] != "X"]):
        p1, p2 = structure_profile(imm["layout"]), structure_profile(other["layout"])
        assert sum(p1[k] != p2[k] for k in p1) >= 2, (imm["name"], other["name"])
        assert geometry_distance(imm["layout"], other["layout"]) >= 0.4


def test_static_anti_patterns_are_absent() -> None:
    for plan in fam.hero_plans() + fam.collage_plans():
        for r in plan["layout"]["regions"]:
            if r["kind"] == "text":
                assert r["align"] != "center", plan["name"]  # no generic centred headline
        assert plan["layout"]["arrangement"] in ("stage", "collage")
        medias = [r for r in plan["layout"]["regions"] if r["kind"] == "media"]
        big = max(m["w"] * m["h"] for m in medias)
        assert big >= (0.20 if plan["layout"]["arrangement"] == "collage" else 0.28), plan["name"]  # never a small rectangle on a page


# ------------------------------------------------------------------------------------------ typography / logo


def test_type_hierarchy_can_be_extreme_without_clipping_cyrillic() -> None:
    layout = fam._layout([
        fam._t(0.07, 0.10, 0.86, 0.36, ref="copy_lead", token="MEGA", max_lines=2),
        fam._t(0.07, 0.50, 0.50, 0.06, ref="copy_rest", token="CAPTION", tone="muted", max_lines=2),
    ], background="ink")
    _v, result = _validate_and_render(layout, "Два слова. Короткое пояснение", {})
    assert result is not None and not result.text_clipped
    sizes = {m["ref"]: m for m in result.notes["text_metrics"]}
    assert sizes["copy_lead"]["font_px"] / sizes["copy_rest"]["font_px"] >= 5
    assert sizes["copy_lead"]["block_h_frac"] >= 0.14 and sizes["copy_lead"]["font_px"] >= 0.15 * _SPEC.width  # short copy gets genuinely large type


def test_logo_placement_is_bounded_renderer_owned_and_canonical() -> None:
    with pytest.raises(ValueError):
        InstagramSlideLayout.model_validate({**fam._layout([fam._t(0.1, 0.1, 0.5, 0.2)]), "logo_position": "CENTER"})
    marks = {}
    for position in ("BOTTOM_RIGHT", "BOTTOM_LEFT"):
        layout = fam._layout([fam._t(0.07, 0.10, 0.80, 0.30, ref="copy", token="DISPLAY", max_lines=3)], background="ink", logo=position)
        _v, result = _validate_and_render(layout, "Заголовок", {})
        assert result is not None and result.visible_brand_mark_count == 1 and result.notes["logo_position"] == position
        marks[position] = result.image.convert("L")

    def lit(gray: Image.Image, zone) -> int:
        box = (round(zone[0] * _SPEC.width), round(zone[1] * _SPEC.height), round(zone[2] * _SPEC.width), round(zone[3] * _SPEC.height))
        return sum(1 for v in gray.crop(box).getdata() if v > 60)

    assert lit(marks["BOTTOM_RIGHT"], LOGO_ZONES["BOTTOM_RIGHT"]) > 50 and lit(marks["BOTTOM_RIGHT"], LOGO_ZONES["BOTTOM_LEFT"]) == 0
    assert lit(marks["BOTTOM_LEFT"], LOGO_ZONES["BOTTOM_LEFT"]) > 50 and lit(marks["BOTTOM_LEFT"], LOGO_ZONES["BOTTOM_RIGHT"]) == 0
    clash = fam._layout([fam._t(0.06, 0.80, 0.30, 0.10, ref="copy", token="BODY")], background="ink", logo="BOTTOM_LEFT")
    validated, result = _validate_and_render(clash, "Заголовок", {})
    assert result is None and "text_collides_with_logo" in validated.rejection_codes


@needs_store
def test_every_renderable_reconstruction_is_unclipped_dark_capable_and_overlay_free() -> None:
    accepted = 0
    for plan in fam.all_plans():
        validated, result, code = render.render_plan(plan)
        if plan["label"] == "X":
            assert result is None
            continue
        assert result is not None, (plan["name"], code)
        accepted += 1
        assert not result.text_clipped and result.notes["source_media_pixels_unaltered"] in (True, None)
        assert result.visible_brand_mark_count == 1
        assert min(m["font_px"] for m in result.notes["text_metrics"]) >= round(0.03 * _SPEC.width)
    assert accepted >= 12
