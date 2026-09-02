"""PRESENTATION RECOVERY (2026-09-02), Phase I.3: dormant manual entry point for the real
Telegram publish of one already-`APPROVED_FOR_PUBLICATION` `FinalPostReview` row.

Launch with:
    python -m scripts.final_post_publication_worker <review_id> [--live]

No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually, mirroring scripts/final_post_review_worker.py's own established convention exactly.
Nothing in this codebase imports or calls this module.

`--live` gates ONLY whether the real Telegram send actually happens, mirroring every other worker
in this pipeline's own two-factor confirmation (`--live` AND `settings.final_post_publication_
enabled=True`). The safe default is a dry run that still re-checks eligibility and would compute
the exact payload that would be sent, without ever calling the Telegram API.

This script makes NO publication decision of its own - it only executes a decision a human has
already made via the ✅ К публикации button (bot/handlers/final_post_review.py). If the named
review is not `APPROVED_FOR_PUBLICATION`, or has already been published, this script sends nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from bot.loader import create_bot
from core.logging import setup_logging
from database.session import async_session_factory
from services.final_post_publication import publish_approved_final_post

logger = logging.getLogger(__name__)


async def run_final_post_publication(review_id: UUID, *, live: bool) -> None:
    async with async_session_factory() as session:
        bot = create_bot()
        try:
            outcome = await publish_approved_final_post(session, bot, review_id, live=live)
        finally:
            await bot.session.close()

        logger.info(
            "final_post_publication_worker_outcome",
            extra={
                "review_id": str(review_id), "status": outcome.status, "live": live,
                "telegram_message_id": outcome.telegram_message_id,
                "telegram_chat_id": outcome.telegram_chat_id,
            },
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id", type=str)
    parser.add_argument(
        "--live", action="store_true",
        help=(
            "Allow a real Telegram send (still requires settings.final_post_publication_enabled=True "
            "as a second, independent confirmation)."
        ),
    )
    return parser.parse_args()


async def main() -> None:
    setup_logging()
    args = _parse_args()
    await run_final_post_publication(UUID(args.review_id), live=args.live)


if __name__ == "__main__":
    asyncio.run(main())
