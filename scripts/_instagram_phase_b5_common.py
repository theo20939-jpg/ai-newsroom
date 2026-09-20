"""Shared, manual-only helpers for the Phase B.4.4 no-overlay canaries: archetype scenarios (inputs +
deterministic FAKE v7-shaped plans for the zero-cost pass), contact-sheet/metrics helpers and the
routing fake gateway. No provider calls anywhere in this module."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramEditorialDecision
from scripts._instagram_phase_b5_examples import _layout, _r

HABR_EVIDENCE = [
    "Автор на Хабре описал переход от самых умных и дорогих моделей к более дешёвым.",
    "Главным критерием он выбрал стоимость выполненной задачи, а не максимальный intelligence index.",
]
AI_HACK_EVIDENCE = [
    "Задача: длинный текст нужно быстро превратить в понятное решение.",
    "Шаг 1: вставить текст и попросить выделить только принятые решения, без описания проблемы.",
    "Шаг 2: попросить модель переформулировать вывод в чек-лист из трёх пунктов.",
    "Результат: вместо чтения длинного текста получается короткий чек-лист для проверки.",
]
TREND_EVIDENCE = [
    "Локальная фикстура-референс: быстрая двухпанельная схема «ожидание vs реальность».",
    "Ритм: широкий план, затем резкий кадр-деталь; сама смена кадра несёт мысль, а не подпись.",
    "Ограничение оригинальности: нельзя копировать подпись и кадры референса, использовать только приём.",
]

SCENARIOS = {
    "ai_hack": dict(
        summary="Практичный приём: как за две минуты превратить длинный текст в чек-лист решений",
        decision=dict(opportunity_type="EVERGREEN", angle_intent="HOW_TO", origin="EVERGREEN", purpose="VALUE",
                      topic="Промпт для разбора длинного текста", angle="Два шага вместо двадцати минут чтения"),
        evidence=AI_HACK_EVIDENCE),
    "news_insight": dict(
        summary="Разработчик на Хабре перестал брать самую умную и дорогую ИИ-модель для каждой задачи",
        decision=dict(opportunity_type="NEWS", angle_intent="EXPLAINER", origin="NEWS", purpose="ENGAGEMENT",
                      topic="Выбор модели по стоимости результата", angle="Самая умная модель не всегда самая полезная"),
        evidence=HABR_EVIDENCE),
    "news_recap": dict(
        summary="Главные истории недели в мире ИИ и технологий",
        decision=dict(opportunity_type="NEWS", angle_intent="EXPLAINER", origin="NEWS", purpose="REACH",
                      topic="Итоги недели", angle="Истории недели, у каждой свой кадр"),
        evidence=[]),
    "trend_generative": dict(
        summary="Ожидание и реальность: мем-механика применительно к очередному ИИ-релизу",
        decision=dict(opportunity_type="NEWS_X_TREND", angle_intent="MEME", origin="TREND", purpose="REACH",
                      topic="Ожидание vs реальность в ИИ-релизах", angle="Резкий контраст обещаний и практики",
                      trend_rationale="Приём «ожидание vs реальность» уже знаком аудитории; берём только механику, не чужой материал."),
        evidence=TREND_EVIDENCE),
}


def editorial_decision(archetype: str) -> InstagramEditorialDecision:
    spec = SCENARIOS[archetype]
    base = {
        "source_summary": spec["summary"], "why_now": "Есть конкретный повод обсудить это сейчас",
        "audience_value": "Понять главное и применить", "recommended_format": "carousel",
        "format_reason": "Последовательность кадров читается лучше одного изображения",
        "creative_direction": "Показать суть, объяснить, закрыть выводом",
        "product_connection": None, "trend_rationale": None, "trend_signal_type": None,
        "trend_signal_provenance": None, "supplementary_story_idea": None, "evidence_used": [],
    }
    base.update(spec["decision"])
    return InstagramEditorialDecision(**base)


def _slide(role, copy, purpose, layout, **kw) -> dict:
    base = {
        "role": role, "slide_copy": copy, "visual_direction": "v", "source_evidence": None, "slide_purpose": purpose,
        "media_need": None, "media_subject": None, "media_function": None, "must_match_story": False, "layout": layout,
    }
    base.update(kw)
    return base


def _wrap(slides, evidence_used, *, strategy, arc, interruptions, focal="the subject") -> dict:
    return {
        "objective": "saves", "slides": slides, "final_cta": None, "evidence_used": evidence_used,
        "final_caption": "Подпись к карусели на русском языке.", "content_archetype": None,
        "visual_rhythm": {"arc": arc, "interruption_slides": interruptions, "repetition_note": None},
        "creative_execution_plan": {
            "main_idea": "idea", "focal_point": focal, "media_strategy": strategy, "media_rationale": "r",
            "composition_direction": "vary with meaning", "branding_treatment": "logo", "visual_treatment": "light editorial",
            "avoid_recent_treatment": None,
        },
    }


def _text(x, y, w, h, ref="copy", token="HEADLINE_M", align="left", valign="top", lines=8, z=0):
    return _r("text", x, y, w, h, content_ref=ref, scale_token=token, align=align, valign=valign, max_lines=lines, z=z)


def _media(x, y, w, h, key="source", fx=0.5, fy=0.42, frame="none", crop="cover"):
    return _r("media", x, y, w, h, content_ref=key, crop_mode=crop, focus_x=fx, focus_y=fy, frame=frame)


def _rule(x, y, w=0.14):
    return _r("accent", x, y, w, 0.006, accent_type="rule_h")


def fake_plan(archetype: str, recap_bundle=None) -> dict:
    """Hand-authored DECLARATIVE plans (v8-shaped) - RENDERER FIXTURES for the zero-cost pass. They
    stand in for a Creative Director and prove pipeline + renderer behaviour, not model quality."""
    if archetype == "ai_hack":
        return _wrap([
            _slide("hook", "Промпт, который экономит 20 минут на длинных текстах", "hook", _layout([
                _rule(0.08, 0.10), _text(0.08, 0.13, 0.80, 0.56, token="DISPLAY", lines=7)], density="LOW", weight="TEXT")),
            _slide("step", "Шаг 1. Вставьте текст и попросите выделить только принятые решения, без описания проблемы.", "step 1", _layout([
                _text(0.08, 0.10, 0.30, 0.30, ref="number", token="DISPLAY", valign="middle", lines=1),
                _rule(0.08, 0.45, 0.10), _text(0.08, 0.50, 0.80, 0.30, ref="copy_no_number", token="HEADLINE_S", lines=6)],
                density="MEDIUM", weight="TEXT"), source_evidence=AI_HACK_EVIDENCE[1], media_function="none"),
            _slide("step", "Шаг 2. Попросите модель переформулировать вывод в чек-лист из трёх пунктов.", "step 2", _layout([
                _text(0.08, 0.10, 0.20, 0.18, ref="number", token="DISPLAY", valign="middle", lines=1),
                _r("graphic", 0.30, 0.16, 0.62, 0.46, graphic_type="ui_frame"),
                _text(0.35, 0.28, 0.52, 0.30, ref="copy_no_number", token="HEADLINE_S", lines=6, z=2),
                _rule(0.30, 0.70, 0.12)], density="MEDIUM", weight="GRAPHIC"), source_evidence=AI_HACK_EVIDENCE[2], media_function="ui_screenshot"),
            _slide("result", "Было: 20 минут чтения. Стало: чек-лист, который читается за 30 секунд.", "result", _layout([
                _r("surface", 0.55, 0.0, 0.45, 1.0, surface="soft"), _r("accent", 0.545, 0.14, 0.006, 0.60, accent_type="rule_v"),
                _text(0.08, 0.20, 0.42, 0.40, ref="copy_lead", token="HEADLINE_L", lines=6),
                _text(0.60, 0.34, 0.32, 0.36, ref="copy_rest", token="HEADLINE_S", lines=8)],
                density="MEDIUM", weight="TEXT"), source_evidence=AI_HACK_EVIDENCE[3], media_function="before_after"),
            _slide("takeaway", "Попробуйте на своём длинном тексте уже сегодня", "close", _layout([
                _r("accent", 0.06, 0.55, 0.008, 0.22, accent_type="rule_v"), _text(0.10, 0.55, 0.78, 0.24, token="HEADLINE_L", lines=4)],
                density="LOW", weight="TEXT", background="soft")),
        ], AI_HACK_EVIDENCE[1:], strategy="typographic",
            arc="уверенный вход, инструкция по шагам, визуальный разрыв через до/после, спокойный вывод", interruptions=[3])
    if archetype == "news_insight":
        return _wrap([
            _slide("hook", "Самая умная модель — не самая полезная", "hook", _layout([
                _media(0.0, 0.0, 1.0, 0.66, fx=0.55, fy=0.45), _rule(0.08, 0.70, 0.10), _text(0.08, 0.73, 0.74, 0.16, token="HEADLINE_M", lines=3)],
                density="LOW", dominance="DOMINANT", weight="MEDIA"), media_subject="source", media_function="hero"),
            _slide("context", "Разработчик на Хабре перестал брать самую умную и дорогую модель для каждой задачи.", "context", _layout([
                _media(0.0, 0.0, 0.20, 1.0, fx=0.7), _rule(0.32, 0.115), _text(0.32, 0.14, 0.56, 0.42, token="HEADLINE_M", lines=8)],
                density="LOW", dominance="SUPPORTING", weight="MIXED"), media_subject="source", media_function="detail", source_evidence=HABR_EVIDENCE[0]),
            _slide("comparison", "Максимальный интеллект vs стоимость выполненной задачи", "contrast", _layout([
                _r("surface", 0.62, 0.0, 0.38, 1.0, surface="soft"), _r("accent", 0.615, 0.12, 0.006, 0.60, accent_type="rule_v"),
                _text(0.08, 0.20, 0.48, 0.40, ref="copy_lead", token="HEADLINE_L", lines=6),
                _text(0.66, 0.30, 0.28, 0.36, ref="copy_rest", token="HEADLINE_S", lines=8)], density="MEDIUM", weight="TEXT"),
                source_evidence=HABR_EVIDENCE[1]),
            _slide("impact", "Практический вывод: не переплачивать за максимум там, где хватает более дешёвой модели.", "impact", _layout([
                _media(0.06, 0.08, 0.60, 0.40, fx=0.5, fy=0.45), _media(0.70, 0.22, 0.24, 0.26, fx=0.8, fy=0.75, frame="accent"),
                _text(0.08, 0.58, 0.74, 0.24, token="HEADLINE_S", lines=5)], density="MEDIUM", dominance="BALANCED", weight="MIXED"),
                media_subject="source", media_function="detail"),
            _slide("takeaway", "Выбирайте модель по цене готового результата", "close", _layout([
                _r("accent", 0.06, 0.26, 0.008, 0.40, accent_type="rule_v"), _text(0.11, 0.26, 0.80, 0.40, token="DISPLAY", valign="middle", lines=6)],
                density="LOW", weight="TEXT", background="soft")),
        ], HABR_EVIDENCE, strategy="source_media", focal="Рука с инструментом и деревянный куб в нижней правой части кадра",
            arc="кадр-история, спокойный контекст, визуальный разрыв через сравнение, деталь, тихая точка", interruptions=[2])
    if archetype == "news_recap":
        variants = [
            lambda k: [_media(0.0, 0.0, 0.40, 1.0, key=k), _text(0.47, 0.16, 0.45, 0.50, token="HEADLINE_S", lines=10)],
            lambda k: [_media(0.0, 0.0, 1.0, 0.50, key=k), _text(0.08, 0.57, 0.74, 0.28, token="HEADLINE_S", lines=6)],
            lambda k: [_media(0.64, 0.0, 0.36, 1.0, key=k), _text(0.08, 0.16, 0.50, 0.55, token="HEADLINE_S", lines=10)],
            lambda k: [_media(0.62, 0.08, 0.30, 0.26, key=k), _text(0.08, 0.40, 0.80, 0.40, token="HEADLINE_S", lines=8)],
        ]
        slides = [_slide("hook", "Главное за неделю", "open", _layout([_rule(0.08, 0.10), _text(0.08, 0.13, 0.80, 0.40, token="DISPLAY", lines=4)], density="LOW", weight="TEXT"))]
        russian = [st for st in recap_bundle.stories if any(("А" <= ch <= "я") or ch in "Ёё" for ch in st.title)]
        for i, story in enumerate(russian, start=1):
            slides.append(_slide("story", story.title, f"story {i}", _layout(variants[(i - 1) % 4](story.key), density="MEDIUM",
                                 dominance="BALANCED", weight="MIXED"), media_subject=story.key, media_function="hero",
                                 must_match_story=True, source_evidence=story.evidence[0]))
        slides.append(_slide("takeaway", "Это главное — остальное подождёт", "close", _layout([
            _r("surface", 0.0, 0.56, 1.0, 0.44, surface="soft"), _rule(0.08, 0.30), _text(0.08, 0.33, 0.80, 0.20, token="HEADLINE_L", lines=3)], density="LOW", weight="TEXT")))
        return _wrap(slides, recap_bundle.evidence, strategy="source_media", focal="each story's own image",
                     arc="короткий вход, ритм сюжетов с разными позициями кадра, спокойное закрытие", interruptions=[])
    return _wrap([
        _slide("hook", "Ожидание: «ИИ всё изменит»", "hook", _layout([
            _media(0.05, 0.06, 0.62, 0.50, fx=0.5, fy=0.5), _media(0.71, 0.22, 0.24, 0.34, fx=0.75, fy=0.7, frame="accent"),
            _text(0.08, 0.64, 0.72, 0.18, token="HEADLINE_M", lines=3)], density="LOW", dominance="BALANCED", weight="MEDIA"),
            media_subject="source", media_function="hero"),
        _slide("beat", "Реальность: ещё один чат-бот", "beat", _layout([
            _r("surface", 0.0, 0.70, 1.0, 0.30, surface="red"), _text(0.08, 0.16, 0.84, 0.44, token="DISPLAY", valign="middle", lines=4)],
            density="LOW", weight="GRAPHIC")),
        _slide("takeaway", "Судите по задаче, а не по презентации", "close", _layout([
            _media(0.70, 0.0, 0.30, 1.0, fx=0.5, fy=0.5), _text(0.08, 0.30, 0.56, 0.36, token="HEADLINE_L", lines=6)],
            density="LOW", dominance="SUPPORTING", weight="MIXED"), media_subject="source", media_function="detail"),
    ], TREND_EVIDENCE[:1], strategy="source_media", arc="громкий контраст кадров, пустой график-панч, спокойный вывод", interruptions=[1])


class RoutingFakeGateway:
    """Zero-cost stand-in transport: answers the editorial-decision call and the carousel call."""

    def __init__(self, decision: dict, carousel: dict) -> None:
        self.decision, self.carousel = decision, carousel

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        props = (request.response_schema or {}).get("properties", {})
        out = self.decision if "opportunity_type" in props else self.carousel
        return GenerateResponse(text=None, structured_output=out, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


def fixture_image(color: tuple[int, int, int], label: str, size=(1200, 1500)) -> Image.Image:
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    d.rectangle([80, 80, size[0] - 80, size[1] - 80], outline=(255, 255, 255), width=6)
    d.text((110, 110), f"FIXTURE: {label}", fill=(255, 255, 255))
    return img


def contact_sheet(images: list[Image.Image], thumb_w: int = 360, gap: int = 16) -> Image.Image:
    thumb_h = round(thumb_w * 1350 / 1080)
    sheet = Image.new("RGB", (gap + len(images) * (thumb_w + gap), thumb_h + 2 * gap), (245, 246, 248))
    for i, image in enumerate(images):
        sheet.paste(image.convert("RGB").resize((thumb_w, thumb_h)), (gap + i * (thumb_w + gap), gap))
    return sheet


def mean_luma(image: Image.Image) -> float:
    hist = image.convert("L").histogram()
    total = sum(hist) or 1
    return sum(i * c for i, c in enumerate(hist)) / total


DARK_SLIDE_LUMA = 100.0  # a slide whose mean luma is below this reads as a dark slide


def dark_slide_count(images: list[Image.Image]) -> int:
    return sum(1 for im in images if mean_luma(im) < DARK_SLIDE_LUMA)
