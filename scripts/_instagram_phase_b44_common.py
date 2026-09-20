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


def _slide(role, copy, purpose, **kw) -> dict:
    base = {
        "role": role, "slide_copy": copy, "visual_direction": "v", "source_evidence": None, "slide_purpose": purpose,
        "media_need": None, "composition": None, "media_position": None, "media_scale": None,
        "media_subject": None, "must_match_story": False,
    }
    base.update(kw)
    return base


def _wrap(slides, evidence_used, *, strategy, focal="the subject") -> dict:
    return {
        "objective": "saves", "slides": slides, "final_cta": None, "evidence_used": evidence_used,
        "final_caption": "Подпись к карусели на русском языке.", "content_archetype": None,
        "creative_execution_plan": {
            "main_idea": "idea", "focal_point": focal, "media_strategy": strategy, "media_rationale": "r",
            "composition_direction": "vary with meaning", "branding_treatment": "logo", "visual_treatment": "light editorial",
            "avoid_recent_treatment": None,
        },
    }


def fake_plan(archetype: str, recap_bundle=None) -> dict:
    """Deterministic, v7-shaped plans standing in for the Creative Director (ZERO-COST pass only)."""
    if archetype == "ai_hack":
        return _wrap([
            _slide("hook", "Промпт, который экономит 20 минут на длинных текстах", "hook", composition="typographic"),
            _slide("step", "Шаг 1. Вставьте текст и попросите выделить только принятые решения, без описания проблемы.", "step 1", composition="typographic", source_evidence=AI_HACK_EVIDENCE[1]),
            _slide("step", "Шаг 2. Попросите модель переформулировать вывод в чек-лист из трёх пунктов.", "step 2", composition="screenshot_ui", source_evidence=AI_HACK_EVIDENCE[2]),
            _slide("result", "Было: 20 минут чтения. Стало: чек-лист, который читается за 30 секунд.", "result", composition="split_compare", source_evidence=AI_HACK_EVIDENCE[3]),
            _slide("takeaway", "Попробуйте на своём длинном тексте уже сегодня", "close", composition="typographic"),
        ], AI_HACK_EVIDENCE[1:], strategy="typographic")
    if archetype == "news_insight":
        return _wrap([
            _slide("hook", "Самая умная модель — не самая полезная", "hook", composition="contained_media", media_position="top", media_scale=0.58, media_subject="source", media_need="photo"),
            _slide("context", "Разработчик на Хабре перестал брать самую умную и дорогую модель для каждой задачи.", "context", composition="contained_media", media_position="left", media_scale=0.44, media_subject="source", source_evidence=HABR_EVIDENCE[0]),
            _slide("comparison", "Максимальный intelligence index vs стоимость выполненной задачи", "contrast", composition="split_compare", source_evidence=HABR_EVIDENCE[1]),
            _slide("impact", "Практический вывод: не переплачивать за максимум там, где хватает более дешёвой модели.", "impact", composition="collage", media_subject="source"),
            _slide("takeaway", "Выбирайте модель по цене готового результата", "close", composition="typographic"),
        ], HABR_EVIDENCE, strategy="source_media", focal="Рука с инструментом и деревянный куб в нижней правой части кадра")
    if archetype == "news_recap":
        slides = [_slide("hook", "Главное за неделю", "open", composition="typographic")]
        positions = ["top", "left", "right", "top", "left", "right"]
        import re as _re

        # The fake plan stands in for a Creative Director that writes RUSSIAN slide copy; it can only
        # reuse a story title verbatim when that title is already Russian.
        for i, story in enumerate([st for st in recap_bundle.stories if _re.search("[А-Яа-яЁё]", st.title)], start=1):
            slides.append(_slide(
                "story", story.title, f"story {i}", composition="contained_media", media_position=positions[(i - 1) % 6],
                media_scale=0.5 if positions[(i - 1) % 6] == "top" else 0.44, media_subject=story.key, must_match_story=True,
                source_evidence=story.evidence[0],
            ))
        slides.append(_slide("takeaway", "Это главное — остальное подождёт", "close", composition="typographic"))
        return _wrap(slides, recap_bundle.evidence, strategy="source_media", focal="each story's own image")
    return _wrap([
        _slide("hook", "Ожидание: «ИИ всё изменит»", "hook", composition="collage", media_subject="source"),
        _slide("beat", "Реальность: ещё один чат-бот", "beat", composition="typographic"),
        _slide("takeaway", "Судите по задаче, а не по презентации", "close", composition="contained_media", media_position="right", media_scale=0.44, media_subject="source"),
    ], TREND_EVIDENCE[:1], strategy="source_media")


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
