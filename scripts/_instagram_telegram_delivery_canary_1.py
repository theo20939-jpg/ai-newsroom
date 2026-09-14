"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1 §12: one real, production-shaped
Instagram package, built through the real pipeline from a real recent news story, delivered
through the real code path into the real Telegram "instagram" topic (chat_id=-1004297182444,
message_thread_id=40). Never auto-run - a one-off, manually-invoked canary script.

Zero Instagram API calls. Uses the real `deliver_instagram_package()` - the ONLY send it performs
is a Telegram Bot API call, gated entirely by `settings.instagram_topic_id`/`settings.
newsroom_telegram_chat_id` already being correctly configured."""
from __future__ import annotations

import asyncio

from bot.loader import create_bot
from core.config import settings
from database.session import async_session_factory
from schemas.instagram_creative import InstagramSingleCreative
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_delivery_state import compute_package_identity
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import deliver_instagram_package, instagram_topic_configured
from services.instagram_telegram_package_presenter import present_single

# Real story, pulled read-only from production `news_events`/`content_drafts`/`editorial_tasks`
# via SSH+psql (INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1 §12 - the same read-only
# pattern used in every prior Instagram phase's canary).
_EVENT_ID = "c4b6f23e-e1aa-4df3-a920-f3bbb266eeb4"
_TITLE = "Blizzard анонсировала новый шутер StarCraft с открытым миром"
_SOURCE_URL = None  # not fetched this canary - kept honestly absent rather than guessed

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description=_TITLE, primary_objective="reach",
    audience_description="gaming-interested Russian-speaking audience", recommended_format="single",
    hook_family=None, creative_concept_summary="real production canary", alternative_format=None,
    alternative_objective=None, product_mention_allowed=False, evidence=[], confidence=0.5,
)


async def main() -> None:
    if not instagram_topic_configured():
        print("INSTAGRAM_TOPIC_NOT_CONFIGURED - aborting, will not send anywhere")
        return

    opp = ContentOpportunity(id=_EVENT_ID, source_type=OpportunitySourceType.NEWS, story_id=_EVENT_ID, product_mention_allowed=False)
    single = InstagramSingleCreative(
        creative_angle="Real production canary - StarCraft open-world FPS announcement",
        visual_concept="Bold headline over dark gradient",
        on_image_copy="Blizzard: New StarCraft FPS Coming in 2030",
        caption_direction=f"{_TITLE}. (Production canary post - INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1)",
        cta="Follow for more gaming news",
    )
    format_decision = FormatDecision(recommended_format=ContentFormat.SINGLE)
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=format_decision, shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), hashtags=["gaming", "StarCraft", "Blizzard"],
    )
    render = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [render])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    presentation = present_single(pkg, render, version=1)

    identity = compute_package_identity(source_key=_EVENT_ID, content_format="single")
    from services.instagram_editorial_package_snapshot import build_package_snapshot
    from services.instagram_creative_director import CreativeDirectorInput

    snapshot = build_package_snapshot(
        package=pkg, opportunity=opp, format_decision=format_decision, shadow_plan=_SP,
        director_input=CreativeDirectorInput(objective="reach", format="single", opportunity_summary=_TITLE),
        previous_creative=single, source_url=_SOURCE_URL,
    )

    bot = create_bot()
    try:
        async with async_session_factory() as session:
            outcome = await deliver_instagram_package(
                bot, session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
                source_story_id=_EVENT_ID, content_format="single", package_snapshot=snapshot, source_url=_SOURCE_URL,
            )
            await session.commit()
        print("gate_decision=", gate.decision.value)
        print("outcome.sent=", outcome.sent, "reason=", outcome.reason)
        print("delivery_id=", outcome.delivery_id, "version=", outcome.version)
        print("configured_chat_id=", settings.newsroom_telegram_chat_id)
        print("configured_topic_id=", settings.instagram_topic_id)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
