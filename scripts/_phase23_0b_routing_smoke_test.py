"""Phase 23.0B - ONE controlled, live Telegram routing smoke test using the real Phase 22
routing layer (services/telegram_routing.py) against the real NINJA NEWSROOM group's real NEWS
topic, discovered manually in Phase 23.0A via /whereami.

Deliberately temporary/manual (underscore-prefixed, matching this repo's own established
throwaway-diagnostic-script convention, e.g. scripts/_phase17_m0_dump_manual_audit_text.py) - not
a test, not imported by anything, run once by hand.

Safety, exactly matching the phase brief:
- Sets settings.newsroom_telegram_chat_id / settings.news_topic_id IN-PROCESS ONLY (plain
  attribute assignment on the already-loaded `settings` singleton) - never writes to .env, never
  persists anywhere; the moment this process exits, nothing about this override survives.
- Uses the real, existing bot/loader.py::create_bot() (the same Bot construction every other
  production entry point uses) - not a new bot application.
- Calls services.telegram_routing.send_to_editorial_destination() unmodified - the real Phase 22
  routing function, not a bypass.
- Does not import, construct, or call any AI/LLM/Research/Copywriting/Intelligence/Quality
  capability, any WorkflowRunner, any CapabilityExecutor, or worker/content_cycle.py - zero AI
  generation, zero paid call, zero DB write of any kind (routing itself performs no DB I/O).
- Sends to NEWS only - never constructs a route for any other destination.
- Prints the fully resolved destination/chat_id/topic_id/payload BEFORE the live call, and first
  performs a dry_run=True call (which never touches the network) so the exact would-be call shape
  is visible before the one real, live send.
"""
import asyncio

from bot.loader import create_bot
from core.config import settings
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import resolve_route, send_to_editorial_destination

_REAL_NEWSROOM_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2
_PAYLOAD = "Phase 23 routing smoke test"


async def main() -> None:
    # In-process only - see module docstring. Never written to .env.
    settings.newsroom_telegram_chat_id = _REAL_NEWSROOM_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID

    route = resolve_route(EditorialDestination.NEWS)
    print("=== BEFORE SENDING ===")
    print(f"Destination: NEWS")
    print(f"Resolved chat_id: {route.chat_id if route else None}")
    print(f"Resolved thread_id: {route.topic_id if route else None}")
    print(f"Payload: {_PAYLOAD!r}")
    print()

    bot = create_bot()

    print("=== DRY RUN (no network call) ===")
    dry_outcome = await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, _PAYLOAD, dry_run=True,
    )
    print(dry_outcome)
    print()

    print("=== LIVE SEND (exactly one real Telegram API call) ===")
    live_outcome = await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, _PAYLOAD, dry_run=False,
    )
    print(live_outcome)

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
