"""MEDIA-PROD-1: manually-invoked, NEVER auto-run diagnostics report over already-persisted
`MediaVisionReview` rows (database/models/media_vision_review.py, Phase 19 M13).

Purely a READ over rows scripts/phase19_m13_vision_review_manual.py has already written - makes no
LLM call itself, mutates nothing, and is not part of any scheduled/automatic path. The goal is
observability and calibration: after running the manual harness against a number of real
candidates, a human operator can use this report to see how often the reviewer would flag a
watermark/logo/website-UI/advertisement or recommend "reject", as real evidence for designing a
FUTURE enforcement rule - this script and `services/media_vision_review_persistence.py`'s own
`get_media_vision_review_calibration_summary()` behind it apply no rule of their own.

Does NOT touch `worker/content_cycle.py` or any automatic path, and does NOT change
`media_vision_review_mode`'s existing two-state (`off`/`shadow`) contract - see core/config.py's
own comment on that setting for the still-intact "manual harness only, regardless of this
setting's value" fence.

Launch with:
    python -m scripts.media_vision_review_diagnostics [--since-days N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.session import async_session_factory
from services.media_vision_review_persistence import get_media_vision_review_calibration_summary


async def run_diagnostics(
    *, since_days: int | None = None, session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days is not None else None
    async with session_factory() as session:
        summary = await get_media_vision_review_calibration_summary(session, since=since)
    return asdict(summary)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-days", type=int, default=None, help="restrict to reviews from the last N days")
    args = parser.parse_args()

    report = await run_diagnostics(since_days=args.since_days)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
