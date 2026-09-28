"""Bounded natural-selection KAGE Telegram batch around the accepted single-event canary path.

Each story goes through exactly the accepted atomic path (production selector -> advisory-lock
claim -> same-event recheck -> unchanged ``run_content_cycle`` for that one event, per-story
envelope capped at ``MAX_COST``). This module only adds the bounded loop around it: attempt and
delivery limits, reserve-before-next-claim batch cost cap, fresh-session forensic verification
after every story, stop conditions, and a durable per-run manifest. It never changes selection,
generation, gate or delivery semantics, and never touches CONTENT_GENERATION_ENABLED.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

MIN_DESIRED_ATTEMPTS = 5
MAX_ATTEMPTS = 10
MAX_DELIVERIES = 10
PER_STORY_MAX_USD = Decimal("0.977229")  # text 0.746389 + visual 0.230840 (one ledger)
BATCH_HARD_CAP_USD = Decimal("3.74")
# Natural waiting window for the whole batch: 12h covers a full daytime news cycle without leaving
# an unattended process running overnight into a second one. Fewer than MIN_DESIRED_ATTEMPTS
# eligible events inside it ends cleanly as INSUFFICIENT_NATURAL_VOLUME.
NATURAL_WINDOW_SECONDS = 12 * 60 * 60
POLL_SECONDS = 15
EXPECTED_CHAT_ID = -1004297182444
EXPECTED_TOPIC_ID = 2
EXPECTED_FOOTER_TEXT = "\U0001F977 KAGE"  # 🥷 KAGE
RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")

# Non-delivered terminal outcomes that are normal editorial/safety results: the batch continues.
CONTINUE_OUTCOMES = frozenset({
    "BLOCKED_FACTUAL_GATE", "BLOCKED_LOCAL_GUARD", "BLOCKED_BOTH", "VISUAL_HOLD", "DUPLICATE_SUPERSEDED",
    "BLOCKED_EDITORIAL_USEFULNESS",
})
CLEAN_TERMINALS = frozenset({
    "COMPLETED_MAX_ATTEMPTS", "COMPLETED_MAX_DELIVERIES", "BUDGET_RESERVATION_EXHAUSTED",
    "NATURAL_WINDOW_ELAPSED", "INSUFFICIENT_NATURAL_VOLUME",
})


class BatchStop(Exception):
    """A hard stop condition. The batch ends immediately; nothing further is claimed."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class BatchLimits:
    min_desired_attempts: int = MIN_DESIRED_ATTEMPTS
    max_attempts: int = MAX_ATTEMPTS
    max_deliveries: int = MAX_DELIVERIES
    per_story_max_usd: Decimal = PER_STORY_MAX_USD
    batch_cap_usd: Decimal = BATCH_HARD_CAP_USD
    window_seconds: float = NATURAL_WINDOW_SECONDS
    poll_seconds: float = POLL_SECONDS


@dataclass
class BatchDeps:
    """Everything that touches the database, providers or Telegram, injected for testability."""

    select_top: Callable[[], Awaitable[dict | None]]
    publication_state: Callable[[UUID], Awaitable[dict]]
    claim: Callable[[UUID], Awaitable[bool]]
    recheck: Callable[[UUID], Awaitable[dict | None]]
    release: Callable[[bool], Awaitable[bool]]  # arg: lock was held; returns unlock integrity
    run_story: Callable[[UUID, dict], Awaitable[dict]]
    forensics: Callable[[UUID], Awaitable[dict]]


def validate_run_id(run_id: str | None) -> str:
    value = (run_id or "").strip()
    if not RUN_ID_RE.fullmatch(value):
        raise BatchStop("INVALID_RUN_ID", f"{run_id!r} must match {RUN_ID_RE.pattern}")
    return value


def claim_run_dir(out_dir: Path, run_id: str) -> Path:
    """Exclusively bind an output directory to one run id. Collision is a hard stop; nothing is
    ever overwritten, and a directory already bound to another run is never reused."""
    run_id = validate_run_id(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = out_dir / "RUN_ID.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        owner = lock.read_text(encoding="utf-8").strip()
        raise BatchStop("RUN_ID_COLLISION", f"{out_dir} already bound to run {owner!r}") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(run_id)
    if (out_dir / "manifest.json").exists():
        raise BatchStop("RUN_ID_COLLISION", f"{out_dir} already contains a manifest")
    return out_dir


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _story_cost(outcome: dict) -> tuple[Decimal, list[dict], bool]:
    """Per-stage costs; a dispatch without an actual cost is charged its reservation and flagged."""
    stages: list[dict] = []
    total = Decimal("0")
    gap = False
    for row in outcome.get("provider_dispatches") or []:
        actual = row.get("actual_cost_usd")
        if actual is None:
            gap = True
            charged = Decimal(str(row.get("reserved_max_cost_usd") or PER_STORY_MAX_USD))
        else:
            charged = Decimal(str(actual))
        total += charged
        stages.append({"stage": row.get("stage"), "model": row.get("model"), "status": row.get("status"),
                       "actual_cost_usd": actual, "charged_usd": str(charged)})
    return total, stages, gap


def _split_post(text: str | None) -> dict:
    lines = [line for line in (text or "").splitlines()]
    non_empty = [line for line in lines if line.strip()]
    return {
        "title": non_empty[0] if non_empty else None,
        "body": "\n".join(lines[1:-1]).strip() if len(non_empty) >= 3 else None,
        "footer": non_empty[-1] if non_empty else None,
    }


class BoundedNaturalBatch:
    def __init__(self, *, run_id: str, out_dir: Path, deps: BatchDeps, limits: BatchLimits = BatchLimits(),
                 git_commit: str = "", image_id: str = "",
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.run_id = validate_run_id(run_id)
        self.out_dir = out_dir
        self.deps = deps
        self.limits = limits
        self.clock = clock
        self.sleep = sleep
        self.attempts = 0
        self.deliveries = 0
        self.spent = Decimal("0")
        self.provider_calls = 0
        self._skipped: set[tuple[str, str]] = set()
        self.manifest: dict[str, Any] = {
            "run_id": self.run_id, "git_commit": git_commit, "image_id": image_id,
            "started_at_utc": _utc(), "finished_at_utc": None,
            "limits": {"min_desired_attempts": limits.min_desired_attempts, "max_attempts": limits.max_attempts,
                       "max_deliveries": limits.max_deliveries, "per_story_max_usd": str(limits.per_story_max_usd),
                       "batch_cap_usd": str(limits.batch_cap_usd), "window_seconds": limits.window_seconds},
            "stories": [], "skipped": [], "terminal_reason": None, "terminal_detail": None,
            "attempts": 0, "deliveries": 0, "cumulative_cost_usd": "0", "provider_calls": 0,
        }

    # -- persistence ---------------------------------------------------------------------------
    def _save(self) -> None:
        self.manifest.update(attempts=self.attempts, deliveries=self.deliveries,
                             cumulative_cost_usd=str(self.spent), provider_calls=self.provider_calls)
        _write_json(self.out_dir / "manifest.json", self.manifest)

    def _artifact(self, index: int, event_id: UUID, payload: dict) -> str:
        name = f"story-{index:02d}-{event_id}.json"
        _write_json(self.out_dir / name, payload)
        return name

    # -- loop ----------------------------------------------------------------------------------
    async def run(self) -> dict:
        deadline = self.clock() + self.limits.window_seconds
        try:
            while True:
                terminal = self._terminal_before_next_claim(deadline)
                if terminal:
                    return self._finish(terminal, "")
                story = await self._next_story()
                if story is None:
                    await self.sleep(self.limits.poll_seconds)
                    continue
                await self._verify_story(*story)
        except BatchStop as stop:
            return self._finish(stop.reason, stop.detail)
        except Exception as exc:  # noqa: BLE001 - any unexpected exception is a hard stop, never silent
            return self._finish("UNEXPECTED_EXCEPTION", f"{type(exc).__name__}: {exc}")

    def _terminal_before_next_claim(self, deadline: float) -> str | None:
        if self.attempts >= self.limits.max_attempts:
            return "COMPLETED_MAX_ATTEMPTS"
        if self.deliveries >= self.limits.max_deliveries:
            return "COMPLETED_MAX_DELIVERIES"
        # Reserve a full per-story worst case BEFORE claiming: the cap can never be exceeded.
        if self.spent + self.limits.per_story_max_usd > self.limits.batch_cap_usd:
            return "BUDGET_RESERVATION_EXHAUSTED"
        if self.clock() >= deadline:
            return ("INSUFFICIENT_NATURAL_VOLUME" if self.attempts < self.limits.min_desired_attempts
                    else "NATURAL_WINDOW_ELAPSED")
        return None

    async def _next_story(self) -> tuple[UUID, dict, dict] | None:
        selection = await self.deps.select_top()
        if selection is None:
            return None
        if not selection.get("valid"):
            if (selection.get("content_generation_tasks", 0) or selection.get("delivery_records", 0)
                    or not selection.get("analysis_fresh")):
                return None
            raise BatchStop("SELECTOR_DISAGREEMENT", str(selection.get("event_id")))
        event_id = UUID(str(selection["event_id"]))
        # Durable event-level duplicate guard, before any claim or provider call.
        if (await self.deps.publication_state(event_id)).get("already_delivered"):
            self._skip(event_id, "ALREADY_DELIVERED_BEFORE_CLAIM")
            return None
        if not await self.deps.claim(event_id):
            await self.deps.release(False)  # lock not held: only close the claim connection
            return None
        try:
            recheck = await self.deps.recheck(event_id)
            if not recheck or not recheck.get("valid"):
                benign = recheck and (recheck.get("content_generation_tasks", 0) or recheck.get("delivery_records", 0)
                                      or not recheck.get("analysis_fresh"))
                if not benign:
                    raise BatchStop("SAME_EVENT_RECHECK_FAILED", str(event_id))
                self._skip(event_id, "RECHECK_NO_LONGER_ELIGIBLE")
                return None
            if (await self.deps.publication_state(event_id)).get("already_delivered"):
                self._skip(event_id, "ALREADY_DELIVERED_AFTER_CLAIM")
                return None
            self.attempts += 1
            selection = {**selection, "claim_acquired_at_utc": _utc()}
            outcome = await self.deps.run_story(event_id, selection)
        finally:
            if not await self.deps.release(True):
                raise BatchStop("ADVISORY_LOCK_INTEGRITY", f"unlock failed for {event_id}")
        return event_id, selection, outcome

    def _skip(self, event_id: UUID, reason: str) -> None:
        key = (str(event_id), reason)
        if key in self._skipped:
            return
        self._skipped.add(key)
        self.manifest["skipped"].append({"event_id": str(event_id), "reason": reason, "at_utc": _utc()})
        self._save()

    async def _verify_story(self, event_id: UUID, selection: dict, outcome: dict) -> None:
        index = self.attempts
        cost, stage_costs, gap = _story_cost(outcome)
        self.spent += cost
        self.provider_calls += len(outcome.get("provider_dispatches") or [])
        record: dict[str, Any] = {
            "index": index, "event_id": str(event_id), "story_id": selection.get("story_id"),
            "title_at_selection": selection.get("title"), "selector_result": selection.get("selector_result"),
            "score": selection.get("score"), "claimed_at_utc": selection.get("claim_acquired_at_utc"),
            "provider_calls": len(outcome.get("provider_dispatches") or []), "stage_costs": stage_costs,
            "story_cost_usd": str(cost), "cumulative_cost_usd": str(self.spent),
            "task_id": None, "draft_id": None, "factual_gate": None, "outcome": None,
            "receipt_id": None, "telegram_message_id": None, "terminal_reason": None, "artifact": None,
        }
        self.manifest["stories"].append(record)
        try:
            await self._check_story(event_id, outcome, record, cost, gap)
        finally:
            self._save()

    async def _check_story(self, event_id: UUID, outcome: dict, record: dict, cost: Decimal, gap: bool) -> None:
        if gap:
            raise BatchStop("COST_ACCOUNTING_FAILURE", f"dispatch without actual cost for {event_id}")
        if cost > self.limits.per_story_max_usd or self.spent > self.limits.batch_cap_usd:
            raise BatchStop("HARD_BUDGET_VIOLATION", f"story ${cost}, cumulative ${self.spent}")
        cycle = outcome.get("cycle") or {}
        if cycle.get("generation_attempts") != 1 or [str(e) for e in cycle.get("event_ids") or []] != [str(event_id)]:
            raise BatchStop("ONE_EVENT_INVARIANT", json.dumps(cycle, default=str)[:300])
        sends = [s for s in outcome.get("sends") or [] if s.get("status") == "accepted"]
        if len(outcome.get("sends") or []) > 1 or len(sends) > 1:
            raise BatchStop("DUPLICATE_SEND", f"{len(outcome.get('sends') or [])} send calls for {event_id}")
        for send in outcome.get("sends") or []:
            if send.get("chat_id") != EXPECTED_CHAT_ID or send.get("topic_id") != EXPECTED_TOPIC_ID:
                raise BatchStop("DESTINATION_MISMATCH", f"chat={send.get('chat_id')} topic={send.get('topic_id')}")

        forensic = await self.deps.forensics(event_id)  # fresh process-independent DB session
        tasks = forensic.get("tasks") or []
        lineage = forensic.get("lineage")
        publication = forensic.get("publication") or {}
        record["artifact"] = self._artifact(record["index"], event_id, {"outcome": outcome, "forensic": forensic})
        if len(tasks) != 1 or not isinstance(lineage, dict):
            raise BatchStop("MISSING_DURABLE_LINEAGE", f"{len(tasks)} generation tasks, lineage={bool(lineage)}")
        identity = lineage.get("identity") or {}
        gate = lineage.get("publication_factual_gate")
        final = lineage.get("publication_outcome") or {}
        status = final.get("status")
        record.update(task_id=identity.get("generation_task_id"), draft_id=identity.get("draft_id"),
                      factual_gate=gate, outcome=status, receipt_id=identity.get("delivery_receipt_id"),
                      telegram_message_id=identity.get("telegram_message_id"))
        if not lineage.get("stages") or not status:
            raise BatchStop("MISSING_DURABLE_LINEAGE", f"stages/outcome missing for {event_id}")
        if status == "GATE_TECHNICAL_BLOCK":
            raise BatchStop("FACTUAL_GATE_TECHNICAL_FAILURE", str(event_id))
        if len(publication.get("delivered_task_ids") or []) > 1:
            raise BatchStop("DUPLICATE_DELIVERED_EVENT", str(event_id))

        if sends:
            send = sends[0]
            receipts = publication.get("sent_receipt_ids") or []
            if (status != "DELIVERED" or final.get("message_id") != send.get("message_id")
                    or identity.get("telegram_message_id") != send.get("message_id") or not receipts
                    or identity.get("delivery_receipt_id") not in receipts):
                raise BatchStop("RECEIPT_OUTCOME_MISMATCH",
                                f"status={status} msg={send.get('message_id')} receipts={receipts}")
            post = _split_post(send.get("text") or send.get("caption"))
            record["delivered_post"] = {
                **post, "message_id": send.get("message_id"), "method": send.get("method"),
                "buttons": send.get("buttons"), "media": send.get("sent_photo"),
                "footer_matches_release": post["footer"] == EXPECTED_FOOTER_TEXT,
            }
            self.deliveries += 1
            record["terminal_reason"] = "DELIVERED"
            if post["footer"] != EXPECTED_FOOTER_TEXT:
                raise BatchStop("FOOTER_CONTRACT_MISMATCH", repr(post["footer"]))
            return
        if status == "DELIVERED" or publication.get("already_delivered") or publication.get("sent_receipt_ids"):
            raise BatchStop("RECEIPT_OUTCOME_MISMATCH", f"no send observed but status={status}")
        if status not in CONTINUE_OUTCOMES:
            raise BatchStop("UNEXPECTED_TERMINAL_OUTCOME", f"{status} for {event_id}")
        record["terminal_reason"] = status

    def _finish(self, reason: str, detail: str) -> dict:
        self.manifest.update(terminal_reason=reason, terminal_detail=detail or None,
                             clean=reason in CLEAN_TERMINALS, finished_at_utc=_utc())
        self._save()
        return self.manifest


# ------------------------------------------------------------------------------------------------
# Production wiring (the accepted canary's own selector / claim / recheck / run path, unchanged).
# ------------------------------------------------------------------------------------------------

async def _production_main() -> int:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from bot.loader import create_bot
    from core.config import settings
    from core.logging import setup_logging
    from database.models.editorial_task import EditorialTask
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from redis.asyncio import Redis
    from schemas.editorial_route import EditorialDestination
    from scripts import _kage_telegram_atomic_natural_canary as canary
    from scripts._kage_telegram_hard_cost_canary import _configure_frozen_canary_settings
    from services.kage_content_lineage_audit import reconstruct_lineage
    from services.kage_delivery_truth import event_publication_state
    from services.kage_telegram_canary_envelope import maximum_canary_cost, validate_request_envelope_contracts
    from services.news_telegram_presentation import build_ninja_pulse_footer_html
    from services.pricing_catalog import ModelRegistryPricingCatalog
    from services.telegram_routing import resolve_route

    setup_logging()
    run_id = validate_run_id(os.environ.get("KAGE_BATCH_RUN_ID"))
    out_dir = claim_run_dir(Path(os.environ.get("KAGE_BATCH_OUTPUT_DIR", "/batch")), run_id)
    if settings.content_generation_enabled:
        raise BatchStop("CONTENT_GENERATION_ENABLED_TRUE", "persistent worker config must stay paused")
    _configure_frozen_canary_settings()
    if resolve_route(EditorialDestination.NEWS) != canary.EXPECTED_ROUTE:
        raise BatchStop("DESTINATION_MISMATCH", "NEWS route changed")
    if canary.EXPECTED_ROUTE.chat_id != EXPECTED_CHAT_ID or canary.EXPECTED_ROUTE.topic_id != EXPECTED_TOPIC_ID:
        raise BatchStop("DESTINATION_MISMATCH", "canary route constant changed")
    if maximum_canary_cost() != PER_STORY_MAX_USD or canary.MAX_COST != PER_STORY_MAX_USD:
        raise BatchStop("HARD_BUDGET_VIOLATION", "per-story worst case changed")
    if build_ninja_pulse_footer_html() != '\U0001F977 <a href="https://t.me/kage_journal">KAGE</a>':
        raise BatchStop("FOOTER_CONTRACT_MISMATCH", "release footer is not the Unicode ninja footer")
    contracts = validate_request_envelope_contracts()
    prompts = FilePromptRepository(canary.PROMPTS_ROOT)
    versions = {name: prompts.resolve(name, version).version for name, version in (
        ("research", "5"), ("intelligence", "4"), ("copywriting", "11.10"),
        ("quality", "9.2"), ("publication_factual_gate", "1"))}
    print(json.dumps({"event": "KAGE_BATCH_PREARM_VALIDATION", "run_id": run_id,
                      "request_envelope_output_contracts": contracts, "runtime_versions": versions,
                      "per_story_max_usd": str(PER_STORY_MAX_USD), "batch_cap_usd": str(BATCH_HARD_CAP_USD),
                      "max_attempts": MAX_ATTEMPTS, "max_deliveries": MAX_DELIVERIES,
                      "window_seconds": NATURAL_WINDOW_SECONDS, "provider_calls": 0}), flush=True)

    isolated = Redis.from_url(canary._configure_isolated_canary_redis(), decode_responses=True)
    if not await isolated.ping() or await isolated.dbsize() != 0:
        raise BatchStop("COST_ACCOUNTING_FAILURE", "isolated Redis unavailable or not empty")
    ai = assemble_ai_integration_layer(settings, prompts, redis_client=isolated)
    pricing = ModelRegistryPricingCatalog(build_model_registry())
    controller = canary.AtomicNaturalCanary()
    ro_engine = create_async_engine(settings.database_url,
                                    connect_args={"server_settings": {"default_transaction_read_only": "on"}})

    async def publication_state(event_id: UUID) -> dict:
        async with controller._read_only_session() as session:
            return await event_publication_state(session, event_id)

    async def release(held: bool) -> bool:
        conn, key = controller.claim_connection, controller.claim_key
        ok = True
        if conn is not None and not conn.is_closed():
            if held and key is not None:
                ok = bool(await conn.fetchval("SELECT pg_advisory_unlock($1::bigint)", key))
            await conn.close()
        controller.claim_connection = None
        controller.claim_key = None
        return ok

    async def run_story(event_id: UUID, selection: dict) -> dict:
        # A fresh bot per story: _run_claimed() wraps it with a one-delivery hard cap and closes it.
        return await canary._run_claimed(event_id, selection, ai, create_bot(), prompts, pricing)

    async def forensics(event_id: UUID) -> dict:
        async with ro_engine.connect() as conn:
            async with AsyncSession(bind=conn) as session:
                tasks = (await session.execute(select(EditorialTask.id).where(
                    EditorialTask.event_id == event_id,
                    EditorialTask.workflow["workflow_name"].as_string() == "CONTENT_GENERATION",
                ))).scalars().all()
                lineage = await reconstruct_lineage(session, tasks[0]) if len(tasks) == 1 else None
                publication = await event_publication_state(session, event_id)
            await conn.rollback()
        return {"tasks": [str(t) for t in tasks], "lineage": lineage, "publication": publication}

    batch = BoundedNaturalBatch(
        run_id=run_id, out_dir=out_dir,
        deps=BatchDeps(select_top=controller.select_top, publication_state=publication_state,
                       claim=controller.claim, recheck=controller.recheck_same_event, release=release,
                       run_story=run_story, forensics=forensics),
        git_commit=os.environ.get("KAGE_BATCH_GIT_COMMIT", ""), image_id=os.environ.get("KAGE_BATCH_IMAGE_ID", ""),
    )
    try:
        manifest = await batch.run()
    finally:
        await controller.close()
        await ro_engine.dispose()
        await isolated.aclose()
    print(json.dumps({"event": "KAGE_BATCH_FINISHED", **{k: manifest[k] for k in (
        "run_id", "terminal_reason", "terminal_detail", "clean", "attempts", "deliveries",
        "cumulative_cost_usd", "provider_calls")}}, ensure_ascii=False), flush=True)
    return 0 if manifest.get("clean") else 3


def main() -> int:
    try:
        return asyncio.run(_production_main())
    except BatchStop as stop:
        print(json.dumps({"event": "KAGE_BATCH_REFUSED", "reason": stop.reason, "detail": stop.detail,
                          "provider_calls": 0}), flush=True)
        return 4


if __name__ == "__main__":
    sys.exit(main())
