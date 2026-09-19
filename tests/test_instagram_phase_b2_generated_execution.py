from dataclasses import replace
from decimal import Decimal
from io import BytesIO

from PIL import Image, ImageDraw
from pydantic import SecretStr
import pytest

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import (
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
    InstagramCreativeExecutionPlan,
    InstagramSingleCreative,
)
from services.budgeted_image_execution import BudgetedImageResult
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel, render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
import services.instagram_creative_media as media


def _png() -> bytes:
    image = Image.new("RGB", (1024, 1536), (35, 72, 145))
    draw = ImageDraw.Draw(image)
    draw.ellipse((110, 180, 820, 890), fill=(240, 167, 60))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _plan(strategy: str) -> InstagramCreativeExecutionPlan:
    return InstagramCreativeExecutionPlan(
        main_idea="Показать выбор между максимальным интеллектом и практической пользой",
        focal_point="Контраст двух неравных систем",
        media_strategy=strategy,
        media_rationale="Концептуальный сюжет лучше стоковой иллюстрации",
        composition_direction="Асимметричная сцена с сильным объектом слева и воздухом справа",
        branding_treatment="Только канонический знак из репозитория",
        visual_treatment="Современная редакционная метафора с материальной глубиной",
        avoid_recent_treatment="Без темной карточки и интерфейсных клише",
    )


def _single(strategy: str = "generated_media") -> InstagramSingleCreative:
    return InstagramSingleCreative(
        creative_angle="Полезность важнее рейтинга",
        visual_concept="Материальная метафора выбора",
        on_image_copy="Самая умная модель ≠ самая полезная",
        caption_direction="Короткая редакционная подпись",
        final_caption="Выбирать стоит по результату задачи.",
        source_subject="выбор модели",
        creative_execution_plan=_plan(strategy),
    )


def _context():
    opportunity = ContentOpportunity(
        id="phase-b2-opportunity",
        source_type=OpportunitySourceType.NEWS,
        story_id="phase-b2-story",
    )
    shadow = ShadowPlanResult(
        campaign_name=None,
        campaign_phase=None,
        opportunity_description="выбор модели",
        primary_objective="VALUE",
        audience_description="",
        recommended_format="carousel",
        hook_family=None,
        creative_concept_summary="метафора выбора",
        alternative_format=None,
        alternative_objective=None,
        product_mention_allowed=False,
        evidence=[],
        confidence=0.9,
    )
    return opportunity, shadow


class _Executor:
    def __init__(self, calls: list[dict]):
        self.calls = calls

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return BudgetedImageResult(
            status="generated",
            response=ImageGenerationResponse(
                image_bytes=_png(),
                provider="openai",
                model_used="gpt-image-2",
                usage=CapabilityUsage(
                    input_tokens=140,
                    output_tokens=2733,
                    units=1,
                    unit_type="image",
                ),
                request_id="openai-request-phase-b2",
            ),
            accounted_cost_usd=Decimal("0.04310"),
            cost_semantics="configured_token_estimate",
            attempt=1,
        )


@pytest.mark.asyncio
async def test_generated_media_reaches_boundary_and_persists_raw_asset(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: _Executor(calls))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))

    result = await media.execute_instagram_creative_media(
        creative=_single(),
        source_image=None,
        source_ref=None,
        opportunity_summary="Почему полезная модель не обязана быть самой умной",
        evidence=["Автор сравнивает стоимость выполненной задачи."],
        content_format="single",
        creative_id="diagnostic-b4-v1",
        opportunity_id="phase-b2-opportunity",
        mode="live",
    )

    assert len(calls) == 1
    assert calls[0]["max_attempts"] == 1
    assert calls[0]["purpose"] == "instagram_phase_b2"
    assert calls[0]["execution_id"] == "instagram:diagnostic-b4-v1:visual:primary:v2"
    asset = result.assets[0]
    assert result.status == "generated_media"
    assert asset.raw_image_bytes == _png()
    assert asset.generated_asset_ref and asset.generated_asset_ref.startswith("generated:images/")
    assert asset.prompt_sha256
    assert "COMPOSITION" in asset.prompt
    assert "FOCAL SUBJECT" in asset.prompt
    assert "REFERENCE-BOARD PRINCIPLES" in asset.prompt
    assert "NO LOGOS" in asset.prompt
    storage_key = asset.generated_asset_ref.removeprefix("generated:")
    assert (tmp_path / storage_key).read_bytes() == _png()


@pytest.mark.asyncio
async def test_source_graphic_and_typographic_assets_never_call_paid_provider(monkeypatch):
    monkeypatch.setattr(
        media,
        "build_budgeted_image_executor",
        lambda: pytest.fail("non-generated media reached paid boundary"),
    )
    source = Image.new("RGB", (1024, 1536), "navy")
    for strategy in ("source_media", "typographic"):
        result = await media.execute_instagram_creative_media(
            creative=_single(strategy),
            source_image=source if strategy == "source_media" else None,
            source_ref="source-asset" if strategy == "source_media" else None,
            opportunity_summary="story",
            evidence=["fact"],
            content_format="single",
            creative_id=f"creative-{strategy}",
            opportunity_id="opp",
            mode="live",
        )
        assert result.assets[0].provider is None

    graphic_carousel = InstagramCarouselCreative(
        objective="VALUE",
        slides=[
            InstagramCarouselSlideCreative(
                role="hook", slide_copy="Схема вместо изображения",
                visual_direction="Графическая система", slide_purpose="объяснить",
                media_need="GRAPHIC diagram",
            ),
            InstagramCarouselSlideCreative(
                role="takeaway", slide_copy="Чистый вывод",
                visual_direction="Типографика", slide_purpose="закончить",
                media_need="TYPOGRAPHIC",
            ),
        ],
        final_caption="Графика и типографика без платного вызова.",
        creative_execution_plan=_plan("typographic"),
    )
    graphic_result = await media.execute_instagram_creative_media(
        creative=graphic_carousel, source_image=None, source_ref=None,
        opportunity_summary="story", evidence=["fact"], content_format="carousel",
        creative_id="creative-graphic", opportunity_id="opp", mode="live",
    )
    assert [asset.media_mode.value for asset in graphic_result.assets] == [
        "GRAPHIC", "TYPOGRAPHIC",
    ]


@pytest.mark.asyncio
async def test_carousel_executes_media_per_slide_and_generated_pixels_reach_compositor(
    monkeypatch, tmp_path,
):
    calls: list[dict] = []
    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: _Executor(calls))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="Одна идея меняет выбор",
            visual_direction="Оригинальная редакционная метафора",
            slide_purpose="остановить скролл", media_need="GENERATED original visual",
        ),
        InstagramCarouselSlideCreative(
            role="context", slide_copy="Источник остается фактической опорой",
            visual_direction="Документальный кадр", slide_purpose="дать контекст",
            media_need="SOURCE photo",
        ),
        InstagramCarouselSlideCreative(
            role="explanation", slide_copy="Схема объясняет механизм",
            visual_direction="КОД → РЕШЕНИЕ → ЦЕННОСТЬ", slide_purpose="объяснить",
            media_need="GRAPHIC diagram",
        ),
        InstagramCarouselSlideCreative(
            role="takeaway", slide_copy="Полезность измеряется результатом",
            visual_direction="Чистый вывод", slide_purpose="оставить мысль",
            media_need="TYPOGRAPHIC",
        ),
    ]
    creative = InstagramCarouselCreative(
        objective="VALUE", slides=slides, final_caption="Четыре разных визуальных шага.",
        creative_execution_plan=_plan("generated_media"),
    )
    source = Image.new("RGB", (1200, 900), (30, 110, 80))
    result = await media.execute_instagram_creative_media(
        creative=creative, source_image=source, source_ref="source-1",
        opportunity_summary="Как выбрать полезную модель", evidence=["Подтвержденный факт"],
        content_format="carousel", creative_id="carousel-v1",
        opportunity_id="phase-b2-opportunity", mode="live",
    )
    assert [asset.media_mode.value for asset in result.assets] == [
        "GENERATED", "SOURCE", "GRAPHIC", "TYPOGRAPHIC",
    ]
    assert len(calls) == 1
    assert set(result.slide_images()) == {0, 1}

    opportunity, shadow = _context()
    package = build_instagram_content_package(
        opportunity=opportunity,
        format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL),
        shadow_plan=shadow,
        creative_outcome=CreativeGenerationOutcome(carousel=creative),
        source_image_ref=result.media_ref,
        media_candidate_id="source-row",
    )
    package = replace(package, media_plan={
        **package.media_plan,
        "media_execution": result.execution_metadata(),
    })
    renders = render_instagram_carousel(package, slide_images=result.slide_images())
    # Phase B.3.1: the old "generated" literal (a value the art validator's own allow-list never
    # actually recognised - a real pre-existing gap found in the Phase B.3 forensic trace) is gone;
    # a GENERATED hook slide now goes through its own dedicated, validator-safe FULL_BLEED
    # treatment like any other real image, not a separate "generated" special case.
    assert renders[0].evidence.source_image_treatment in ("cover_cropped", "contain_preserved")
    assert renders[0].evidence.notes["media_primitive_selected"] == "source_full_bleed"
    assert renders[1].evidence.notes["per_slide_media_consumed"] is True
    assert renders[2].evidence.notes["per_slide_media_consumed"] is False
    assert renders[3].evidence.notes["per_slide_media_consumed"] is False
    assert renders[0].evidence.visible_brand_mark_count == 1
    assert "Одна идея" in renders[0].evidence.notes["rendered_copy"][0]
    assert renders[0].image_bytes != result.assets[0].raw_image_bytes


@pytest.mark.asyncio
async def test_generated_base_receives_exact_russian_copy_and_current_brand(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: _Executor(calls))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    creative = _single()
    result = await media.execute_instagram_creative_media(
        creative=creative, source_image=None, source_ref=None,
        opportunity_summary="Полезность модели", evidence=["Факт"], content_format="single",
        creative_id="single-v1", opportunity_id="phase-b2-opportunity", mode="live",
    )
    opportunity, shadow = _context()
    package = build_instagram_content_package(
        opportunity=opportunity,
        format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=replace(shadow, recommended_format="single"),
        creative_outcome=CreativeGenerationOutcome(single=creative),
        source_image_ref=result.media_ref,
    )
    package = replace(package, media_plan={
        **package.media_plan,
        "media_execution": result.execution_metadata(),
    })
    rendered = render_instagram_feed_image(package, source_image=result.image)
    assert rendered.evidence.visible_brand_mark_count == 1
    assert rendered.evidence.source_image_treatment != "none"
    assert "Самая умная модель" in rendered.evidence.notes["rendered_copy"][0]
    assert result.assets[0].prompt and "NO OUTDATED NNJ/NINJA BRANDING" in result.assets[0].prompt
