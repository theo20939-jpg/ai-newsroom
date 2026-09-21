"""Phase B.5R.3: hero-object-stage and internet-culture-collage reconstructions, third pass. Same declarative system, REAL existing media
only, neutral copy, no Creative Director, no provider. Hero: tighter crops, split panels and type that shares the object's ground.
Collage: four different mechanics (reaction/punchline, mixed social editorial, poll/choice UI, screenshot chaos), one reaction image and
one starburst in the whole set, different real assets per composition."""
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
    # A - DARK CINEMATIC OBJECT: the object is closer and crosses the right and bottom edges; headline upper-left, a large deliberate void between
    plans.append(dict(family=HERO, label="A", name="A_dark_cinematic_moon_crosses_right_and_bottom", copy="Два слова. Короткое пояснение", assets=["hero_moon_on_black"], layout=_layout([
        _ground("hero_moon_on_black"),
        _m(0.12, 0.30, 1.10, 0.95, "hero_moon_on_black", crop_mode="object_contain", focus_x=1.0, focus_y=1.0),
        _t(0.07, 0.07, 0.64, 0.17, ref="copy_lead", token="HEADLINE_XL", max_lines=2),
        _t(0.07, 0.25, 0.40, 0.045, ref="copy_rest", token="CAPTION", tone="muted", max_lines=1),
    ], background="ink", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_LEFT")))
    # B - DARK OBJECT-DOMINANT POSTER: the object IS the frame; type only in the calm zone the pixels offer
    gpu = plan_immersive("hero_gpu_on_black", focus_x=0.5, focus_y=0.5, copy="Заголовок. Короткое пояснение", lead_token="HEADLINE_L",
                         rest_token="CAPTION", name="B_dark_object_fills_frame_type_in_measured_calm_zone", label="B")
    if gpu is not None:
        gpu["family"] = HERO
        gpu["layout"] = {**gpu["layout"], "arrangement": "stage", "density": "LOW"}
        plans.append(gpu)
    # C - LIGHT UTILITY OBJECT: a macro-close phone crossing the top, bottom and right edges; poster-scale type SHARES its ground
    plans.append(dict(family=HERO, label="C", name="C_light_phone_macro_crosses_three_edges_type_shares_the_ground", copy="Два слова. Короткое пояснение", assets=["hero_dark_phone_on_white"], layout=_layout([
        _ground("hero_dark_phone_on_white"),
        _m(-0.05, -0.12, 1.23, 1.24, "hero_dark_phone_on_white", crop_mode="object_contain", focus_x=0.8, focus_y=0.5),
        _t(0.05, 0.07, 0.34, 0.42, ref="copy_lead", token="DISPLAY", max_lines=3, on_media=True),
        _t(0.05, 0.86, 0.32, 0.05, ref="copy_rest", token="CAPTION", tone="muted", max_lines=1, on_media=True),
    ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")))
    # D - CROPPED PREMIUM OBJECT (mixed ground): a graphite band carries the headline, the object crosses the left, right and bottom edges of its photo panel
    plans.append(dict(family=HERO, label="D", name="D_mixed_graphite_band_over_a_cropped_object_panel", copy="Два слова в заголовке", assets=["hero_red_foldable"], layout=_layout([
        _r("surface", 0.0, 0.0, 1.0, 0.34, surface="graphite"),
        _m(0.0, 0.34, 1.0, 0.66, "hero_red_foldable", crop_mode="object_cover", focus_x=0.5, focus_y=0.5),
        _t(0.06, 0.05, 0.88, 0.25, ref="copy", token="DISPLAY", max_lines=2),
    ], background="ink", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")))
    # E - GIANT NUMBER + OBJECT (mixed ground): a tight object panel on the left, a graphite column with a giant numeral on the right
    plans.append(dict(family=HERO, label="E", name="E_mixed_object_panel_left_graphite_column_numeral_right", copy="5. Короткое пояснение к списку", assets=["hero_white_phone_on_white"], layout=_layout([
        _r("surface", 0.58, 0.0, 0.42, 1.0, surface="graphite"),
        _m(0.0, 0.0, 0.58, 1.0, "hero_white_phone_on_white", crop_mode="object_cover", focus_x=0.5, focus_y=0.5),
        _t(0.62, 0.07, 0.34, 0.26, ref="number", token="NUMERAL", tone="accent", valign="top", max_lines=1),
        _t(0.62, 0.38, 0.32, 0.36, ref="copy_no_number", token="HEADLINE_L", max_lines=6),
    ], background="ink", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage", logo="BOTTOM_LEFT")))
    # F - OBJECT-DOMINANT POSTER (light): a tall object at poster scale, cropped by the top, right and bottom edges; a giant numeral and short type anchor the lower-left
    plans.append(dict(family=HERO, label="F", name="F_light_tall_object_full_height_bleed_right_numeral_lower_left", copy="7. Причин коротко", assets=["hero_power_bank"], layout=_layout([
        _ground("hero_power_bank"),
        _m(0.34, -0.40, 0.96, 1.40, "hero_power_bank", crop_mode="object_contain", focus_x=0.5, focus_y=0.5),
        _t(0.04, 0.50, 0.28, 0.30, ref="number", token="NUMERAL", tone="accent", valign="bottom", max_lines=1),
        _t(0.04, 0.83, 0.28, 0.11, ref="copy_no_number", token="HEADLINE_M", valign="top", max_lines=3),
    ], background="paper", density="LOW", dominance="DOMINANT", weight="MEDIA", arrangement="stage")))
    return plans


def collage_plans() -> list[dict[str, Any]]:
    return [
        # A - REACTION / PUNCHLINE (dark): the punchline leads at the TOP, the one reaction image sits below it and bleeds off the bottom, two evidence fragments collide with it
        dict(family=COL, label="A", name="A_punchline_on_top_reaction_image_below_evidence_fragments", copy="Ну и ну. Пояснение", assets=["col_reaction_gamer", "col_chart", "col_chip_macro"], layout=_layout([
            _r("graphic", 0.05, 0.045, 0.60, 0.115, graphic_type="highlight", tone="accent", tilt_deg=-2.0, z=5),
            _t(0.07, 0.06, 0.56, 0.085, ref="copy_lead", token="DISPLAY", max_lines=1, z=7),
            _r("surface", 0.05, 0.185, 0.20, 0.06, surface="accent2", tilt_deg=-4.0, z=5),
            _t(0.06, 0.192, 0.18, 0.045, ref="copy_rest", token="CAPTION", tilt_deg=-4.0, max_lines=1, z=6),
            _m(0.08, 0.28, 0.95, 0.62, "col_reaction_gamer", focus_x=0.5, focus_y=0.3, tilt_deg=-2.0, z=1),
            _m(0.56, 0.14, 0.38, 0.18, "col_chart", frame="torn", tilt_deg=5.0, z=3),
            _m(0.62, 0.84, 0.30, 0.16, "col_chip_macro", frame="paper", tilt_deg=6.0, z=4),
            _r("graphic", 0.45, 0.34, 0.30, 0.22, graphic_type="circle_scribble", tone="accent2", z=6),
        ], background="ink", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage", logo="BOTTOM_LEFT")),
        # B - MIXED SOCIAL / PAPER EDITORIAL (light): a die-cut cut-out anchors the frame, evidence screenshots collide with it, the only starburst, a giant numeral
        dict(family=COL, label="B", name="B_light_mixed_social_die_cut_anchor_evidence_screens_numeral", copy="6. Причин коротко о каждой", assets=["col_portrait_cutout", "col_table_screenshot", "col_three_phone_ui", "col_comic_panels"], layout=_layout([
            _m(0.54, 0.02, 0.44, 0.34, "col_table_screenshot", frame="torn", tilt_deg=5.0, focus_y=0.15, z=1),
            _m(0.52, 0.42, 0.46, 0.22, "col_three_phone_ui", frame="torn", tilt_deg=-4.0, z=2),
            _m(0.00, 0.40, 0.66, 0.40, "col_portrait_cutout", crop_mode="cutout", frame="die_cut", focus_x=0.5, focus_y=0.0, z=3),
            _m(0.03, 0.30, 0.22, 0.12, "col_comic_panels", frame="paper", tilt_deg=-7.0, z=4),
            _r("graphic", 0.44, 0.34, 0.14, 0.09, graphic_type="burst", tone="accent", tilt_deg=-10.0, z=5),
            _r("graphic", 0.56, 0.06, 0.26, 0.10, graphic_type="box_scribble", tone="accent", z=6),
            _r("graphic", 0.29, 0.205, 0.24, 0.05, graphic_type="underline_scribble", tone="accent", z=6),
            _t(0.05, 0.03, 0.24, 0.20, ref="number", token="NUMERAL", tone="accent", valign="top", max_lines=1, z=7),
            _t(0.29, 0.07, 0.24, 0.13, ref="copy_no_number", token="HEADLINE_M", max_lines=3, z=7),
        ], background="paper", palette="brand", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage")),
        # C - POLL / CHOICE UI (dark): the option-card stack is the central mechanic; two small real fragments are secondary; the question is the type anchor
        dict(family=COL, label="C", name="C_dark_poll_choice_ui_is_the_mechanic", copy="Что выбираешь? Вариант А | Вариант Б | Вариант В | Вариант Г", assets=["repo_yellow_kiosk", "col_teardown"], layout=_layout([
            _t(0.06, 0.05, 0.88, 0.20, ref="copy_lead", token="DISPLAY", tone="accent", max_lines=2, z=7),
            _r("graphic", 0.06, 0.245, 0.60, 0.05, graphic_type="underline_scribble", tone="accent2", z=6),
            _r("graphic", 0.06, 0.34, 0.88, 0.36, graphic_type="poll_cards", z=4),
            _m(0.50, 0.68, 0.46, 0.24, "col_teardown", frame="torn", tilt_deg=5.0, z=3),
            _m(0.05, 0.74, 0.24, 0.18, "repo_yellow_kiosk", frame="paper", tilt_deg=-7.0, z=5),
            _r("graphic", 0.30, 0.72, 0.18, 0.10, graphic_type="arrow_scribble", tone="accent", z=6),
        ], background="ink", palette="culture", density="HIGH", dominance="BALANCED", weight="GRAPHIC", arrangement="collage", logo="BOTTOM_LEFT")),
        # D - SCREENSHOT CHAOS (graphite): five real screenshots at uneven scale, the primary rotated hard and bleeding left, annotated with a hand-drawn box, an arrow and a highlight; no reaction image, no burst
        dict(family=COL, label="D", name="D_graphite_screenshot_chaos_rotated_primary_annotated", copy="Что там?", assets=["col_dashboard_ui", "col_flow_diagram", "col_wallet_ui", "repo_ev_infographic", "repo_keyboard_app"], layout=_layout([
            _r("graphic", 0.05, 0.035, 0.42, 0.075, graphic_type="highlight", tone="accent", tilt_deg=-1.5, z=6),
            _t(0.07, 0.04, 0.38, 0.065, ref="copy", token="HEADLINE_XL", max_lines=1, z=7),
            _m(-0.06, 0.18, 0.80, 0.44, "col_dashboard_ui", focus_y=0.3, tilt_deg=-6.0, z=1),
            _m(0.46, 0.50, 0.52, 0.24, "col_flow_diagram", frame="paper", tilt_deg=5.0, z=2),
            _m(0.04, 0.63, 0.34, 0.22, "repo_keyboard_app", frame="torn", tilt_deg=-4.0, z=3),
            _m(0.66, 0.10, 0.18, 0.22, "col_wallet_ui", frame="paper", tilt_deg=9.0, z=4),
            _m(0.56, 0.77, 0.38, 0.17, "repo_ev_infographic", frame="paper", tilt_deg=-3.0, z=5),
            _r("graphic", 0.30, 0.26, 0.28, 0.10, graphic_type="box_scribble", tone="accent", z=6),
            _r("graphic", 0.46, 0.14, 0.18, 0.10, graphic_type="arrow_scribble", tone="accent2", z=6),
        ], background="graphite", palette="culture", density="HIGH", dominance="BALANCED", weight="MIXED", arrangement="collage", logo="BOTTOM_LEFT")),
]


def all_plans() -> list[dict[str, Any]]:
    return immersive_plans() + hero_plans() + collage_plans()
