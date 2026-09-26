"""One-shot Telegram NEWS canary with the application-level provider cost envelope.

Manual invocation only. It does not loop, start analysis, or enable autonomous
publishing. Normal worker behavior is unchanged outside the envelope context.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from scripts._canary_delivery_cap import HardDeliveryCap, wrap_bot_with_hard_cap
from services.kage_telegram_canary_envelope import (
    CANARY_HARD_CAP_USD,
    CANARY_STAGE_INPUT_TOKEN_CAPS,
    CANARY_STAGE_OUTPUT_TOKEN_CAPS,
    TelegramCanaryEnvelope,
    maximum_canary_cost,
    telegram_canary_envelope,
)
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from worker.content_cycle import run_content_cycle

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_EXPECTED_CHAT_ID = -1004297182444
_EXPECTED_NEWS_TOPIC_ID = 2


def _configure_frozen_canary_settings() -> None:
    if "copywriting_prompt_version" not in settings.model_fields_set:
        settings.copywriting_prompt_version = "11.10"
    if settings.copywriting_prompt_version != "11.10":
        raise RuntimeError("refusing canary: Copywriting 11.10 is not active")
    if settings.content_generation_dry_run:
        raise RuntimeError("refusing canary: content generation is in dry-run mode")
    if settings.editorial_delivery_mode != "router":
        raise RuntimeError("refusing canary: accepted Telegram router delivery mode is not active")
    if settings.instagram_automatic_generation_enabled or settings.instagram_product_lane_enabled:
        raise RuntimeError("refusing canary: Instagram lane must remain disabled")
    if settings.meme_opportunity_mode != "off":
        raise RuntimeError("refusing canary: optional meme generation must remain disabled")
    # This process handles one selected event only. It is not persisted to the environment.
    settings.content_generation_batch_size = 1


async def main() -> None:
    setup_logging()
    _configure_frozen_canary_settings()
    route = resolve_route(EditorialDestination.NEWS)
    expected = RouteTarget(chat_id=_EXPECTED_CHAT_ID, topic_id=_EXPECTED_NEWS_TOPIC_ID)
    if route != expected:
        raise RuntimeError(f"refusing canary: NEWS route mismatch ({route!r})")

    envelope = TelegramCanaryEnvelope()
    maximum = maximum_canary_cost()
    if maximum > CANARY_HARD_CAP_USD:
        raise RuntimeError(f"refusing canary: computed maximum ${maximum} exceeds ${CANARY_HARD_CAP_USD}")

    prompts = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompts)
    bot = create_bot()
    delivery_cap = HardDeliveryCap(max_deliveries=1)
    wrap_bot_with_hard_cap(bot, delivery_cap)
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    print(json.dumps({
        "event": "KAGE_CANARY_PREFLIGHT_PASS",
        "max_provider_cost_usd": str(maximum),
        "hard_cap_usd": str(CANARY_HARD_CAP_USD),
        "route": {"chat_id": route.chat_id, "topic_id": route.topic_id},
        "copywriting_version": settings.copywriting_prompt_version,
        "input_token_caps": CANARY_STAGE_INPUT_TOKEN_CAPS,
        "output_token_caps": CANARY_STAGE_OUTPUT_TOKEN_CAPS,
        "hard_delivery_limit": delivery_cap.max_deliveries,
    }, ensure_ascii=False, sort_keys=True))
    try:
        with telegram_canary_envelope(envelope):
            result = await run_content_cycle(
                ai_layer.capability_registry,
                bot,
                session_factory=async_session_factory,
                cost_tracker=ai_layer.cost_tracker,
                pricing_catalog=pricing_catalog,
                gate_gateway=ai_layer.gateway,
                gate_prompt_repository=prompts,
            )
        print(json.dumps({
            "event": "KAGE_CANARY_FINISHED",
            "event_ids": [str(event_id) for event_id in result.event_ids],
            "generation_attempts": result.generation_attempts,
            "notified": result.notified,
            "delivery_attempts": delivery_cap.attempted,
            "provider_dispatches": envelope.dispatch_records,
            "reserved_spend_usd": str(envelope._spent_reserved),  # noqa: SLF001
            "hard_cap_usd": str(envelope.hard_cap_usd),
        }, ensure_ascii=False, sort_keys=True, default=str))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
