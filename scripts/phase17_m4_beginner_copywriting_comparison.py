"""Phase 17 M4 - controlled Beginner-Friendly Copywriting comparison tooling (docs/
phase17_m4_beginner_friendly_copywriting_report.md).

A separate, manually-invoked script - never called by any worker, never run automatically. Reads
real, already-persisted ContentDraft/EditorialTask/NewsEvent rows (SELECT only, zero mutation),
builds a BeginnerFriendlyPlan for each (pure, zero LLM cost), and - only when explicitly asked -
generates exactly one M4 "candidate" draft per case using the `copywriting_beginner_candidate`
prompt (a deliberately separate governed prompt name from both production `copywriting` and Phase
17 M3's `copywriting_adaptive_candidate` - see prompts/copywriting_beginner_candidate/v1.yaml's
own docstring). Reuses Phase 17 M3's own saved comparison artifact
(scripts/_phase17_m3_comparison_results.json) for the M3 column rather than re-generating those
candidates - no redundant paid calls.

Also runs the new, zero-cost `services.candidate_fact_safety.evaluate_candidate_fact_safety()`
deterministic second-pass audit against the baseline, M3 candidate, and M4 candidate for every
case - no new LLM call, reuses Phase 15 M5's own claim extraction.

Safety, all enforced in code, matching scripts/phase17_m3_adaptive_length_comparison.py's own
established discipline exactly:
- Defaults to --dry-run (no LLM Gateway call of any kind, plan-only output).
- A real (paid) call additionally requires ALL of: --live, --confirm-paid-calls, AND
  core.config.settings.beginner_copywriting_mode == "comparison".
- Hard cap of 32 candidate-generation calls per run, enforced regardless of --max-cases.
- Exactly one M4 candidate call per case (no extra fact-check LLM call - Fact Safety auditing is
  entirely deterministic, §"AUTOMATED FACT SAFETY SECOND PASS").
- Resume support: an existing --output file's already-successful records are kept, not
  re-generated, on a subsequent run.
- Never calls session.add/flush/commit on ContentDraft/EditorialTask/NewsEvent - read-only.
- Never imports anything from bot/ or aiogram, never imports services.collector/
  integrations.sources - Telegram sends and new event collection are structurally unreachable.
- A per-case failure is logged and the run continues - never aborts the whole batch.
- Output is a local, untracked JSON artifact - never written to ContentDraft/EditorialTask.

Launch with (dry-run, default, zero cost):
    python -m scripts.phase17_m4_beginner_copywriting_comparison --sample-ids-file <path>

Launch with (real, paid, up to 32 calls - requires the environment opt-in too):
    BEGINNER_COPYWRITING_MODE=comparison python -m \
        scripts.phase17_m4_beginner_copywriting_comparison --sample-ids-file <path> \
        --live --confirm-paid-calls
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

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
from services.editorial_brief import SourceSufficiency, build_editorial_brief
from services.editorial_glossary import lookup as glossary_lookup
from services.pricing_catalog import ModelRegistryPricingCatalog

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_CANDIDATE_PROMPT_NAME = "copywriting_beginner_candidate"
_CANDIDATE_PROMPT_VERSION = "1"
_MAX_CANDIDATE_CALLS = 32
_DEFAULT_OUTPUT_PATH = "scripts/_phase17_m4_comparison_results.json"
_M3_RESULTS_PATH = "scripts/_phase17_m3_comparison_results.json"


def _step_result(state: WorkflowExecutionState, step_name: str) -> dict[str, Any]:
    for step in state.step_results:
        if step.step_name == step_name and step.status == "SUCCESS" and step.result is not None:
            return step.result
    return {}


def _load_m3_candidates() -> dict[str, dict[str, Any]]:
    path = Path(_M3_RESULTS_PATH)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["draft_id"]: r for r in data.get("records", []) if r.get("candidate_generated")}


def _load_existing_output(output_path: str) -> dict[str, dict[str, Any]]:
    path = Path(output_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {r["draft_id"]: r for r in data.get("records", []) if r.get("candidate_generated")}


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
    brief, adaptive_plan, plan: BeginnerFriendlyPlan, prompt,
) -> GenerateRequest:
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
    max_tokens = min(1200, round(plan.safe_range.max_words * 4) + 150)
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=f"CONTEXT:\n{context_text}\n\nTASK:\n{task_text}")]),
        ],
        max_tokens=max_tokens,
        reasoning_effort="medium",  # bumped from production's "low" - this milestone's own
        # root-cause hypothesis (docs/phase17_m4_beginner_friendly_copywriting_report.md §4)
        # that low reasoning effort correlates with terser stopping behavior in this model family;
        # a deliberate, disclosed deviation from M3's "match production routing exactly" choice.
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


async def run_comparison(
    sample_ids: list[str], *, dry_run: bool, max_cases: int, output_path: str,
) -> dict[str, Any]:
    m3_candidates = _load_m3_candidates()
    existing = _load_existing_output(output_path)
    effective_max = min(max_cases, _MAX_CANDIDATE_CALLS, len(sample_ids))

    live_requested = not dry_run
    live_allowed = live_requested and settings.beginner_copywriting_mode == "comparison"
    if live_requested and not live_allowed:
        logger.warning(
            "comparison_live_requested_but_blocked",
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
    calls_made = 0
    total_cost = 0.0

    async with async_session_factory() as session:
        for draft_id in sample_ids[:effective_max]:
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
                adaptive_plan = build_adaptive_length_plan(
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
                "baseline_word_count": len((draft.body or "").split()),
                "beginner_friendly_plan": plan.model_dump(mode="json"),
                "candidate_generated": False,
            }

            # Deterministic, zero-cost Fact Safety audits - baseline and the saved M3 candidate,
            # available regardless of dry-run/live (no LLM call involved in either).
            record["baseline_fact_safety"] = evaluate_candidate_fact_safety(
                draft.title or "", draft.body or "", event.title, event.content, research_facts,
            ).model_dump(mode="json")
            m3_record = m3_candidates.get(draft_id)
            if m3_record and m3_record.get("candidate"):
                m3_candidate = m3_record["candidate"]
                record["m3_candidate"] = m3_candidate
                record["m3_fact_safety"] = evaluate_candidate_fact_safety(
                    m3_candidate.get("title", ""), m3_candidate.get("body", ""),
                    event.title, event.content, research_facts,
                ).model_dump(mode="json")

            skip_reason = None
            if brief.source_sufficiency == SourceSufficiency.EMPTY:
                skip_reason = "empty_source_skip_comparison_candidate"
            elif dry_run:
                skip_reason = "dry_run"
            elif not live_allowed:
                skip_reason = "live_not_allowed_missing_env_opt_in_or_flags"
            elif calls_made >= effective_max:
                skip_reason = "max_cases_reached"

            if skip_reason is not None:
                record["candidate_skipped_reason"] = skip_reason
                records.append(record)
                continue

            logger.info("comparison_candidate_started", extra={"draft_id": str(draft.id)})
            try:
                assert gateway is not None and prompt is not None
                request = _build_candidate_request(
                    event.title, event.category.value, settings.default_content_language,
                    research_output, intelligence_output, brief, adaptive_plan, plan, prompt,
                )
                runtime = RuntimeContext(
                    task_id=task.id, event_id=event.id, capability_name=_CANDIDATE_PROMPT_NAME,
                    priority=task.priority if isinstance(task.priority, TaskPriority) else TaskPriority.C,
                    attempt=1, iteration_count=0,
                )
                outcome = await call_generate(gateway, request, runtime=runtime, sequence=calls_made)
                calls_made += 1
                if outcome.error is not None or outcome.response is None:
                    record["candidate_error"] = str(outcome.error)
                    logger.warning("comparison_candidate_failed", extra={"draft_id": str(draft.id)})
                    records.append(record)
                    continue

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
                total_cost += cost

                m4_candidate = response.structured_output or {}
                record["candidate_generated"] = True
                record["candidate"] = m4_candidate
                record["model_used"] = response.model_used
                record["token_usage"] = {
                    "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                }
                record["estimated_cost_usd"] = round(cost, 6)
                record["m4_fact_safety"] = evaluate_candidate_fact_safety(
                    m4_candidate.get("title", ""), m4_candidate.get("body", ""),
                    event.title, event.content, research_facts, plan,
                ).model_dump(mode="json")
                logger.info(
                    "comparison_candidate_completed",
                    extra={"draft_id": str(draft.id), "model_used": response.model_used, "estimated_cost": cost},
                )
            except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
                record["candidate_error"] = str(exc)
                logger.warning("comparison_candidate_failed", extra={"draft_id": str(draft.id)})
            records.append(record)

    summary = {
        "sample_size": len(sample_ids),
        "cases_processed": len(records),
        "dry_run": dry_run,
        "live_allowed": live_allowed,
        "resumed_from_existing": len(existing),
        "candidate_calls_made": calls_made,
        "total_estimated_cost_usd": round(total_cost, 6),
    }
    output = {"summary": summary, "records": records}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(json.dumps(summary, indent=2))
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-ids-file", required=True, help="JSON file: a list of ContentDraft UUID strings.")
    parser.add_argument("--max-cases", type=int, default=_MAX_CANDIDATE_CALLS, help=f"Hard-capped at {_MAX_CANDIDATE_CALLS} regardless.")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    parser.add_argument("--live", action="store_true", help="Disable dry-run. Still requires --confirm-paid-calls and the env opt-in.")
    parser.add_argument("--confirm-paid-calls", action="store_true", help="Explicit acknowledgment this may spend real API budget.")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = _parse_args()
    with open(args.sample_ids_file, encoding="utf-8") as f:
        sample_ids = json.load(f)

    dry_run = not (args.live and args.confirm_paid_calls)
    asyncio.run(run_comparison(sample_ids, dry_run=dry_run, max_cases=args.max_cases, output_path=args.output))


if __name__ == "__main__":
    main()
