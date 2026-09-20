"""Phase B.5 renderer fixtures: hand-authored DECLARATIVE layouts (A-H). These are RENDERER FIXTURES
only - they prove the safe renderer can express real asymmetry; they say nothing about model
quality. Shared by the tests and by the example contact sheet."""
from __future__ import annotations

from typing import Any


def _r(kind: str, x: float, y: float, w: float, h: float, **kw: Any) -> dict[str, Any]:
    base = {
        "kind": kind, "x": x, "y": y, "w": w, "h": h, "z": 0, "content_ref": None, "scale_token": None,
        "align": None, "valign": None, "max_lines": None, "surface": None, "crop_mode": None,
        "focus_x": None, "focus_y": None, "frame": None, "accent_type": None, "graphic_type": None,
    }
    base.update(kw)
    return base


def _layout(regions, *, density="MEDIUM", dominance="NONE", weight="TEXT", background="paper") -> dict[str, Any]:
    return {"background": background, "density": density, "media_dominance": dominance,
            "visual_weight": weight, "show_progress": True, "regions": regions}


EXAMPLES: dict[str, dict[str, Any]] = {
    "A_large_left_headline_small_right_media": dict(
        copy="Самая умная модель — не самая полезная",
        layout=_layout([
            _r("accent", 0.08, 0.075, 0.14, 0.006, accent_type="rule_h"),
            _r("text", 0.08, 0.10, 0.52, 0.55, content_ref="copy", scale_token="DISPLAY", align="left", valign="top", max_lines=7),
            _r("media", 0.66, 0.10, 0.26, 0.24, content_ref="source", crop_mode="cover", focus_x=0.55, focus_y=0.45, frame="none"),
        ], density="LOW", dominance="SUPPORTING", weight="TEXT"),
        needs_media=True),
    "B_narrow_left_media_strip_large_whitespace": dict(
        copy="Разработчик перестал брать самую дорогую модель для каждой задачи",
        layout=_layout([
            _r("media", 0.0, 0.0, 0.20, 1.0, content_ref="source", crop_mode="cover", focus_x=0.7, focus_y=0.5),
            _r("accent", 0.32, 0.115, 0.14, 0.006, accent_type="rule_h"),
            _r("text", 0.32, 0.14, 0.56, 0.34, content_ref="copy", scale_token="HEADLINE_M", align="left", valign="top", max_lines=8),
        ], density="LOW", dominance="SUPPORTING", weight="MIXED"),
        needs_media=True),
    "C_seventy_percent_media_small_caption": dict(
        copy="Один кадр решает историю",
        layout=_layout([
            _r("media", 0.0, 0.0, 1.0, 0.70, content_ref="source", crop_mode="cover", focus_x=0.55, focus_y=0.45),
            _r("accent", 0.08, 0.745, 0.10, 0.006, accent_type="rule_h"),
            _r("text", 0.08, 0.77, 0.74, 0.14, content_ref="copy", scale_token="HEADLINE_S", align="left", valign="top", max_lines=3),
        ], density="LOW", dominance="DOMINANT", weight="MEDIA"),
        needs_media=True),
    "D_two_unequal_media_regions": dict(
        copy="Общий план и деталь одного и того же предмета",
        layout=_layout([
            _r("media", 0.06, 0.08, 0.60, 0.44, content_ref="source", crop_mode="cover", focus_x=0.5, focus_y=0.45),
            _r("media", 0.70, 0.22, 0.24, 0.30, content_ref="source", crop_mode="cover", focus_x=0.78, focus_y=0.72, frame="accent"),
            _r("text", 0.08, 0.60, 0.72, 0.22, content_ref="copy", scale_token="HEADLINE_S", align="left", valign="top", max_lines=4),
        ], density="MEDIUM", dominance="BALANCED", weight="MIXED"),
        needs_media=True),
    "E_large_central_number_supporting_text": dict(
        copy="20 минут чтения превращаются в чек-лист на 30 секунд",
        layout=_layout([
            _r("text", 0.10, 0.12, 0.80, 0.34, content_ref="number", scale_token="DISPLAY", align="center", valign="middle", max_lines=1),
            _r("accent", 0.43, 0.50, 0.14, 0.006, accent_type="rule_h"),
            _r("text", 0.14, 0.55, 0.70, 0.24, content_ref="copy_no_number", scale_token="HEADLINE_S", align="center", valign="top", max_lines=4),
        ], density="LOW", dominance="NONE", weight="TEXT"),
        needs_media=False),
    "F_offset_screenshot_card_with_explanation": dict(
        copy="Шаг 2. Попросите модель переформулировать вывод в чек-лист",
        layout=_layout([
            _r("media", 0.36, 0.09, 0.56, 0.42, content_ref="source", crop_mode="cover", focus_x=0.5, focus_y=0.4, frame="accent"),
            _r("text", 0.08, 0.60, 0.62, 0.24, content_ref="copy", scale_token="HEADLINE_S", align="left", valign="top", max_lines=5),
        ], density="MEDIUM", dominance="BALANCED", weight="MIXED"),
        needs_media=True),
    "G_image_free_editorial_statement": dict(
        copy="Выбирайте модель по цене готового результата",
        layout=_layout([
            _r("accent", 0.06, 0.26, 0.008, 0.40, accent_type="rule_v"),
            _r("text", 0.11, 0.26, 0.80, 0.40, content_ref="copy", scale_token="DISPLAY", align="left", valign="middle", max_lines=6),
        ], density="LOW", dominance="NONE", weight="TEXT", background="soft"),
        needs_media=False),
    "H_asymmetric_comparison": dict(
        copy="Максимальный интеллект vs стоимость готового результата",
        layout=_layout([
            _r("surface", 0.62, 0.0, 0.38, 1.0, surface="soft"),
            _r("accent", 0.615, 0.12, 0.006, 0.60, accent_type="rule_v"),
            _r("text", 0.08, 0.14, 0.48, 0.40, content_ref="copy_lead", scale_token="HEADLINE_L", align="left", valign="top", max_lines=6),
            _r("text", 0.66, 0.30, 0.28, 0.36, content_ref="copy_rest", scale_token="HEADLINE_S", align="left", valign="top", max_lines=6),
        ], density="MEDIUM", dominance="NONE", weight="TEXT"),
        needs_media=False),
}
