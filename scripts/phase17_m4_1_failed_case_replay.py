"""Phase 17 M4.1 - failed-case replay tooling (docs/phase17_m4_1_reasoning_budget_fix_report.md).

Fixes M4's own disclosed truncation defect: 7/32 `copywriting_beginner_candidate` calls returned
an empty visible output because `reasoning_effort="medium"` let internal reasoning tokens consume
the entire `max_output_tokens` cap (docs/phase17_m4_beginner_friendly_copywriting_report.md §22,
root-caused with certainty via `output_tokens == max_tokens_cap` matching in all 7 cases).

This script replays ONLY those 7 pinned failed cases (`scripts/_phase17_m4_1_failed_case_ids.json`
by default), using `services.candidate_generation_policy`'s corrected configuration
(`reasoning_effort="low"`, matching M3's own proven-safe, zero-truncation real run - see that
module's own docstring for the full root-cause chain). The 25 already-successful M4 candidates
are never regenerated - reused verbatim from `scripts/_phase17_m4_comparison_results.json`.

Safety, matching `scripts/phase17_m4_beginner_copywriting_comparison.py`'s own established
discipline exactly:
- Defaults to --dry-run (no LLM Gateway call of any kind, plan-only output).
- A real (paid) call additionally requires ALL of: --live, --confirm-paid-calls, AND
  core.config.settings.beginner_copywriting_mode == "comparison".
- Hard cap of 7 primary calls (one per failed case) + at most 1 retry per case (14 calls total,
  worst case) - enforced regardless of --max-cases.
- A retry happens only when `services.candidate_generation_policy.classify_empty_output()`
  classifies the primary attempt's response as empty - never for a valid response.
- Resume support: an existing --output file's already-resolved (non-empty) records are kept, not
  re-generated, on a subsequent run.
- Never calls session.add/flush/commit on ContentDraft/EditorialTask/NewsEvent - read-only.
- Never imports anything from bot/ or aiogram, never imports services.collector/
  integrations.sources - Telegram sends and new event collection are structurally unreachable.
- A per-case failure is logged and the run continues - never aborts the whole batch.
- Output is a local, untracked JSON artifact - never written to ContentDraft/EditorialTask.
- Deterministically merges the 7 replayed records into a fresh copy of the 25 already-successful
  M4 records (--merged-output) - the 25 originals are never touched or re-derived; an old, empty
  artifact for a replayed ID is always replaced by that ID's own newest replay outcome, never
  mixed with it.

Launch with (dry-run, default, zero cost):
    python -m scripts.phase17_m4_1_failed_case_replay

Launch with (real, paid, up to 14 calls worst case - requires the environment opt-in too):
    BEGINNER_COPYWRITING_MODE=comparison python -m \
        scripts.phase17_m4_1_failed_case_replay --live --confirm-paid-calls
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select

from capabilities.gateway_call import call_generate
from core.config import settings
from core.logging import setup_logging
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.prompts.file_repository import FilePromptRepository
from schemas.beginner_friendly import BeginnerFriendlyPlan
from schemas.capability import RuntimeContext
from schemas.workflow import WorkflowExecutionState
from services.adaptive_length import build_adaptive_length_plan
from services.beginner_friendly import build_beginner_friendly_plan
from services.candidate_fact_safety import evaluate_candidate_fact_safety
from services.candidate_generation_policy import (
    MAX_RETRIES,
    PRIMARY_REASONING_EFFORT,
    RETRY_REASONING_EFFORT,
    candidate_max_tokens,
    classify_empty_output,
)
from services.editorial_brief import SourceSufficiency, build_editorial_brief
from services.editorial_glossary import lookup as glossary_lookup
from services.pricing_catalog import ModelRegistryPricingCatalog

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_CANDIDATE_PROMPT_NAME = "copywriting_beginner_candidate"
_CANDIDATE_PROMPT_VERSION = "1"
_MAX_FAILED_CASES = 7
_DEFAULT_FAILED_IDS_PATH = "scripts/_phase17_m4_1_failed_case_ids.json"
_DEFAULT_OUTPUT_PATH = "scripts/_phase17_m4_1_replay_results.json"
_DEFAULT_MERGED_OUTPUT_PATH = "scripts/_phase17_m4_1_merged_results.json"
_M4_RESULTS_PATH = "scripts/_phase17_m4_comparison_results.json"


def _step_result(state: WorkflowExecutionState, step_name: str) -> dict[str, Any]:
    for step in state.step_results:
        if step.step_name == step_name and step.status == "SUCCESS" and step.result is not None:
            return step.result
    return {}


def _load_m4_records() -> dict[str, dict[str, Any]]:
    path = Path(_M4_RESULTS_PATH)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["draft_id"]: r for r in data.get("records", [])}


def _load_existing_output(output_path: str) -> dict[str, dict[str, Any]]:
    """Resume support: a prior replay's already-*resolved* records (final_status present) are
    kept, not re-attempted. A record without a resolved final_status (e.g. an interrupted run)
    is re-attempted."""
    path = Path(output_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {r["draft_id"]: r for r in data.get("records", []) if r.get("final_status")}


def _format_research(research_output: dict[str, Any]) -> str:
    if not research_output:
        return "(none)"
    return f"Facts: {research_output.get('facts', [])}\nGaps: {research_output.get('gaps', [])}"


def _format_intelligence(intelligence_output: dict[str, Any]) -> str:
    if not intelligence_output:
        return "(none)"
    return (
        f"Significance: {intelligence_output.get('significance')}\n"
        f"Angle: {intelligence_output.get('angle')}\n"
        f"Recommendation: {intelligence_output.get('recommendation')}"
    )


def _build_candidate_request(
    news_event_title: str, news_event_category: str, language: str,
    research_output: dict[str, Any], intelligence_output: dict[str, Any],
    brief, plan: BeginnerFriendlyPlan, prompt,
    reasoning_effort: Literal["none", "low", "medium", "high"],
) -> GenerateRequest:
    """Identical prompt/context assembly to
    `scripts/phase17_m4_beginner_copywriting_comparison.py`'s own `_build_candidate_request()` -
    the M4.1 fix is entirely in `reasoning_effort` (parameterized here), never in the prompt
    content itself (docs/phase17_m4_1_reasoning_budget_fix_report.md §11: root cause is fully in
    reasoning budget, so the prompt is intentionally left unmodified)."""
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    brief_text = (
        f"headline_fact: {brief.headline_fact}\n"
        f"event_details: {brief.event_details}\n"
        f"why_it_matters: {brief.why_it_matters}\n"
        f"what_next: {brief.what_next}\n"
        f"uncertainties: {brief.uncertainties}\n"
        f"source_sufficiency: {brief.source_sufficiency.value}"
    )
    beginner_text = (
        f"audience_level: {plan.audience_level.value}\n"
        f"explanation_required: {plan.explanation_required}\n"
        f"subjects_to_explain: {plan.subjects_to_explain}\n"
        f"terms_to_explain: {plan.terms_to_explain} "
        f"(definitions: {({t: glossary_lookup(t) for t in plan.terms_to_explain})})\n"
        f"assumed_knowledge (never explain): {plan.assumed_knowledge}\n"
        f"unexplainable_terms (never explain, no safe evidence): {plan.unexplainable_terms}\n"
        f"explanation_budget_words: {plan.explanation_budget}\n"
        f"why_it_matters_required: {plan.why_it_matters_required}\n"
        f"what_next_allowed: {plan.what_next_allowed}\n"
        f"uncertainty_required: {plan.uncertainty_required}\n"
        f"paragraph_target: {plan.paragraph_target}\n"
        f"safe_range: min={plan.safe_range.min_words} target={plan.safe_range.target_words} max={plan.safe_range.max_words}\n"
        f"evidence_constraints: {plan.evidence_constraints}"
    )
    context_text = (
        f"Title: {news_event_title}\n"
        f"Category: {news_event_category}\n"
        f"Target output language: {language}\n\n"
        f"Research output:\n{_format_research(research_output)}\n\n"
        f"Intelligence output:\n{_format_intelligence(intelligence_output)}\n\n"
        f"EditorialBrief:\n{brief_text}\n\n"
        f"BeginnerFriendlyPlan:\n{beginner_text}"
    )
    task_text = (
        "Write the candidate post (title, body, hashtags) for the event above, following every "
        "rule in priority order - grounded only in the evidence shown, using the safe_range as "
        "your length guide."
    )
    max_tokens = candidate_max_tokens(plan.safe_range.max_words)
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=f"CONTEXT:\n{context_text}\n\nTASK:\n{task_text}")]),
        ],
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


async def _attempt_generation(
    gateway, prompt, pricing_catalog, *,
    news_event_title: str, news_event_category: str, language: str,
    research_output: dict[str, Any], intelligence_output: dict[str, Any],
    brief, plan: BeginnerFriendlyPlan, task, event,
    reasoning_effort: Literal["none", "low", "medium", "high"],
    attempt_number: int, sequence: int, draft_id: str,
) -> dict[str, Any]:
    """One Gateway call + classification. Never raises - a Gateway-level failure is captured as
    its own attempt record with empty_output_reason="provider_empty_response" via the caller's
    own try/except (mirrors phase17_m4_beginner_copywriting_comparison.py's per-case discipline).
    Logs `replay_candidate_attempt_completed` with metadata only - never full source/candidate
    text (docs/phase17_m4_1_reasoning_budget_fix_report.md's own redaction rules)."""
    request = _build_candidate_request(
        news_event_title, news_event_category, language, research_output, intelligence_output,
        brief, plan, prompt, reasoning_effort,
    )
    runtime = RuntimeContext(
        task_id=task.id, event_id=event.id, capability_name=_CANDIDATE_PROMPT_NAME,
        priority=task.priority if isinstance(task.priority, TaskPriority) else TaskPriority.C,
        attempt=attempt_number, iteration_count=0,
    )
    outcome = await call_generate(gateway, request, runtime=runtime, sequence=sequence)

    if outcome.error is not None or outcome.response is None:
        attempt_record: dict[str, Any] = {
            "attempt": attempt_number,
            "reasoning_effort": reasoning_effort,
            "max_tokens": request.max_tokens,
            "gateway_error": str(outcome.error),
            "visible_output_present": False,
            "empty_output_reason": "provider_empty_response",
            "estimated_cost_usd": 0.0,
        }
        logger.warning(
            "replay_candidate_attempt_completed",
            extra={"replay_case_id": draft_id, **attempt_record},
        )
        return {"candidate": {}, **attempt_record}

    response = outcome.response
    usage = response.usage
    cost = 0.0
    if pricing_catalog is not None and response.model_used is not None:
        try:
            tier = pricing_catalog.get_tier(response.model_used)
            cost = float(
                (usage.input_tokens or 0) / 1_000_000 * float(tier.input_price_per_million)
                + (usage.output_tokens or 0) / 1_000_000 * float(tier.output_price_per_million)
            )
        except Exception:  # noqa: BLE001 - cost is observability, never fatal
            cost = 0.0

    empty_reason = classify_empty_output(
        structured_output=response.structured_output,
        response_text=response.text,
        finish_reason=response.finish_reason,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
    )
    attempt_record = {
        "attempt": attempt_number,
        "reasoning_effort": reasoning_effort,
        "max_tokens": request.max_tokens,
        "finish_reason": response.finish_reason,
        "model_used": response.model_used,
        "token_usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
        },
        "visible_output_present": empty_reason is None,
        "empty_output_reason": empty_reason.value if empty_reason is not None else None,
        "estimated_cost_usd": round(cost, 6),
    }
    logger.info(
        "replay_candidate_attempt_completed",
        extra={"replay_case_id": draft_id, **{k: v for k, v in attempt_record.items() if k != "token_usage"},
               "output_tokens": usage.output_tokens, "cap_reached": response.finish_reason == "length"},
    )
    candidate = response.structured_output if empty_reason is None else {}
    return {"candidate": candidate, **attempt_record}


async def generate_with_retry(
    gateway, prompt, pricing_catalog, *,
    news_event_title: str, news_event_category: str, language: str,
    research_output: dict[str, Any], intelligence_output: dict[str, Any],
    brief, plan: BeginnerFriendlyPlan, task, event, draft_id: str, sequence_start: int,
) -> dict[str, Any]:
    """One case's full retry orchestration - the primary attempt at
    `PRIMARY_REASONING_EFFORT`, and, only when that attempt's own output is classified empty, a
    single retry at `RETRY_REASONING_EFFORT` (`MAX_RETRIES == 1`, enforced here, not just by
    convention). Deliberately DB-free and gateway-agnostic (a duck-typed `gateway` with an async
    `generate()` is enough) so this orchestration is unit-testable with a fake gateway, without
    any real database session or LLM spend - see `tests/test_phase17_m4_1_replay.py`."""
    attempt = await _attempt_generation(
        gateway, prompt, pricing_catalog,
        news_event_title=news_event_title, news_event_category=news_event_category,
        language=language, research_output=research_output, intelligence_output=intelligence_output,
        brief=brief, plan=plan, task=task, event=event,
        reasoning_effort=PRIMARY_REASONING_EFFORT, attempt_number=1,
        sequence=sequence_start, draft_id=draft_id,
    )
    calls_made = 1
    attempts = [{k: v for k, v in attempt.items() if k != "candidate"}]
    candidate = attempt["candidate"]
    final_empty_reason = attempt["empty_output_reason"]
    retry_used = False

    if attempt["empty_output_reason"] is not None and MAX_RETRIES >= 1:
        retry_used = True
        retry_attempt = await _attempt_generation(
            gateway, prompt, pricing_catalog,
            news_event_title=news_event_title, news_event_category=news_event_category,
            language=language, research_output=research_output, intelligence_output=intelligence_output,
            brief=brief, plan=plan, task=task, event=event,
            reasoning_effort=RETRY_REASONING_EFFORT, attempt_number=2,
            sequence=sequence_start + 1, draft_id=draft_id,
        )
        calls_made += 1
        attempts.append({k: v for k, v in retry_attempt.items() if k != "candidate"})
        candidate = retry_attempt["candidate"]
        final_empty_reason = retry_attempt["empty_output_reason"]

    return {
        "attempts": attempts,
        "retry_used": retry_used,
        "candidate": candidate,
        "final_empty_output_reason": final_empty_reason,
        "final_status": "still_empty" if final_empty_reason is not None else "valid",
        "total_estimated_cost_usd": round(sum(a["estimated_cost_usd"] for a in attempts), 6),
        "calls_made": calls_made,
    }


async def run_replay(
    failed_ids: list[str], *, dry_run: bool, output_path: str, merged_output_path: str,
) -> dict[str, Any]:
    m4_records = _load_m4_records()
    existing = _load_existing_output(output_path)
    effective_ids = failed_ids[:_MAX_FAILED_CASES]

    live_requested = not dry_run
    live_allowed = live_requested and settings.beginner_copywriting_mode == "comparison"
    if live_requested and not live_allowed:
        logger.warning(
            "replay_live_requested_but_blocked",
            extra={"beginner_copywriting_mode": settings.beginner_copywriting_mode},
        )

    gateway = None
    prompt = None
    pricing_catalog = None
    if live_allowed:
        prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
        layer = assemble_ai_integration_layer(settings, prompt_repository)
        gateway = layer.gateway
        prompt = prompt_repository.resolve(_CANDIDATE_PROMPT_NAME, _CANDIDATE_PROMPT_VERSION)
        pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    records: list[dict[str, Any]] = []
    total_calls = 0
    total_cost = 0.0

    async with async_session_factory() as session:
        for draft_id in effective_ids:
            if draft_id in existing:
                records.append(existing[draft_id])
                continue

            stmt = (
                select(ContentDraft, EditorialTask, NewsEvent, NewsSource)
                .join(EditorialTask, EditorialTask.id == ContentDraft.task_id)
                .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
                .join(NewsSource, NewsSource.id == NewsEvent.source_id)
                .where(ContentDraft.id == draft_id)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                records.append({"draft_id": draft_id, "skipped": True, "reason": "not_found"})
                continue
            draft, task, event, _source = row
            if task.workflow is None:
                records.append({"draft_id": draft_id, "skipped": True, "reason": "no_workflow_state"})
                continue

            state = WorkflowExecutionState.model_validate(task.workflow)
            research_output = _step_result(state, "research")
            intelligence_output = _step_result(state, "intelligence")
            image_intelligence = _step_result(state, "copywriting").get("image_intelligence")
            has_image_candidate = (
                image_intelligence.get("candidates_accepted", 0) > 0
                if isinstance(image_intelligence, dict) else None
            )
            research_facts = (
                [f for f in research_output.get("facts", []) if isinstance(f, str)]
                if isinstance(research_output.get("facts"), list) else []
            )

            try:
                brief = build_editorial_brief(event.title, event.content, research_output, intelligence_output)
                build_adaptive_length_plan(  # re-derived for parity/logging only, not reused below
                    event.title, event.content, research_output, intelligence_output,
                    has_image_candidate=has_image_candidate,
                )
                plan = build_beginner_friendly_plan(
                    event.title, event.content, research_output, intelligence_output,
                    has_image_candidate=has_image_candidate,
                )
            except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
                records.append({"draft_id": draft_id, "skipped": True, "reason": f"plan_build_failed: {exc}"})
                continue

            record: dict[str, Any] = {
                "draft_id": str(draft.id),
                "event_id": str(event.id),
                "category": event.category.value,
                "beginner_friendly_plan": plan.model_dump(mode="json"),
                "attempts": [],
            }

            if dry_run or not live_allowed or brief.source_sufficiency == SourceSufficiency.EMPTY:
                record["replay_skipped_reason"] = (
                    "empty_source_skip_replay_candidate"
                    if brief.source_sufficiency == SourceSufficiency.EMPTY
                    else "dry_run" if dry_run else "live_not_allowed_missing_env_opt_in_or_flags"
                )
                records.append(record)
                continue

            assert gateway is not None and prompt is not None
            try:
                result = await generate_with_retry(
                    gateway, prompt, pricing_catalog,
                    news_event_title=event.title, news_event_category=event.category.value,
                    language=settings.default_content_language,
                    research_output=research_output, intelligence_output=intelligence_output,
                    brief=brief, plan=plan, task=task, event=event,
                    draft_id=draft_id, sequence_start=total_calls,
                )
                total_calls += result["calls_made"]
                total_cost += result["total_estimated_cost_usd"]
                record.update({k: v for k, v in result.items() if k != "calls_made"})

                if record["final_status"] == "valid":
                    candidate = record["candidate"]
                    record["m4_1_fact_safety"] = evaluate_candidate_fact_safety(
                        candidate.get("title", ""), candidate.get("body", ""),
                        event.title, event.content, research_facts, plan,
                    ).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
                record["replay_error"] = str(exc)
                record["final_status"] = "error"
                logger.warning("replay_case_failed", extra={"replay_case_id": draft_id})
            records.append(record)

    summary = {
        "failed_case_count": len(failed_ids),
        "cases_processed": len(records),
        "dry_run": dry_run,
        "live_allowed": live_allowed,
        "resumed_from_existing": len(existing),
        "total_calls_made": total_calls,
        "total_estimated_cost_usd": round(total_cost, 6),
        "valid_count": sum(1 for r in records if r.get("final_status") == "valid"),
        "still_empty_count": sum(1 for r in records if r.get("final_status") == "still_empty"),
        "retry_used_count": sum(1 for r in records if r.get("retry_used")),
    }
    output = {"summary": summary, "records": records}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(json.dumps(summary, indent=2))

    _write_merged_output(m4_records, records, merged_output_path)
    return output


def _write_merged_output(
    m4_records: dict[str, dict[str, Any]], replay_records: list[dict[str, Any]], merged_output_path: str,
) -> None:
    """Deterministic merge: every M4 record NOT among the replayed IDs is copied unchanged; each
    replayed ID's OLD (empty) M4 record is fully replaced (never mixed) by its own newest replay
    outcome, reusing that ID's own already-computed baseline_fact_safety/m3_candidate/
    m3_fact_safety (independent of M4's own candidate, zero additional cost to recompute-by-
    copy)."""
    replayed_by_id = {r["draft_id"]: r for r in replay_records if r.get("draft_id")}
    merged: list[dict[str, Any]] = []
    for draft_id, old_record in m4_records.items():
        if draft_id not in replayed_by_id:
            merged.append(old_record)
            continue
        replay = replayed_by_id[draft_id]
        merged_record = {
            "draft_id": draft_id,
            "event_id": old_record.get("event_id"),
            "category": old_record.get("category"),
            "baseline_word_count": old_record.get("baseline_word_count"),
            "beginner_friendly_plan": replay.get("beginner_friendly_plan", old_record.get("beginner_friendly_plan")),
            "baseline_fact_safety": old_record.get("baseline_fact_safety"),
            "m3_candidate": old_record.get("m3_candidate"),
            "m3_fact_safety": old_record.get("m3_fact_safety"),
            "candidate_generated": replay.get("final_status") == "valid",
            "candidate": replay.get("candidate", {}),
            "model_used": next(
                (a.get("model_used") for a in reversed(replay.get("attempts", [])) if a.get("model_used")),
                None,
            ),
            "token_usage": next(
                (a.get("token_usage") for a in reversed(replay.get("attempts", [])) if a.get("token_usage")),
                None,
            ),
            "estimated_cost_usd": replay.get("total_estimated_cost_usd", 0.0),
            "m4_fact_safety": replay.get("m4_1_fact_safety"),
            "m4_1_replayed": True,
            "m4_1_attempts": replay.get("attempts", []),
            "m4_1_retry_used": replay.get("retry_used", False),
            "m4_1_final_status": replay.get("final_status"),
            "m4_1_final_empty_output_reason": replay.get("final_empty_output_reason"),
        }
        merged.append(merged_record)

    with open(merged_output_path, "w", encoding="utf-8") as f:
        json.dump({"records": merged}, f, indent=2, default=str, ensure_ascii=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failed-ids-file", default=_DEFAULT_FAILED_IDS_PATH)
    parser.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    parser.add_argument("--merged-output", default=_DEFAULT_MERGED_OUTPUT_PATH)
    parser.add_argument("--live", action="store_true", help="Disable dry-run. Still requires --confirm-paid-calls and the env opt-in.")
    parser.add_argument("--confirm-paid-calls", action="store_true", help="Explicit acknowledgment this may spend real API budget.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = _parse_args()
    with open(args.failed_ids_file, encoding="utf-8") as f:
        failed_ids = json.load(f)

    dry_run = not (args.live and args.confirm_paid_calls)
    asyncio.run(
        run_replay(
            failed_ids, dry_run=dry_run, output_path=args.output, merged_output_path=args.merged_output,
        )
    )


if __name__ == "__main__":
    main()
