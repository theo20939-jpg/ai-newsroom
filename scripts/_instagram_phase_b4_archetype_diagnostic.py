"""Manual-only Phase B.4 content-archetype diagnostic.

Renders one of four content archetypes (ai_hack / news_insight / news_recap / trend_generative)
through the REAL carousel pipeline (schemas.instagram_creative -> instagram_content_package ->
instagram_platform_renderer -> instagram_art_validator), using the SAME structured
composition/media_position/media_scale/overlay_mode fields introduced in Phase B.4.

Zero image-provider calls: imports nothing from services.budgeted_image_execution or any
provider adapter. NEWS_INSIGHT reuses the real, founder-approved B.2 RAW asset (read from durable
storage exactly like the Phase B.3 diagnostic); AI_HACK/NEWS_RECAP/TREND_GENERATIVE use local,
synthetically-generated fixture images (explicitly labelled as fixtures, never claimed as real
screenshots or real news photography) - the exact "local fixtures" allowance in the B.4 spec.
No Telegram, no DB session, no publication - this only writes local review artifacts.
"""
from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from core.config import settings
from integrations.storage.image_storage import LocalImageStorage
from schemas.instagram_creative import (
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
)
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_reference_deconstruction import ReferenceDeconstruction
from services.instagram_shadow_pipeline import ShadowPlanResult

_RAW_STORAGE_KEY = "images/ff/ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png"


def _load_news_insight_raw(raw_path_override: str | None) -> Image.Image:
    if raw_path_override:
        data = Path(raw_path_override).read_bytes()
    else:
        data = LocalImageStorage(settings.image_storage_root).read(_RAW_STORAGE_KEY)
    return Image.open(io.BytesIO(data)).convert("RGB")


def _fixture(color: tuple[int, int, int], label: str, *, size: tuple[int, int] = (1200, 1500)) -> Image.Image:
    """A deterministic, clearly-synthetic LOCAL fixture image - never claimed as a real
    screenshot/photo. Used only for archetypes this diagnostic has no real asset for
    (AI_HACK/NEWS_RECAP/TREND_GENERATIVE), per the B.4 spec's own "local fixtures" allowance."""
    img = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(255, 255, 255), width=6)
    draw.text((80, 80), f"FIXTURE: {label}", fill=(255, 255, 255))
    return img


def _base_context():
    opp = ContentOpportunity(
        id="phase-b4-diagnostic", source_type=OpportunitySourceType.NEWS, story_id="phase-b4",
        news_value=0.7, audience_relevance=0.8, evidence=[], confidence=0.9,
    )
    sp = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description="Phase B.4 diagnostic",
        primary_objective="value", audience_description="Разработчики и пользователи ИИ.",
        recommended_format="carousel", hook_family=None, creative_concept_summary="Phase B.4 diagnostic",
        alternative_format=None, alternative_objective=None, product_mention_allowed=False,
        evidence=[], confidence=0.9,
    )
    return opp, sp


# ======================================================================================
# AI_HACK
# ======================================================================================

def _ai_hack_creative() -> InstagramCarouselCreative:
    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="Промпт, который экономит 20 минут разбора длинного текста",
            visual_direction="Полнокадровый крючок, крупный заголовок.",
            slide_purpose="hook", composition="full_bleed_media", media_position="full", overlay_mode="gradient",
        ),
        InstagramCarouselSlideCreative(
            role="step", slide_copy="Шаг 1. Вставьте текст и попросите выделить только решения, а не описание проблемы.",
            visual_direction="Скриншот-карточка интерфейса сверху, инструкция снизу.",
            slide_purpose="step_1", composition="screenshot_ui", media_position="top", media_scale=0.48, overlay_mode="none",
            media_subject="chat_ui_step_1",
        ),
        InstagramCarouselSlideCreative(
            role="step", slide_copy="Шаг 2. Попросите модель переформулировать вывод как чек-лист из 3 пунктов.",
            visual_direction="Скриншот-карточка интерфейса сверху, инструкция снизу.",
            slide_purpose="step_2", composition="screenshot_ui", media_position="top", media_scale=0.48, overlay_mode="none",
            media_subject="chat_ui_step_2",
        ),
        InstagramCarouselSlideCreative(
            role="result", slide_copy="Результат: 20 минут чтения превращаются в чек-лист на 30 секунд.",
            visual_direction="Контейнерное изображение слева, результат текстом справа.",
            slide_purpose="result", composition="contained_media", media_position="left", media_scale=0.42, overlay_mode="subtle",
            media_subject="before_after_result",
        ),
        InstagramCarouselSlideCreative(
            role="takeaway", slide_copy="Попробовать в NINJA AI",
            visual_direction="Чистая типографика, сдержанный продуктовый хендофф.",
            slide_purpose="cta", composition="typographic",
        ),
    ]
    return InstagramCarouselCreative(
        objective="value", slides=slides, content_archetype="ai_hack",
        final_caption="Один промпт, который реально экономит время при разборе длинных текстов.",
    )


def _ai_hack_assets() -> dict[int, Image.Image]:
    return {
        0: _fixture((40, 70, 110), "AI_HACK hook"),
        1: _fixture((25, 25, 30), "chat UI step 1"),
        2: _fixture((25, 25, 30), "chat UI step 2"),
        3: _fixture((60, 100, 70), "before/after result"),
    }


# ======================================================================================
# NEWS_INSIGHT (the B.3 regression case)
# ======================================================================================

def _news_insight_creative() -> InstagramCarouselCreative:
    from schemas.instagram_creative import InstagramCreativeExecutionPlan

    evidence = [
        "Автор на Хабре описал переход от самых умных и дорогих моделей к более дешёвым.",
        "Главным критерием он выбрал стоимость выполненной задачи, а не максимальный intelligence index.",
    ]
    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="Самая умная модель ≠ самая полезная",
            visual_direction="Полнокадровое использование одобренного B.2 сгенерированного изображения, без изменений композиции.",
            slide_purpose="Визуальный крючок обложки", media_need="полный кадр, герой обложки",
        ),
        InstagramCarouselSlideCreative(
            role="context", slide_copy="Разработчик на Хабре перестал всегда брать самую «умную» и дорогую модель для каждой задачи.",
            visual_direction="Боковая полоса с крупным планом инструмента и куба, не общий план всей сцены.",
            source_evidence=evidence[0], slide_purpose="Минимальный факт для понимания истории",
            media_need="боковая полоса, крупный план деталь",
        ),
        InstagramCarouselSlideCreative(
            role="comparison", slide_copy="Максимальный intelligence index vs стоимость выполненной задачи",
            visual_direction="Двухпанельное сравнение критериев без изображения, только типографика.",
            source_evidence=evidence[1], slide_purpose="Центральный контраст статьи",
            media_need="без фото, только графика - сильное графическое сравнение не нуждается в изображении",
        ),
        InstagramCarouselSlideCreative(
            role="impact", slide_copy="Практический вывод: не переплачивать за максимальный интеллект там, где хватает более дешёвой и быстрой модели.",
            visual_direction="Крупный план инструмента и куба - сфокусированная деталь, а не общий приглушённый фон.",
            source_evidence=evidence[1], slide_purpose="Практическое значение для читателя",
            media_need="крупный план, деталь инструмента",
        ),
        InstagramCarouselSlideCreative(
            role="takeaway", slide_copy="Разумный выбор модели - не самый мощный вариант, а тот, что решает задачу с наименьшими издержками.",
            visual_direction="Закрывающий красный фон системы, чистая типографика без изображения.",
            slide_purpose="Вывод, закрывающий тезис обложки", media_need="без изображения, чистая типографика для вывода",
        ),
    ]
    return InstagramCarouselCreative(
        objective="value", slides=slides, evidence_used=evidence, content_archetype="news_insight",
        final_caption=(
            "Автор на Хабре пишет, что перестал выбирать самые умные ИИ-модели для каждой задачи. "
            "Вместо рейтинга интеллекта он смотрит на стоимость готового результата."
        ),
        creative_execution_plan=InstagramCreativeExecutionPlan(
            main_idea="Показать разницу между максимальной вычислительной мощью и практической полезностью через один визуальный конфликт, развёрнутый в карусель.",
            focal_point="Рука с инструментом и деревянный куб в нижней правой части кадра",
            media_strategy="generated_media",
            media_rationale="Один реальный сгенерированный кадр из B.2 переиспользуется по всей карусели через разные производные обработки вместо повторной генерации.",
            composition_direction="Обложка - полный кадр; контекст и практический вывод - крупный план детали инструмента и куба; сравнение и вывод - чистая типографика без изображения.",
            branding_treatment="Логотип не генерировать; текущий знак добавляет compositor.",
            visual_treatment="Premium editorial still life, tactile industrial materials, warm natural light.",
            avoid_recent_treatment="Без роботов, неона, чёрной карточки, интерфейсов, мозгов из микросхем и sci-fi клише.",
        ),
    )


# ======================================================================================
# NEWS_RECAP
# ======================================================================================

def _news_recap_creative() -> InstagramCarouselCreative:
    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="4 истории недели в мире ИИ",
            visual_direction="Чистая типографика для обложки-обзора.",
            slide_purpose="hook", composition="typographic",
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="История A: новая модель снижает стоимость инференса.",
            visual_direction="Контейнерное изображение сверху, привязанное именно к этой истории.",
            slide_purpose="story_a", composition="contained_media", media_position="top", media_scale=0.46,
            media_subject="story_a_visual", must_match_story=True, media_asset_identity="story-a-2026w38",
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="История B: новый бенчмарк для агентных задач.",
            visual_direction="Контейнерное изображение сверху, привязанное именно к этой истории.",
            slide_purpose="story_b", composition="contained_media", media_position="top", media_scale=0.46,
            media_subject="story_b_visual", must_match_story=True, media_asset_identity="story-b-2026w38",
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="История C: обновление в области on-device моделей.",
            visual_direction="Контейнерное изображение сверху, привязанное именно к этой истории.",
            slide_purpose="story_c", composition="contained_media", media_position="top", media_scale=0.46,
            media_subject="story_c_visual", must_match_story=True, media_asset_identity="story-c-2026w38",
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="История D: новая практика safety-тестирования перед релизом.",
            visual_direction="Контейнерное изображение сверху, привязанное именно к этой истории.",
            slide_purpose="story_d", composition="contained_media", media_position="top", media_scale=0.46,
            media_subject="story_d_visual", must_match_story=True, media_asset_identity="story-d-2026w38",
        ),
        InstagramCarouselSlideCreative(
            role="takeaway", slide_copy="Сохраните, чтобы не потерять контекст недели.",
            visual_direction="Чистая типографика для закрытия.",
            slide_purpose="cta", composition="typographic",
        ),
    ]
    return InstagramCarouselCreative(
        objective="saves", slides=slides, content_archetype="news_recap",
        final_caption="Синтетический recap-фикстур: 4 независимые истории недели, каждая со своим изображением.",
    )


def _news_recap_assets() -> dict[int, Image.Image]:
    return {
        1: _fixture((60, 90, 140), "Story A"),
        2: _fixture((140, 60, 90), "Story B"),
        3: _fixture((90, 140, 60), "Story C"),
        4: _fixture((140, 120, 40), "Story D"),
    }


# ======================================================================================
# TREND_GENERATIVE
# ======================================================================================

def _trend_reference_deconstruction() -> ReferenceDeconstruction:
    """Reuses the EXISTING originality-discipline dataclass (services/instagram_reference_
    deconstruction.py) - a learned MECHANIC, never a copied expression."""
    return ReferenceDeconstruction(
        reference_description="A local trend fixture: a fast-cut two-panel 'expectation vs reality' visual mechanic.",
        hook_mechanics="Immediate visual contrast in the first frame, no build-up.",
        visual_rhythm="Two-beat collage: wide establishing frame, then an abrupt detail cut.",
        typography_behavior="Minimal on-image copy, large and short.",
        what_appears_effective=["the abrupt cut itself carries the joke/insight, not the caption"],
        must_not_copy=["the reference's own exact caption wording", "the reference's own exact footage/imagery"],
        originality_constraints=["use NINJA's own real generated/fixture asset only, never the reference's own pixels"],
    )


def _trend_generative_creative() -> InstagramCarouselCreative:
    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="Ожидание vs реальность: очередной AI-релиз",
            visual_direction="Коллаж из двух производных кадров одного медиа - широкий план сверху, деталь снизу.",
            slide_purpose="hook", composition="collage", media_position="full", overlay_mode="subtle",
        ),
        InstagramCarouselSlideCreative(
            role="beat", slide_copy="Маркетинг: «меняет всё»",
            visual_direction="Медиа-доминантный кадр, минимум текста.",
            slide_purpose="beat_1", composition="full_bleed_media", media_position="full", overlay_mode="subtle",
        ),
        InstagramCarouselSlideCreative(
            role="takeaway", slide_copy="На практике: ещё один чат-бот",
            visual_direction="Тот же реальный ассет, другой деривативный кроп для контраста.",
            slide_purpose="beat_2", composition="contained_media", media_position="right", media_scale=0.5, overlay_mode="none",
        ),
    ]
    return InstagramCarouselCreative(
        objective="reach", slides=slides, content_archetype="trend_generative",
        final_caption="Синтетический trend-фикстур: механика 'ожидание vs реальность', не копия конкретного референса.",
    )


def _trend_generative_assets() -> dict[int, Image.Image]:
    img = _fixture((30, 30, 35), "TREND fixture asset")
    return {0: img, 1: img, 2: img}


_ARCHETYPES = {
    "ai_hack": (_ai_hack_creative, _ai_hack_assets),
    "news_insight": (_news_insight_creative, None),  # uses the real RAW asset instead
    "news_recap": (_news_recap_creative, _news_recap_assets),
    "trend_generative": (_trend_generative_creative, _trend_generative_assets),
}


def _build_contact_sheet(slide_images: list[Image.Image]) -> Image.Image:
    thumb_w = 360
    thumb_h = round(thumb_w * 1350 / 1080)
    gap = 16
    sheet_w = thumb_w * len(slide_images) + gap * (len(slide_images) + 1)
    sheet_h = thumb_h + gap * 2
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 20))
    for i, img in enumerate(slide_images):
        thumb = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        sheet.paste(thumb, (gap + i * (thumb_w + gap), gap))
    return sheet


def run_archetype(archetype: str, *, raw_override: str | None, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    opp, sp = _base_context()
    creative_fn, assets_fn = _ARCHETYPES[archetype]
    carousel = creative_fn()

    if archetype == "news_insight":
        raw_image = _load_news_insight_raw(raw_override)
        slide_images = {i: raw_image for i in range(len(carousel.slides))}
        source_image_ref = "generated:images/ff/ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png"
    else:
        slide_images = assets_fn()
        source_image_ref = f"fixture:{archetype}"

    package = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(
            recommended_format=ContentFormat.CAROUSEL, why=f"Phase B.4 {archetype} diagnostic.",
            expected_role="value", confidence=0.9,
        ),
        shadow_plan=sp, creative_outcome=CreativeGenerationOutcome(carousel=carousel), account_key="ninja_pulse",
        source_image_ref=source_image_ref,
    )
    results = render_instagram_carousel(package, slide_images=slide_images)
    art = validate_instagram_art(package, results)
    gate = evaluate_instagram_editorial_gate(package, art)

    slide_paths = []
    manifest_slides = []
    decoded_images = []
    for i, result in enumerate(results):
        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
        assert img.size == (1080, 1350), f"slide {i} wrong canvas size: {img.size}"
        decoded_images.append(img)
        path = out_dir / f"slide_{i + 1:02d}.png"
        img.save(path, format="PNG")
        slide_paths.append(str(path))
        manifest_slides.append({
            "index": i, "file": path.name, "role": carousel.slides[i].role, "text": carousel.slides[i].slide_copy,
            "layout_variant": result.evidence.notes.get("layout_variant"),
            "composition_requested": result.evidence.notes.get("composition_requested"),
            "media_primitive_selected": result.evidence.notes.get("media_primitive_selected"),
            "source_image_treatment": result.evidence.source_image_treatment,
            "must_match_story": result.evidence.notes.get("must_match_story"),
            "media_asset_identity": result.evidence.notes.get("media_asset_identity"),
            "text_clipped": result.evidence.text_clipped,
            "visible_brand_mark_count": result.evidence.visible_brand_mark_count,
        })

    contact_sheet = _build_contact_sheet(decoded_images)
    contact_sheet_path = out_dir / "contact_sheet.png"
    contact_sheet.save(contact_sheet_path, format="PNG")

    manifest = {
        "archetype": archetype,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_slides": len(results),
        "slides": manifest_slides,
        "art_validation": art.to_dict(),
        "gate_decision": getattr(gate.decision, "value", str(gate.decision)),
        "provider_image_calls": 0,
        "incremental_image_cost_usd": "0",
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "archetype": archetype, "art_passed": art.passed, "art_blocking_issues": art.blocking_issues,
        "gate_decision": manifest["gate_decision"], "slide_paths": slide_paths,
        "contact_sheet_path": str(contact_sheet_path), "manifest_path": str(manifest_path),
        "decoded_images": decoded_images,
    }


def main() -> None:
    archetype = sys.argv[1] if len(sys.argv) > 1 else "news_insight"
    raw_override = sys.argv[2] if len(sys.argv) > 2 else None
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(f"artifacts/instagram_phase_b4_{archetype}/carousel")
    result = run_archetype(archetype, raw_override=raw_override, out_dir=out_dir)
    result.pop("decoded_images")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
