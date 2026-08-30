"""TELEGRAPH LIVE PUBLISH: manual operator retry - publishes ONE already-APPROVED
`TelegraphArticleReview` that has no `published_url` yet (or reports its existing URL if already
published).

Run with:
    python -m scripts.publish_telegraph_review <review_id>

Does NOT regenerate research or the article - services.telegraph_publish_orchestrator::
publish_approved_telegraph_article() only ever reads the already-COMPLETED TELEGRAPH_ARTICLE
task's existing "generate_article" step result; it never calls the LLM Gateway and never re-runs
a WorkflowRunner.

Idempotent - safe to run multiple times, including after a prior failed attempt (this script's own
sole purpose is manually re-invoking that exact orchestration entry point, e.g. after fixing a
transient Telegraph API outage, without waiting for the bot callback path to be re-triggered)."""
from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from core.logging import setup_logging
from database.session import async_session_factory
from services.telegraph_publish_orchestrator import publish_approved_telegraph_article


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id", type=str)
    return parser.parse_args()


async def main() -> None:
    setup_logging()
    args = _parse_args()
    review_id = UUID(args.review_id)

    async with async_session_factory() as session:
        outcome = await publish_approved_telegraph_article(session, review_id)

    print(f"status: {outcome.status}")
    if outcome.url:
        print(f"url: {outcome.url}")
    if outcome.error:
        print(f"error: {outcome.error}")


if __name__ == "__main__":
    asyncio.run(main())
