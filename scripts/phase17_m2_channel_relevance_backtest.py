"""Phase 17 M2 - Channel/Topic Relevance shadow backtest (docs/
phase17_m2_channel_topic_relevance_shadow_report.md).

Read-only. Reuses the exact 269 real ContentDraft IDs pinned by Phase 17 M0/M1
(`scripts/_phase17_m0_output_quality_samples.json`) for direct comparability. For each draft:
loads its EditorialTask, extracts the already-persisted "research" step_results from
`EditorialTask.workflow` (no re-run, no LLM call), and calls
`services.channel_relevance.assess_channel_relevance()` directly - the same pure function the
production shadow hook calls.

Zero LLM/provider calls, zero Telegram sends, zero DB mutations (SELECT only, no session.add/
flush/commit anywhere in this file), zero changes to any NewsEvent/ContentDraft/EditorialTask row.

Launch with:
    python -m scripts.phase17_m2_channel_relevance_backtest
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
from schemas.article_relevance import FitDecision
from schemas.topic_taxonomy import ArticleTopic
from schemas.workflow import WorkflowExecutionState
from services.channel_relevance import assess_channel_relevance
from services.editorial_brief import SourceSufficiency, classify_source_sufficiency

_SAMPLE_IDS_PATH = "scripts/_phase17_m0_output_quality_samples.json"
_OUTPUT_PATH = "scripts/_phase17_m2_channel_relevance_backtest_results.json"

_THIN_SUFFICIENCY = {
    SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY,
    SourceSufficiency.CONFLICTING, SourceSufficiency.UNKNOWN,
}


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
            research_facts = (
                [f for f in research_output.get("facts", []) if isinstance(f, str)]
                if isinstance(research_output.get("facts"), list) else []
            )
            research_gaps = (
                [g for g in research_output.get("gaps", []) if isinstance(g, str)]
                if isinstance(research_output.get("gaps"), list) else []
            )

            try:
                topic, fit, decision = assess_channel_relevance(
                    event.title, event.content, event.category, research_output,
                )
                sufficiency = classify_source_sufficiency(event.title, event.content, research_facts, research_gaps)
            except Exception as exc:  # noqa: BLE001 - counted, never raised; read-only script
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
                "source_category": event.category.value,
                "build_succeeded": True,
                "primary_topic": topic.primary_topic.value,
                "secondary_topics": [t.value for t in topic.secondary_topics],
                "normalized_category": topic.normalized_category.value if topic.normalized_category else None,
                "category_match": topic.category_match,
                "topic_confidence": topic.confidence.value,
                "detected_entities": topic.detected_entities,
                "fit_decision": fit.fit_decision.value,
                "fit_score": fit.fit_score,
                "fit_confidence": fit.confidence.value,
                "matched_topics": [t.value for t in fit.matched_topics],
                "excluded_topics": [t.value for t in fit.excluded_topics],
                "conditional_matches": [t.value for t in fit.conditional_matches],
                "human_review_required": fit.human_review_required,
                "reason_codes": fit.reason_codes,
                "source_sufficiency": sufficiency.sufficiency.value,
            })

    succeeded = [r for r in results if r["build_succeeded"]]
    n = len(succeeded)

    topic_counts: dict[str, int] = defaultdict(int)
    normalized_category_counts: dict[str, int] = defaultdict(int)
    decision_counts: dict[str, int] = defaultdict(int)
    confidence_counts: dict[str, int] = defaultdict(int)
    reason_code_counts: dict[str, int] = defaultdict(int)
    sufficiency_decision_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for r in succeeded:
        topic_counts[r["primary_topic"]] += 1
        normalized_category_counts[r["normalized_category"] or "NONE"] += 1
        decision_counts[r["fit_decision"]] += 1
        confidence_counts[r["fit_confidence"]] += 1
        for code in r["reason_codes"]:
            reason_code_counts[code] += 1
        sufficiency_decision_counts[r["source_sufficiency"]][r["fit_decision"]] += 1

    mismatch_count = sum(1 for r in succeeded if not r["category_match"])
    unknown_count = topic_counts.get(ArticleTopic.UNKNOWN.value, 0)
    excluded_count = sum(1 for r in succeeded if r["excluded_topics"])
    mixed_count = sum(1 for r in succeeded if "mixed_tech_and_nontech_signals" in r["reason_codes"])
    headline_only_decisions: dict[str, int] = defaultdict(int)
    for r in succeeded:
        if r["source_sufficiency"] == SourceSufficiency.HEADLINE_ONLY.value:
            headline_only_decisions[r["fit_decision"]] += 1

    reject_count = decision_counts.get(FitDecision.REJECT.value, 0)
    review_count = decision_counts.get(FitDecision.REVIEW.value, 0)
    accept_count = decision_counts.get(FitDecision.ACCEPT.value, 0)

    summary = {
        "sample_size": len(draft_ids),
        "rows_found": len(results),
        "build_succeeded": n,
        "build_failed": build_failures,
        "primary_topic_distribution": dict(topic_counts),
        "normalized_category_distribution": dict(normalized_category_counts),
        "source_vs_article_category_mismatch_count": mismatch_count,
        "source_vs_article_category_mismatch_rate": round(mismatch_count / n, 4) if n else None,
        "fit_decision_distribution": dict(decision_counts),
        "fit_decision_rate": {k: round(v / n, 4) for k, v in decision_counts.items()} if n else {},
        "confidence_distribution": dict(confidence_counts),
        "unknown_topic_count": unknown_count,
        "unknown_topic_rate": round(unknown_count / n, 4) if n else None,
        "excluded_topic_present_count": excluded_count,
        "excluded_topic_present_rate": round(excluded_count / n, 4) if n else None,
        "mixed_topic_signal_count": mixed_count,
        "mixed_topic_signal_rate": round(mixed_count / n, 4) if n else None,
        "headline_only_decision_distribution": dict(headline_only_decisions),
        "reason_code_distribution": dict(sorted(reason_code_counts.items(), key=lambda kv: -kv[1])),
        "sufficiency_x_decision": {k: dict(v) for k, v in sufficiency_decision_counts.items()},
        "reject_count": reject_count,
        "review_count": review_count,
        "accept_count": accept_count,
        "potential_offtopic_reduction": (
            f"{reject_count}/{n} ({round(reject_count / n, 4) if n else 0:.2%}) of the real "
            "population would have been flagged REJECT in shadow - a shadow-only ceiling on "
            "how much off-topic material a future enforcement mode could catch, not a live effect."
        ),
    }
    print(json.dumps(summary, indent=2, default=str))

    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": results}, f, indent=2, default=str, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
