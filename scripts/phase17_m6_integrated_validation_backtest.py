"""Phase 17 M6 - Integrated Editorial Validation backtest (docs/
phase17_m6_integrated_editorial_validation_report.md).

Read-only, deterministic, zero LLM calls, zero Telegram sends. Reuses M5's own real backtest
output (`scripts/_phase17_m5_backtest_results.json` - completeness + calibrated Fact Safety
already computed for the same 269 baseline / 32 M3 / 32 M4 cases) and adds two more real,
deterministic signals: Channel/Topic Relevance (M2's own `assess_channel_relevance()`, rebuilt
fresh, read-only) and Telegram delivery feasibility (`bot/formatting.py`'s own unmodified
renderer, via `services.integrated_editorial_validation.validate_delivery()`). Image context is
read from the real, already-persisted `image_candidates` table (`eligible_for_editorial`) where
joinable - never invented when absent (`image_intelligence_mode` is "off" by default in
production, so most of these 269/32/32 cases will legitimately have "unknown" image state).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.logging import setup_logging
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.integrated_editorial_validation import CandidateKind
from schemas.workflow import WorkflowExecutionState
from services.channel_relevance import assess_channel_relevance
from services.integrated_editorial_validation import build_integrated_editorial_validation, validate_delivery

_M5_BACKTEST_PATH = "scripts/_phase17_m5_backtest_results.json"
_DEFAULT_OUTPUT_PATH = "scripts/_phase17_m6_backtest_results.json"


def _step_result(state: WorkflowExecutionState, step_name: str) -> dict[str, Any]:
    for step in state.step_results:
        if step.step_name == step_name and step.status == "SUCCESS" and step.result is not None:
            return step.result
    return {}


async def _has_image_candidate(session, event_id: UUID) -> bool | None:
    stmt = select(ImageCandidateRecord.eligible_for_editorial).where(ImageCandidateRecord.news_event_id == event_id)
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None
    return any(rows)


async def _process_variant(
    session, m5_records: list[dict[str, Any]], candidate_kind: CandidateKind, text_lookup: dict[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    """`text_lookup` maps short draft_id -> (title, body) for the actual text being validated -
    the real production baseline text, or the saved M3/M4 candidate text (never regenerated)."""
    out: list[dict[str, Any]] = []
    for m5_row in m5_records:
        if m5_row.get("skipped"):
            out.append(m5_row)
            continue
        draft_id = m5_row["draft_id"]
        short = draft_id[:8]
        title_body = text_lookup.get(short)
        if title_body is None:
            out.append({"draft_id": draft_id, "skipped": True, "reason": "no_text"})
            continue
        title, body = title_body

        stmt = (
            select(EditorialTask, NewsEvent)
            .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
            .join(ContentDraft, ContentDraft.task_id == EditorialTask.id)
            .where(ContentDraft.id == draft_id)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            out.append({"draft_id": draft_id, "skipped": True, "reason": "event_not_found"})
            continue
        task, event = row
        try:
            state = WorkflowExecutionState.model_validate(task.workflow)
            research_output = _step_result(state, "research")
            _, channel_fit, _ = assess_channel_relevance(event.title, event.content, event.category, research_output)

            has_image = await _has_image_candidate(session, event.id)
            delivery = validate_delivery(
                draft_id=event.id, draft_title=title, draft_body=body, hashtags=None,
                news_title=event.title, news_category=event.category.value, news_url=event.url,
                has_image_candidate=has_image,
            )

            from schemas.editorial_completeness import EditorialCompletenessAssessment
            from schemas.calibrated_fact_safety import CalibratedFactSafetyAssessment

            completeness = EditorialCompletenessAssessment.model_validate(m5_row["editorial_completeness"])
            fact_safety = CalibratedFactSafetyAssessment.model_validate(m5_row["calibrated_fact_safety"])

            validation = build_integrated_editorial_validation(
                event_id=event.id, candidate_kind=candidate_kind, draft_title=title, draft_body=body,
                channel_fit=channel_fit, completeness=completeness, fact_safety=fact_safety,
                delivery=delivery, has_image_candidate=has_image,
            )
            out.append({"draft_id": draft_id, "integrated_validation": validation.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
            out.append({"draft_id": draft_id, "skipped": True, "reason": f"validation_failed: {exc}"})
    return out


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in records if not r.get("skipped")]
    if not scored:
        return {"cases_processed": len(records), "cases_scored": 0}
    decision_counts: dict[str, int] = {}
    caption_known = 0
    caption_fit = 0
    text_required = 0
    delivery_unknown = 0
    for r in scored:
        v = r["integrated_validation"]
        decision_counts[v["overall_decision"]] = decision_counts.get(v["overall_decision"], 0) + 1
        delivery = v.get("delivery")
        if delivery is not None:
            if delivery["fits_photo_caption"] is not None:
                caption_known += 1
                if delivery["fits_photo_caption"]:
                    caption_fit += 1
            if delivery["recommended_delivery_mode"] == "text_message":
                text_required += 1
            if delivery["recommended_delivery_mode"] == "unknown":
                delivery_unknown += 1
    return {
        "cases_processed": len(records),
        "cases_scored": len(scored),
        "overall_decision_distribution": decision_counts,
        "caption_fit_known_sample_size": caption_known,
        "caption_fit_rate_among_known": round(caption_fit / caption_known, 4) if caption_known else None,
        "text_message_required_count": text_required,
        "delivery_unknown_count": delivery_unknown,
    }


async def main(output_path: str) -> dict[str, Any]:
    m5 = json.loads(Path(_M5_BACKTEST_PATH).read_text(encoding="utf-8"))

    async with async_session_factory() as session:
        baseline_text: dict[str, tuple[str, str]] = {}
        for m5_row in m5["baseline"]["records"]:
            if m5_row.get("skipped"):
                continue
            draft = await session.get(ContentDraft, m5_row["draft_id"])
            if draft is not None and draft.title is not None and draft.body is not None:
                baseline_text[m5_row["draft_id"][:8]] = (draft.title, draft.body)

        m3_comparison = json.loads(Path("scripts/_phase17_m3_comparison_results.json").read_text(encoding="utf-8"))
        m3_text = {
            r["draft_id"][:8]: (r["candidate"]["title"], r["candidate"]["body"])
            for r in m3_comparison["records"] if isinstance(r.get("candidate"), dict) and r["candidate"].get("title")
        }
        m4_merged = json.loads(Path("scripts/_phase17_m4_1_merged_results.json").read_text(encoding="utf-8"))
        m4_text = {
            r["draft_id"][:8]: (r["candidate"]["title"], r["candidate"]["body"])
            for r in m4_merged["records"] if isinstance(r.get("candidate"), dict) and r["candidate"].get("title")
        }

        baseline_out = await _process_variant(session, m5["baseline"]["records"], CandidateKind.PRODUCTION_BASELINE, baseline_text)
        m3_out = await _process_variant(session, m5["m3"]["records"], CandidateKind.M3_CANDIDATE, m3_text)
        m4_out = await _process_variant(session, m5["m4"]["records"], CandidateKind.M4_CANDIDATE, m4_text)

    output = {
        "baseline": {"summary": _summarize(baseline_out), "records": baseline_out},
        "m3": {"summary": _summarize(m3_out), "records": m3_out},
        "m4": {"summary": _summarize(m4_out), "records": m4_out},
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(json.dumps({k: v["summary"] for k, v in output.items()}, indent=2, ensure_ascii=False))
    return output


if __name__ == "__main__":
    setup_logging()
    import argparse

    parser = argparse.ArgumentParser(description="Phase 17 M6 integrated validation backtest (read-only, no LLM)")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    asyncio.run(main(args.output))
