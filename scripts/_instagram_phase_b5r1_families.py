"""Phase B.5R.1: REAL-MEDIA reconstructions of the three hardest reference families (immersive image field, hero
object stage, internet-culture collage). Renderer fixtures over neutral copy - no Creative Director, no provider,
no reference imagery. Each plan is declarative; immersive text zones come from the deterministic quiet-zone
measurement of the actual (cropped) image pixels, never from a fixed template position."""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from scripts import _instagram_phase_b5r1_assets as assets
from services.instagram_declarative_layout import _fit_in_box
from services.instagram_image_handling import fit_image_cover
from services.instagram_layout_validation import copy_parts
from services.instagram_quiet_zones import NAMED_ZONES, ZoneSelection, select_text_zone
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile

SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
IMM, HERO, COL = assets.IMM, assets.HERO, assets.COL


def _r(kind: str, x: float, y: float, w: float, h: float, **kw: Any) -> dict[str, Any]:
    base = {
        "kind": kind, "x": x, "y": y, "w": w, "h": h, "z": 0, "content_ref": None, "scale_token": None, "align": None,
        "valign": None, "max_lines": None, "surface": None, "crop_mode": None, "focus_x": None, "focus_y": None,
        "frame": None, "accent_type": None, "graphic_type": None, "tone": None, "on_media": None, "tilt_deg": None,
    }
    base.update(kw)
    return base


def _layout(regions, *, background="ink", palette="brand", density="MEDIUM", dominance="NONE", weight="TEXT",
            progress=False, logo="BOTTOM_RIGHT", arrangement="standard") -> dict[str, Any]:
    return {"background": background, "palette": palette, "density": density, "media_dominance": dominance, "visual_weight": weight,
            "show_progress": progress, "logo_position": logo, "arrangement": arrangement, "regions": regions}


def _t(x, y, w, h, ref="copy", token="HEADLINE_M", **kw):
    return _r("text", x, y, w, h, content_ref=ref, scale_token=token, align=kw.pop("align", "left"), valign=kw.pop("valign", "top"),
              max_lines=kw.pop("max_lines", 6), **kw)


def _m(x, y, w, h, key, **kw):
    return _r("media", x, y, w, h, content_ref=key, crop_mode=kw.pop("crop_mode", "cover"), focus_x=kw.pop("focus_x", 0.5),
              focus_y=kw.pop("focus_y", 0.5), frame=kw.pop("frame", "none"), **kw)


def _ground(key: str) -> dict[str, Any]:
    return _r("surface", 0.0, 0.0, 1.0, 1.0, surface="media_ground", content_ref=key)


# ------------------------------------------------------------------------------------------------ immersive


def fitted_for_canvas(asset_id: str, focus_x: float, focus_y: float) -> Image.Image:
    img = assets.resolve(asset_id)
    assert img is not None, asset_id
    return fit_image_cover(img.convert("RGB"), width=SPEC.width, height=SPEC.height, focus_x=focus_x, focus_y=focus_y).image


def immersive_eligibility(asset_id: str, focus_x: float, focus_y: float, *, avoid_logo: str = "BOTTOM_RIGHT") -> ZoneSelection:
    from services.instagram_layout_validation import LOGO_ZONES

    return select_text_zone(fitted_for_canvas(asset_id, focus_x, focus_y), avoid=LOGO_ZONES[avoid_logo],
                            subject_focus=(focus_x, focus_y))


def plan_immersive(asset_id: str, *, focus_x: float, focus_y: float, copy: str, lead_token: str, rest_token: str,
                   name: str, label: str, palette: str = "brand", zone: str | None = None) -> dict[str, Any] | None:
    """A full-frame image with its headline set in the quiet zone the pixels actually offer. Returns None (fail
    closed) when no candidate zone is calm and high-contrast: the image is then not suitable for this family."""
    selection = immersive_eligibility(asset_id, focus_x, focus_y)
    if zone is not None:
        chosen = next((r for r in selection.reports if r.name == zone and r.quiet), None)
        if chosen is None:
            return None
        selection = ZoneSelection(chosen, selection.reports, f"{zone}: requested zone verified quiet")
    if selection.selected is None:
        return None
    sx, sy, sw, sh = NAMED_ZONES[selection.selected.name]
    right = sx >= 0.3
    bottom = sy >= 0.5
    lead_h = min(sh * 0.66, 0.30)
    draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    _font, _lines, block_h, _clipped = _fit_in_box(draw, copy_parts(copy)["copy_lead"], box_w=round(sw * SPEC.width),
                                                  box_h=round(lead_h * SPEC.height), token=lead_token, max_lines=4, spec=SPEC)
    if not bottom:  # top / column zones: the headline box is exactly its measured block, the supporting line follows it
        lead_h = block_h / SPEC.height + 0.014
    rest_y = sy + lead_h + 0.014 if not bottom else sy + lead_h + 0.02
    regions = [
        _m(0.0, 0.0, 1.0, 1.0, asset_id, focus_x=focus_x, focus_y=focus_y),
        _r("accent", sx, sy - 0.022, 0.10, 0.006, accent_type="rule_h"),
        _t(sx, sy, sw, lead_h, ref="copy_lead", token=lead_token, align="right" if right else "left", valign="bottom" if bottom else "top",
           max_lines=4, on_media=True),
        _t(sx, rest_y, sw, 0.07, ref="copy_rest", token=rest_token, align="right" if right else "left", valign="top",
           max_lines=2, on_media=True),
    ]
    return {
        "family": IMM, "label": label, "name": name, "copy": copy, "assets": [asset_id], "selection": selection,
        "layout": _layout(regions, palette=palette, density="LOW", dominance="DOMINANT", weight="MEDIA",
                          logo="BOTTOM_LEFT" if (bottom and right) else "BOTTOM_RIGHT"),
    }


# ------------------------------------------------------------------------------------------------ hero object stage


def hero_plans() -> list[dict[str, Any]]:
    return [
        dict(family=HERO, label="X", name="X_attempt_bright_product_photo_text_on_media_refused", copy="Два слова в заголовке", assets=["repo_orange_phone"], layout=_layout([
            _m(0.0, 0.0, 1.0, 1.0, "repo_orange_phone", focus_x=0.5, focus_y=0.5),
            _t(0.07, 0.04, 0.86, 0.19, ref="copy", token="DISPLAY", max_lines=2, on_media=True),
        ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_LEFT")),
        dict(family=HERO, label="A", name="A_dark_ground_moon_bleeds_bottom_right", copy="Два слова. Короткое пояснение", assets=["hero_moon_on_black"], layout=_layout([
            _ground("hero_moon_on_black"),
            _m(0.20, 0.30, 0.98, 0.86, "hero_moon_on_black", focus_x=0.3, focus_y=0.5),
            _t(0.07, 0.06, 0.70, 0.17, ref="copy_lead", token="HEADLINE_XL", max_lines=2, on_media=False),
            _t(0.07, 0.245, 0.40, 0.045, ref="copy_rest", token="CAPTION", tone="muted", max_lines=1),
        ], background="ink", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")),
        dict(family=HERO, label="B", name="B_light_ground_numeral_and_type_left_phone_right", copy="5. Короткое пояснение к списку", assets=["hero_dark_phone_on_white"], layout=_layout([
            _ground("hero_dark_phone_on_white"),
            _m(0.40, -0.08, 0.90, 1.16, "hero_dark_phone_on_white", focus_x=0.5, focus_y=0.5),
            _t(0.06, 0.07, 0.32, 0.24, ref="number", token="MEGA", valign="middle", max_lines=1),
            _t(0.06, 0.34, 0.32, 0.34, ref="copy_no_number", token="HEADLINE_XL", max_lines=5),
        ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")),
        dict(family=HERO, label="C", name="C_near_full_height_phone_tiny_copy", copy="Заголовок. Короткое пояснение", assets=["hero_white_phone_on_white"], layout=_layout([
            _ground("hero_white_phone_on_white"),
            _m(0.30, -0.10, 0.84, 1.20, "hero_white_phone_on_white", focus_x=0.5, focus_y=0.5),
            _t(0.06, 0.78, 0.21, 0.07, ref="copy_lead", token="HEADLINE_S", max_lines=2),
            _t(0.06, 0.86, 0.22, 0.05, ref="copy_rest", token="CAPTION", tone="muted", max_lines=2),
        ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_RIGHT")),
        dict(family=HERO, label="D", name="D_wide_pair_bleeds_off_right_heavy_headline_above", copy="Два слова в заголовке", assets=["hero_red_foldable"], layout=_layout([
            _ground("hero_red_foldable"),
            _m(0.12, 0.34, 1.28, 0.66, "hero_red_foldable", focus_x=0.3, focus_y=0.5),
            _t(0.06, 0.06, 0.88, 0.24, ref="copy", token="DISPLAY", max_lines=2),
        ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_LEFT")),
    ]


# ------------------------------------------------------------------------------------------------ culture collage


def collage_plans() -> list[dict[str, Any]]:
    return [
        dict(family=COL, label="A", name="A_dark_meme_reaction_collage", copy="Хуже не бывает. Пояснение", assets=["col_reaction_gamer", "col_comic_panels", "col_wallet_ui"], layout=_layout([
            _m(0.32, -0.02, 0.72, 0.58, "col_reaction_gamer", focus_x=0.5, focus_y=0.4, tilt_deg=2.0, z=1),
            _m(0.03, 0.34, 0.44, 0.36, "col_comic_panels", frame="paper", tilt_deg=-5.0, z=3),
            _m(0.62, 0.50, 0.22, 0.24, "col_wallet_ui", frame="paper", tilt_deg=6.0, z=4),
            _r("surface", 0.05, 0.05, 0.27, 0.07, surface="accent2", tilt_deg=-4.0, z=5),
            _t(0.065, 0.062, 0.235, 0.045, ref="copy_rest", token="CAPTION", tilt_deg=-4.0, max_lines=1, z=6),
            _r("graphic", 0.36, 0.60, 0.16, 0.14, graphic_type="arrow_scribble", tone="accent", z=6),
            _r("graphic", 0.50, 0.06, 0.24, 0.20, graphic_type="circle_scribble", tone="accent2", z=6),
            _t(0.06, 0.76, 0.72, 0.15, ref="copy_lead", token="HEADLINE_XL", max_lines=2, z=7),
        ], background="ink", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage")),
        dict(family=COL, label="B", name="B_light_paper_editorial_collage", copy="6. Причин и коротко о каждой", assets=["col_three_phone_ui", "col_table_screenshot", "col_chart", "col_portrait_cutout"], layout=_layout([
            _m(0.04, 0.05, 0.64, 0.34, "col_three_phone_ui", frame="paper", tilt_deg=-3.0, z=1),
            _m(0.56, 0.24, 0.38, 0.32, "col_table_screenshot", frame="paper", tilt_deg=4.0, focus_y=0.2, z=2),
            _m(0.06, 0.35, 0.30, 0.16, "col_chart", frame="paper", tilt_deg=2.0, z=3),
            _m(0.66, 0.52, 0.40, 0.24, "col_portrait_cutout", crop_mode="cutout", focus_x=0.5, focus_y=0.0, z=4),
            _r("graphic", 0.02, 0.665, 0.20, 0.19, graphic_type="circle_scribble", tone="accent", z=6),
            _r("graphic", 0.40, 0.56, 0.18, 0.10, graphic_type="arrow_scribble", tone="accent", z=6),
            _t(0.06, 0.69, 0.16, 0.14, ref="number", token="NUMERAL", valign="middle", max_lines=1, z=7),
            _t(0.24, 0.72, 0.40, 0.14, ref="copy_no_number", token="HEADLINE_L", max_lines=3, z=7),
        ], background="paper", palette="brand", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage", logo="BOTTOM_RIGHT")),
        dict(family=COL, label="C", name="C_dark_interface_reaction_hybrid", copy="Что выбираешь? Вариант А | Вариант Б | Вариант В", assets=["col_dashboard_ui", "col_reaction_gamer", "col_wallet_ui"], layout=_layout([
            _m(0.02, 0.04, 0.78, 0.40, "col_dashboard_ui", focus_y=0.3, tilt_deg=-2.0, z=1),
            _m(0.46, 0.30, 0.52, 0.36, "col_reaction_gamer", focus_x=0.55, focus_y=0.4, tilt_deg=4.0, z=2),
            _m(0.08, 0.44, 0.20, 0.26, "col_wallet_ui", frame="paper", tilt_deg=-6.0, z=3),
            _r("graphic", 0.44, 0.68, 0.50, 0.14, graphic_type="poll_cards", z=4),
            _r("graphic", 0.40, 0.26, 0.30, 0.18, graphic_type="circle_scribble", tone="accent", z=5),
            _r("graphic", 0.86, 0.02, 0.10, 0.08, graphic_type="badge", tone="accent2", z=5),
            _t(0.06, 0.73, 0.34, 0.20, ref="copy_lead", token="HEADLINE_XL", max_lines=3, z=6),
        ], background="ink", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage")),
    ]


def immersive_plans() -> list[dict[str, Any]]:
    """Real images whose pixels actually offer a quiet zone; an image without one is reported, not forced."""
    specs = [
        dict(asset_id="imm_lunar_lander", focus_x=0.3, focus_y=0.5, copy="Два слова. Короткое пояснение к кадру", lead_token="DISPLAY",
             rest_token="CAPTION", name="A_lander_subject_left_headline_in_black_sky", label="A"),
        dict(asset_id="imm_gamer_reaction", focus_x=0.1, focus_y=0.5, copy="Заголовок в три строки. Короткое пояснение", lead_token="HEADLINE_XL",
             rest_token="BODY", name="B_reaction_subject_right_headline_in_dark_left_column", label="B"),
        dict(asset_id="imm_rocket_launch", focus_x=0.1, focus_y=0.5, copy="Один жест. Короткое пояснение к сцене", lead_token="MEGA",
             rest_token="CAPTION", name="C_vertical_fire_column_headline_top_left", label="C"),
        dict(asset_id="imm_black_object", focus_x=0.5, focus_y=0.5, copy="Заголовок. Короткое пояснение", lead_token="HEADLINE_L",
             rest_token="CAPTION", name="D_near_black_object_tiny_type", label="D"),
        dict(asset_id="imm_purple_phone", focus_x=0.7, focus_y=0.5, copy="Новый масштаб. Короткое пояснение к теме", lead_token="HEADLINE_XL",
             rest_token="BODY", name="E_shattering_phone_headline_in_right_column", label="E", palette="neo"),
    ]
    out = []
    for spec in specs:
        plan = plan_immersive(**spec)
        if plan is not None:
            out.append(plan)
    return out


def all_plans() -> list[dict[str, Any]]:
    return immersive_plans() + hero_plans() + collage_plans()
