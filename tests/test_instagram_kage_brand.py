"""KAGE identity swap - Instagram brand skin only (founder decisions 1-6, zero provider calls).

Pins: the canonical palette (printed brandboard labels), the K symbol assets (one exact geometry, two colour roles), the adaptive mark,
ONE mark per slide, no old NNJ/NINJA pixels or text, violet restraint (no solid violet flow card, no violet surfaces), and the boundary:
Instagram never reaches the shared NNJ rasterizer, and nothing outside Instagram imports the KAGE layer."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from schemas.instagram_creative import InstagramSlideLayout
from services import instagram_design_tokens as tok
from services import instagram_kage_brand as kage
from services.instagram_declarative_layout import PALETTES, _surface_colour, render_declared_slide
from services.instagram_visual_profiles import InstagramRenderProfile, ig_brand_mark, profile_spec

ROOT = Path(__file__).resolve().parent.parent
SPEC = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
OLD_BRAND_COLOURS = {(237, 28, 36), (218, 30, 38), (140, 18, 24), (152, 96, 255), (255, 72, 190), (212, 240, 36), (255, 72, 200)}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    return names + [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]


def test_palette_is_the_printed_brandboard_labels():
    assert (kage.SHADOW, kage.GRAPHITE, kage.STONE, kage.MIST, kage.LIGHT, kage.ACCENT) == (
        (0x0B, 0x0B, 0x0D), (0x1A, 0x1A, 0x1D), (0x2B, 0x2B, 0x2F), (0x8E, 0x8E, 0x93), (0xED, 0xED, 0xED), (0x7F, 0x5F, 0xFF))
    assert (tok.INK, tok.PAPER, tok.RED) == (kage.SHADOW, kage.LIGHT, kage.ACCENT)  # every Instagram layout inherits the roles
    assert all(pair == (kage.ACCENT, kage.MIST) for pair in PALETTES.values())  # no red / pink / lime palette survives


def test_the_light_surface_symbol_is_the_same_geometry_with_inverted_planes():
    on_dark = Image.open(kage.SYMBOL_ON_DARK).convert("RGBA")
    on_light = Image.open(kage.SYMBOL_ON_LIGHT).convert("RGBA")
    assert on_dark.size == on_light.size
    assert on_dark.getchannel("A").tobytes() == on_light.getchannel("A").tobytes()  # identical alpha mask = identical geometry
    for band in range(3):
        assert ImageChops.invert(on_dark.getchannel(band)).tobytes() == on_light.getchannel(band).tobytes()


def test_the_brand_mark_is_the_k_not_the_nnj_rasterizer():
    mark = ig_brand_mark(target_width=60, on_light=True)
    ratio = Image.open(kage.SYMBOL_ON_DARK).width / Image.open(kage.SYMBOL_ON_DARK).height
    assert abs(mark.width / mark.height - ratio) < 0.05  # the compact K, not the wide NNJ wordmark
    for path in ROOT.glob("services/instagram_*.py"):
        assert not any("nnj_" in m for m in _imports(path)), path.name  # the shared NNJ rasterizer is never imported


def test_nothing_outside_instagram_imports_the_kage_layer():
    for folder in ("services", "bot", "worker", "core"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name.startswith("instagram_"):
                continue
            assert not any("instagram_kage_brand" in n for n in _imports(path)), path


@pytest.mark.parametrize(("ground", "on_light"), [(kage.LIGHT, True), (kage.SHADOW, False), ((150, 140, 120), True), ((60, 50, 40), False)])
def test_the_mark_variant_follows_the_pixels_beneath_it(ground, on_light):
    canvas = Image.new("RGB", (400, 300), ground)
    box = kage.place_kage_symbol(canvas, reserve_x=300, bottom_y=280, reserve_width=60)
    expected = kage.kage_symbol(target_width=box[2] - box[0], on_light=on_light)
    reference = Image.new("RGB", (400, 300), ground)
    reference.paste(expected, box[:2], expected)
    assert canvas.tobytes() == reference.tobytes()


def _layout(background: str, regions: list[dict], palette: str = "brand") -> InstagramSlideLayout:
    return InstagramSlideLayout.model_validate({"background": background, "palette": palette, "logo_position": "BOTTOM_RIGHT",
                                                "show_progress": False, "density": "LOW", "media_dominance": "NONE",
                                                "visual_weight": "TEXT", "regions": regions})


def _render(layout: InstagramSlideLayout, copy: str = "Заголовок"):
    return render_declared_slide(spec=SPEC, layout=layout, slide_copy=copy, index=0, total=3, subject_assets={})


@pytest.mark.parametrize("background", ["ink", "graphite", "paper", "soft"])
def test_one_k_per_slide_and_no_old_brand_pixel(background):
    layout = _layout(background, [{"kind": "accent", "tone": "accent", "x": 0.07, "y": 0.06, "w": 0.1, "h": 0.01},
                                  {"kind": "text", "content_ref": "copy", "scale_token": "HEADLINE_L", "x": 0.07, "y": 0.1, "w": 0.8, "h": 0.2}])
    result = _render(layout)
    assert result.visible_brand_mark_count == 1
    colours = {c for _, c in result.image.getcolors(maxcolors=1 << 20)}
    assert not colours & OLD_BRAND_COLOURS


def test_a_flow_is_neutral_cards_with_violet_only_on_the_key_card():
    layout = _layout("ink", [{"kind": "text", "content_ref": "copy", "scale_token": "HEADLINE_L", "x": 0.07, "y": 0.08, "w": 0.8, "h": 0.16},
                             {"kind": "graphic", "graphic_type": "flow_diagram", "flow_steps": ["ДЛИННЫЙ ТЕКСТ", "ТОЛЬКО РЕШЕНИЯ", "ВЫВОД"],
                              "x": 0.07, "y": 0.45, "w": 0.86, "h": 0.36}])
    image = _render(layout).image
    violet = sum(n for n, c in image.getcolors(maxcolors=1 << 20) if c == kage.ACCENT)
    assert 0 < violet < 0.01 * image.width * image.height  # an outline + a number, never a solid violet card (was ~8.6% red)


def test_a_declared_accent_surface_renders_neutral_not_violet():
    layout = _layout("ink", [{"kind": "surface", "surface": "accent", "x": 0, "y": 0, "w": 1, "h": 0.5}])
    assert _surface_colour(layout, layout.regions[0], {}) == kage.STONE


def test_no_ninja_pulse_kicker_reaches_pixels():
    from services.instagram_platform_renderer import _kicker_for

    assert _kicker_for(None) is None  # the K mark is the one brand signature; the wordmark is never typeset
