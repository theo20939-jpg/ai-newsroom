"""Phase 15 M5 - Fact Safety historical shadow backtest.

Read-only. Computes fact-safety verdicts from already-persisted ContentDraft rows and their
originating NewsEvent/Research evidence - never mutates any row, never calls an LLM/provider.

Launch with:
    python -m scripts.phase15_m5_fact_safety_backtest
"""
import asyncio
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from services.cleaning import is_valid_title
from services.fact_safety import FactEvidence, evaluate_fact_safety


def _research_facts(workflow: dict[str, Any] | None) -> list[str]:
    if not workflow:
        return []
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "research" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                facts = result.get("facts")
                if isinstance(facts, list):
                    return [f for f in facts if isinstance(f, str)]
    return []


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(ContentDraft, EditorialTask, NewsEvent, NewsSource)
            .join(EditorialTask, ContentDraft.task_id == EditorialTask.id)
            .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
            .join(NewsSource, NewsEvent.source_id == NewsSource.id)
        )
        rows = (await session.execute(stmt)).all()

        samples: list[dict[str, Any]] = []
        excluded_synthetic = 0
        excluded_malformed = 0

        for draft, task, event, source in rows:
            if not is_valid_title(event.title):
                excluded_malformed += 1
                continue
            if "synthetic, not real news" in event.title or "[M6 VALIDATION]" in (draft.title or ""):
                excluded_synthetic += 1
                continue

            research_facts = _research_facts(task.workflow)
            evidence = FactEvidence(
                source_title=event.title, source_content=event.content, source_url=event.url,
                research_facts=research_facts,
            )
            result = evaluate_fact_safety(draft.title or "", draft.body or "", evidence)

            samples.append({
                "draft_id": str(draft.id), "event_id": str(event.id), "source_type": source.type.value,
                "category": event.category.value, "draft_title": (draft.title or "")[:80],
                "status": result["status"], "claims_checked": result["claims_checked"],
                "supported": result["supported"], "uncertain": result["uncertain"],
                "unsupported": result["unsupported"], "highest_risk": result["highest_risk"],
                "findings": result["findings"],
            })

    status_counts: dict[str, int] = defaultdict(int)
    severity_counts: dict[str, int] = defaultdict(int)
    claim_type_counts: dict[str, int] = defaultdict(int)
    by_source_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for s in samples:
        status_counts[s["status"]] += 1
        by_source_type[s["source_type"]][s["status"]] += 1
        by_category[s["category"]][s["status"]] += 1
        for f in s["findings"]:
            severity_counts[f["severity"] or "none"] += 1
            claim_type_counts[f["type"]] += 1

    report = {
        "sample_size": len(samples),
        "excluded_synthetic": excluded_synthetic,
        "excluded_malformed_title": excluded_malformed,
        "status_counts": dict(status_counts),
        "severity_counts": dict(severity_counts),
        "claim_type_counts_in_findings": dict(claim_type_counts),
        "by_source_type": {k: dict(v) for k, v in by_source_type.items()},
        "by_category": {k: dict(v) for k, v in by_category.items()},
        "samples": samples,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
