"""KAGE INSTAGRAM - CONTROLLED COMPLETION RUN from the saved canary-10 artifacts (founder decision 2026-09-28). NOT a natural canary.

The REAL trigger (services.instagram_automatic_trigger.evaluate_and_submit_instagram_candidate) runs again for the canary-10 event with the
canary's saved Director facts, but every model call canary 10 already paid for is REPLAYED from its saved response instead of being sent:
  01 Phase A, 02 Director (first), 03 semantic judge (first), 04 Director (the ONE correction) - byte-for-byte the saved responses, and each
  replayed request is compared with the saved request (the comparison is recorded, never hidden).
Only work canary 10 never reached is live: exactly ONE final semantic judge call (the ONLY live LLM request allowed - any other un-recorded
LLM request is refused before it is sent: that would be a divergence from canary 10), then the accepted visual pipeline (source selection,
image generation behind a capped isolated ledger), art validation and the render. No evidence acquisition, no nomination, no Director or
correction re-run. No Telegram (delivery recorded to the scratch DB only), no publication, no production write.
Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_controlled_completion.py <out dir>
"""
from __future__ import annotations

import asyncio
import difflib
import json
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("KAGE_E2E_CAP_USD", os.environ.get("KAGE_CANARY_LLM_CAP_USD", "0.45"))

import scripts._instagram_e2e_week as harness  # noqa: E402

from core.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary10_20260928"
CANARY9 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary9_20260928"  # its cached vision verdict served canary 10
IMAGE_CAP = Decimal(os.environ.get("KAGE_CANARY_IMAGE_CAP_USD", "0.55"))
LLM_NAMESPACE = os.environ.get("KAGE_CANARY_LLM_NAMESPACE", "kage_controlled_completion_c10_llm_20260928")
IMAGE_NAMESPACE = os.environ.get("KAGE_CANARY_IMAGE_NAMESPACE", "kage_controlled_completion_c10_images_20260928")
LIVE_ALLOWED = {"SEMANTIC_JUDGE": 1}  # the final judge canary 10 never reached - nothing else may go live


def _request_text(request) -> list[dict]:
    return [{"role": m.role, "text": [part.text for part in m.content if getattr(part, "type", None) == "text"]} for m in request.messages]


FIXTURE: dict | None = None  # CONTROLLED_VISUAL_FIXTURE (optional 2nd argument): replaces ONLY the replayed correction's output


def install_replay(out: Path) -> dict:
    """Wraps the (already guarded) provider: saved canary-10 responses first, in call order per kind; then the allowed live calls."""
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter

    queues: dict[str, list[dict]] = {}
    for path in sorted((SOURCE / "post/calls").glob("*.json")):
        call = json.loads(path.read_text(encoding="utf-8"))
        queues.setdefault(call["record"]["kind"], []).append({"file": path.name, **call})
    # canary 10 made NO vision call of its own: its identical source-suitability request was answered by the LLM gateway's response cache
    # (integrations/llm_gateway/cache/coordinator.py, TTL 3600 s) from canary 9's call 54 minutes earlier - the SAME Guardian image, and
    # canary 10's recorded verdict is canary 9's verbatim. Replaying that saved response reproduces exactly what canary 10 consumed.
    vision = CANARY9 / "post/calls/02_vision.json"
    queues.setdefault("VISION", []).insert(0, {"file": f"canary9_{vision.name}", **json.loads(vision.read_text(encoding="utf-8"))})
    log: dict = {"replayed": [], "live": [], "refused": []}
    guarded = OpenAIAdapter.generate

    def lines(request_text: list[dict]) -> list[str]:
        return "\n".join(t for m in request_text for t in m["text"]).splitlines()

    def normalized(request_text: list[dict]) -> list[str]:
        # the lines that legitimately differ from canary 10's saved requests (both stay visible in the recorded diff):
        #  - the prompt's own clock;
        #  - the VIRAL COPY CONTRACT the correction note carries since 2026-09-28 (added AFTER canary 10's correction was paid for - the
        #    saved correction response was produced without it, and the controlled fixture replaces that output anyway)
        return [line for line in lines(request_text)
                if not line.startswith("BUSINESS CONTEXT AS OF:") and not line.startswith("VIRAL COPY CONTRACT (binding")]

    async def replay_or_live(self, request):
        kind = harness._call_kind(request)
        now_text = _request_text(request)
        # a saved call is replayed only for the SAME request (clock line aside) - never by position, so a response can never answer a
        # different question (the final judge's corrected-slide request matches no saved call and therefore goes live)
        match = next((c for c in queues.get(kind, []) if normalized(c["request"]) == normalized(now_text)), None)
        if match is not None:
            queues[kind].remove(match)
            saved = match
            saved_text = saved["request"]
            a, b = lines(saved_text), lines(now_text)
            diff = [line for line in difflib.unified_diff(a, b, lineterm="", n=0) if line[:1] in "+-" and line[:3] not in ("+++", "---")]
            log["replayed"].append({"kind": kind, "saved_call": saved["file"], "request_identical": not diff, "diff_lines": diff[:40],
                                    "historical_cost_usd": saved["record"].get("cost_usd")})
            harness._write(out / "post" / "calls" / f"replayed_{saved['file']}", {"saved_call": saved["file"], "request_identical": not diff,
                                                                                 "diff_lines": diff, "request_now": now_text})
            response = GenerateResponse.model_validate(saved["response"])
            if FIXTURE is not None and saved["file"] == "04_director.json":
                # the controlled visual fixture: the saved correction's output with ONLY the declared change (see the fixture file)
                log["replayed"][-1]["fixture_substituted"] = FIXTURE["only_change"]
                response = response.model_copy(update={"structured_output": FIXTURE["structured_output"]})
            return response
        if LIVE_ALLOWED.get(kind, 0) <= 0:
            log["refused"].append({"kind": kind})
            raise harness.SafeStop(f"controlled run: a {kind} request canary 10 never made - refused before sending (divergence)")
        LIVE_ALLOWED[kind] -= 1
        response = await guarded(self, request)
        log["live"].append({"kind": kind, **harness.STATE["calls"][-1]})
        return response

    OpenAIAdapter.generate = replay_or_live
    # the gateway's 1-hour response cache is bypassed IN THIS PROCESS ONLY: every model request reaches the replay above (so replays are
    # decided by request content) and the ONE final judge is a real call, never an earlier cached answer
    from integrations.llm_gateway.cache.coordinator import CacheCoordinator

    async def no_lookup(self, *_a, **_k):
        return None

    async def no_store(self, *_a, **_k):
        return None

    CacheCoordinator.lookup = no_lookup
    CacheCoordinator.store = no_store
    return log


def install_review_payload_capture(out: Path) -> None:
    """The EXACT Telegram review payload the founder would receive (media in order, control text, overflow) - written to disk, never sent."""
    import services.instagram_automatic_trigger as trigger

    recorded = trigger.deliver_instagram_package  # the harness's no-Telegram recorder

    async def capture(bot, session, *, presentation, **kw):
        target = out / "telegram_review_payload"
        target.mkdir(parents=True, exist_ok=True)
        files = []
        for i, media in enumerate(presentation.media, 1):
            path = target / f"media_{i:02d}.png"
            path.write_bytes(media)
            files.append(path.name)
        (target / "control_text.html").write_text(presentation.control_text, encoding="utf-8")
        if presentation.overflow_text:
            (target / "overflow_text.html").write_text(presentation.overflow_text, encoding="utf-8")
        harness._write(target / "payload.json", {"LABEL": "REVIEW ARTIFACT - NOT SENT - NO INSTAGRAM PUBLICATION", "kind": presentation.kind,
                                                "version_label": presentation.version_label, "media_in_order": files,
                                                "gate_decision": kw.get("gate_decision").value if kw.get("gate_decision") else None,
                                                "hold_or_block_reason": kw.get("hold_or_block_reason"), "package_identity": kw.get("package_identity"),
                                                "destination": "NONE - no send authorized for this task"})
        return await recorded(bot, session, presentation=presentation, **kw)

    trigger.deliver_instagram_package = capture


async def main() -> None:
    global FIXTURE
    out = Path(sys.argv[1])
    if len(sys.argv) > 2:
        FIXTURE = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        assert FIXTURE["LABEL"].startswith("CONTROLLED_VISUAL_FIXTURE"), "not a controlled visual fixture"
    if (out / "manifest.json").exists():
        raise SystemExit(f"{out} already holds a controlled run - never run twice into the same directory")
    out.mkdir(parents=True, exist_ok=True)
    # the canary's stored source images (the image candidates in the scratch DB point at them): a COPY, the canary's artifacts stay untouched
    if (SOURCE / "_image_storage").exists() and not (out / "_image_storage").exists():
        shutil.copytree(SOURCE / "_image_storage", out / "_image_storage")
    settings.article_acquisition_mode = "enforce"
    settings.image_intelligence_mode = "shadow"
    settings.image_candidate_persistence_mode = "finalists"
    settings.image_storage_root = str(out / "_image_storage")
    settings.instagram_image_generation_mode = "live"
    assert harness.SCRATCH_DB in settings.database_url

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import integrations.llm_gateway.boot as boot
    import services.instagram_creative_media as media_mod
    import worker.content_cycle as cc
    from database.models.news_event import NewsEvent
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from services.budget_guard import RedisBudgetGuard
    from services.budgeted_image_execution import BudgetedImageExecutor
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.instagram_automatic_trigger import evaluate_and_submit_instagram_candidate
    from services.instagram_feed_product import FeedFormat
    from services.pricing_catalog import ModelRegistryPricingCatalog

    canary = json.loads((SOURCE / "outcome.json").read_text(encoding="utf-8"))
    diag = Redis.from_url(harness.DIAG_REDIS_URL, decode_responses=True)
    for namespace in (LLM_NAMESPACE, IMAGE_NAMESPACE):
        if await diag.get(f"phase7:cost_ledger:{namespace}"):
            raise SystemExit(f"ledger {namespace} already holds spend - the controlled run never runs twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(harness.CAP),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=LLM_NAMESPACE)
    repo = FilePromptRepository(harness.ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    harness._install_provider_guard(pricing, CostEstimator(pricing), models, RedisCostTracker(diag, pricing, ledger_namespace=LLM_NAMESPACE))
    replay_log = install_replay(out)
    suit = harness._install_capture()
    install_review_payload_capture(out)
    image_guard = RedisBudgetGuard(diag, settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(IMAGE_CAP),
                                                                     "redis_unavailable_policy": "fail_closed"}), ledger_namespace=IMAGE_NAMESPACE)
    media_mod.build_budgeted_image_executor = lambda: BudgetedImageExecutor(budget_guard=image_guard)
    generated: list = []
    real_generate = media_mod._execute_generated_asset

    async def record_generation(**kw):
        import time

        t0 = time.monotonic()
        asset = await real_generate(**kw)
        entry = {"asset_key": kw.get("asset_key"), "status": asset.status, "accounted_usd": asset.accounted_cost_usd,
                 "reserved_usd": asset.reserved_cost_usd, "provider_request_id": asset.provider_request_id, "prompt": asset.prompt,
                 "duration_seconds": round(time.monotonic() - t0, 2),
                 "dimensions": list(asset.image.size) if asset.image is not None else None}
        generated.append(entry)
        if asset.image is not None:
            (out / "post" / "generated").mkdir(parents=True, exist_ok=True)
            asset.image.save(out / "post" / "generated" / f"asset_{kw.get('asset_key')}.png")
        return asset

    media_mod._execute_generated_asset = record_generation

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    harness.STATE["post"], harness.STATE["post_dir"] = "post", out / "post"
    verdicts: list = []
    suit.set_verdict_sink(verdicts)
    run: dict = {"fixture": (FIXTURE or {}).get("LABEL"), "fixture_change": (FIXTURE or {}).get("only_change"), "controlled_run": True, "natural_canary": False, "source_canary": "viral_nominated_canary10_20260928 (55016a4)",
                 "event": canary["selected_event"], "evidence_copy": canary["evidence_copy"], "director_facts": canary["director_facts"]}
    async with factory() as session:
        event_id = UUID(canary["evidence_copy"]["event_id"])
        row = await session.get(NewsEvent, event_id)
        if row is None:
            raise SystemExit("the canary-10 evidence copy is not in the scratch DB")
        treatment = await cc._classify_event_for_router_treatment(session, event_id)  # a DB read - the same classification canary 10 used
        run["treatment"] = {"treatment": treatment.treatment, "reason": treatment.reason, "canary10": canary["treatment"]}
        outcome = await evaluate_and_submit_instagram_candidate(
            session, AsyncMock(), event_id=str(event_id), event_title=row.title or "", treatment=treatment,
            research_facts=list(canary["director_facts"]), gateway=layer.gateway, prompt_repository=repo, source_url=row.url,
            phase_a_enabled=True, feed_format=FeedFormat.MEME_TREND)
        await session.commit()
        run.update(reason=outcome.reason, gate=outcome.gate_decision, delivery=outcome.delivery_reason, chosen_format=outcome.chosen_format)
    run.update(replay=replay_log, vision_verdicts=verdicts, generated=generated, live_llm_calls=harness.STATE["calls"],
               new_llm_spent_usd=str(harness.STATE["spent"]),
               llm_ledger_usd=await diag.get(f"phase7:cost_ledger:{LLM_NAMESPACE}"),
               image_ledger_usd=await diag.get(f"phase7:cost_ledger:{IMAGE_NAMESPACE}"),
               historical_canary10_llm_usd=canary.get("llm_spent_usd"))
    harness._write(out / "manifest.json", run)
    print(json.dumps({k: run.get(k) for k in ("reason", "gate", "delivery", "chosen_format", "new_llm_spent_usd", "image_ledger_usd")}
                     | {"replayed": [(r["kind"], r["saved_call"], r["request_identical"]) for r in replay_log["replayed"]],
                        "live": [(r["kind"], r.get("cost_usd")) for r in replay_log["live"]], "refused": replay_log["refused"],
                        "generated": [(g["asset_key"], g["status"], g["accounted_usd"]) for g in generated]},
                     ensure_ascii=False, indent=1, default=str))
    await engine.dispose()
    await diag.aclose()


if __name__ == "__main__":
    asyncio.run(main())
