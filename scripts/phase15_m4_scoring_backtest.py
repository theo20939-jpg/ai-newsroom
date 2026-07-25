"""Phase 15 M4 - Editorial Score V2 shadow backtest.

Read-only. Computes V2 from already-persisted data (NewsEvent, NewsSource) and already-persisted
NEWS_ANALYSIS task step_results for every real, completed NEWS_ANALYSIS task - never mutates any
row, never calls an LLM/provider, never touches EditorialTask.workflow.

Launch with:
    python -m scripts.phase15_m4_scoring_backtest
"""
import asyncio
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from schemas.workflow import WorkflowType
from services.cleaning import is_valid_title
from services.editorial_scoring import compute_editorial_score_v2, fetch_engagement_baseline

CONTENT_GENERATION_MIN_SCORE_UNDER_TEST = 65  # the live .env's current threshold (core/config.py default is 70)


def _extract_legacy_score(workflow: dict[str, Any] | None) -> int | None:
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "scoring" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                score = result.get("score")
                if isinstance(score, int) and not isinstance(score, bool):
                    return score
    return None


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return float(ordered[index])


def _summary(values: list[int]) -> dict[str, float]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": round(statistics.mean(values), 2),
        "median": statistics.median(values),
        "p75": _percentile(values, 75),
        "p90": _percentile(values, 90),
        ">=65": sum(1 for v in values if v >= 65),
        ">=70": sum(1 for v in values if v >= 70),
    }


async def main() -> None:
    reference_now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        stmt = (
            select(EditorialTask.id, EditorialTask.event_id, EditorialTask.workflow)
            .where(
                EditorialTask.status == TaskStatus.COMPLETED,
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            )
        )
        rows = (await session.execute(stmt)).all()

        source_cache: dict[UUID, tuple[float | None, str]] = {}
        old_scores: list[int] = []
        v2_scores: list[int] = []
        by_source_type: dict[str, list[int]] = defaultdict(list)
        by_source_type_v2: dict[str, list[int]] = defaultdict(list)
        by_category: dict[str, list[int]] = defaultdict(list)
        by_category_v2: dict[str, list[int]] = defaultdict(list)
        movers: list[tuple[int, str, int, int]] = []  # (delta, title, old, new)
        samples: list[dict[str, Any]] = []
        excluded_no_legacy_score = 0
        excluded_no_event = 0
        excluded_malformed_title = 0
        excluded_synthetic = 0

        for task_id, event_id, workflow in rows:
            legacy_score = _extract_legacy_score(workflow)
            if legacy_score is None:
                excluded_no_legacy_score += 1
                continue

            event = await session.get(NewsEvent, event_id)
            if event is None:
                excluded_no_event += 1
                continue

            # Pre-M1/pre-M2-deployment historical rows: a malformed title (raw HTML fragment,
            # bare URL) would be rejected by services.triage_orchestrator's gate today, before
            # ever reaching a NEWS_ANALYSIS task at all - the M1 gate is already live (see the
            # Phase 13-15 M3 checkpoint commit) but these tasks predate it. Excluded from the
            # comparison entirely: scoring V1-vs-V2 on data that can no longer occur live would
            # misrepresent what V2 will actually face going forward.
            if not is_valid_title(event.title):
                excluded_malformed_title += 1
                continue
            if "synthetic, not real news" in event.title:
                excluded_synthetic += 1
                continue

            if event.source_id not in source_cache:
                source = await session.get(NewsSource, event.source_id)
                source_cache[event.source_id] = (
                    source.reliability_score if source is not None else None,
                    source.type.value if source is not None else "UNKNOWN",
                )
            reliability_score, source_type = source_cache[event.source_id]

            baseline = await fetch_engagement_baseline(session, event.source_id, event.id)

            v2 = compute_editorial_score_v2(
                legacy_llm_score=legacy_score,
                published_at=event.published_at,
                collected_at=event.collected_at,
                reference_now=reference_now,
                reliability_score=reliability_score,
                event_metrics={
                    "views_count": event.views_count, "forwards_count": event.forwards_count,
                    "replies_count": event.replies_count, "reactions_count": event.reactions_count,
                },
                baseline_samples=baseline,
            )

            old_scores.append(legacy_score)
            v2_scores.append(v2["score"])
            by_source_type[source_type].append(legacy_score)
            by_source_type_v2[source_type].append(v2["score"])
            by_category[event.category.value].append(legacy_score)
            by_category_v2[event.category.value].append(v2["score"])
            movers.append((v2["score"] - legacy_score, event.title, legacy_score, v2["score"]))
            samples.append({
                "event_id": str(event.id), "task_id": str(task_id), "source_type": source_type,
                "category": event.category.value, "title": event.title[:80],
                "legacy_score": legacy_score, "v2_score": v2["score"],
                "components": v2["components"], "coverage": v2["coverage"], "reason": v2["reason"],
            })

    old_top20 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["legacy_score"])[:20]}
    v2_top20 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["v2_score"])[:20]}
    old_top10 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["legacy_score"])[:10]}
    v2_top10 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["v2_score"])[:10]}

    report = {
        "sample_size": len(samples),
        "excluded_no_legacy_score": excluded_no_legacy_score,
        "excluded_no_event": excluded_no_event,
        "excluded_malformed_title": excluded_malformed_title,
        "excluded_synthetic": excluded_synthetic,
        "old_distribution": _summary(old_scores),
        "v2_distribution": _summary(v2_scores),
        "by_source_type_old": {k: _summary(v) for k, v in by_source_type.items()},
        "by_source_type_v2": {k: _summary(v) for k, v in by_source_type_v2.items()},
        "by_category_old": {k: _summary(v) for k, v in by_category.items()},
        "by_category_v2": {k: _summary(v) for k, v in by_category_v2.items()},
        "top10_overlap": len(old_top10 & v2_top10),
        "top20_overlap": len(old_top20 & v2_top20),
        "top_movers_up": sorted(movers, key=lambda m: -m[0])[:5],
        "top_movers_down": sorted(movers, key=lambda m: m[0])[:5],
    }
    print(json.dumps(report, indent=2, default=str))

    # Full sample dump for the report's own appendix / manual review table construction.
    with open("scripts/_phase15_m4_backtest_samples.json", "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=2, default=str)


if __name__ == "__main__":
    asyncio.run(main())
