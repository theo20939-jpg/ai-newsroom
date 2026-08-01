"""Phase 17 M1 - Editorial Brief shadow backtest (docs/phase17_m1_editorial_brief_shadow_report.md).

Read-only. Reuses the exact 269 real ContentDraft IDs pinned by Phase 17 M0
(`scripts/_phase17_m0_output_quality_samples.json`) for direct comparability with that report's
own numbers. For each draft: loads its EditorialTask, extracts the already-persisted "research"/
"intelligence" step_results from `EditorialTask.workflow` (no re-run, no LLM call - the exact
same data `capabilities/executor.py` would have used had `editorial_brief_mode=shadow` been on
when the task originally ran), and calls `services.editorial_brief.build_editorial_brief()`
directly - the same pure function the production shadow hook calls.

Zero LLM/provider calls, zero Telegram sends, zero DB mutations (SELECT only, no session.add/
flush/commit anywhere in this file), zero changes to any NewsEvent/ContentDraft/EditorialTask row.

Launch with:
    python -m scripts.phase17_m1_editorial_brief_backtest
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
from schemas.editorial_brief import SourceSufficiency
from schemas.workflow import WorkflowExecutionState
from services.editorial_brief import build_editorial_brief, populated_field_count

_SAMPLE_IDS_PATH = "scripts/_phase17_m0_output_quality_samples.json"
_OUTPUT_PATH = "scripts/_phase17_m1_editorial_brief_backtest_results.json"

_THIN_SUFFICIENCY = {
    SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY,
    SourceSufficiency.CONFLICTING, SourceSufficiency.UNKNOWN,
}
_CONTENT_FIELDS = (
    "headline_fact", "subject_explanation", "event_details", "background_context",
    "difference_or_change", "why_it_matters", "what_next", "uncertainties",
)


def _step_result(state: WorkflowExecutionState, step_name: str) -> dict[str, Any]:
    for step in state.step_results:
        if step.step_name == step_name and step.status == "SUCCESS" and step.result is not None:
            return step.result
    return {}


async def main() -> None:
    with open(_SAMPLE_IDS_PATH, encoding="utf-8") as f:
        sample_records = json.load(f)
    draft_ids = [record["draft_id"] for record in sample_records]

    results: list[dict[str, Any]] = []
    build_failures = 0

    async with async_session_factory() as session:
        for draft_id in draft_ids:
            stmt = (
                select(ContentDraft, EditorialTask, NewsEvent, NewsSource)
                .join(EditorialTask, EditorialTask.id == ContentDraft.task_id)
                .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
                .join(NewsSource, NewsSource.id == NewsEvent.source_id)
                .where(ContentDraft.id == draft_id)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                continue
            draft, task, event, source = row

            if task.workflow is None:
                continue
            state = WorkflowExecutionState.model_validate(task.workflow)
            research_output = _step_result(state, "research")
            intelligence_output = _step_result(state, "intelligence")

            try:
                brief = build_editorial_brief(event.title, event.content, research_output, intelligence_output)
            except Exception as exc:  # noqa: BLE001 - counted, not raised; this script never mutates anything
                build_failures += 1
                results.append({
                    "draft_id": str(draft.id), "event_id": str(event.id), "build_succeeded": False,
                    "error": str(exc),
                })
                continue

            results.append({
                "draft_id": str(draft.id),
                "event_id": str(event.id),
                "source_type": source.type.value,
                "category": event.category.value,
                "build_succeeded": True,
                "source_sufficiency": brief.source_sufficiency.value,
                "source_sufficiency_reason_codes": brief.source_sufficiency_reason_codes,
                "recommended_format": brief.recommended_format.value,
                "target_min_words": brief.target_word_range.min_words,
                "target_max_words": brief.target_word_range.max_words,
                "event_details_count": len(brief.event_details),
                "why_it_matters_empty": len(brief.why_it_matters) == 0,
                "what_next_empty": len(brief.what_next) == 0,
                "uncertainties_empty": len(brief.uncertainties) == 0,
                "populated_field_count": populated_field_count(brief),
                "false_confidence_case": (
                    brief.source_sufficiency in _THIN_SUFFICIENCY
                    and (len(brief.why_it_matters) > 0 or len(brief.what_next) > 0)
                ),
                "had_research_output": bool(research_output),
                "had_intelligence_output": bool(intelligence_output),
            })

    succeeded = [r for r in results if r["build_succeeded"]]
    n = len(succeeded)

    sufficiency_counts: dict[str, int] = defaultdict(int)
    format_counts: dict[str, int] = defaultdict(int)
    range_counts: dict[str, int] = defaultdict(int)
    for r in succeeded:
        sufficiency_counts[r["source_sufficiency"]] += 1
        format_counts[r["recommended_format"]] += 1
        range_counts[f"{r['target_min_words']}-{r['target_max_words']}"] += 1

    event_details_counts = [r["event_details_count"] for r in succeeded]
    why_it_matters_empty = sum(1 for r in succeeded if r["why_it_matters_empty"])
    what_next_empty = sum(1 for r in succeeded if r["what_next_empty"])
    uncertainties_nonempty = sum(1 for r in succeeded if not r["uncertainties_empty"])
    headline_only_count = sufficiency_counts.get(SourceSufficiency.HEADLINE_ONLY.value, 0)
    false_confidence_count = sum(1 for r in succeeded if r["false_confidence_case"])
    no_research_count = sum(1 for r in succeeded if not r["had_research_output"])
    no_intelligence_count = sum(1 for r in succeeded if not r["had_intelligence_output"])

    summary = {
        "sample_size": len(draft_ids),
        "rows_found": len(results),
        "build_succeeded": n,
        "build_failed": build_failures,
        "build_success_rate": round(n / len(results), 4) if results else None,
        "source_sufficiency_distribution": dict(sufficiency_counts),
        "recommended_format_distribution": dict(format_counts),
        "target_word_range_distribution": dict(range_counts),
        "event_details_count_mean": round(sum(event_details_counts) / n, 2) if n else None,
        "event_details_count_min": min(event_details_counts) if event_details_counts else None,
        "event_details_count_max": max(event_details_counts) if event_details_counts else None,
        "why_it_matters_empty_count": why_it_matters_empty,
        "why_it_matters_empty_rate": round(why_it_matters_empty / n, 4) if n else None,
        "what_next_empty_count": what_next_empty,
        "what_next_empty_rate": round(what_next_empty / n, 4) if n else None,
        "uncertainties_present_count": uncertainties_nonempty,
        "uncertainties_present_rate": round(uncertainties_nonempty / n, 4) if n else None,
        "headline_only_count": headline_only_count,
        "headline_only_rate": round(headline_only_count / n, 4) if n else None,
        "false_confidence_case_count": false_confidence_count,
        "false_confidence_case_rate": round(false_confidence_count / n, 4) if n else None,
        "no_research_output_count": no_research_count,
        "no_intelligence_output_count": no_intelligence_count,
        "populated_field_count_mean": round(sum(r["populated_field_count"] for r in succeeded) / n, 2) if n else None,
    }
    print(json.dumps(summary, indent=2, default=str))

    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": results}, f, indent=2, default=str, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
