"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §9/§10/§11: the Instagram editorial-review callback
handler. Mirrors `bot/handlers/telegraph_article_review.py`'s own discipline exactly - thin
orchestration only, every DB read/write goes through
`services.instagram_editorial_delivery_state.InstagramEditorialDeliveryService`, state is
re-queried fresh from the database on every single callback, never cached.

Authorization: the same chat-scope check `bot/handlers/telegraph_article_review.py` already
established (the newsroom supergroup itself is the access boundary - only its members can see the
"instagram" topic or its buttons at all; no separate per-user approver allowlist exists for
Instagram, and inventing one is out of this phase's scope).

DISCLOSED SCOPE LIMITATION (report §H/§J): `_regenerator_factory` is `None` by default - real
production wiring of the Creative Director's `LLMGateway`/`PromptRepository` into a live Telegram
callback is an application-boot-lifecycle concern (`integrations/llm_gateway/boot.py::
assemble_ai_integration_layer()`) this phase does not thread through the bot's own startup, since
doing so blindly risked constructing a second, divergent gateway instance rather than reusing the
app's real one. Until `set_regenerator_factory()` is called (by a future, explicitly-authorized
wiring phase, or by a test), a regenerate button press replies honestly that regeneration is not
yet wired, and safely reverts the delivery back to its previous, still-actionable state - never a
crash, never a silent no-op, never a fabricated result. "✅ Принять" needs no generation at all and
is fully real today."""
from __future__ import annotations

import logging
from typing import Callable

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.instagram_editorial_review import parse_callback_data
from core.config import settings
from database.models.instagram_editorial_delivery import InstagramEditorialDeliveryState
from database.session import async_session_factory
from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService
from services.instagram_editorial_package_snapshot import restore_media_identity, restore_regeneration_inputs
from services.instagram_editorial_regeneration import (
    CreativeRegenerator,
    RegenerationError,
    regenerate_full,
    regenerate_text_only,
    regenerate_visual_only,
)
from services.instagram_editorial_package_snapshot import build_package_snapshot
from services.instagram_telegram_delivery import deliver_new_version, deliver_text_only_new_version
from services.instagram_telegram_package_presenter import present_caption_only, present_carousel, present_reel, present_single
from services.instagram_format_director import ContentFormat

logger = logging.getLogger(__name__)

router = Router(name="instagram_editorial_review")

_ACK_RU = {
    "approve": "Принято. Готово к ручной публикации.",
    "regen_full": "Начинаю полную переделку...",
    "regen_text": "Обновляю текст...",
    "regen_visual": "Обновляю визуал...",
}
_REGEN_KIND = {
    "regen_full": InstagramEditorialDeliveryState.REGENERATING_FULL,
    "regen_text": InstagramEditorialDeliveryState.REGENERATING_TEXT,
    "regen_visual": InstagramEditorialDeliveryState.REGENERATING_VISUAL,
}

RegeneratorFactory = Callable[[], "CreativeRegenerator"]
_regenerator_factory: RegeneratorFactory | None = None


def set_regenerator_factory(factory: RegeneratorFactory | None) -> None:
    """The one seam a future wiring phase (or a test) uses to supply a real/fake
    `CreativeRegenerator` - see this module's own docstring for why production leaves it unset by
    default today."""
    global _regenerator_factory
    _regenerator_factory = factory


def _is_authorized_chat(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


async def _safely_clear_keyboard(message: Message) -> None:
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass  # message already edited/deleted/identical - never a delivery failure


@router.callback_query(F.data.startswith("igrev:"))
async def handle_instagram_editorial_review_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, delivery_id, version = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not _is_authorized_chat(message):
        logger.warning("instagram_editorial_review_unauthorized_chat", extra={"chat_id": message.chat.id, "delivery_id": str(delivery_id)})
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    service = InstagramEditorialDeliveryService()
    async with async_session_factory() as session:
        delivery = await service.get_by_id(session, delivery_id)
        if delivery is None:
            await callback.answer("Пакет больше недоступен.", show_alert=True)
            return

        if action == "approve":
            if not service.is_actionable(delivery, expected_version=version):
                await callback.answer("Уже обработано или устарело.", show_alert=True)
                return
            await service.set_approved(session, delivery, telegram_user_id=callback.from_user.id)
            await session.commit()
            await _safely_clear_keyboard(message)
            await callback.answer(_ACK_RU["approve"])
            return

        # §11 double-regeneration guard - atomic state check-and-set, committed BEFORE any
        # generation work begins, so a second tap (or a second editor) arriving while the first
        # regeneration is still running always sees the guarded state and no-ops safely.
        kind = _REGEN_KIND[action]
        guarded = await service.begin_regeneration(session, delivery, kind=kind, expected_version=version)
        if guarded is None:
            await session.rollback()
            await callback.answer("Уже в процессе или устарело.", show_alert=True)
            return
        await session.commit()
        await callback.answer(_ACK_RU[action])

        factory = _regenerator_factory
        if factory is None:
            await service.fail_regeneration_back_to_delivered(session, delivery)
            await session.commit()
            await message.reply(
                "⚠️ Регенерация пока не подключена к этой кнопке (см. отчёт фазы, §H). "
                "Пакет остаётся доступным для действий в прежнем виде."
            )
            return

        try:
            await _run_regeneration(session, service, bot=message.bot, delivery=delivery, action=action, regenerator=factory())
        except RegenerationError as exc:
            await service.fail_regeneration_back_to_delivered(session, delivery)
            await session.commit()
            await message.reply(f"⚠️ Не удалось выполнить регенерацию: {exc}")
        except Exception:
            logger.exception("instagram_editorial_review_regeneration_failed", extra={"delivery_id": str(delivery_id), "action": action})
            await service.fail_regeneration_back_to_delivered(session, delivery)
            await session.commit()
            await message.reply("⚠️ Не удалось выполнить регенерацию из-за внутренней ошибки. Пакет не изменён.")


async def _run_regeneration(session, service: InstagramEditorialDeliveryService, *, bot, delivery, action: str, regenerator) -> None:
    inputs = restore_regeneration_inputs(delivery.package_snapshot)
    source_url = delivery.package_snapshot.get("source_url")

    if action == "regen_text":
        result = await regenerate_text_only(
            opportunity=inputs.opportunity, format_decision=inputs.format_decision, shadow_plan=inputs.shadow_plan,
            director_input=inputs.director_input, previous_creative=inputs.previous_creative,
            account_key=inputs.account_key, external_video_asset_ref=inputs.external_video_asset_ref,
            presentation_family=inputs.presentation_family, source_image_ref=inputs.source_image_ref,
            regenerator=regenerator,
        )
        new_package = restore_media_identity(result.package, inputs)
        new_snapshot = build_package_snapshot(
            package=new_package, opportunity=inputs.opportunity, format_decision=inputs.format_decision,
            shadow_plan=inputs.shadow_plan, director_input=inputs.director_input, previous_creative=result.creative,
            source_url=source_url,
        )
        new_version = await service.create_new_version(session, previous=delivery, package_snapshot=new_snapshot)
        await session.commit()
        presentation = present_caption_only(new_package, version=new_version.version)
        await deliver_text_only_new_version(
            bot, session, delivery=new_version, previous=delivery, control_text=presentation.control_text,
            overflow_text=presentation.overflow_text, source_url=source_url,
        )
        await session.commit()
        return

    if action == "regen_visual":
        result = await regenerate_visual_only(
            opportunity=inputs.opportunity, format_decision=inputs.format_decision, shadow_plan=inputs.shadow_plan,
            director_input=inputs.director_input, previous_creative=inputs.previous_creative,
            account_key=inputs.account_key, external_video_asset_ref=inputs.external_video_asset_ref,
            presentation_family=inputs.presentation_family, source_image_ref=inputs.source_image_ref,
            regenerator=regenerator,
        )
    else:  # regen_full
        result = await regenerate_full(
            opportunity=inputs.opportunity, format_decision=inputs.format_decision, shadow_plan=inputs.shadow_plan,
            director_input=inputs.director_input, account_key=inputs.account_key,
            external_video_asset_ref=inputs.external_video_asset_ref, presentation_family=inputs.presentation_family,
            source_image_ref=inputs.source_image_ref, regenerator=regenerator,
        )

    new_package = restore_media_identity(result.package, inputs) if action == "regen_visual" else result.package
    new_snapshot = build_package_snapshot(
        package=new_package, opportunity=inputs.opportunity, format_decision=inputs.format_decision,
        shadow_plan=inputs.shadow_plan, director_input=inputs.director_input,
        previous_creative=result.creative, source_url=source_url,
    )
    new_version = await service.create_new_version(session, previous=delivery, package_snapshot=new_snapshot)
    await session.commit()

    fmt = inputs.format_decision.recommended_format
    if fmt is ContentFormat.SINGLE:
        presentation = present_single(new_package, result.renders[0], version=new_version.version)
    elif fmt is ContentFormat.CAROUSEL:
        presentation = present_carousel(new_package, result.renders, version=new_version.version)
    else:
        presentation = present_reel(new_package, result.renders[0], version=new_version.version)

    if not result.gate_outcome.permits_publication:
        await service.mark_hold_or_block(
            session, new_version,
            state=InstagramEditorialDeliveryState.HOLD if result.gate_outcome.decision.value == "hold" else InstagramEditorialDeliveryState.BLOCK,
        )
        await session.commit()
        await bot.send_message(delivery.telegram_chat_id, "⚠️ Новая версия не прошла проверку контроля качества и не будет показана как готовая.")
        return

    await deliver_new_version(bot, session, delivery=new_version, presentation=presentation, source_url=source_url)
    await session.commit()
