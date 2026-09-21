"""Phase B.5R: hand-authored DECLARATIVE reconstruction compositions - two DIFFERENT ones per visual family in
Visual DNA v2 - over NEUTRAL SYNTHETIC content. They are RENDERER FIXTURES: they answer 'can the renderer
express this family?', not 'is this a good post' and not 'does this copy a reference slide'. No Creative
Director call, no real news, no provider."""
from __future__ import annotations

from typing import Any

from PIL import Image

from scripts import _instagram_phase_b5r_placeholders as ph
from services import instagram_design_tokens as tok
from services.instagram_declarative_layout import GRAPHITE

_INK, _PAPER = tok.INK, tok.PAPER


def _r(kind: str, x: float, y: float, w: float, h: float, **kw: Any) -> dict[str, Any]:
    base = {
        "kind": kind, "x": x, "y": y, "w": w, "h": h, "z": 0, "content_ref": None, "scale_token": None, "align": None,
        "valign": None, "max_lines": None, "surface": None, "crop_mode": None, "focus_x": None, "focus_y": None,
        "frame": None, "accent_type": None, "graphic_type": None, "tone": None, "on_media": None, "tilt_deg": None,
    }
    base.update(kw)
    return base


def _layout(regions, *, background="ink", palette="brand", density="MEDIUM", dominance="NONE", weight="TEXT", progress=True) -> dict[str, Any]:
    return {"background": background, "palette": palette, "density": density, "media_dominance": dominance,
            "visual_weight": weight, "show_progress": progress, "regions": regions}


def _t(x, y, w, h, ref="copy", token="HEADLINE_M", **kw):
    return _r("text", x, y, w, h, content_ref=ref, scale_token=token, align=kw.pop("align", "left"), valign=kw.pop("valign", "top"), max_lines=kw.pop("max_lines", 6), **kw)


def _m(x, y, w, h, key, **kw):
    return _r("media", x, y, w, h, content_ref=key, crop_mode=kw.pop("crop_mode", "cover"), focus_x=kw.pop("focus_x", 0.5), focus_y=kw.pop("focus_y", 0.5), frame=kw.pop("frame", "none"), **kw)


def assets() -> dict[str, Image.Image]:
    """All synthetic placeholder images, by subject key."""
    return {
        "obj_dark": ph.object_on(_INK), "obj_dark_wide": ph.object_on(_INK, size=(1200, 1000)), "obj_light": ph.object_on(_PAPER, body=(58, 62, 72), light=True, glow=False),
        "tile_light": ph.app_tile(_PAPER), "portrait": ph.portrait_dark(), "neon": ph.neon_scene(), "neon_side": ph.neon_scene(size=(760, 1350), glow=(120, 90, 255)),
        "reaction": ph.reaction_blob(), "band": ph.photo_band(), "paper_a": ph.photo_paper(), "paper_b": ph.photo_paper(sky=(210, 170, 190), ground=(120, 96, 140)),
        "paper_c": ph.photo_paper(size=(700, 700), sky=(180, 210, 170), ground=(70, 110, 90)),
    }


# family_id -> [composition, composition]. copy strings are neutral placeholders; needs = subject keys drawn.
FAMILY_COMPOSITIONS: dict[str, list[dict[str, Any]]] = {
    "dark_type_number_statement": [
        dict(name="A1_numeral_left_void_right", copy="42. Короткое пояснение к числу", layout=_layout([
            _r("accent", 0.07, 0.075, 0.10, 0.006, accent_type="rule_h"),
            _t(0.07, 0.10, 0.74, 0.36, ref="number", token="NUMERAL", valign="middle", max_lines=1),
            _t(0.07, 0.50, 0.62, 0.26, ref="copy_no_number", token="HEADLINE_L", max_lines=5),
        ], density="LOW", weight="TEXT")),
        dict(name="A2_display_headline_object_bleeds_right", copy="Заголовок. Короткое пояснение к нему", layout=_layout([
            _t(0.07, 0.09, 0.82, 0.40, ref="copy_lead", token="DISPLAY", max_lines=4),
            _t(0.07, 0.56, 0.46, 0.14, ref="copy_rest", token="BODY", tone="muted", max_lines=3),
            _m(0.60, 0.50, 0.40, 0.44, "obj_dark", focus_x=0.4),
            _r("accent", 0.07, 0.52, 0.08, 0.006, accent_type="rule_h"),
        ], density="MEDIUM", dominance="SUPPORTING", weight="TEXT")),
    ],
    "hero_object_stage": [
        dict(name="B1_isolated_object_tiny_caption", copy="Заголовок. Короткое пояснение", layout=_layout([
            _m(0.18, 0.10, 0.64, 0.56, "obj_dark", crop_mode="cover"),
            _t(0.07, 0.72, 0.70, 0.11, ref="copy_lead", token="HEADLINE_S", max_lines=2),
            _t(0.07, 0.84, 0.60, 0.06, ref="copy_rest", token="CAPTION", tone="muted", max_lines=2),
        ], density="LOW", dominance="BALANCED", weight="MEDIA")),
        dict(name="B2_light_diagonal_object_bleeds_corner", copy="Заголовок. Короткое пояснение", background="paper", layout=_layout([
            _t(0.07, 0.08, 0.50, 0.26, ref="copy_lead", token="HEADLINE_L", max_lines=3),
            _t(0.07, 0.36, 0.27, 0.10, ref="copy_rest", token="CAPTION", tone="muted", max_lines=3),
            _m(0.36, 0.44, 0.64, 0.56, "obj_light", crop_mode="cover", focus_x=0.7),
        ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA")),
    ],
    "immersive_image_field": [
        dict(name="C1_full_bleed_scene_text_in_quiet_zone", copy="Заголовок на сцене", layout=_layout([
            _m(0.0, 0.0, 1.0, 1.0, "portrait", focus_x=0.6, focus_y=0.4),
            _r("accent", 0.07, 0.585, 0.10, 0.006, accent_type="rule_h"),
            _t(0.07, 0.62, 0.62, 0.26, ref="copy", token="HEADLINE_L", max_lines=4, on_media=True),
        ], density="LOW", dominance="DOMINANT", weight="MEDIA", progress=False)),
        dict(name="C2_numeral_column_beside_scene", copy="10. Короткое пояснение к списку", layout=_layout([
            _m(0.42, 0.0, 0.58, 1.0, "neon_side", focus_x=0.6, focus_y=0.5),
            _t(0.06, 0.08, 0.34, 0.22, ref="number", token="NUMERAL", valign="middle", max_lines=1),
            _t(0.06, 0.34, 0.33, 0.40, ref="copy_no_number", token="HEADLINE_M", max_lines=8),
        ], palette="neo", density="MEDIUM", dominance="BALANCED", weight="MEDIA")),
    ],
    "culture_collage": [
        dict(name="D1_setup_band_punchline", copy="Заголовок. Короткое пояснение", layout=_layout([
            _t(0.07, 0.07, 0.80, 0.12, ref="copy_lead", token="HEADLINE_S", max_lines=2),
            _m(0.0, 0.22, 1.0, 0.46, "band", focus_x=0.5, focus_y=0.5),
            _r("graphic", 0.60, 0.235, 0.30, 0.06, graphic_type="scribble", tone="accent"),
            _r("graphic", 0.72, 0.55, 0.14, 0.11, graphic_type="badge", tone="accent2"),
            _t(0.07, 0.73, 0.70, 0.12, ref="copy_rest", token="HEADLINE_M", tone="accent", max_lines=2),
        ], palette="culture", density="MEDIUM", dominance="BALANCED", weight="MIXED")),
        dict(name="D2_paper_fragments_tilted_dense", copy="6. Короткое пояснение к списку", layout=_layout([
            _m(0.06, 0.06, 0.46, 0.34, "paper_a", frame="paper", tilt_deg=-4.0),
            _m(0.54, 0.20, 0.34, 0.30, "paper_b", frame="paper", tilt_deg=5.0),
            _m(0.10, 0.44, 0.30, 0.22, "paper_c", frame="paper", tilt_deg=3.0),
            _r("graphic", 0.70, 0.56, 0.13, 0.10, graphic_type="badge", tone="accent2"),
            _r("graphic", 0.08, 0.68, 0.34, 0.05, graphic_type="scribble", tone="accent"),
            _t(0.46, 0.56, 0.22, 0.16, ref="number", token="NUMERAL", valign="middle", max_lines=1),
            _t(0.08, 0.76, 0.72, 0.14, ref="copy_no_number", token="HEADLINE_M", max_lines=3),
        ], background="paper", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED")),
    ],
    "interface_cards": [
        dict(name="E1_question_top_cards_below", copy="Что выбираешь? Вариант А | Вариант Б | Вариант В", layout=_layout([
            _r("graphic", 0.55, 0.035, 0.36, 0.05, graphic_type="scribble", tone="accent"),
            _t(0.07, 0.10, 0.72, 0.16, ref="copy_lead", token="HEADLINE_M", max_lines=2),
            _r("graphic", 0.07, 0.30, 0.86, 0.44, graphic_type="poll_cards"),
        ], palette="neo", density="HIGH", dominance="BALANCED", weight="GRAPHIC")),
        dict(name="E2_tall_question_column_cards_right", copy="Что выбираешь? Вариант А | Вариант Б | Вариант В | Вариант Г", layout=_layout([
            _t(0.06, 0.12, 0.34, 0.46, ref="copy_lead", token="HEADLINE_M", max_lines=6),
            _r("graphic", 0.44, 0.24, 0.50, 0.50, graphic_type="poll_cards"),
            _r("graphic", 0.06, 0.70, 0.12, 0.09, graphic_type="badge", tone="accent2"),
            _r("graphic", 0.50, 0.10, 0.40, 0.07, graphic_type="scribble", tone="accent2"),
        ], background="graphite", palette="culture", density="HIGH", dominance="BALANCED", weight="GRAPHIC")),
    ],
    "light_utility_editorial": [
        dict(name="F1_numeral_headline_object_right", copy="5. Короткое пояснение к списку", background="paper", layout=_layout([
            _t(0.06, 0.08, 0.22, 0.16, ref="number", token="NUMERAL", valign="middle", max_lines=1),
            _t(0.06, 0.27, 0.50, 0.36, ref="copy_no_number", token="HEADLINE_L", max_lines=6),
            _m(0.60, 0.05, 0.40, 0.46, "tile_light", crop_mode="cover", focus_x=0.7),
        ], background="paper", density="MEDIUM", dominance="BALANCED", weight="TEXT")),
        dict(name="F2_no_media_heading_and_short_list", copy="Заголовок: первый пункт, второй пункт, третий пункт", background="paper", layout=_layout([
            _r("accent", 0.07, 0.10, 0.09, 0.008, accent_type="rule_h", tone="accent"),
            _t(0.07, 0.13, 0.86, 0.30, ref="copy_lead", token="DISPLAY", max_lines=2),
            _r("accent", 0.07, 0.49, 0.86, 0.003, accent_type="rule_h", tone="muted"),
            _t(0.07, 0.53, 0.74, 0.30, ref="copy_rest", token="HEADLINE_S", tone="muted", max_lines=4),
        ], background="paper", density="MEDIUM", dominance="NONE", weight="TEXT")),
    ],
}


def dark_surfaces() -> tuple[tuple[int, int, int], ...]:
    return (_INK, GRAPHITE)
