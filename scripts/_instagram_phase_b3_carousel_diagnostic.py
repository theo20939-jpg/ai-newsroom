"""Manual-only Phase B.3 carousel system diagnostic.

Validates the CAROUSEL pipeline (creative -> package -> per-slide layout selection ->
compositor -> QA -> gate -> packaged asset set) end to end, using the SAME real story/RAW
asset behind the founder-approved Phase B.2 single-image diagnostic.

Zero image-provider calls: this file deliberately imports nothing from
`services.budgeted_image_execution` or `integrations.llm_gateway.providers.*` - the RAW asset is
read from durable storage (already paid for and persisted during B.2), never regenerated. No
Telegram, no DB session, no publication - this only writes local review artifacts.
"""
from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

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
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_shadow_pipeline import ShadowPlanResult

_STORY_ID = "5d82a32b-8afe-4c08-8c3b-75d1f56769b7"
_OPPORTUNITY_ID = f"phase-b3-carousel-diagnostic-{_STORY_ID}"
_CAROUSEL_ID = "phase-b3-carousel-diagnostic-20260919-v1"
_SOURCE_URL = "https://habr.com/ru/articles/1083368/"
_RAW_STORAGE_KEY = "images/ff/ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png"
_EVIDENCE = [
    "Автор на Хабре описал переход от самых умных и дорогих моделей к более дешёвым.",
    "Главным критерием он выбрал стоимость выполненной задачи, а не максимальный intelligence index.",
]
_SUMMARY = "Почему разработчик выбрал полезность модели вместо максимального рейтинга"
_APPROVED_COVER_HEADLINE = "Самая умная модель ≠ самая полезная"

_OPP = ContentOpportunity(
    id=_OPPORTUNITY_ID, source_type=OpportunitySourceType.NEWS, story_id=_STORY_ID,
    news_value=0.8, audience_relevance=0.9, evidence=_EVIDENCE, confidence=0.95,
    editorial_decision={
        "opportunity_type": "CULTURE", "angle": _SUMMARY, "angle_intent": "REACTION",
        "audience_value": "Получить практичную рамку выбора модели.", "recommended_format": "carousel",
        "format_reason": "История содержит контекст, контраст и практический вывод - хватает на карусель.",
        "purpose": "VALUE", "origin": "NEWS", "topic": _SUMMARY,
        "why_now": "Диагностика carousel-системы на подтверждённой B4/B.2-возможности.",
        "creative_direction": "Editorial carousel reusing the approved B.2 generated cover.",
    },
)
_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description=_SUMMARY, primary_objective="value",
    audience_description="Разработчики и пользователи ИИ.", recommended_format="carousel", hook_family=None,
    creative_concept_summary="Максимум интеллекта модели не всегда даёт лучший результат на задачу.",
    alternative_format=None, alternative_objective=None, product_mention_allowed=False,
    evidence=_EVIDENCE, confidence=0.95,
)


def _carousel_creative() -> InstagramCarouselCreative:
    """Five slides, grounded only in `_EVIDENCE`/`_SUMMARY` - no invented facts, no fake stats."""
    slides = [
        InstagramCarouselSlideCreative(
            role="hook",
            slide_copy=_APPROVED_COVER_HEADLINE,
            visual_direction="Полнокадровое использование одобренного B.2 сгенерированного изображения, без изменений композиции.",
            source_evidence=None,
            slide_purpose="Визуальный крючок обложки",
            media_need="источник/generated",
        ),
        InstagramCarouselSlideCreative(
            role="context",
            slide_copy="Разработчик на Хабре перестал всегда брать самую «умную» и дорогую модель для каждой задачи.",
            visual_direction="Светлое редакционное поле с вертикальной полосой изображения слева, как в остальной carousel-системе.",
            source_evidence=_EVIDENCE[0],
            slide_purpose="Минимальный факт для понимания истории",
            media_need=None,
        ),
        InstagramCarouselSlideCreative(
            role="comparison",
            slide_copy="Максимальный intelligence index vs стоимость выполненной задачи",
            visual_direction="Двухпанельное сравнение критериев без изображения, только типографика.",
            source_evidence=_EVIDENCE[1],
            slide_purpose="Центральный контраст статьи",
            media_need=None,
        ),
        InstagramCarouselSlideCreative(
            role="impact",
            slide_copy="Практический вывод: не переплачивать за максимальный интеллект там, где хватает более дешёвой и быстрой модели.",
            visual_direction="Тёмная карточка с приглушённым фоновым индексом слайда, без нового изображения.",
            source_evidence=_EVIDENCE[1],
            slide_purpose="Практическое значение для читателя",
            media_need=None,
        ),
        InstagramCarouselSlideCreative(
            role="takeaway",
            slide_copy="Разумный выбор модели - не самый мощный вариант, а тот, что решает задачу с наименьшими издержками.",
            visual_direction="Закрывающий красный фон системы, без нового изображения.",
            source_evidence=None,
            slide_purpose="Вывод, закрывающий тезис обложки",
            media_need=None,
        ),
    ]
    return InstagramCarouselCreative(
        objective="value",
        slides=slides,
        final_cta=None,
        evidence_used=_EVIDENCE,
        final_caption=(
            "Автор на Хабре пишет, что перестал выбирать самые умные ИИ-модели для каждой задачи. "
            "Вместо рейтинга интеллекта он смотрит на стоимость готового результата."
        ),
        creative_execution_plan=None,
    )


def _load_raw_image(raw_path_override: str | None) -> tuple[Image.Image, bytes, str]:
    if raw_path_override:
        data = Path(raw_path_override).read_bytes()
        ref = f"local_override:{raw_path_override}"
    else:
        storage = LocalImageStorage(settings.image_storage_root)
        data = storage.read(_RAW_STORAGE_KEY)
        ref = f"generated:{_RAW_STORAGE_KEY}"
    image = Image.open(io.BytesIO(data)).convert("RGB")
    return image, data, ref


def _build_contact_sheet(slide_images: list[Image.Image]) -> Image.Image:
    thumb_w = 360
    thumb_h = round(thumb_w * 1350 / 1080)
    gap = 16
    sheet_w = thumb_w * len(slide_images) + gap * (len(slide_images) + 1)
    sheet_h = thumb_h + gap * 2
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 20))
    for i, img in enumerate(slide_images):
        thumb = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        x = gap + i * (thumb_w + gap)
        sheet.paste(thumb, (x, gap))
    return sheet


def main() -> None:
    raw_override = sys.argv[1] if len(sys.argv) > 1 else None
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("artifacts/instagram_phase_b3_carousel_diagnostic_1/carousel")
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_image, raw_bytes, raw_ref = _load_raw_image(raw_override)

    carousel = _carousel_creative()
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(
            recommended_format=ContentFormat.CAROUSEL, why="История содержит контекст, контраст и вывод.",
            expected_role="culture", confidence=0.95,
        ),
        shadow_plan=_SP, creative_outcome=CreativeGenerationOutcome(carousel=carousel),
        account_key="ninja_pulse", source_image_ref=raw_ref,
    )
    package = replace(package, media_plan={
        **package.media_plan,
        "media_execution": {
            "strategy": "generated_media",
            "assets": [{
                # media_mode is deliberately omitted (not "GENERATED"): render_instagram_carousel
                # reads this same field to pick the per-slide render path, and forcing "GENERATED"
                # routes the hook slide through the generic _slide_media_base treatment, whose
                # `source_image_treatment="generated"` value the art validator's own allow-list does
                # not recognise (a narrow pre-existing gap, not something this diagnostic works
                # around by lying - the fields below already record the asset's true provenance).
                "asset_key": "0", "status": "generated_media",
                "asset_ref": raw_ref, "generation_execution_id": "instagram:phase-b2-diagnostic-b4-20260918-retry1:visual:primary:v2",
                "provider": "openai", "model": "gpt-image-2", "reused_from": "phase_b2_diagnostic",
            }],
        },
    })

    # Phase B.3 forensic fix: reuse the SAME real RAW asset across every slide (not just the hook)
    # now that COMPARISON/DETAIL/CLOSING can consume it as a dimmed/blurred background instead of
    # a synthetic fallback - real cross-slide visual continuity, still zero provider calls.
    results = render_instagram_carousel(package, slide_images={i: raw_image for i in range(5)})
    art = validate_instagram_art(package, results)
    gate = evaluate_instagram_editorial_gate(package, art)

    slide_images_decoded: list[Image.Image] = []
    manifest_slides = []
    slide_paths = []
    for i, result in enumerate(results):
        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
        assert img.size == (1080, 1350), f"slide {i} has wrong canvas size: {img.size}"
        slide_images_decoded.append(img)
        path = out_dir / f"slide_{i + 1:02d}.png"
        img.save(path, format="PNG")
        slide_paths.append(str(path))
        manifest_slides.append({
            "index": i,
            "file": path.name,
            "role": carousel.slides[i].role,
            "text": carousel.slides[i].slide_copy,
            "slide_purpose": carousel.slides[i].slide_purpose,
            "source_evidence": carousel.slides[i].source_evidence,
            "layout_variant": result.evidence.notes.get("layout_variant"),
            "content_identity": result.evidence.content_identity,
            "text_clipped": result.evidence.text_clipped,
            "visible_brand_mark_count": result.evidence.visible_brand_mark_count,
            "source_image_treatment": result.evidence.source_image_treatment,
        })

    contact_sheet = _build_contact_sheet(slide_images_decoded)
    contact_sheet_path = out_dir / "contact_sheet.png"
    contact_sheet.save(contact_sheet_path, format="PNG")

    manifest = {
        "carousel_id": _CAROUSEL_ID,
        "story_id": _STORY_ID,
        "source_url": _SOURCE_URL,
        "opportunity_id": _OPPORTUNITY_ID,
        "format": "carousel",
        "language": "ru",
        "total_slides": len(results),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": 1,
        "raw_asset_ref": raw_ref,
        "raw_asset_bytes_sha256": __import__("hashlib").sha256(raw_bytes).hexdigest(),
        "slides": manifest_slides,
        "package_id": package.package_id,
        "gate_decision": getattr(gate.decision, "value", str(gate.decision)),
        "art_validation": art.to_dict(),
        "provider_image_calls": 0,
        "incremental_image_cost_usd": "0",
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": "CAROUSEL_RENDERED",
        "carousel_id": _CAROUSEL_ID,
        "slide_count": len(results),
        "slide_paths": slide_paths,
        "manifest_path": str(manifest_path),
        "contact_sheet_path": str(contact_sheet_path),
        "art_passed": art.passed,
        "art_blocking_issues": art.blocking_issues,
        "art_warnings": art.warnings,
        "gate_decision": getattr(gate.decision, "value", str(gate.decision)),
        "provider_image_calls": 0,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
