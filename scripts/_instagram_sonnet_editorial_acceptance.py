"""KAGE INSTAGRAM - CONTROLLED EDITORIAL ACCEPTANCE on the saved Claude Sonnet 5.5 story with the NEW evidence (founder task 2026-09-30,
after 1a271eb). NOT a natural canary: no nomination, no selection, no acquisition, no image, no render, no Telegram.

Exactly the call the final natural acceptance made (scripts/_instagram_viral_nominated_canary.py -> services.instagram_automatic_trigger
.evaluate_and_submit_instagram_candidate, feed_format=MEME_TREND, phase_a_enabled=True), with ONE input changed: the evidence package is
rebuilt by the current code (1a271eb) from the SAVED real sources of the same copy, with the event's own saved verdict (ai_launch). Everything
the trigger does up to and including the Director sequence runs for real: Phase A -> Director -> deterministic validation -> semantic judge
-> at most ONE editorial correction -> final validation + judge. The run STOPS at the first visual step (the trigger's exact-subject media
preference, which only a finished carousel reaches) - that stop carries the final carousel out.

Isolation: the database is a COPY of the canary scratch DB (kage_sonnet_acc_20260930) in its state BEFORE the 29 Sep run's review delivery
(that run's 1 delivery + 1 draft + 1 plan removed in the copy only): the same story re-run would otherwise stop at the delivery idempotency /
duplicate guard before the Director. Image generation and Telegram delivery are hard-disabled as a second line of defence.
Spend: only PHASE_A / DIRECTOR / SEMANTIC_JUDGE requests may be sent (anything else is refused before sending); a request is refused before
sending when the spend so far plus 1.3x what the same kind actually cost in the saved run would pass $0.15, and nothing is sent once $0.15 is
reached. The harness provider guard (worst case vs its own cap, max_retries=0, one model) stays in front of every request.
Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_sonnet_editorial_acceptance.py <out dir>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["KAGE_E2E_CAP_USD"] = "0.30"  # the harness worst-case guard; the binding $0.15 limit is enforced below on real spend
os.environ["KAGE_E2E_NAMESPACE"] = "kage_sonnet_editorial_acceptance_20260930"

import scripts._instagram_e2e_week as harness  # noqa: E402  (scratch DB env, provider guard, diagnostics capture)

from core.config import settings  # noqa: E402

ACCEPTANCE_DB = "kage_sonnet_acc_20260930"
# RESUME (founder task 2026-09-30, after the first run stopped at its $0.15 limit): the SAME run continues. The two calls it already paid for
# (Phase A, the whitespace-runaway Director) are REPLAYED from its saved responses - matched by request content (clock line aside), never by
# position - and cost nothing again; the ledger and the spend carry the $0.085694 already spent; the cap is $0.30 CUMULATIVE, checked BEFORE
# every live request as spend so far + that request's worst case (the gateway guard and the harness guard both enforce it). Live: only
# what the accepted pipeline itself sends next - the Director's ONE technical recovery, the judge, at most ONE editorial correction and its
# judge. Phase A never goes live (a different Phase A request would be a divergence, refused before sending).
RESUME = "--resume" in sys.argv
PRIOR_SPEND = Decimal("0.085694")
LIMIT = Decimal("0.30") if RESUME else Decimal("0.15")
RESUME_LIVE = {"DIRECTOR": 2, "SEMANTIC_JUDGE": 2}  # recovery + correction; first judge + the correction's judge - the pipeline's own bounds
EVENT_ID = "c728f8d6-248a-4ea0-83bf-20a9520d4007"
ALLOWED_KINDS = {"PHASE_A", "DIRECTOR", "SEMANTIC_JUDGE"}
# what each kind actually cost in the saved natural acceptance run (outcome.json llm_calls): the projection basis for the $0.15 limit
SAVED_ACTUAL = {"PHASE_A": Decimal("0.008916"), "DIRECTOR": Decimal("0.054928"), "SEMANTIC_JUDGE": Decimal("0.005786")}
FIXTURES = harness.ROOT / "tests/fixtures"


class EditorialDone(Exception):
    """Raised at the first visual step: the editorial path is complete; carries the final carousel."""

    def __init__(self, carousel):
        super().__init__("editorial path complete - stopped before any media / image / render / delivery work")
        self.carousel = carousel


def install_limits() -> None:
    from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter

    guarded = OpenAIAdapter.generate  # the harness guard, already installed

    async def limited(self, request):
        kind = harness._call_kind(request)
        if kind not in ALLOWED_KINDS:
            harness.STATE["calls"].append({"post": harness.STATE["post"], "kind": kind, "status": "REFUSED_NOT_AUTHORISED", "cost_usd": "0"})
            raise harness.SafeStop(f"{kind} is not authorised in this acceptance run - refused before sending")
        projected = harness.STATE["spent"] + SAVED_ACTUAL[kind] * Decimal("1.3")
        if harness.STATE["spent"] >= LIMIT or projected > LIMIT:
            harness.STATE["calls"].append({"post": harness.STATE["post"], "kind": kind, "status": "REFUSED_LIMIT", "cost_usd": "0",
                                           "spent_before": str(harness.STATE["spent"]), "projected": str(projected)})
            raise harness.SafeStop(f"{kind}: spent {harness.STATE['spent']} + projected would pass ${LIMIT} - refused before sending")
        return await guarded(self, request)

    OpenAIAdapter.generate = limited


def install_resume(prev_calls: Path, out: Path) -> dict:
    """The first run's paid calls are replayed for the SAME request; everything else is live within RESUME_LIVE and the cumulative cap."""
    import difflib

    from integrations.llm_gateway.cache.coordinator import CacheCoordinator
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter

    queues: dict[str, list[dict]] = {}
    for path in sorted(prev_calls.glob("*.json")):
        call = json.loads(path.read_text(encoding="utf-8"))
        queues.setdefault(call["record"]["kind"], []).append({"file": path.name, **call})
    log: dict = {"replayed": [], "live": [], "refused": []}
    guarded = OpenAIAdapter.generate  # the harness guard: max_retries=0, one model, spend + worst case vs the cumulative cap

    def request_text(request) -> list[dict]:
        return [{"role": m.role, "text": [p.text for p in m.content if getattr(p, "type", None) == "text"]} for m in request.messages]

    def lines(text: list[dict]) -> list[str]:
        return "\n".join(t for m in text for t in m["text"]).splitlines()

    def normalized(text: list[dict]) -> list[str]:
        return [line for line in lines(text) if not line.startswith("BUSINESS CONTEXT AS OF:")]  # the prompt's own clock only

    async def replay_or_live(self, request):
        kind = harness._call_kind(request)
        now_text = request_text(request)
        match = next((c for c in queues.get(kind, []) if normalized(c["request"]) == normalized(now_text)), None)
        if match is not None:
            queues[kind].remove(match)
            diff = [d for d in difflib.unified_diff(lines(match["request"]), lines(now_text), lineterm="", n=0)
                    if d[:1] in "+-" and d[:3] not in ("+++", "---")]
            log["replayed"].append({"kind": kind, "saved_call": match["file"], "request_identical_except_clock": True, "diff_lines": diff,
                                    "already_paid_usd": match["record"].get("cost_usd"), "finish_reason": match["record"].get("finish_reason")})
            harness._write(out / "post" / "calls" / f"replayed_{match['file']}", {"saved_call": match["file"], "diff_lines": diff,
                                                                                 "request_now": now_text})
            return GenerateResponse.model_validate(match["response"])
        if RESUME_LIVE.get(kind, 0) <= 0:
            log["refused"].append({"kind": kind, "reason": "not an authorised live call"})
            raise harness.SafeStop(f"resume: a live {kind} request is not authorised - refused before sending")
        before = len(harness.STATE["calls"])
        try:
            response = await guarded(self, request)
        except harness.SafeStop as exc:  # the cumulative cap: the pending call and its reservation are reported, nothing is sent
            log["refused"].append({"kind": kind, "reason": str(exc), "spent_before": str(harness.STATE["spent"])})
            raise
        RESUME_LIVE[kind] -= 1
        log["live"].append({"kind": kind, **(harness.STATE["calls"][-1] if len(harness.STATE["calls"]) > before else {})})
        return response

    OpenAIAdapter.generate = replay_or_live

    async def no_lookup(self, *_a, **_k):  # every request reaches the replay above; no cached answer stands in for a live call
        return None

    async def no_store(self, *_a, **_k):
        return None

    CacheCoordinator.lookup = no_lookup
    CacheCoordinator.store = no_store
    return log


def evidence_package(title: str):
    from services.instagram_evidence_package import EvidenceSource, SourceMedia, assemble_package

    saved = json.loads((FIXTURES / "instagram_launch_substance/saved_packages.json").read_text(encoding="utf-8"))["sonnet_en"]
    run = json.loads((FIXTURES / "instagram_sonnet55_acceptance/saved_run.json").read_text(encoding="utf-8"))
    assert saved["premise"] == title, "the saved sources belong to another copy"
    media_line = run["director_input"]["allowed_evidence"][-1]  # 'SOURCE MEDIA: 1600x800 source image available' - the saved truth
    assert media_line.startswith("SOURCE MEDIA: 1600x800")
    media = SourceMedia(status="AVAILABLE", url="https://9to5mac.com/wp-content/uploads/sites/6/2026/07/claude.webp?w=1600", width=1600,
                        height=800, mime_type="image/jpeg", source="rss_inline_image", reason="validated source image (saved run)")
    launch = bool({"ai_launch", "device_launch", "software_launch"} & set(saved["event_verdict"]["mechanisms"]))
    return assemble_package(post_id=EVENT_ID, fmt=saved["format"], premise=title, sources=[EvidenceSource(**s) for s in saved["sources"]],
                            media=media, launch=launch), saved["event_verdict"]


async def main(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    settings.instagram_image_generation_mode = "live"  # as in the saved run: the Director is told generated media is available ...
    settings.image_intelligence_mode = "shadow"
    settings.image_storage_root = str(out / "_image_storage")

    from redis.asyncio import Redis
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import integrations.llm_gateway.boot as boot
    import services.instagram_automatic_trigger as trigger
    import services.instagram_creative_media as media_mod
    import services.instagram_exact_subject_media as exact_mod
    import worker.content_cycle as cc
    from database.models.editorial_task import EditorialTask, TaskStatus
    from database.models.news_event import NewsEvent
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.workflow import WorkflowType
    from services.budget_guard import RedisBudgetGuard
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.instagram_automatic_trigger import evaluate_and_submit_instagram_candidate
    from services.instagram_feed_product import FeedFormat
    from services.pricing_catalog import ModelRegistryPricingCatalog

    # ... but no image is ever generated and nothing is delivered (the run stops earlier; these refuse if it did not)
    async def no_generation(**_kw):
        raise harness.SafeStop("image generation is not authorised in this acceptance run")

    async def no_delivery(*_a, **_kw):
        raise harness.SafeStop("delivery is not authorised in this acceptance run")

    media_mod._execute_generated_asset = no_generation
    trigger.deliver_instagram_package = no_delivery

    def stop_at_visuals(carousel, _keys):
        raise EditorialDone(carousel)

    exact_mod.prefer_exact_subject_media = stop_at_visuals

    diag = Redis.from_url(harness.DIAG_REDIS_URL, decode_responses=True)
    ledger = await diag.get(f"phase7:cost_ledger:{harness.NAMESPACE}")
    if RESUME:
        # the same run continues from exactly what it already spent - never a reset ledger, never a second resume
        if ledger is None or Decimal(ledger) != PRIOR_SPEND:
            raise SystemExit(f"ledger {harness.NAMESPACE} holds {ledger}, not the first run's {PRIOR_SPEND} - resume refused")
        harness.STATE["spent"] = PRIOR_SPEND
    elif ledger:
        raise SystemExit(f"ledger {harness.NAMESPACE} already holds spend - this acceptance run never runs twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(LIMIT),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=harness.NAMESPACE)
    repo = FilePromptRepository(harness.ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    harness._install_provider_guard(pricing, CostEstimator(pricing), models, RedisCostTracker(diag, pricing, ledger_namespace=harness.NAMESPACE))
    resume_log = install_resume(out.parent / "post" / "calls", out) if RESUME else None
    if not RESUME:
        install_limits()
    harness._install_capture()  # raw Director diagnostics (Phase A, judge verdicts, validation errors) -> <out>/post/director_*.json
    trigger.deliver_instagram_package = no_delivery  # _install_capture re-points delivery at the scratch DB; this run delivers nowhere
    harness.STATE["post"], harness.STATE["post_dir"] = "post", out / "post"

    url = settings.database_url
    assert url.rsplit("/", 1)[-1].split("?")[0] == harness.SCRATCH_DB, "unexpected database"
    engine = create_async_engine(url.replace(f"/{harness.SCRATCH_DB}", f"/{ACCEPTANCE_DB}"))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    run: dict = {"database": ACCEPTANCE_DB, "event_id": EVENT_ID, "limit_usd": str(LIMIT), "mode": "resume" if RESUME else "first",
                 "prior_spend_usd": str(PRIOR_SPEND) if RESUME else "0"}
    async with factory() as session:
        row = await session.get(NewsEvent, UUID(EVENT_ID))
        assert row is not None, "the saved copy is not in the acceptance DB"
        package, verdict = evidence_package(row.title or "")
        harness._write(out / "post" / "evidence_package.json", package)
        treatment = await cc._classify_event_for_router_treatment(session, UUID(EVENT_ID))
        na_task = await session.scalar(select(EditorialTask).where(
            EditorialTask.event_id == UUID(EVENT_ID), EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.status == TaskStatus.COMPLETED).limit(1))
        facts = package.director_evidence() + [f[:800] for f in cc._extract_research_facts(na_task.workflow if na_task else None) if f]
        # chronology_fact(event) is None for this CURRENT_EVENT verdict (the saved run's Director facts carry no chronology line either)
        run.update(event_verdict=verdict, package_quality=package.quality, package_why=package.why,
                   treatment={"treatment": treatment.treatment, "reason": treatment.reason}, director_facts=facts)
        try:
            outcome = await evaluate_and_submit_instagram_candidate(
                session, AsyncMock(), event_id=EVENT_ID, event_title=row.title or "", treatment=treatment, research_facts=facts,
                gateway=layer.gateway, prompt_repository=repo, source_url=row.url, phase_a_enabled=True, feed_format=FeedFormat.MEME_TREND)
            run.update(result="STOPPED_BEFORE_EDITORIAL_COMPLETION", reason=outcome.reason, chosen_format=outcome.chosen_format)
        except EditorialDone as done:
            carousel = done.carousel
            run.update(result="EDITORIAL_PATH_COMPLETE", final_carousel=carousel.model_dump(mode="json"),
                       final_slides=[{"role": s.role, "headline": s.slide_copy, "body": s.slide_body, "source_evidence": s.source_evidence}
                                     for s in carousel.slides],
                       final_caption=carousel.final_caption)
        await session.rollback()  # uncommitted work is discarded; anything the trigger committed stays in the disposable acceptance copy only
    if resume_log is not None:
        run.update(replayed=resume_log["replayed"], live=resume_log["live"], refused=resume_log["refused"],
                   new_spend_usd=str(harness.STATE["spent"] - PRIOR_SPEND))
    run.update(llm_calls=harness.STATE["calls"], llm_spent_usd=str(harness.STATE["spent"]),
               llm_ledger_usd=await diag.get(f"phase7:cost_ledger:{harness.NAMESPACE}"))
    harness._write(out / "outcome.json", run)
    await engine.dispose()
    await diag.aclose()
    return run


if __name__ == "__main__":
    base = harness.ROOT / "artifacts/instagram_feed_product/sonnet_editorial_acceptance_20260930"
    args = [a for a in sys.argv[1:] if a != "--resume"]
    target = Path(args[0]) if args else (base / "resume" if RESUME else base)
    result = asyncio.run(main(target))
    print(json.dumps({k: result.get(k) for k in ("result", "reason", "package_quality", "llm_spent_usd", "new_spend_usd")}
                     | {"calls": [(c["kind"], c["status"], c.get("cost_usd")) for c in result["llm_calls"]]}, ensure_ascii=False, indent=1))
