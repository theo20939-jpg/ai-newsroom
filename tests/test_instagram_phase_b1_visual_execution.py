from dataclasses import replace

from PIL import Image

from schemas.instagram_creative import (
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
    InstagramCreativeExecutionPlan,
    InstagramReelCreative,
    InstagramSingleCreative,
)
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import (
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
)
from services.instagram_shadow_pipeline import ShadowPlanResult


_OPP = ContentOpportunity(
    id="phase-b1-opp", source_type=OpportunitySourceType.NEWS,
    story_id="phase-b1-story", product_mention_allowed=True,
)
_SHADOW = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS",
    primary_objective="VALUE", audience_description="", recommended_format="single",
    hook_family=None, creative_concept_summary="concept", alternative_format=None,
    alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.9,
)
_SOURCE = Image.new("RGB", (1200, 800), (25, 70, 130))


def _plan(*, media_strategy: str, composition: str, treatment: str) -> InstagramCreativeExecutionPlan:
    return InstagramCreativeExecutionPlan(
        main_idea="Одна ясная визуальная идея",
        focal_point="Главный объект",
        media_strategy=media_strategy,
        media_rationale="Лучший материал для истории",
        composition_direction=composition,
        branding_treatment="Канонический знак",
        visual_treatment=treatment,
        avoid_recent_treatment="Не повторять темную карточку",
    )


def test_phase_b1_single_hero_plan_changes_pixel_geometry_and_trace() -> None:
    creative = InstagramSingleCreative(
        creative_angle="путь к точке L2", visual_concept="космический герой",
        on_image_copy="Телескоп увидел точку L2", caption_direction="готовая подпись",
        final_caption="Телескоп продолжает путь.", source_subject="NASA",
        creative_execution_plan=_plan(
            media_strategy="source_media",
            composition="Полный кадр, короткий заголовок, много воздуха",
            treatment="Cinematic space hero",
        ),
    )
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=_SHADOW, creative_outcome=CreativeGenerationOutcome(single=creative),
        source_image_ref="nasa-source",
    )
    result = render_instagram_feed_image(package, source_image=_SOURCE)
    notes = result.evidence.notes
    assert notes["layout_variant"] == "news_full_bleed"
    assert notes["source_coverage_fraction"] == 1.0
    assert notes["render_interpretation"] == "editorial_hero"
    assert "full_bleed_image" in notes["used_primitives"]
    assert notes["internal_labels_rendered"] == []
    assert "VALUE" not in notes["rendered_copy"]
    assert "Телескоп" in notes["rendered_copy"][0]
    assert validate_instagram_art(package, [result]).passed


def test_phase_b1_typographic_plan_does_not_render_internal_value_label() -> None:
    creative = InstagramSingleCreative(
        creative_angle="культура", visual_concept="типографический знак",
        on_image_copy="Онлайн ≠ близость", caption_direction="готовая подпись",
        final_caption="Связь измеряется не онлайном.",
        creative_execution_plan=_plan(
            media_strategy="typographic", composition="Один крупный знак и короткая фраза",
            treatment="Premium minimal typography",
        ),
    )
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=_SHADOW, creative_outcome=CreativeGenerationOutcome(single=creative),
    )
    result = render_instagram_feed_image(package)
    assert result.evidence.notes["layout_variant"] == "news_typographic_focal"
    assert result.evidence.notes["internal_labels_rendered"] == []
    assert "VALUE" not in result.evidence.notes["rendered_copy"]
    assert validate_instagram_art(package, [result]).passed


def test_phase_b1_carousel_roles_become_distinct_compositions_without_internal_labels() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Google открывает дверь GrapheneOS", visual_direction="Pixel крупным планом", slide_purpose="зацепить", media_need="hero"),
        InstagramCarouselSlideCreative(role="context", slide_copy="Разговор начался с поддержки устройств", visual_direction="Фото становится боковой полосой", slide_purpose="дать контекст", media_need="source"),
        InstagramCarouselSlideCreative(role="problem", slide_copy="Но открытый код без доступа к железу не решает проблему", visual_direction="разрыв и конфликт", slide_purpose="показать конфликт", media_need="graphic"),
        InstagramCarouselSlideCreative(role="explanation", slide_copy="Теперь путь обновлений может стать короче", visual_direction="«КОД → API → ОБНОВЛЕНИЯ»", slide_purpose="объяснить механизм", media_need="diagram"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Открытость проверяется не обещаниями, а доступом", visual_direction="светлый финал", slide_purpose="вывод", media_need="typographic"),
    ]
    creative = InstagramCarouselCreative(
        objective="saves", slides=slides, final_caption="Что меняется для GrapheneOS.",
        creative_execution_plan=_plan(
            media_strategy="source_media",
            composition="Фото на обложке, затем контекст, конфликт, схема и чистый вывод",
            treatment="Tech editorial с меняющейся плотностью",
        ),
    )
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL),
        shadow_plan=_SHADOW, creative_outcome=CreativeGenerationOutcome(carousel=creative),
        source_image_ref="graphene-source",
    )
    results = render_instagram_carousel(package, hero_image=_SOURCE)
    assert len(package.media_plan["render_trace"]["assets"]) == 5
    variants = [result.evidence.notes["layout_variant"] for result in results]
    assert len(set(variants)) >= 4  # distinct light compositions, incl. the mechanism diagram
    assert "generic_flow_diagram" in variants
    assert results[1].evidence.source_image_treatment == "cover_cropped"
    assert all(result.evidence.notes["internal_labels_rendered"] == [] for result in results)
    assert all(result.evidence.notes["render_plan_applied"] for result in results)
    assert results[3].evidence.notes["mechanism_tokens"] == ["КОД", "API", "ОБНОВЛЕНИЯ"]
    assert all(result.evidence.notes["overlay_operations_executed"] == 0 for result in results)
    assert validate_instagram_art(package, results).passed


def test_phase_b1_reel_source_typography_is_cropped_and_recomposed() -> None:
    creative = InstagramReelCreative(
        objective="reach", hook="Ремастер без перерисовки каждого кадра",
        target_duration_seconds=18, scene_sequence=["до", "после"], pacing="быстро",
        caption_direction="готовая подпись", final_caption="Нейросеть меняет старую графику.",
        creative_execution_plan=_plan(
            media_strategy="source_media",
            composition="Центральная обложка, split-screen детали",
            treatment="Game-tech transformation",
        ),
    )
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.REEL),
        shadow_plan=_SHADOW, creative_outcome=CreativeGenerationOutcome(reel=creative),
        source_image_ref="game-screenshot",
    )
    result = render_instagram_reel_cover(package, source_image=_SOURCE)
    notes = result.evidence.notes
    assert notes["layout_variant"] == "reel_recomposed_source"
    assert notes["embedded_text_conflict_risk"] is True
    assert notes["embedded_text_strategy"] == "crop_top_22pct_blur_background_masked_detail"
    assert "masked_source_crop" in notes["used_primitives"]
    assert validate_instagram_art(package, [result]).passed


def test_phase_b1_validator_blocks_missing_plan_trace_and_internal_label() -> None:
    creative = InstagramSingleCreative(
        creative_angle="a", visual_concept="v", on_image_copy="Русский заголовок",
        caption_direction="подпись", final_caption="Финальная подпись.",
        creative_execution_plan=_plan(
            media_strategy="source_media", composition="full bleed hero",
            treatment="cinematic",
        ),
    )
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=_SHADOW, creative_outcome=CreativeGenerationOutcome(single=creative),
        source_image_ref="source",
    )
    result = render_instagram_feed_image(package, source_image=_SOURCE)
    broken_notes = dict(result.evidence.notes)
    broken_notes.pop("used_primitives")
    broken_notes["internal_labels_rendered"] = ["VALUE"]
    broken = replace(result, evidence=replace(result.evidence, notes=broken_notes))
    art = validate_instagram_art(package, [broken])
    assert not art.passed
    assert any("creative_plan_not_applied" in issue for issue in art.blocking_issues)
    assert any("internal_render_label_leaked" in issue for issue in art.blocking_issues)
