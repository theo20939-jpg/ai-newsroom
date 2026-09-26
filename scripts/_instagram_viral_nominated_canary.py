"""KAGE INSTAGRAM - FIRST REAL VIRAL CAROUSEL CANARY through the ACCEPTED selection path (founder-approved event, 2026-09-26).

Exactly the worker's per-slot path (worker.content_cycle._run_instagram_automatic_trigger), with only the database loading replaced:
  fresh READ-ONLY production pool (JSON lines) -> services.instagram_viral_nomination.nominate_viral_events (the full KAGE pool, the
  accepted gate) -> nominated_reads (the viral slot's shortlist, ONE entry per event) -> worker.content_cycle._viral_evidence_copy (the
  worker's own copy order and bound, the existing acquisition path, the evidence preflight) -> STOP unless PASS -> treatment of the copy that
  carries the evidence -> facts = package.director_evidence() + NEWS_ANALYSIS facts + chronology_fact(event) -> evaluate_and_submit_
  instagram_candidate(feed_format=MEME_TREND): Phase A -> Creative Director (+ its accepted technical recovery / one editorial correction)
  -> deterministic checks -> semantic judge -> image selection / generation -> render.
The event's copies are read-only copied from production into the local scratch DB; acquisition / image rows land there only.
Image generation is LIVE in this process only (the accepted no-photo => generated rule) behind an isolated, capped ledger; the LLM goes
through the harness provider guard (worst-case refused above the cap). No Telegram send (captured), no production write, no publication.
Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_viral_nominated_canary.py <pool.jsonl> <members.jsonl> <out dir>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("KAGE_E2E_CAP_USD", os.environ.get("KAGE_CANARY_LLM_CAP_USD", "0.45"))

import scripts._instagram_e2e_week as harness  # noqa: E402  (scratch DB env, provider guard, render / delivery capture)

from core.config import settings  # noqa: E402

IMAGE_CAP = Decimal(os.environ.get("KAGE_CANARY_IMAGE_CAP_USD", "0.55"))
LLM_NAMESPACE = "kage_viral_nominated_llm_20260926"
IMAGE_NAMESPACE = "kage_viral_nominated_images_20260926"


async def main() -> None:
    pool_path, members_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    settings.article_acquisition_mode = "enforce"  # production's mode
    settings.image_intelligence_mode = "shadow"  # production's mode
    settings.image_candidate_persistence_mode = "finalists"  # production's mode
    settings.image_storage_root = str(out / "_image_storage")
    settings.instagram_image_generation_mode = "live"  # in-process only, capped below
    assert harness.SCRATCH_DB in settings.database_url

    from redis.asyncio import Redis
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import integrations.llm_gateway.boot as boot
    import scripts._instagram_viral_story_audit as audit
    import services.instagram_creative_media as media_mod
    import worker.content_cycle as cc
    from database.models.editorial_task import EditorialTask, TaskStatus
    from database.models.news_event import NewsEvent
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.workflow import WorkflowType
    from services.budget_guard import RedisBudgetGuard
    from services.budgeted_image_execution import BudgetedImageExecutor
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.instagram_automatic_trigger import evaluate_and_submit_instagram_candidate
    from services.instagram_evidence_package import BLOCKING
    from services.instagram_feed_product import DAILY_SHORTLIST_PER_FORMAT, FeedFormat, _clean_title, kage_core, read_candidate
    from services.instagram_viral_nomination import chronology_fact, nominate_viral_events, nominated_reads, viral_evidence_preflight
    from services.instagram_viral_story_gate import ClusterMember
    from services.pricing_catalog import ModelRegistryPricingCatalog

    # --- 1. the viral slot: nomination from the full fresh KAGE pool (same inputs the planner would load) ------------------------------
    rows, members = audit.load(pool_path, members_path)
    now = audit._dt(rows[0]["now"])
    assert now is not None
    by_id = {r["id"]: r for r in rows}
    headlines = [ClusterMember(title=r["title"] or "", source_id=r["source_name"] or "", source_name=r["source_name"] or "",
                               seen_at=audit._dt(r["published_at"]) or audit._dt(r["collected_at"]), collected_at=audit._dt(r["collected_at"]))
                 for r in rows]
    seen: set[str] = set()
    candidates = []
    for r in rows:
        if r["id"] in seen or now - audit._dt(r["collected_at"]) > timedelta(hours=24):
            continue
        seen.add(r["id"])
        c = audit.candidate_of(r, members)
        if read_candidate(c).format is not FeedFormat.REJECT and kage_core(_clean_title(c.title, c.source_name.lower())):
            candidates.append(c)
    nomination = nominate_viral_events(candidates, headlines=headlines,
                                       evidence={c.id: by_id[c.id].get("article_text") or "" for c in candidates}, now=now)
    shortlist = nominated_reads(nomination, DAILY_SHORTLIST_PER_FORMAT)
    if not shortlist:
        raise SystemExit("NO VIRAL STORY - nothing nominated; the canary does not pick a weaker story")
    planned, read = shortlist[0]
    event = read.viral_event
    run: dict = {"now": rows[0]["now"], "pool": len(candidates), "distinct_events": len(nomination.events),
                 "eligible_events": [e.key for e in nomination.eligible], "selected_event": event.key, "copies": list(event.candidate_ids),
                 "planned_copy": {"id": planned.id, "source": planned.source_name, "title": planned.title},
                 "verdict": {"actuality": event.verdict.actuality.type, "actuality_reason": event.verdict.actuality.date_source,
                             "underlying_time": event.verdict.actuality.underlying_time,
                             "disclosed_at": str(event.verdict.actuality.disclosed_at), "newly_disclosed": list(event.verdict.actuality.newly_disclosed),
                             "kage": list(event.verdict.kage_core), "broad": event.verdict.broad_interest, "strength": event.verdict.strength,
                             "mechanisms": list(event.verdict.mechanisms), "momentum": event.verdict.momentum,
                             "momentum_evidence": list(event.verdict.momentum_signals), "hook": event.verdict.hook, "reason": event.verdict.reason},
                 "outlets": list(event.outlets), "first_seen": str(event.first_seen)}
    if "government" not in event.key.lower():
        raise SystemExit(f"the nominated event is not the founder-approved one: {event.key!r} - stopping, never switching events")

    # --- providers: capped, isolated ledgers ---------------------------------------------------------------------------------------
    diag = Redis.from_url(harness.DIAG_REDIS_URL, decode_responses=True)
    for namespace in (LLM_NAMESPACE, IMAGE_NAMESPACE):
        if await diag.get(f"phase7:cost_ledger:{namespace}"):
            raise SystemExit(f"ledger {namespace} already holds spend - this canary never runs twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(harness.CAP),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=LLM_NAMESPACE)
    repo = FilePromptRepository(harness.ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    harness._install_provider_guard(pricing, CostEstimator(pricing), models, RedisCostTracker(diag, pricing, ledger_namespace=LLM_NAMESPACE))
    suit = harness._install_capture()
    image_guard = RedisBudgetGuard(diag, settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(IMAGE_CAP),
                                                                     "redis_unavailable_policy": "fail_closed"}), ledger_namespace=IMAGE_NAMESPACE)
    media_mod.build_budgeted_image_executor = lambda: BudgetedImageExecutor(budget_guard=image_guard)
    generated: list = []
    real_generate = media_mod._execute_generated_asset

    async def record_generation(**kw):  # observation only
        asset = await real_generate(**kw)
        generated.append({"asset_key": kw.get("asset_key"), "status": asset.status, "accounted_usd": asset.accounted_cost_usd,
                          "reserved_usd": asset.reserved_cost_usd, "provider_request_id": asset.provider_request_id, "prompt": asset.prompt})
        if asset.image is not None:
            (out / "post" / "generated").mkdir(parents=True, exist_ok=True)
            asset.image.save(out / "post" / "generated" / f"asset_{kw.get('asset_key')}.png")
        return asset

    media_mod._execute_generated_asset = record_generation

    # observation only: every copy the worker's own _viral_evidence_copy acquires, with the preflight it gets
    attempts: list = []
    real_package = cc._feed_evidence_package

    async def record_package(session, copy_id, row, slot_format):
        package = await real_package(session, copy_id, row, slot_format)
        body = [item.exact_text for item in (*package.steps, *package.facts, *package.limitations)]
        pf = viral_evidence_preflight(event, title=row.title or "", body_lines=body, published_at=getattr(row, "published_at", None), now=now)
        n = len(attempts) + 1
        harness._write(out / "post" / "evidence_attempts" / f"{n:02d}_package.json", package)
        attempts.append({"order": n, "event_id": str(copy_id), "source": by_id.get(str(copy_id), {}).get("source_name"), "title": row.title,
                         "url": row.url, "acquisition": [{"type": s.source_type, "status": s.status, "chars": len(s.text or "")} for s in package.sources],
                         "package_quality": package.quality, "body_chars": sum(len(b) for b in body), "preflight": pf.status,
                         "checks": pf.checks, "reason": pf.reason})
        return package

    cc._feed_evidence_package = record_package

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    harness.STATE["post"], harness.STATE["post_dir"] = "post", out / "post"
    verdicts: list = []
    suit.set_verdict_sink(verdicts)
    async with factory() as session:
        for cid in event.candidate_ids:
            if await session.get(NewsEvent, UUID(cid)) is None:
                raise SystemExit(f"copy {cid} is not in the scratch DB - copy it read-only from production first")
        planned_id = UUID(planned.id)
        planned_row = await session.get(NewsEvent, planned_id)
        # --- 2. the worker's own evidence step ----------------------------------------------------------------------------------
        event_id, event_row, package, preflight = await cc._viral_evidence_copy(
            session, event, planned_id, planned_row, slot_format=FeedFormat.MEME_TREND, now=now)
        await session.commit()
        run.update(evidence_attempts=attempts, evidence_copy={"event_id": str(event_id), "title": event_row.title, "url": event_row.url},
                   preflight={"status": preflight.status, "checks": preflight.checks, "reason": preflight.reason})
        harness._write(out / "post" / "evidence_package.json", package)
        if preflight.status != "PASS":
            run["reason"] = f"STOPPED: evidence preflight {preflight.status} on every allowed copy - no generation"
        elif package.quality == BLOCKING:
            run["reason"] = f"STOPPED: evidence package BLOCKING ({package.why})"
        else:
            # --- 3. the worker's creative boundary --------------------------------------------------------------------------------
            treatment = await cc._classify_event_for_router_treatment(session, event_id)
            na_task = await session.scalar(select(EditorialTask).where(
                EditorialTask.event_id == event_id, EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                EditorialTask.status == TaskStatus.COMPLETED).limit(1))
            facts = package.director_evidence() + [f[:800] for f in cc._extract_research_facts(na_task.workflow if na_task else None) if f]
            chronology = chronology_fact(event)
            if chronology:
                facts.append(chronology)
            run.update(treatment={"treatment": treatment.treatment, "reason": treatment.reason}, director_facts=facts)
            outcome = await evaluate_and_submit_instagram_candidate(
                session, AsyncMock(), event_id=str(event_id), event_title=event_row.title or "", treatment=treatment, research_facts=facts,
                gateway=layer.gateway, prompt_repository=repo, source_url=event_row.url, phase_a_enabled=True, feed_format=FeedFormat.MEME_TREND)
            await session.commit()
            run.update(reason=outcome.reason, gate=outcome.gate_decision, delivery=outcome.delivery_reason, chosen_format=outcome.chosen_format)
    run.update(vision_verdicts=verdicts, generated=generated, llm_calls=harness.STATE["calls"], llm_spent_usd=str(harness.STATE["spent"]),
               llm_ledger_usd=await diag.get(f"phase7:cost_ledger:{LLM_NAMESPACE}"),
               image_ledger_usd=await diag.get(f"phase7:cost_ledger:{IMAGE_NAMESPACE}"))
    harness._write(out / "outcome.json", run)
    print(json.dumps({k: run.get(k) for k in ("selected_event", "preflight", "reason", "gate", "chosen_format", "llm_spent_usd", "image_ledger_usd")}
                     | {"attempts": [(a["source"], a["preflight"]) for a in attempts]}, ensure_ascii=False, indent=1, default=str))
    await engine.dispose()
    await diag.aclose()


if __name__ == "__main__":
    asyncio.run(main())
