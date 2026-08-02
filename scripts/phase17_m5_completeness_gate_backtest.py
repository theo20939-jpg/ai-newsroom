"""Phase 17 M5 - Editorial Completeness Gate + Fact Safety calibration backtest (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

Read-only, deterministic, zero LLM calls. Runs `services.editorial_completeness.
build_editorial_completeness_assessment()` + `services.fact_safety_calibration.
calibrate_fact_safety()` against three already-saved datasets, never generating anything new:

- Production baseline drafts: the same pinned M0 sample
  (`scripts/_phase17_m0_output_quality_samples.json`, up to 269 draft IDs) - real `ContentDraft`
  text, `EditorialBrief`/`AdaptiveLengthPlan`/`BeginnerFriendlyPlan` rebuilt deterministically from
  each draft's own already-persisted `research`/`intelligence` step_results (the same read-only
  reconstruction `scripts/phase17_m4_1_failed_case_replay.py` already established for a smaller
  sample) - never mutated, never regenerated.
- M3 candidates: the 32 saved records in `scripts/_phase17_m3_comparison_results.json`
  (`m3_candidate`).
- M4/M4.1 candidates: the 32 merged records in `scripts/_phase17_m4_1_merged_results.json`
  (`candidate`, post-M4.1 fix).

Never calls the LLM Gateway, never sends Telegram messages, never mutates `ContentDraft` or
`EditorialTask.workflow` - `session` is opened read-only and no `session.add/flush/commit` is ever
called on any mutable row.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.logging import setup_logging
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.adaptive_length import AdaptiveLengthPlan
from schemas.beginner_friendly import BeginnerFriendlyPlan
from schemas.editorial_brief import EditorialBrief, SourceSufficiency
from schemas.editorial_completeness import DraftKind
from schemas.workflow import WorkflowExecutionState
from services.adaptive_length import build_adaptive_length_plan
from services.beginner_friendly import build_beginner_friendly_plan
from services.candidate_fact_safety import evaluate_candidate_fact_safety
from services.editorial_brief import build_editorial_brief
from services.editorial_completeness import build_editorial_completeness_assessment
from services.fact_safety_calibration import calibrate_fact_safety

logger = logging.getLogger(__name__)

_BASELINE_SAMPLE_PATH = "scripts/_phase17_m0_output_quality_samples.json"
_M3_RESULTS_PATH = "scripts/_phase17_m3_comparison_results.json"
_M4_MERGED_PATH = "scripts/_phase17_m4_1_merged_results.json"
_DEFAULT_OUTPUT_PATH = "scripts/_phase17_m5_backtest_results.json"


def _step_result(state: WorkflowExecutionState, step_name: str) -> dict[str, Any]:
    for step in state.step_results:
        if step.step_name == step_name and step.status == "SUCCESS" and step.result is not None:
            return step.result
    return {}


def _build_plans(
    event_title: str, event_content: str | None, research_output: dict[str, Any], intelligence_output: dict[str, Any],
) -> tuple[EditorialBrief | None, AdaptiveLengthPlan | None, BeginnerFriendlyPlan | None]:
    """Rebuilds every upstream deterministic plan fresh from already-persisted `research`/
    `intelligence` step_results - never reuses a plan a draft happened to have persisted already
    (most production baseline drafts have none, all shadow modes being "off" by default), and
    never regenerates or mutates anything. Each builder failing independently (e.g. malformed
    stored state) degrades to `None` for that one plan only - one failure never blocks the other
    two or aborts the case."""
    try:
        brief: EditorialBrief | None = build_editorial_brief(event_title, event_content, research_output, intelligence_output)
    except Exception:
        brief = None
    try:
        adaptive_plan: AdaptiveLengthPlan | None = build_adaptive_length_plan(
            event_title, event_content, research_output, intelligence_output, has_image_candidate=None,
        )
    except Exception:
        adaptive_plan = None
    try:
        beginner_plan: BeginnerFriendlyPlan | None = build_beginner_friendly_plan(
            event_title, event_content, research_output, intelligence_output, has_image_candidate=None,
        )
    except Exception:
        beginner_plan = None
    return brief, adaptive_plan, beginner_plan


def _assess_case(
    *, draft_id: str, title: str, body: str, event_title: str, event_content: str | None,
    research_output: dict[str, Any], intelligence_output: dict[str, Any], draft_kind: DraftKind,
) -> dict[str, Any]:
    research_facts = [f for f in research_output.get("facts", []) if isinstance(f, str)]
    brief, adaptive_plan, beginner_plan = _build_plans(event_title, event_content, research_output, intelligence_output)

    raw_audit = evaluate_candidate_fact_safety(title, body, event_title, event_content, research_facts, beginner_plan)
    calibrated = calibrate_fact_safety(
        raw_audit, draft_title=title, news_event_title=event_title, news_event_content=event_content,
        research_facts=research_facts,
    )
    source_sufficiency = (
        brief.source_sufficiency if brief is not None
        else adaptive_plan.source_sufficiency if adaptive_plan is not None
        else SourceSufficiency.UNKNOWN
    )
    assessment = build_editorial_completeness_assessment(
        draft_title=title, draft_body=body, draft_kind=draft_kind, source_sufficiency=source_sufficiency,
        editorial_brief=brief, adaptive_length_plan=adaptive_plan, beginner_friendly_plan=beginner_plan,
        calibrated_fact_safety=calibrated,
    )
    return {
        "draft_id": draft_id,
        "editorial_completeness": assessment.model_dump(mode="json"),
        "raw_fact_safety": raw_audit.model_dump(mode="json"),
        "calibrated_fact_safety": calibrated.model_dump(mode="json"),
    }


async def _run_baseline(session, draft_ids: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for draft_id in draft_ids:
        stmt = (
            select(ContentDraft, EditorialTask, NewsEvent)
            .join(EditorialTask, EditorialTask.id == ContentDraft.task_id)
            .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
            .where(ContentDraft.id == draft_id)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            records.append({"draft_id": draft_id, "skipped": True, "reason": "not_found"})
            continue
        draft, task, event = row
        if task.workflow is None:
            records.append({"draft_id": draft_id, "skipped": True, "reason": "no_workflow_state"})
            continue
        try:
            state = WorkflowExecutionState.model_validate(task.workflow)
            research_output = _step_result(state, "research")
            intelligence_output = _step_result(state, "intelligence")
            record = _assess_case(
                draft_id=draft_id, title=draft.title, body=draft.body, event_title=event.title,
                event_content=event.content, research_output=research_output,
                intelligence_output=intelligence_output, draft_kind=DraftKind.PRODUCTION_BASELINE,
            )
        except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
            record = {"draft_id": draft_id, "skipped": True, "reason": f"assessment_failed: {exc}"}
            logger.warning("m5_backtest_case_failed", extra={"draft_id": draft_id})
        records.append(record)
    return records


async def _run_candidate_dataset(
    session, results_path: str, candidate_key: str,
) -> list[dict[str, Any]]:
    path = Path(results_path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for row in data.get("records", []):
        draft_id = row.get("draft_id")
        candidate = row.get(candidate_key)
        if not draft_id or not isinstance(candidate, dict) or not candidate.get("title") or not candidate.get("body"):
            records.append({"draft_id": draft_id, "skipped": True, "reason": "no_candidate_text"})
            continue
        event_stmt = (
            select(EditorialTask, NewsEvent)
            .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
            .join(ContentDraft, ContentDraft.task_id == EditorialTask.id)
            .where(ContentDraft.id == draft_id)
        )
        event_row = (await session.execute(event_stmt)).first()
        if event_row is None:
            records.append({"draft_id": draft_id, "skipped": True, "reason": "event_not_found"})
            continue
        task, event = event_row
        try:
            state = WorkflowExecutionState.model_validate(task.workflow)
            research_output = _step_result(state, "research")
            intelligence_output = _step_result(state, "intelligence")
            record = _assess_case(
                draft_id=draft_id, title=candidate["title"], body=candidate["body"], event_title=event.title,
                event_content=event.content, research_output=research_output,
                intelligence_output=intelligence_output, draft_kind=DraftKind.SHADOW_CANDIDATE,
            )
        except Exception as exc:  # noqa: BLE001
            record = {"draft_id": draft_id, "skipped": True, "reason": f"assessment_failed: {exc}"}
            logger.warning("m5_backtest_case_failed", extra={"draft_id": draft_id})
        records.append(record)
    return records


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in records if not r.get("skipped")]
    if not scored:
        return {"cases_processed": len(records), "cases_scored": 0}
    rec_counts: dict[str, int] = {}
    hr_counts: dict[str, int] = {}
    fs_raw_counts: dict[str, int] = {}
    fs_cal_counts: dict[str, int] = {}
    scores = []
    for r in scored:
        a = r["editorial_completeness"]
        rec_counts[a["editorial_recommendation"]] = rec_counts.get(a["editorial_recommendation"], 0) + 1
        hr_counts[a["headline_rewrite_risk"]] = hr_counts.get(a["headline_rewrite_risk"], 0) + 1
        fs_raw_counts[r["raw_fact_safety"]["status"]] = fs_raw_counts.get(r["raw_fact_safety"]["status"], 0) + 1
        fs_cal_counts[r["calibrated_fact_safety"]["calibrated_status"]] = (
            fs_cal_counts.get(r["calibrated_fact_safety"]["calibrated_status"], 0) + 1
        )
        scores.append(a["completeness_score"])
    scores.sort()
    n = len(scores)
    median = scores[n // 2] if n % 2 else (scores[n // 2 - 1] + scores[n // 2]) / 2
    missing_rates = {}
    for criterion in (
        "headline_fact_covered", "event_details_covered", "subject_explanation_covered",
        "background_context_covered", "why_it_matters_covered", "uncertainty_covered",
    ):
        applicable = [r for r in scored if any(c["criterion"] == criterion and c["required"] for c in r["editorial_completeness"]["criteria"])]
        failing = [
            r for r in applicable
            if next(c for c in r["editorial_completeness"]["criteria"] if c["criterion"] == criterion)["status"] == "fail"
        ]
        missing_rates[criterion] = {
            "applicable": len(applicable), "failing": len(failing),
            "rate": round(len(failing) / len(applicable), 4) if applicable else None,
        }
    return {
        "cases_processed": len(records),
        "cases_scored": len(scored),
        "cases_skipped": len(records) - len(scored),
        "editorial_recommendation_distribution": rec_counts,
        "headline_rewrite_risk_distribution": hr_counts,
        "raw_fact_safety_distribution": fs_raw_counts,
        "calibrated_fact_safety_distribution": fs_cal_counts,
        "completeness_score_mean": round(sum(scores) / n, 4),
        "completeness_score_median": round(median, 4),
        "missing_criterion_rates": missing_rates,
    }


async def main(baseline_limit: int, output_path: str) -> dict[str, Any]:
    baseline_ids = json.loads(Path(_BASELINE_SAMPLE_PATH).read_text(encoding="utf-8"))
    baseline_ids = [row["draft_id"] for row in baseline_ids][:baseline_limit]

    async with async_session_factory() as session:
        baseline_records = await _run_baseline(session, baseline_ids)
        m3_records = await _run_candidate_dataset(session, _M3_RESULTS_PATH, "candidate")
        m4_records = await _run_candidate_dataset(session, _M4_MERGED_PATH, "candidate")

    output = {
        "baseline": {"summary": _summarize(baseline_records), "records": baseline_records},
        "m3": {"summary": _summarize(m3_records), "records": m3_records},
        "m4": {"summary": _summarize(m4_records), "records": m4_records},
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(json.dumps({
        "baseline_summary": output["baseline"]["summary"],
        "m3_summary": output["m3"]["summary"],
        "m4_summary": output["m4"]["summary"],
    }, indent=2, ensure_ascii=False))
    return output


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Phase 17 M5 completeness gate backtest (read-only, no LLM)")
    parser.add_argument("--baseline-limit", type=int, default=269)
    parser.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    asyncio.run(main(args.baseline_limit, args.output))
