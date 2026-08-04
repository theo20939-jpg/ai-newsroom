"""Phase 17 Stage 2 - controlled candidate generation (docs/
phase17_stage2_controlled_candidate_generation_plan.md, authorized by docs/
phase17_stage1_human_acceptance_result.md, 2026-08-04).

A separate, manually-invoked script - never called by any worker, never run automatically, never
imports anything from bot/ or aiogram, never imports services.collector/integrations.sources
(Telegram sends and new event collection are structurally unreachable from this module).

Stage 2 scope, verbatim from the authorizing message, all enforced in code below:
- no auto publishing            -> never writes ContentDraft.body, never sends anything
- no enforcement                -> no accept/reject decision of any kind is made by this script
- no automatic reject           -> same as above; channel_relevance/completeness are not consulted
- manual selection required     -> editorial_preference always starts "not_yet_reviewed"; only the
                                    separate `record-preference` command (a human, or a human-driven
                                    step) ever sets it to "baseline"/"candidate"/"neither"
- compare baseline vs candidate -> both texts are recorded side by side, per case

This reuses the existing, already-tested M4.1 candidate-generation path
(`scripts/phase17_m4_1_failed_case_replay.generate_with_retry`/`_attempt_generation`/
`_build_candidate_request` - see `tests/test_phase17_m4_1_replay.py`) rather than re-implementing
prompt assembly or retry orchestration: that path is the most recent, most correct candidate
generator in this repository (fixes M4's own disclosed reasoning-budget truncation defect), and
Stage 2's plan (`docs/phase17_stage2_controlled_candidate_generation_plan.md` §1) explicitly says
not to rebuild what already exists. The only genuinely new things this script adds, per that same
plan's §2, are: (1) a record schema built around baseline-vs-candidate comparison rather than a
single candidate artifact, and (2) `editorial_preference`/`failure_reasons` as first-class, human-
settable fields.

Safety, matching the M3/M4/M4.1 scripts' own established discipline exactly:
- Defaults to --dry-run (no LLM Gateway call of any kind, plan-only output).
- A real (paid) call additionally requires ALL of: --live, --confirm-paid-calls, AND
  core.config.settings.beginner_copywriting_mode == "comparison" (the same config gate the M6.1
  runbook's own Stage 2 row names: "beginner_copywriting_mode=comparison").
- Hard cap: at most 16 cases get a live generation attempt per run, each case at most 1 primary +
  1 retry call (mirrors M4.1's own MAX_RETRIES=1) - 32 calls worst case, matching the pre-existing
  32-call ceiling established by M3/M4.
- Resume support: an existing --output file's already-resolved records (generation_status set to
  anything other than "not_attempted") are kept verbatim, never regenerated or overwritten - this
  is also what protects a human's already-recorded editorial_preference/editorial_notes/
  failure_reasons across a re-run.
- Never calls session.add/flush/commit on ContentDraft/EditorialTask/NewsEvent - read-only.
- A per-case failure is logged and the run continues - never aborts the whole batch.
- Output is a local, untracked JSON artifact - never written to ContentDraft/EditorialTask, never
  read by any worker or by the Telegram send path.
- `editorial_preference` can ONLY be set via the separate `record-preference` command below, which
  only ever edits the local JSON artifact - it has no database access at all.

Launch (dry-run, default, zero cost, builds baseline text + plan for every sampled case):
    python -m scripts.phase17_stage2_candidate_generation generate --sample-ids-file <path>

Launch (real, paid, up to 32 calls worst case - requires the environment opt-in too):
    BEGINNER_COPYWRITING_MODE=comparison python -m \
        scripts.phase17_stage2_candidate_generation generate --sample-ids-file <path> \
        --live --confirm-paid-calls

Record a human's editorial preference against an already-generated case (no LLM call, no DB
access, edits only the local --output JSON file):
    python -m scripts.phase17_stage2_candidate_generation record-preference \
        --output scripts/_phase17_stage2_candidate_results.json \
        --draft-id <uuid> --preference candidate --notes "reads better, still grounded" \
        --failure-reason baseline_too_short
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.config import settings
from core.logging import setup_logging
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.beginner_friendly import build_beginner_friendly_plan
from services.candidate_fact_safety import evaluate_candidate_fact_safety
from services.editorial_brief import SourceSufficiency, build_editorial_brief
from services.pricing_catalog import ModelRegistryPricingCatalog

import scripts.phase17_m4_1_failed_case_replay as candidate_generation

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_CANDIDATE_PROMPT_NAME = "copywriting_beginner_candidate"
_CANDIDATE_PROMPT_VERSION = "1"
_MAX_CASES_WITH_LIVE_GENERATION = 16
_DEFAULT_OUTPUT_PATH = "scripts/_phase17_stage2_candidate_results.json"

VALID_EDITORIAL_PREFERENCES = {"not_yet_reviewed", "baseline", "candidate", "neither"}


def _load_existing_output(output_path: str) -> dict[str, dict[str, Any]]:
    """Resume support: a prior run's already-resolved records (generation_status set to anything
    other than "not_attempted") are kept, never regenerated - this is also what protects a human's
    already-recorded editorial_preference/editorial_notes/failure_reasons across a re-run."""
    path = Path(output_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        r["draft_id"]: r
        for r in data.get("records", [])
        if r.get("generation_status") and r["generation_status"] != "not_attempted"
    }


def _new_record(draft: ContentDraft, event: NewsEvent, plan_dump: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_id": str(draft.id),
        "event_id": str(event.id),
        "category": event.category.value,
        "baseline_text": {"title": draft.title or "", "body": draft.body or ""},
        "candidate_text": None,
        "candidate_generated": False,
        "generation_status": "not_attempted",
        "failure_reasons": [],
        "beginner_friendly_plan": plan_dump,
        "baseline_fact_safety": None,
        "candidate_fact_safety": None,
        "editorial_preference": "not_yet_reviewed",
        "editorial_notes": "",
    }


async def run_stage2_candidate_generation(
    sample_ids: list[str], *, dry_run: bool, max_cases: int, output_path: str,
) -> dict[str, Any]:
    existing = _load_existing_output(output_path)
    effective_max = min(max_cases, _MAX_CASES_WITH_LIVE_GENERATION, len(sample_ids))

    live_requested = not dry_run
    live_allowed = live_requested and settings.beginner_copywriting_mode == "comparison"
    if live_requested and not live_allowed:
        logger.warning(
            "stage2_live_requested_but_blocked",
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
    cases_with_live_attempt = 0
    total_calls = 0
    total_cost = 0.0

    async with async_session_factory() as session:
        for draft_id in sample_ids:
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
                records.append({
                    "draft_id": draft_id, "generation_status": "error",
                    "failure_reasons": ["draft_not_found"],
                })
                continue
            draft, task, event, _source = row
            if task.workflow is None:
                records.append({
                    "draft_id": draft_id, "generation_status": "error",
                    "failure_reasons": ["no_workflow_state"],
                })
                continue

            from schemas.workflow import WorkflowExecutionState

            state = WorkflowExecutionState.model_validate(task.workflow)
            research_output = candidate_generation._step_result(state, "research")
            intelligence_output = candidate_generation._step_result(state, "intelligence")
            image_intelligence = candidate_generation._step_result(state, "copywriting").get("image_intelligence")
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
                plan = build_beginner_friendly_plan(
                    event.title, event.content, research_output, intelligence_output,
                    has_image_candidate=has_image_candidate,
                )
            except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
                records.append({
                    "draft_id": str(draft.id), "generation_status": "error",
                    "failure_reasons": [f"plan_build_failed: {exc}"],
                })
                continue

            record = _new_record(draft, event, plan.model_dump(mode="json"))
            record["baseline_fact_safety"] = evaluate_candidate_fact_safety(
                draft.title or "", draft.body or "", event.title, event.content, research_facts,
            ).model_dump(mode="json")

            if brief.source_sufficiency == SourceSufficiency.EMPTY:
                record["generation_status"] = "skipped_insufficient_source"
                record["failure_reasons"] = ["empty_source_skip_candidate"]
                records.append(record)
                continue
            if dry_run:
                record["generation_status"] = "dry_run"
                record["failure_reasons"] = ["dry_run"]
                records.append(record)
                continue
            if not live_allowed:
                record["generation_status"] = "live_not_allowed"
                record["failure_reasons"] = ["live_not_allowed_missing_env_opt_in_or_flags"]
                records.append(record)
                continue
            if cases_with_live_attempt >= effective_max:
                record["generation_status"] = "skipped_max_cases_reached"
                record["failure_reasons"] = ["max_cases_reached"]
                records.append(record)
                continue

            cases_with_live_attempt += 1
            assert gateway is not None and prompt is not None
            try:
                result = await candidate_generation.generate_with_retry(
                    gateway, prompt, pricing_catalog,
                    news_event_title=event.title, news_event_category=event.category.value,
                    language=settings.default_content_language,
                    research_output=research_output, intelligence_output=intelligence_output,
                    brief=brief, plan=plan, task=task, event=event,
                    draft_id=str(draft.id), sequence_start=total_calls,
                )
                total_calls += result["calls_made"]
                total_cost += result["total_estimated_cost_usd"]

                if result["final_status"] == "valid":
                    candidate = result["candidate"]
                    record["candidate_generated"] = True
                    record["generation_status"] = "valid"
                    record["candidate_text"] = {
                        "title": candidate.get("title", ""), "body": candidate.get("body", ""),
                    }
                    record["candidate_fact_safety"] = evaluate_candidate_fact_safety(
                        candidate.get("title", ""), candidate.get("body", ""),
                        event.title, event.content, research_facts, plan,
                    ).model_dump(mode="json")
                else:
                    record["generation_status"] = "still_empty"
                    record["failure_reasons"] = [
                        f"generation_empty:{result['final_empty_output_reason']}"
                    ]
                record["generation_attempts"] = result["attempts"]
                record["generation_retry_used"] = result["retry_used"]
                record["generation_cost_usd"] = result["total_estimated_cost_usd"]
            except Exception as exc:  # noqa: BLE001 - continue the batch, never abort on one case
                record["generation_status"] = "error"
                record["failure_reasons"] = [f"generation_error: {exc}"]
                logger.warning("stage2_candidate_generation_failed", extra={"draft_id": str(draft.id)})
            records.append(record)

    summary = {
        "sample_size": len(sample_ids),
        "cases_processed": len(records),
        "dry_run": dry_run,
        "live_allowed": live_allowed,
        "resumed_from_existing": len(existing),
        "cases_with_live_attempt": cases_with_live_attempt,
        "total_calls_made": total_calls,
        "total_estimated_cost_usd": round(total_cost, 6),
        "candidate_generated_count": sum(1 for r in records if r.get("candidate_generated")),
        "not_yet_reviewed_count": sum(
            1 for r in records if r.get("editorial_preference") == "not_yet_reviewed"
        ),
    }
    output = {"summary": summary, "records": records}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(json.dumps(summary, indent=2))
    return output


def record_editorial_preference(
    output_path: str, draft_id: str, preference: str,
    *, notes: str | None = None, failure_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Human-only mutation path: edits ONLY the local --output JSON artifact this script itself
    produced. No database session is opened anywhere in this function - `ContentDraft`/
    `EditorialTask` cannot be touched by this code path even in principle."""
    if preference not in VALID_EDITORIAL_PREFERENCES:
        raise ValueError(
            f"invalid editorial_preference: {preference!r} "
            f"(must be one of {sorted(VALID_EDITORIAL_PREFERENCES)})"
        )
    path = Path(output_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("records", [])
    matched = next((r for r in records if r.get("draft_id") == draft_id), None)
    if matched is None:
        raise ValueError(f"draft_id {draft_id!r} not found in {output_path}")

    matched["editorial_preference"] = preference
    if notes is not None:
        matched["editorial_notes"] = notes
    if failure_reasons:
        existing_reasons = matched.get("failure_reasons") or []
        matched["failure_reasons"] = list(dict.fromkeys([*existing_reasons, *failure_reasons]))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    return matched


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command")

    generate = subparsers.add_parser(
        "generate", help="Generate Stage 2 candidates alongside baseline production drafts.",
    )
    generate.add_argument("--sample-ids-file", required=True, help="JSON file: a list of ContentDraft UUID strings.")
    generate.add_argument("--max-cases", type=int, default=_MAX_CASES_WITH_LIVE_GENERATION,
                           help=f"Hard-capped at {_MAX_CASES_WITH_LIVE_GENERATION} regardless.")
    generate.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    generate.add_argument("--live", action="store_true", help="Disable dry-run. Still requires --confirm-paid-calls and the env opt-in.")
    generate.add_argument("--confirm-paid-calls", action="store_true", help="Explicit acknowledgment this may spend real API budget.")

    preference = subparsers.add_parser(
        "record-preference",
        help="Record a human's editorial preference against an existing generated case (no LLM call, no DB access).",
    )
    preference.add_argument("--output", default=_DEFAULT_OUTPUT_PATH)
    preference.add_argument("--draft-id", required=True)
    preference.add_argument("--preference", required=True, choices=sorted(VALID_EDITORIAL_PREFERENCES))
    preference.add_argument("--notes", default=None)
    preference.add_argument("--failure-reason", action="append", default=None, dest="failure_reasons")

    args = parser.parse_args()
    if args.command is None:
        parser.error("a command is required: 'generate' or 'record-preference'")
    return args


def main() -> None:
    setup_logging()
    args = _parse_args()

    if args.command == "record-preference":
        result = record_editorial_preference(
            args.output, args.draft_id, args.preference,
            notes=args.notes, failure_reasons=args.failure_reasons,
        )
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return

    with open(args.sample_ids_file, encoding="utf-8") as f:
        sample_ids = json.load(f)
    dry_run = not (args.live and args.confirm_paid_calls)
    asyncio.run(
        run_stage2_candidate_generation(
            sample_ids, dry_run=dry_run, max_cases=args.max_cases, output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
