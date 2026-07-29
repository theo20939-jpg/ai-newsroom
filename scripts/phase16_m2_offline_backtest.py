"""Phase 16 M2 - offline/read-only backtest (docs/phase16_m2_secure_fetch_and_validation_report.md
§22). Read-only. No network request, no database mutation, no provider call.

First stage only (as scoped by the M2 task brief's Step 25): evaluates which recent NewsEvents
have a usable public article URL and which source types can use article-metadata discovery,
preserving the real source distribution - it does not fetch any page (that is Step 26's separately
bounded, live-network validation, run only after this stage and only after security tests pass).

Launch with:
    python -m scripts.phase16_m2_offline_backtest
"""
import asyncio
import json
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.session import async_session_factory

SAMPLE_SIZE = 400  # oversample of the required >=200


def _classify(event: NewsEvent, source: NewsSource) -> str:
    """Read-only, offline classification of whether article-metadata discovery would even be
    attempted for this event under the real services.image_intelligence.run_shadow_discovery()
    logic (source_type != TELEGRAM, a non-empty http(s) url)."""
    if source.type == SourceType.TELEGRAM:
        return "skipped_telegram_internal_url"
    if not event.url:
        return "skipped_no_url"
    parsed = urlsplit(event.url)
    if parsed.scheme not in ("http", "https"):
        return "skipped_non_http_url"
    if not parsed.hostname:
        return "skipped_no_hostname"
    return "eligible_for_article_fetch"


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(NewsEvent, NewsSource)
            .join(NewsSource, NewsEvent.source_id == NewsSource.id)
            .order_by(NewsEvent.collected_at.desc())
            .limit(SAMPLE_SIZE)
        )
        rows = (await session.execute(stmt)).all()

    by_source_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_domain_eligible: dict[str, int] = defaultdict(int)
    total = 0

    for event, source in rows:
        total += 1
        classification = _classify(event, source)
        by_source_type[source.type.value][classification] += 1
        if classification == "eligible_for_article_fetch":
            domain = urlsplit(event.url).hostname or "unknown"
            by_domain_eligible[domain] += 1

    eligible_total = sum(
        counts.get("eligible_for_article_fetch", 0) for counts in by_source_type.values()
    )

    summary: dict[str, Any] = {
        "sample_size": total,
        "eligible_for_article_fetch_total": eligible_total,
        "eligible_fraction": round(eligible_total / total, 4) if total else 0,
        "by_source_type": {k: dict(v) for k, v in by_source_type.items()},
        "distinct_eligible_domains": len(by_domain_eligible),
        "top_eligible_domains": dict(
            sorted(by_domain_eligible.items(), key=lambda kv: kv[1], reverse=True)[:15]
        ),
        "note": (
            "This is the offline/read-only candidate-URL-population stage only (Step 25) - no "
            "page was fetched. Step 26's separately bounded, live-network validation (max 20 "
            "article pages) determines real og:image/twitter:image/JSON-LD hit rates against "
            "actually-fetched pages, not estimated here."
        ),
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
