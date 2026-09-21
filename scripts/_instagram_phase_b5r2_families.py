"""Phase B.5R.2: hero-object-stage and internet-culture-collage reconstructions, second pass. Same declarative system as B.5R.1
(`scripts/_instagram_phase_b5r1_families.py`), REAL existing media only, neutral copy, no Creative Director, no provider.
Hero objects are staged by their measured extent (`object_contain`, over-canvas regions for bleed); collage fragments use
torn paper edges, a die-cut outline on a real alpha cutout, highlighter and starburst marks and coloured type."""
from __future__ import annotations

from typing import Any

from scripts._instagram_phase_b5r1_families import (  # noqa: F401 - re-exported for the render/test scripts
    COL,
    HERO,
    IMM,
    SPEC,
    _ground,
    _layout,
    _m,
    _r,
    _t,
    immersive_plans,
    plan_immersive,
)


def hero_plans() -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    # A - dark: a large round object bleeds off the right and bottom edges, headline upper-left, a large void between them
    plans.append(dict(family=HERO, label="A", name="A_dark_moon_bleeds_bottom_right_headline_upper_left", copy="Два слова. Короткое пояснение", assets=["hero_moon_on_black"], layout=_layout([
        _ground("hero_moon_on_black"),
        _m(0.30, 0.40, 0.95, 0.80, "hero_moon_on_black", crop_mode="object_contain", focus_x=1.0, focus_y=1.0),
        _t(0.07, 0.07, 0.64, 0.17, ref="copy_lead", token="HEADLINE_XL", max_lines=2),
        _t(0.07, 0.25, 0.40, 0.045, ref="copy_rest", token="CAPTION", tone="muted", max_lines=1),
    ], background="ink", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_LEFT")))
    # B - dark: the object IS the frame (cropped by every edge); type sits in the calm zone the pixels offer (measured)
    gpu = plan_immersive("hero_gpu_on_black", focus_x=0.5, focus_y=0.5, copy="Заголовок. Короткое пояснение", lead_token="HEADLINE_L",
                         rest_token="CAPTION", name="B_dark_object_fills_frame_type_in_measured_calm_zone", label="B")
    if gpu is not None:
        gpu["family"] = HERO
        gpu["layout"] = {**gpu["layout"], "arrangement": "stage", "density": "LOW"}
        plans.append(gpu)
    # C - light: near full-height object cropped top and bottom, tiny supporting type opposite
    plans.append(dict(family=HERO, label="C", name="C_light_phone_cropped_top_and_bottom_tiny_type_left", copy="Заголовок. Короткое пояснение", assets=["hero_dark_phone_on_white"], layout=_layout([
        _ground("hero_dark_phone_on_white"),
        _m(0.38, -0.06, 0.66, 1.12, "hero_dark_phone_on_white", crop_mode="object_contain", focus_x=0.5, focus_y=0.5),
        _t(0.06, 0.79, 0.27, 0.075, ref="copy_lead", token="HEADLINE_S", max_lines=2),
        _t(0.06, 0.875, 0.27, 0.05, ref="copy_rest", token="CAPTION", tone="muted", max_lines=2),
    ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")))
    # D - light: object bottom-left, cropped by the bottom edge; small headline in the opposite (top-right) corner
    plans.append(dict(family=HERO, label="D", name="D_light_phone_bottom_left_cropped_headline_top_right", copy="Короткий заголовок. Пояснение", assets=["hero_white_phone_on_white"], layout=_layout([
        _ground("hero_white_phone_on_white"),
        _m(-0.04, 0.28, 0.92, 0.94, "hero_white_phone_on_white", crop_mode="object_contain", focus_x=0.15, focus_y=1.0),
        _t(0.58, 0.05, 0.36, 0.14, ref="copy_lead", token="HEADLINE_M", align="right", max_lines=3),
        _t(0.58, 0.20, 0.36, 0.05, ref="copy_rest", token="CAPTION", tone="muted", align="right", max_lines=1),
    ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")))
    # E - light: object central/lower with a giant numeral and a narrow text column nearby
    plans.append(dict(family=HERO, label="E", name="E_light_object_lower_right_giant_numeral_upper_left", copy="7. Причин коротко", assets=["hero_power_bank"], layout=_layout([
        _ground("hero_power_bank"),
        _m(0.36, 0.16, 0.60, 0.86, "hero_power_bank", crop_mode="object_contain", focus_x=0.5, focus_y=1.0),
        _t(0.05, 0.05, 0.30, 0.30, ref="number", token="NUMERAL", tone="accent", valign="top", max_lines=1),
        _t(0.05, 0.38, 0.28, 0.30, ref="copy_no_number", token="HEADLINE_L", max_lines=4),
    ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_LEFT")))
    # F - light: a wide two-object shot cropped by the LEFT edge, heavy headline low on the opposite side
    plans.append(dict(family=HERO, label="F", name="F_light_pair_cropped_by_left_edge_headline_low_left", copy="Два слова в заголовке", assets=["hero_red_foldable"], layout=_layout([
        _ground("hero_red_foldable"),
        _m(-0.30, 0.10, 1.28, 0.62, "hero_red_foldable", crop_mode="object_contain", focus_x=1.0, focus_y=0.5),
        _t(0.06, 0.76, 0.66, 0.17, ref="copy", token="DISPLAY", max_lines=2),
    ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")))
    return plans


def collage_plans() -> list[dict[str, Any]]:
    return [
        # A - dark reaction / meme: cropped reaction image, torn comic fragment, small colour-heavy fragment, sticker burst, highlighter under the headline
        dict(family=COL, label="A", name="A_dark_reaction_meme_torn_comic_burst_highlight", copy="Ну и ну. Пояснение", assets=["col_reaction_gamer", "col_comic_panels", "repo_yellow_kiosk"], layout=_layout([
            _m(0.30, -0.04, 0.79, 0.66, "col_reaction_gamer", focus_x=0.5, focus_y=0.35, tilt_deg=2.0, z=1),
            _m(0.02, 0.36, 0.46, 0.34, "col_comic_panels", frame="torn", tilt_deg=-6.0, z=3),
            _m(0.60, 0.52, 0.22, 0.24, "repo_yellow_kiosk", frame="torn", tilt_deg=7.0, z=4),
            _r("graphic", 0.72, 0.03, 0.24, 0.16, graphic_type="burst", tone="accent2", tilt_deg=12.0, z=5),
            _r("graphic", 0.05, 0.735, 0.60, 0.115, graphic_type="highlight", tone="accent", tilt_deg=-2.0, z=5),
            _r("graphic", 0.55, 0.13, 0.26, 0.20, graphic_type="circle_scribble", tone="accent2", z=6),
            _r("graphic", 0.36, 0.63, 0.18, 0.12, graphic_type="arrow_scribble", tone="accent", z=6),
            _t(0.07, 0.75, 0.56, 0.085, ref="copy_lead", token="DISPLAY", max_lines=1, z=7),
            _t(0.07, 0.865, 0.34, 0.045, ref="copy_rest", token="CAPTION", tone="accent2", max_lines=1, z=7),
        ], background="ink", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage")),
        # B - light editorial / paper collision: a big tilted text screenshot, torn UI fragment, chart, a die-cut cutout overlapping both, red marks
        dict(family=COL, label="B", name="B_light_paper_collision_die_cut_cutout_red_marks", copy="6. Причин коротко о каждой", assets=["col_table_screenshot", "col_three_phone_ui", "col_chart", "col_portrait_cutout"], layout=_layout([
            _m(0.30, 0.02, 0.72, 0.56, "col_table_screenshot", frame="torn", tilt_deg=5.0, focus_y=0.15, z=1),
            _m(0.03, 0.20, 0.56, 0.26, "col_three_phone_ui", frame="torn", tilt_deg=-4.0, z=2),
            _m(0.05, 0.50, 0.30, 0.16, "col_chart", frame="paper", tilt_deg=3.0, z=3),
            _m(0.52, 0.42, 0.57, 0.30, "col_portrait_cutout", crop_mode="cutout", frame="die_cut", focus_x=0.5, focus_y=0.0, z=4),
            _r("graphic", 0.02, 0.03, 0.18, 0.11, graphic_type="burst", tone="accent", tilt_deg=-10.0, z=5),
            _r("graphic", 0.02, 0.665, 0.25, 0.235, graphic_type="circle_scribble", tone="accent", z=6),
            _r("graphic", 0.29, 0.905, 0.36, 0.05, graphic_type="highlight", tone="accent", tilt_deg=-2.0, z=6),
            _r("graphic", 0.38, 0.60, 0.20, 0.10, graphic_type="arrow_scribble", tone="accent", z=6),
            _t(0.06, 0.685, 0.22, 0.21, ref="number", token="NUMERAL", tone="accent", valign="middle", max_lines=1, z=7),
            _t(0.30, 0.73, 0.40, 0.16, ref="copy_no_number", token="HEADLINE_L", max_lines=3, z=7),
        ], background="paper", palette="brand", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage")),
        # C - dark UI / reaction hybrid: huge dashboard fragment, torn reaction image, tilted UI card, option cards, marks
        dict(family=COL, label="C", name="C_dark_dashboard_reaction_option_cards_hybrid", copy="Что выбираешь? Вариант А | Вариант Б | Вариант В", assets=["col_dashboard_ui", "col_reaction_gamer", "col_wallet_ui"], layout=_layout([
            _m(0.02, 0.03, 0.96, 0.42, "col_dashboard_ui", focus_y=0.3, tilt_deg=-2.0, z=1),
            _m(0.40, 0.32, 0.60, 0.40, "col_reaction_gamer", frame="torn", focus_x=0.55, focus_y=0.4, tilt_deg=4.0, z=2),
            _m(0.05, 0.40, 0.22, 0.28, "col_wallet_ui", frame="paper", tilt_deg=-7.0, z=3),
            _r("graphic", 0.40, 0.72, 0.42, 0.14, graphic_type="poll_cards", z=4),
            _r("graphic", 0.80, 0.02, 0.16, 0.10, graphic_type="burst", tone="accent2", tilt_deg=-10.0, z=5),
            _r("graphic", 0.22, 0.34, 0.20, 0.10, graphic_type="arrow_scribble", tone="accent", z=6),
            _r("graphic", 0.50, 0.28, 0.32, 0.18, graphic_type="circle_scribble", tone="accent2", z=6),
            _t(0.06, 0.74, 0.32, 0.20, ref="copy_lead", token="HEADLINE_XL", tone="accent", max_lines=3, z=7),
        ], background="ink", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage")),
        # D - media-heavy social-native: one huge reaction image owns the frame, tiny torn fragments, sticker burst, giant accent-coloured type below
        dict(family=COL, label="D", name="D_media_heavy_reaction_giant_accent_type", copy="Ну и ну. Короткое пояснение", assets=["imm_gamer_reaction", "col_comic_panels", "col_wallet_ui"], layout=_layout([
            _m(0.0, 0.0, 1.0, 0.62, "imm_gamer_reaction", focus_x=0.5, focus_y=0.3, z=1),
            _m(0.55, 0.50, 0.40, 0.24, "col_comic_panels", frame="torn", tilt_deg=-5.0, z=3),
            _m(0.04, 0.54, 0.18, 0.24, "col_wallet_ui", frame="paper", tilt_deg=6.0, z=4),
            _r("graphic", 0.68, 0.04, 0.26, 0.16, graphic_type="burst", tone="accent2", tilt_deg=12.0, z=5),
            _r("graphic", 0.26, 0.60, 0.20, 0.10, graphic_type="arrow_scribble", tone="accent", z=6),
            _t(0.06, 0.79, 0.50, 0.12, ref="copy_lead", token="MEGA", tone="accent", max_lines=1, z=7),
            _t(0.06, 0.915, 0.40, 0.045, ref="copy_rest", token="CAPTION", tone="muted", max_lines=1, z=7),
        ], background="ink", palette="culture", density="HIGH", dominance="DOMINANT", weight="MEDIA", arrangement="collage")),
    ]


def all_plans() -> list[dict[str, Any]]:
    return immersive_plans() + hero_plans() + collage_plans()
