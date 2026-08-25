"""Phase I.2: dormant manual entry point for the ContentDraft (FINAL_POST_AUTHORING) -> eligibility
check -> Final Post Preview send pipeline, for exactly ONE explicitly-named ContentDraft.

Launch with:
    python -m scripts.final_post_review_worker <content_draft_id> [--live]

No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually, mirroring scripts/event_recap_pipeline_worker.py's own established convention exactly.
Nothing in this codebase imports or calls this module.

Makes NO LLM call at all (Phase I.2's own explicit "No LLM" invariant - unlike scripts/
event_recap_pipeline_worker.py/scripts/final_post_authoring_worker.py, this script never assembles
an AI integration layer). `--live` gates ONLY whether the two real Telegram sends (MESSAGE 1
preview + MESSAGE 2 control) actually happen, mirroring scripts/event_recap_pipeline_worker.py's
own two-factor confirmation (`--live` AND `settings.final_post_review_enabled=True`) - the safe
default is a dry run that still validates eligibility and creates/reuses the durable
`FinalPostReview` row (mirrors that script's own "review row is created either way, only the
Telegram send itself is gated" established semantics).

If eligibility fails (services/final_post_review_eligibility.py), this script sends nothing and
creates no `FinalPostReview` row at all - "NO Telegram, NO review" (Phase I.2's own Part A
instruction).

This script never approves/rejects anything itself, never creates a ContentDraft, never publishes
anything - it only sends the preview + control message and durably records MESSAGE 2's own
delivery metadata. The actual publication-review DECISION is made later, by a human pressing the
✅/✏️ button (bot/handlers/final_post_review.py).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.content_draft import ContentDraft
from database.session import async_session_factory
from schemas.editorial_route import EditorialDestination
from services.final_post_review_eligibility import check_final_post_preview_eligibility
from services.final_post_review_notifier import send_final_post_preview
from services.final_post_review_service import create_final_post_review

logger = logging.getLogger(__name__)


async def run_final_post_review_for_draft(content_draft_id: UUID, *, live: bool) -> None:
    async with async_session_factory() as session:
        eligibility = await check_final_post_preview_eligibility(session, content_draft_id)
        if not eligibility.eligible:
            logger.info(
                "final_post_review_worker_not_eligible",
                extra={"content_draft_id": str(content_draft_id), "reason": eligibility.reason},
            )
            return

        draft = await session.get(ContentDraft, content_draft_id)
        assert draft is not None  # eligibility just confirmed this row exists
        assert eligibility.final_post_source is not None
        assert eligibility.fact_safety_result is not None

        review = await create_final_post_review(session, content_draft_id=content_draft_id)

        dry_run = not (live and settings.final_post_review_enabled)
        bot = create_bot()
        try:
            outcome = await send_final_post_preview(
                bot, session, review,
                title=draft.title or "", body=draft.body or "",
                final_post_source=eligibility.final_post_source,
                authoring_prompt_version=eligibility.final_post_source.get("authoring_prompt_version") or "",
                fact_safety_status=eligibility.fact_safety_result.get("status") or "",
                dry_run=dry_run, destination=EditorialDestination.TELEGRAPH,
            )
        finally:
            await bot.session.close()

        logger.info(
            "final_post_review_worker_outcome",
            extra={
                "content_draft_id": str(content_draft_id), "review_id": str(review.id),
                "status": outcome.status, "dry_run": dry_run,
                "preview_message_id": outcome.preview_message_id,
                "control_message_id": outcome.control_message_id,
            },
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_draft_id", type=str)
    parser.add_argument(
        "--live", action="store_true",
        help=(
            "Allow a real Telegram send (still requires settings.final_post_review_enabled=True "
            "as a second, independent confirmation)."
        ),
    )
    return parser.parse_args()


async def main() -> None:
    setup_logging()
    args = _parse_args()
    await run_final_post_review_for_draft(UUID(args.content_draft_id), live=args.live)


if __name__ == "__main__":
    asyncio.run(main())
