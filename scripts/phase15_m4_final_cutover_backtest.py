"""Phase 15 - final M4 cutover review (autonomous completion task, Workstream C).

Read-only. Re-runs the M4.2 clean-post-M3-sample methodology
(docs/phase15_m4_editorial_scoring_v2_report.md's own M4.2 section) against however much
additional post-M3 history has accumulated since that review, and sweeps
CONTENT_GENERATION_MIN_SCORE candidates 55/57.5/60/62.5/65/67.5/70 for both v1 and v2. Never
mutates a row, never calls an LLM/provider, never touches EditorialTask.workflow.

Boundary: reuses M4.2's own established `2026-07-25 07:30:00 UTC` clean-sample boundary (the
verified M3 engagement-capture cutover point) rather than re-deriving it - that boundary is a
historical fact about when M3 deployed, not something that changes with the passage of time.

Launch with:
    python -m scripts.phase15_m4_final_cutover_backtest
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

CLEAN_SAMPLE_BOUNDARY = datetime(2026, 7, 25, 7, 30, 0, tzinfo=timezone.utc)
THRESHOLDS = [55, 57.5, 60, 62.5, 65, 67.5, 70]


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


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return float(ordered[index])


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values), "min": min(values), "max": max(values),
        "avg": round(statistics.mean(values), 2), "median": statistics.median(values),
        "p75": _percentile(values, 75), "p90": _percentile(values, 90),
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
        samples: list[dict[str, Any]] = []
        excluded_no_legacy_score = 0
        excluded_no_event = 0
        excluded_malformed_title = 0
        excluded_synthetic = 0
        excluded_pre_boundary = 0

        for task_id, event_id, workflow in rows:
            legacy_score = _extract_legacy_score(workflow)
            if legacy_score is None:
                excluded_no_legacy_score += 1
                continue

            event = await session.get(NewsEvent, event_id)
            if event is None:
                excluded_no_event += 1
                continue

            if event.collected_at < CLEAN_SAMPLE_BOUNDARY:
                excluded_pre_boundary += 1
                continue
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

            samples.append({
                "event_id": str(event.id), "task_id": str(task_id), "source_type": source_type,
                "category": event.category.value, "title": event.title[:80],
                "legacy_score": legacy_score, "v2_score": v2["score"],
                "components": v2["components"], "coverage": v2["coverage"], "reason": v2["reason"],
                "collected_at": event.collected_at.isoformat(),
            })

    old_scores = [s["legacy_score"] for s in samples]
    v2_scores = [s["v2_score"] for s in samples]
    by_source_type: dict[str, list[float]] = defaultdict(list)
    by_source_type_v2: dict[str, list[float]] = defaultdict(list)
    by_category: dict[str, list[float]] = defaultdict(list)
    for s in samples:
        by_source_type[s["source_type"]].append(s["legacy_score"])
        by_source_type_v2[s["source_type"]].append(s["v2_score"])
        by_category[s["category"]].append(s["legacy_score"])
    movers = sorted(
        ((s["v2_score"] - s["legacy_score"], s["title"], s["legacy_score"], s["v2_score"]) for s in samples),
        key=lambda m: -m[0],
    )

    old_top20 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["legacy_score"])[:20]}
    v2_top20 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["v2_score"])[:20]}
    old_top10 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["legacy_score"])[:10]}
    v2_top10 = {s["event_id"] for s in sorted(samples, key=lambda s: -s["v2_score"])[:10]}

    threshold_sweep = {}
    for t in THRESHOLDS:
        v1_eligible = sum(1 for s in old_scores if s >= t)
        v2_eligible = sum(1 for s in v2_scores if s >= t)
        threshold_sweep[str(t)] = {
            "v1_eligible": v1_eligible, "v2_eligible": v2_eligible,
            "v1_eligible_pct": round(100 * v1_eligible / len(samples), 1) if samples else None,
            "v2_eligible_pct": round(100 * v2_eligible / len(samples), 1) if samples else None,
        }

    report = {
        "boundary": CLEAN_SAMPLE_BOUNDARY.isoformat(),
        "reference_now": reference_now.isoformat(),
        "sample_size": len(samples),
        "excluded_pre_boundary": excluded_pre_boundary,
        "excluded_no_legacy_score": excluded_no_legacy_score,
        "excluded_no_event": excluded_no_event,
        "excluded_malformed_title": excluded_malformed_title,
        "excluded_synthetic": excluded_synthetic,
        "by_source_type_count": {k: len(v) for k, v in by_source_type.items()},
        "old_distribution": _summary(old_scores),
        "v2_distribution": _summary(v2_scores),
        "by_source_type_old": {k: _summary(v) for k, v in by_source_type.items()},
        "by_source_type_v2": {k: _summary(v) for k, v in by_source_type_v2.items()},
        "by_category_old": {k: _summary(v) for k, v in by_category.items()},
        "top10_overlap": len(old_top10 & v2_top10),
        "top20_overlap": len(old_top20 & v2_top20) if len(samples) >= 20 else None,
        "threshold_sweep": threshold_sweep,
        "top_movers_up": movers[:5],
        "top_movers_down": movers[-5:],
    }
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))

    with open("scripts/_phase15_m4_final_cutover_samples.json", "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=2, default=str, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
