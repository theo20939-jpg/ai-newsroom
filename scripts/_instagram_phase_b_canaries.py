"""Manual-only Phase B canaries: four real stories, zero paid image calls."""
from __future__ import annotations
import asyncio
import json
import os
from dataclasses import replace
from io import BytesIO
from uuid import UUID
from PIL import Image
from sqlalchemy import select
from bot.loader import create_bot
from core.config import settings
from database.models.instagram_editorial_delivery import InstagramEditorialDelivery, InstagramEditorialDeliveryState
from database.session import async_session_factory
from integrations.storage.image_storage import LocalImageStorage
from schemas.instagram_creative import (
    InstagramCarouselCreative, InstagramCarouselSlideCreative,
    InstagramCreativeExecutionPlan, InstagramReelCreative,
    InstagramReelSceneCreative, InstagramSingleCreative,
)
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeDirectorInput, CreativeGenerationOutcome
from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService, compute_package_identity
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_editorial_package_snapshot import build_package_snapshot
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import (
    render_instagram_carousel, render_instagram_feed_image, render_instagram_reel_cover,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import deliver_instagram_package, deliver_new_version, instagram_topic_configured
from services.instagram_telegram_package_presenter import present_carousel, present_reel, present_single

_STORAGE = LocalImageStorage(settings.image_storage_root)


def plan(idea, focal, strategy, rationale, composition, treatment, avoid):
    return InstagramCreativeExecutionPlan(
        main_idea=idea, focal_point=focal, media_strategy=strategy,
        media_rationale=rationale, composition_direction=composition,
        branding_treatment="Только канонический знак NINJA из репозитория.",
        visual_treatment=treatment, avoid_recent_treatment=avoid,
    )


def source_image(storage_key):
    if storage_key is None:
        return None
    with Image.open(BytesIO(_STORAGE.read(storage_key))) as image:
        return image.convert("RGB")


def opportunity(spec):
    return ContentOpportunity(
        id=f"phase-b-{spec['key']}-{spec['story_id']}",
        source_type=OpportunitySourceType.NEWS, story_id=spec["story_id"],
        news_value=.9, audience_relevance=.9, evidence=spec["evidence"], confidence=.95,
        editorial_decision={
            "opportunity_type": spec["type"], "angle": spec["angle"],
            "angle_intent": spec["intent"], "audience_value": spec["value"],
            "recommended_format": spec["fmt"].value,
            "format_reason": "Формат выбран под идею, а не по ротации шаблонов.",
            "purpose": "VALUE", "origin": "NEWS", "topic": spec["angle"],
            "why_now": "Свежий материал из production Newsroom.",
            "creative_direction": "Instagram-композиция с короткой иерархичной подачей.",
        },
    )


async def deliver(bot, spec):
    creative, fmt = spec["creative"], spec["fmt"]
    media_plan = creative.creative_execution_plan
    assert media_plan is not None and media_plan.media_strategy != "generated_media"
    opp = opportunity(spec)
    creative_outcome = CreativeGenerationOutcome(
        single=creative if fmt is ContentFormat.SINGLE else None,
        carousel=creative if fmt is ContentFormat.CAROUSEL else None,
        reel=creative if fmt is ContentFormat.REEL else None,
    )
    shadow = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description=spec["angle"],
        primary_objective="value", audience_description=spec["audience"],
        recommended_format=fmt.value, hook_family=None,
        creative_concept_summary=media_plan.main_idea, alternative_format=None,
        alternative_objective=None, product_mention_allowed=False,
        evidence=spec["evidence"], confidence=.95,
    )
    decision = FormatDecision(
        recommended_format=fmt, why=opp.editorial_decision["format_reason"],
        expected_role=spec["type"].lower(), confidence=.95,
    )
    package = build_instagram_content_package(
        opportunity=opp, format_decision=decision, shadow_plan=shadow,
        creative_outcome=creative_outcome, account_key="ninja_pulse",
        source_image_ref=spec["candidate_id"], media_candidate_id=spec["image_row_id"],
        reel_script_readiness=spec.get("reel_readiness"),
    )
    package = replace(package, media_plan={
        **package.media_plan,
        "media_execution": {
            "strategy": media_plan.media_strategy,
            "status": "source_media" if spec["storage_key"] else "typographic",
            "generation_cost_usd": None, "generation_request_id": None,
        },
    })
    image = source_image(spec["storage_key"])
    remediation = os.getenv("INSTAGRAM_PHASE_B1_REMEDIATION") == "1"
    presentation_version = 2 if remediation else 1
    if fmt is ContentFormat.CAROUSEL:
        renders = render_instagram_carousel(package, hero_image=image)
        presentation = present_carousel(package, renders, version=presentation_version)
    elif fmt is ContentFormat.REEL:
        renders = [render_instagram_reel_cover(package, source_image=image)]
        presentation = present_reel(package, renders[0], version=presentation_version)
    else:
        renders = [render_instagram_feed_image(package, source_image=image)]
        presentation = present_single(package, renders[0], version=presentation_version)
    art = validate_instagram_art(package, renders)
    gate = evaluate_instagram_editorial_gate(package, art)
    if gate.decision is not InstagramGateDecision.READY_FOR_EDITOR:
        raise RuntimeError(f"{spec['key']} gate={gate.decision.value} issues={art.blocking_issues} reasons={gate.reason_codes}")
    director_input = CreativeDirectorInput(
        objective="value", format=fmt.value, opportunity_summary=spec["angle"],
        allowed_evidence=spec["evidence"], audience_summary=spec["audience"],
        locale="ru", external_news_entities_allowed=True,
        editorial_decision=json.dumps(opp.editorial_decision, ensure_ascii=False),
    )
    snapshot = build_package_snapshot(
        package=package, opportunity=opp, format_decision=decision, shadow_plan=shadow,
        director_input=director_input, previous_creative=creative, source_url=spec["url"],
    )
    identity = compute_package_identity(
        source_key=f"instagram-phase-b-{spec['key']}:{spec['story_id']}",
        content_format=fmt.value,
    )
    async with async_session_factory() as session:
        if remediation:
            current = (await session.execute(
                select(InstagramEditorialDelivery).where(
                    InstagramEditorialDelivery.package_identity == identity,
                    InstagramEditorialDelivery.state != InstagramEditorialDeliveryState.SUPERSEDED,
                ).order_by(InstagramEditorialDelivery.version.desc())
            )).scalars().first()
            if current is None or current.version != 1:
                raise RuntimeError(
                    f"{spec['key']} remediation requires exactly current version 1; "
                    f"found {None if current is None else current.version}"
                )
            snapshot["phase_b1_remediation"] = {
                "renderer_revision": "instagram-render-v2",
                "replaces_media_message_ids": list(current.media_message_ids or []),
                "replaces_control_message_id": current.control_message_id,
            }
            new_delivery = await InstagramEditorialDeliveryService().create_new_version(
                session, previous=current, package_snapshot=snapshot,
            )
            result = await deliver_new_version(
                bot, session, delivery=new_delivery, presentation=presentation, source_url=spec["url"],
            )
        else:
            result = await deliver_instagram_package(
                bot, session, presentation=presentation, gate_decision=gate.decision,
                package_identity=identity, source_story_id=spec["story_id"],
                content_format=fmt.value, package_snapshot=snapshot, source_url=spec["url"],
            )
        await session.commit()
        row = (await session.execute(select(InstagramEditorialDelivery).where(
            InstagramEditorialDelivery.id == UUID(result.delivery_id)
        ))).scalar_one()
    return {
        "key": spec["key"], "source_story_id": spec["story_id"],
        "opportunity_id": opp.id, "format": fmt.value, "opportunity_type": spec["type"],
        "angle": spec["angle"], "audience_value": spec["value"],
        "creative_plan": media_plan.model_dump(), "source_vs_ai": media_plan.media_strategy,
        "final_caption": package.caption, "slide_count": package.slide_count,
        "slides": package.media_plan.get("slides"),
        "reel": ({
            "hook": package.media_plan.get("hook"),
            "duration": package.media_plan.get("target_duration_seconds"),
            "scenes": package.media_plan.get("scenes"),
            "voiceover_script": package.media_plan.get("voiceover_script"),
            "on_screen_text": package.media_plan.get("on_screen_text"),
            "visual_direction": package.media_plan.get("visual_direction"),
        } if fmt is ContentFormat.REEL else None),
        "render_variants": [r.evidence.notes.get("layout_variant") for r in renders],
        "qa": {"passed": art.passed, "warnings": art.warnings, "gate": gate.decision.value},
        "delivery": {
            "sent": result.sent, "reason": result.reason, "delivery_id": result.delivery_id,
            "version": result.version, "media_message_ids": row.media_message_ids,
            "control_message_id": row.control_message_id,
            "telegram_chat_id": row.telegram_chat_id, "telegram_topic_id": row.telegram_topic_id,
        },
    }


E1 = [
    "Android 17 QPR1 принёс новые функции устройствам Pixel.",
    "GrapheneOS заявила об ограничении части API и задержке обновлений безопасности для AOSP.",
]
B1 = InstagramCarouselCreative(
    objective="Объяснить конфликт Google и GrapheneOS.",
    slides=[
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="Android становится разным",
            visual_direction="Полноэкранный исходный кадр и крупный короткий тезис.",
            source_evidence=E1[1], slide_purpose="Остановить скролл и обозначить конфликт.",
            media_need="Исходное изображение GrapheneOS/Android.",
        ),
        InstagramCarouselSlideCreative(
            role="context", slide_copy="Android 17 QPR1 принёс новые функции устройствам Pixel",
            visual_direction="Спокойный контекстный слайд с большим воздухом.",
            source_evidence=E1[0], slide_purpose="Дать исходную точку новости.",
            media_need="Типографика внутри общей арт-дирекции.",
        ),
        InstagramCarouselSlideCreative(
            role="problem", slide_copy="GrapheneOS: часть API закрыта, а патчи приходят позже",
            visual_direction="Плотный редакционный слайд с визуальным разрывом.",
            source_evidence=E1[1], slide_purpose="Сформулировать претензию проекта.",
            media_need="Типографика и графический акцент.",
        ),
        InstagramCarouselSlideCreative(
            role="explanation", slide_copy="Открытый код не гарантирует AOSP-проектам равный доступ к функциям",
            visual_direction="Схема «код → API → обновления» без выдуманного интерфейса.",
            source_evidence=E1[1], slide_purpose="Перевести спор в понятное последствие.",
            media_need="Графическая типографика.",
        ),
        InstagramCarouselSlideCreative(
            role="takeaway", slide_copy="Открытая платформа — это ещё и равные правила обновлений",
            visual_direction="Чистый финальный тезис с новым ритмом.",
            source_evidence=E1[1], slide_purpose="Оставить ясный вывод.",
            media_need="Минимальная типографика.",
        ),
    ],
    final_caption=(
        "Android 17 QPR1 добрался до Pixel, но для GrapheneOS новость оказалась не только про функции. "
        "Проект утверждает, что часть API остаётся закрытой, а обновления безопасности для AOSP приходят позже.\n\n"
        "Спор об «открытом Android» теперь касается не только кода, но и равных правил игры."
    ),
    evidence_used=E1,
    creative_execution_plan=plan(
        "Разложить технический конфликт на пять последовательных визуальных ударов.",
        "Разрыв между Pixel и AOSP", "source_media",
        "Реальное изображение привязывает объяснение к конкретной экосистеме.",
        "Фото на обложке; далее контекст, конфликт, объяснение и чистый вывод.",
        "Tech editorial с меняющейся плотностью", "Не повторять один тёмный макет.",
    ),
)

E2 = [
    "Телескоп Nancy Grace Roman запущен 30 августа и летит к L2 около трёх месяцев.",
    "L2 находится примерно в 1,5 млн км от Земли.",
    "Первые научные снимки ожидаются в начале 2027 года после калибровки.",
]
B2 = InstagramSingleCreative(
    creative_angle="Путь телескопа как один кинематографичный момент без ложного обещания снимка.",
    visual_concept="Космический hero visual с минимальным текстом.",
    on_image_copy="Roman уже в пути к L2",
    caption_direction="Короткий апдейт о включении телескопа.",
    final_caption=(
        "Телескоп Roman уже в пути к точке L2 — примерно в 1,5 млн км от Земли. Инженеры NASA начали "
        "включать его бортовое оборудование, а перелёт займёт около трёх месяцев.\n\n"
        "Первые научные снимки ждём в начале 2027 года: сначала — долгая калибровка."
    ),
    source_subject="телескоп Roman", evidence_used=E2,
    creative_execution_plan=plan(
        "Один сильный космический кадр вместо перегруженной карточки.",
        "Телескоп на фоне космоса", "source_media",
        "Снимок NASA даёт подлинность и масштаб.",
        "Полный кадр, короткий заголовок, много воздуха.",
        "Cinematic space hero", "Не использовать коллаж.",
    ),
)

E3 = [
    "Разработчик coye2 создаёт Uncanny для автоматических ремастеров старых игр.",
    "Проект опирается на нейронный рендеринг.",
]
SCENES = [
    InstagramReelSceneCreative(
        start_seconds=0, end_seconds=4,
        spoken_line="Старые игры смогут выглядеть по-новому прямо во время запуска.",
        on_screen_text="Ремастер на лету?",
        visual_direction="Исходный игровой кадр, затем мгновенный split-screen.",
    ),
    InstagramReelSceneCreative(
        start_seconds=4, end_seconds=9,
        spoken_line="В основе Uncanny — нейронный рендеринг. Проект делает разработчик coye2.",
        on_screen_text="Uncanny + нейронный рендеринг",
        visual_direction="Показать исходный кадр и преобразование как процесс.",
    ),
    InstagramReelSceneCreative(
        start_seconds=9, end_seconds=14,
        spoken_line="Идея — автоматически переосмысливать графику старых игр без ручной переделки каждой сцены.",
        on_screen_text="Сцена меняется автоматически",
        visual_direction="Быстрая последовательность деталей окружения.",
    ),
    InstagramReelSceneCreative(
        start_seconds=14, end_seconds=18,
        spoken_line="Пока это проект разработчика. Но сам подход уже меняет представление о ремастерах.",
        on_screen_text="Пока проект — уже новый подход",
        visual_direction="Вернуться к первому кадру и замкнуть петлю.",
    ),
]
B3 = InstagramReelCreative(
    objective="Объяснить технологическую идею за 18 секунд.",
    hook="Ремастеры игр — прямо на лету?", target_duration_seconds=18,
    scene_sequence=["Хук", "Как работает", "Что меняется", "Оговорка"],
    shot_list=["Игровой кадр", "До/после", "Детали", "Возврат к началу"],
    voiceover_script=" ".join(s.spoken_line for s in SCENES),
    on_screen_text=[s.on_screen_text or "" for s in SCENES],
    b_roll_requirements=["Исходные кадры Uncanny"], pacing="Быстро, с паузой на оговорке.",
    audio_direction="Оригинальный технологичный ритм; без заявления о трендовом аудио.",
    loop_ending_concept="Финальный кадр совпадает с первым split-screen.",
    caption_direction="Объяснить проект без обещания готового продукта.",
    final_caption=(
        "Нейронный рендеринг добрался до старых игр: разработчик coye2 создаёт Uncanny — движок, "
        "который должен обновлять графику прямо во время запуска.\n\n"
        "Пока это проект, а не готовая функция для всех. Но идея ремастера «на лету» уже выглядит убедительно."
    ),
    source_subject="нейронный рендеринг", evidence_used=E3,
    visual_direction="Вертикальная игровая сцена; split-screen как мотив.",
    asset_requirements=["Исходное изображение Uncanny"], scenes=SCENES,
    creative_execution_plan=plan(
        "Показать превращение старой игры в ремастер как визуальную петлю.",
        "Контраст исходной и обновлённой сцены", "source_media",
        "Кадр реального проекта важнее абстрактной AI-иллюстрации.",
        "Center-safe cover; split-screen, детали, возврат.",
        "Game-tech transformation", "Не имитировать Instagram-тренд.",
    ),
)

E4 = [
    "Автор на Хабре описал переход от самых умных и дорогих моделей к более дешёвым.",
    "Главным критерием он выбрал стоимость выполненной задачи, а не максимальный intelligence index.",
]
B4 = InstagramSingleCreative(
    creative_angle="Максимум интеллекта модели не всегда даёт лучший результат на задачу.",
    visual_concept="Смелая типографическая заметка без стокового робота.",
    on_image_copy="Самая умная модель ≠ самая полезная",
    caption_direction="Разговорно пересказать личный опыт автора.",
    final_caption=(
        "Автор на Хабре пишет, что перестал выбирать самые умные ИИ-модели для каждой задачи. "
        "Вместо рейтинга интеллекта он смотрит на стоимость готового результата.\n\n"
        "Иногда хорошо поставленная задача и более лёгкая модель выигрывают у режима «включить максимум»."
    ),
    source_subject="самые умные ИИ-модели", evidence_used=E4,
    creative_execution_plan=plan(
        "Превратить знакомую разработчикам дилемму в один цитируемый тезис.",
        "Знак «≠» между умной и полезной моделью", "typographic",
        "Здесь важна мысль; стоковый AI-визуал сделал бы её банальнее.",
        "Крупная асимметричная типографика и свободные поля.",
        "Internet culture / typographic note",
        "Без роботов, неона и принудительного вопроса.",
    ),
)

SPECS = [
    dict(key="B1", story_id="aab615ec-1986-41ec-bcf4-f74116c82205", url="https://3dnews.ru/1148638",
         fmt=ContentFormat.CAROUSEL, creative=B1, evidence=E1, type="NEWS", intent="EXPLAINER",
         angle="Что спор Google и GrapheneOS говорит об открытости Android",
         value="Понять последствия закрытых API и задержки патчей.", audience="Аудитория Android и приватности.",
         storage_key="images/f8/f8f12c8896a2e287d6f836842e2b14feadcdb097fcf27a010f96aa8ca1ccae9c.jpg",
         candidate_id="ff9271f74d111ff92edb51a29706d8318bee1eb8983ecea5dacdca173ff6f571",
         image_row_id="fa596d6d-804b-4909-8723-d3e3d36514da"),
    dict(key="B2", story_id="bcaea42c-4212-4694-bc34-4559516ad75e", url="https://3dnews.ru/1148612",
         fmt=ContentFormat.SINGLE, creative=B2, evidence=E2, type="NEWS", intent="IMPACT",
         angle="Roman начал путь к L2: что происходит до первых научных снимков",
         value="Увидеть масштаб миссии и ближайшие этапы.", audience="Широкая технологическая аудитория.",
         storage_key="images/e2/e21486b35809ccd2f683de7a38bf473cddef3f7a3f18c91d8147fad314eca594.jpg",
         candidate_id="6db0be67617c13ef1bda8a5d6f07b0a32ad77cec10319600b0b372e6cd36cf6f",
         image_row_id="e5040258-f1f8-456d-a90f-c6aa7e58b273"),
    dict(key="B3", story_id="8426126e-6bca-43fd-ba8a-9b6538b01105",
         url="https://www.ixbt.com/news/2026/09/17/436400-neironnyi-rendering-pozvolit-geimeram-samim-sozdavat-sebe-remastery-staryx-igr-priamo-na-letu-predstavlen-proekt-uncanny.html",
         fmt=ContentFormat.REEL, creative=B3, evidence=E3, type="NEWS", intent="EXPLAINER",
         angle="Как нейронный рендеринг превращает запуск старой игры в ремастер",
         value="За 18 секунд понять идею и ограничения.", audience="Геймеры и технологическая аудитория.",
         storage_key="images/b1/b109030d1cb9e7d8392a5d71015adba56bbcce5bf5cf65a4b2a561bbec3b1b8c.jpg",
         candidate_id="7422a69fd83b3a7a583fbdccaa81ecaf5b66ceb568f6fb9dc3d24db469d06658",
         image_row_id="1a84ce79-30e8-4aaf-b2bf-967259be24fe", reel_readiness="production_script"),
    dict(key="B4", story_id="5d82a32b-8afe-4c08-8c3b-75d1f56769b7", url="https://habr.com/ru/articles/1083368/",
         fmt=ContentFormat.SINGLE, creative=B4, evidence=E4, type="CULTURE", intent="REACTION",
         angle="Почему разработчик выбрал полезность модели вместо максимального рейтинга",
         value="Получить практичную рамку выбора модели.", audience="Разработчики и пользователи ИИ.",
         storage_key=None, candidate_id=None, image_row_id=None),
]


async def main():
    if not instagram_topic_configured():
        raise RuntimeError("Instagram Telegram topic is not configured")
    if settings.instagram_image_generation_mode != "off":
        raise RuntimeError("Canary requires paid image generation OFF")
    if os.getenv("INSTAGRAM_PHASE_B1_REMEDIATION") == "1":
        print(json.dumps({"mode": "PHASE_B1_REMEDIATION", "target_version": 2}))
    bot = create_bot()
    try:
        results = []
        for spec in SPECS:
            result = await deliver(bot, spec)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        print(json.dumps({"status": "PASS", "canaries": len(results)}))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
