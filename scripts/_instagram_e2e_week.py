"""KAGE INSTAGRAM - PAID END-TO-END WEEK VALIDATION (founder-authorized, hard cap $3.80 incl. existing retries).

The frozen 5-11 Aug 2026 week, downstream of selection only:
  daily (12 posts + the Tuesday gym copy the frozen cross-language dedup must block): exactly the worker's per-attempt block -
    treatment gate -> post-selection evidence package (existing get_or_acquire / run_shadow_discovery, persisted in the scratch DB) ->
    BLOCKING gate -> evaluate_and_submit_instagram_candidate (Phase A decision + duplicate guard, Creative Director with its existing
    single contract retry, media + vision suitability, render, editorial gate) ;
  weekly recap: the accepted v2 editor's 7 picks (primary candidate's widest fragment -> representative event, exactly the planner's
    mapping) -> source media via the existing run_shadow_discovery -> build_instagram_recap_bundle (sanitized bodies of each pick's
    cited candidates) -> evaluate_and_submit_instagram_opportunity, as _run_instagram_weekly_recap does.

Isolation and safety:
  - a SCRATCH database (a clone of the local dev DB, migrated to head) - never the source DB, never production; image storage in the out dir;
  - image generation OFF (production default); no Telegram contact: the delivery step records the real delivery row (so the dedup
    history is real) and saves the presentation to disk instead of sending it;
  - every provider request is pinned to the router's first pick (gpt-5.6-luna; a fallback to another model is refused), the OpenAI SDK's
    own retries are off, a request whose worst case would push the spend past the cap is refused BEFORE it is sent, every call is
    recorded in a dedicated diagnostic ledger that the enforce-mode budget guard also reads, and every raw response is saved.

Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_e2e_week.py <scratch> <out dir>
  <scratch> = the directory holding feed_window / story_identity / feed_replay / editor_run_final/weekly_editor_live_v2_final.json
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent.parent
SCRATCH_DB = "kage_e2e_20260925"
for line in (ROOT.parent.parent / ".env").read_text(encoding="utf-8").splitlines():  # DB credentials only, never printed
    if line.startswith("POSTGRES_") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
os.environ["POSTGRES_DB"] = SCRATCH_DB
sys.path.insert(0, str(ROOT))

from core.config import settings  # noqa: E402

CAP = Decimal(os.environ.get("KAGE_E2E_CAP_USD", "3.80"))  # the TOTAL authorization minus any earlier attempt's spend
NAMESPACE = os.environ.get("KAGE_E2E_NAMESPACE", "kage_e2e_week_20260925")
DIAG_REDIS_URL = "redis://localhost:6379/13"
ALLOWED_MODEL = "gpt-5.6-luna"
RECAP_SUMMARY = "Главное за неделю: ИИ, гаджеты, интернет"


class SafeStop(RuntimeError):
    pass


STATE: dict = {"spent": Decimal(0), "calls": [], "post": None, "post_dir": None}


def _jsonable(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=1), encoding="utf-8")


def _call_kind(request) -> str:
    props = (request.response_schema or {}).get("properties", {})
    if "angle_intent" in props:
        return "PHASE_A"
    if "image_kind" in props:
        return "VISION"
    if "slides" in props or "hook" in props or "creative_angle" in props:
        return "DIRECTOR"
    return "OTHER"


def _install_provider_guard(pricing, estimator, models, tracker):
    from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter
    from schemas.capability import CapabilityCall

    real_generate = OpenAIAdapter.generate
    tier = next(t for t in models[ALLOWED_MODEL].pricing_tiers if t.condition == "standard")

    async def guarded(self, request):
        model = self._resolve_model_id(request)
        kind = _call_kind(request)
        if os.environ.get("KAGE_E2E_DRY") == "1":  # plumbing check: every provider request is refused before it is sent
            STATE["calls"].append({"post": STATE["post"], "kind": kind, "model": model, "status": "DRY_REFUSED", "cost_usd": "0",
                                   "worst_case_usd": str(estimator.estimate(models[ALLOWED_MODEL], request).worst_case)})
            raise SafeStop("dry run: provider request refused before sending")
        if model != ALLOWED_MODEL:
            raise SafeStop(f"router picked {model}, not {ALLOWED_MODEL} - refused before sending (no fallback model)")
        worst = estimator.estimate(models[ALLOWED_MODEL], request).worst_case
        if STATE["spent"] + worst > CAP:
            raise SafeStop(f"{kind}: spent {STATE['spent']} + worst {worst} would exceed the cap {CAP} - refused before sending")
        self._client = self._client.with_options(max_retries=0)
        started = datetime.now(UTC)
        t0 = time.monotonic()
        record = {"post": STATE["post"], "kind": kind, "model": model, "max_tokens": request.max_tokens, "worst_case_usd": str(worst)}
        try:
            response = await real_generate(self, request)
        except Exception as exc:
            record.update(status="PROVIDER_ERROR", error=f"{type(exc).__name__}: {str(exc)[:300]}", cost_usd="0")
            STATE["calls"].append(record)
            raise
        usage = response.usage
        cost = (Decimal(usage.input_tokens or 0) * tier.input_price_per_million
                + Decimal(usage.output_tokens or 0) * tier.output_price_per_million) / Decimal(1_000_000)
        STATE["spent"] += cost
        call = CapabilityCall(call_id=uuid4(), sequence=0, gateway_method="generate", status="SUCCESS", model_used=model, provider="openai",
                              usage=usage, started_at=started, finished_at=datetime.now(UTC), duration_seconds=time.monotonic() - t0)
        await tracker.record(uuid4(), f"kage_e2e_{kind.lower()}", call)
        record.update(status="OK", finish_reason=response.finish_reason, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                      reasoning_tokens=usage.reasoning_tokens, cost_usd=str(cost))
        STATE["calls"].append(record)
        if STATE["post_dir"] is not None:
            n = sum(1 for c in STATE["calls"] if c["post"] == STATE["post"])
            _write(STATE["post_dir"] / "calls" / f"{n:02d}_{kind.lower()}.json", {"record": record, "response": response})
        return response

    OpenAIAdapter.generate = guarded


def _install_capture():
    """Rendered slides, the package (copy + plan), the Creative Director raw output, vision verdicts and the delivery presentation."""
    import services.instagram_automatic_trigger as trigger
    import services.instagram_creative_director as cd
    import services.instagram_source_suitability as suit
    from database.models.instagram_editorial_delivery import InstagramEditorialDeliveryState
    from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService
    from services.instagram_editorial_gate import InstagramGateDecision

    real_render, real_snapshot = trigger.render_instagram_carousel, trigger.build_package_snapshot

    def spy_render(pkg, **kw):
        renders = real_render(pkg, **kw)
        for i, r in enumerate(renders, 1):
            path = STATE["post_dir"] / "slides" / f"slide_{i:02d}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.image_bytes)
        _write(STATE["post_dir"] / "render_evidence.json", [r.evidence for r in renders])
        return renders

    def spy_snapshot(**kw):
        _write(STATE["post_dir"] / "package.json", kw.get("package"))
        _write(STATE["post_dir"] / "director_input.json", kw.get("director_input"))
        return real_snapshot(**kw)

    async def record_delivery(bot, session, *, presentation, gate_decision, package_identity, source_story_id, content_format, package_snapshot,
                              source_url=None, hold_or_block_reason=None):
        # NO Telegram contact: the real delivery row (the dedup history reads it) + the presentation on disk
        service = InstagramEditorialDeliveryService()
        delivery, _created = await service.get_or_create_first_version(
            session, package_identity=package_identity, source_story_id=source_story_id, content_format=content_format,
            package_snapshot=package_snapshot)
        if gate_decision is InstagramGateDecision.READY_FOR_EDITOR:
            await service.mark_delivered(session, delivery, chat_id=0, topic_id=None, media_message_ids=[], control_message_id=None)
        else:
            await service.mark_hold_or_block(session, delivery, state=InstagramEditorialDeliveryState.HOLD
                                             if gate_decision is InstagramGateDecision.HOLD else InstagramEditorialDeliveryState.BLOCK)
        _write(STATE["post_dir"] / "presentation.json", {"kind": presentation.kind, "control_text": presentation.control_text,
                                                         "overflow_text": presentation.overflow_text, "media_count": len(presentation.media),
                                                         "gate_decision": gate_decision.value, "gate_reason": hold_or_block_reason})
        return SimpleNamespace(sent=False, reason=f"recorded_{gate_decision.value}_no_telegram", delivery_id=str(delivery.id))

    def raw_sink(event, payload):
        _write(STATE["post_dir"] / f"director_{event}.json", payload)

    trigger.render_instagram_carousel = spy_render
    trigger.build_package_snapshot = spy_snapshot
    trigger.deliver_instagram_package = record_delivery
    cd.set_raw_output_sink(raw_sink)
    return suit


def _stage(reason: str, evidence_blocking: bool = False) -> str:
    if evidence_blocking:
        return "EVIDENCE"
    if reason in ("submitted", "already_submitted"):
        return "OK"
    if reason.startswith(("editorial_decision_failed", "duplicate_angle_blocked", "feed_format_mismatch", "treatment=")):
        return "PHASE A" if not reason.startswith("treatment=") else "OTHER"
    if reason.startswith(("creative_director_failed", "creative_director_returned")):
        return "DIRECTOR"
    if reason.startswith(("creative_media_failed", "source_", "generation_", "provider_not_configured")):
        return "MEDIA / VISION"
    if reason == "render_failed":
        return "RENDER"
    return "OTHER"


def _week(scratch: Path):
    import scripts._instagram_weekly_editor_validation as editor_harness
    from services.instagram_weekly_recap_editor import attach_evidence, build_editor_candidates

    items, evidence, daily_by_story, _posts = editor_harness._week(scratch / "feed_window_2026-08-05_11.json",
                                                                   scratch / "story_identity_2026-08-05_11.json", scratch / "feed_replay_r6.json")
    candidates = attach_evidence(build_editor_candidates(items, daily_premise_by_story=daily_by_story), evidence)
    return {c.candidate_id: c for c in candidates}


async def main() -> None:
    scratch, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    settings.article_acquisition_mode = "shadow"
    settings.image_intelligence_mode = "shadow"
    settings.image_candidate_persistence_mode = "finalists"
    settings.image_storage_root = str(out / "_image_storage")
    settings.instagram_image_generation_mode = "off"
    assert settings.postgres_db == SCRATCH_DB if hasattr(settings, "postgres_db") else SCRATCH_DB in settings.database_url

    from redis.asyncio import Redis
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import integrations.llm_gateway.boot as boot
    import services.instagram_recap_bundle as bundle_module
    import worker.content_cycle as cc
    from database.models.editorial_task import EditorialTask, TaskStatus
    from database.models.news_event import NewsEvent
    from database.models.news_source import NewsSource
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.workflow import WorkflowType
    from services.budget_guard import RedisBudgetGuard
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.image_intelligence import run_shadow_discovery
    from services.instagram_automatic_trigger import evaluate_and_submit_instagram_candidate, evaluate_and_submit_instagram_opportunity
    from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
    from services.instagram_evidence_package import BLOCKING, build_daily_evidence_package, build_recap_story_package, clean_body
    from services.instagram_feed_planner import weekly_recap_identity
    from services.instagram_feed_product import FeedFormat
    from services.instagram_recap_bundle import build_instagram_recap_bundle
    from services.pricing_catalog import ModelRegistryPricingCatalog
    from services.weekly_recap_selection import WeeklyRecapCandidate

    diag = Redis.from_url(DIAG_REDIS_URL, decode_responses=True)
    if await diag.get(f"phase7:cost_ledger:{NAMESPACE}"):
        raise SafeStop("the diagnostic ledger already holds spend for this run - it never runs twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(CAP), "enabled_providers": ["openai"],
                                                "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=NAMESPACE)
    repo = FilePromptRepository(ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    tracker = RedisCostTracker(diag, pricing, ledger_namespace=NAMESPACE)
    _install_provider_guard(pricing, CostEstimator(pricing), models, tracker)
    suit = _install_capture()

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    events = {e["id"]: e for e in json.loads((scratch / "feed_window_2026-08-05_11.json").read_text(encoding="utf-8"))["events"]}
    by_title = {}
    for e in events.values():
        by_title.setdefault((e["title"], e["source_name"]), e)
    results = []

    # --- daily: chronological, slot order; the Tuesday gym copy is included (the frozen dedup must block it at Phase A) ---------------
    for day in json.loads((scratch / "feed_replay_r6.json").read_text(encoding="utf-8"))["days"]:
        for slot, post in enumerate(day["enriched"]["posts"], 1):
            e = by_title[(post["title"], post["source"])]
            key = f"{day['day']}_{slot}_{post['format']}"
            only = os.environ.get("KAGE_E2E_ONLY")  # a targeted canary: only these daily posts (the recap always runs)
            if only and key not in only.split(","):
                continue
            STATE["post"], STATE["post_dir"] = key, out / key
            (out / key).mkdir(parents=True, exist_ok=True)
            verdicts: list = []
            suit.set_verdict_sink(verdicts)
            row = {"key": key, "day": day["day"], "slot": slot, "format": post["format"], "title": post["title"], "source": post["source"]}
            event_id = UUID(e["id"])
            try:
                async with factory() as session:
                    treatment = await cc._classify_event_for_router_treatment(session, event_id)
                    event_row = await session.get(NewsEvent, event_id)
                    na_task = await session.scalar(
                        select(EditorialTask).where(
                            EditorialTask.event_id == event_id,
                            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                            EditorialTask.status == TaskStatus.COMPLETED,
                        ).order_by(EditorialTask.updated_at.desc()).limit(1))
                    source_row = await session.get(NewsSource, event_row.source_id)
                    package = await build_daily_evidence_package(
                        post_id=str(event_id), fmt=post["format"], title=event_row.title or "", url=event_row.url,
                        source_type=getattr(getattr(source_row, "type", None), "value", "RSS"), source_name=getattr(source_row, "name", None),
                        stored_body=event_row.content or event_row.summary, event=event_row, event_id=event_id, session=session,
                        acquisition_enabled=True, media_mode="shadow")
                    await session.commit()
                    _write(out / key / "evidence_package.json", package)
                    row.update(evidence=package.quality, evidence_why=package.why, source_media=package.media.status)
                    if package.quality == BLOCKING:
                        row.update(reason="evidence_blocking", stage="EVIDENCE")
                    else:
                        facts = package.director_evidence() + [
                            f[:800] for f in cc._extract_research_facts(na_task.workflow if na_task is not None else None) if f]
                        outcome = await evaluate_and_submit_instagram_candidate(
                            session, AsyncMock(), event_id=str(event_id), event_title=event_row.title or "", treatment=treatment,
                            research_facts=facts, gateway=layer.gateway, prompt_repository=repo, source_url=event_row.url,
                            phase_a_enabled=True, feed_format=FeedFormat(post["format"]))
                        await session.commit()
                        row.update(reason=outcome.reason, stage=_stage(outcome.reason), gate=outcome.gate_decision,
                                   delivery=outcome.delivery_reason)
            except SafeStop as exc:
                row.update(reason=f"safe_stop: {exc}", stage="OTHER")
            except Exception as exc:  # noqa: BLE001 - recorded per post, never retried, never hides the failure
                row.update(reason=f"harness_exception: {type(exc).__name__}: {str(exc)[:300]}", stage="OTHER")
            _write(out / key / "vision_verdicts.json", verdicts)
            row.update(calls=[c for c in STATE["calls"] if c["post"] == key], slides=len(list((out / key / "slides").glob("*.png")))
                       if (out / key / "slides").exists() else 0, spent_so_far=str(STATE["spent"]))
            _write(out / key / "outcome.json", row)
            results.append(row)
            print(f"{key:40} {row.get('evidence', '-'):10} {row.get('stage', '-'):14} {row.get('reason', '')[:60]:60} slides={row['slides']} "
                  f"spent=${STATE['spent']:.4f}", flush=True)

    # --- weekly recap: the accepted 7 v2 picks through the actual downstream path ---------------------------------------------------
    key = "weekly_recap"
    STATE["post"], STATE["post_dir"] = key, out / key
    (out / key).mkdir(parents=True, exist_ok=True)
    verdicts = []
    suit.set_verdict_sink(verdicts)
    row = {"key": key, "format": "weekly_recap", "title": RECAP_SUMMARY}
    try:
        picks = json.loads((scratch / "editor_run_final" / "weekly_editor_live_v2_final.json").read_text(encoding="utf-8"))["live"]["picks"]
        candidates = _week(scratch)
        ident = json.loads((scratch / "story_identity_2026-08-05_11.json").read_text(encoding="utf-8"))
        members: dict[str, list[str]] = {}
        for eid, link in ident["links"].items():
            members.setdefault(link["story_id"], []).append(eid)
        selected, cited_by_event = [], {}
        for pick in picks:
            primary = candidates[pick["primary_candidate_id"]]
            main = max(primary.item.stories, key=lambda s: len(s.sources))
            unit_events = [main.story_id.split(":", 1)[1]] if main.story_id.startswith("event:") else members.get(main.story_id, [])
            representative = min((events[i] for i in unit_events if i in events), key=lambda ev: ev["created_at"])
            cited = []
            for sid in pick["story_ids"]:
                cited += [sid.split(":", 1)[1]] if sid.startswith("event:") else members.get(sid, [])
            cited_by_event[representative["id"]] = (pick["weekly_premise"], list(dict.fromkeys(cited)))
            selected.append(WeeklyRecapCandidate(
                story_id=UUID(representative["id"]), representative_event_id=UUID(representative["id"]),
                relevance_tier=f"INSTAGRAM_WEEKLY_{pick['category']}", score=None, significance=None, major_impact_override=False,
                company_key=None, entities=[], updated_at=datetime.fromisoformat(representative["created_at"]),
                reason=f"{pick['weekly_premise']} - {pick['why_this_made_the_week']}", rank_score=float(9 - pick["rank"])))

        async def pick_bodies(session, story_id, representative):
            """Each pick's CITED candidates' confirmed members (production Story identity replay) - then sanitized by the package."""
            premise, cited = cited_by_event[str(representative.id)]
            rows = (await session.execute(select(NewsEvent).where(NewsEvent.id.in_([UUID(i) for i in cited[:40]])))).scalars().all()
            from services.article_acquisition import get_effective_acquisition
            from services.evidence_package import TRUSTED_FULL_ARTICLE_STATUSES
            bodies = []
            for ev in rows:
                if ev.content:
                    bodies.append((f"event:{ev.id}:body", ev.content))
                acq = await get_effective_acquisition(session, ev.id)
                if acq is not None and acq.acquisition_status in TRUSTED_FULL_ARTICLE_STATUSES and acq.raw_extracted_text:
                    bodies.append((f"event:{ev.id}:article", clean_body(acq.raw_extracted_text, ev.title)))
            package = await build_recap_story_package(post_id=str(representative.id), premise=premise, headlines=[r.title for r in rows if r.title],
                                                      bodies=bodies)
            _write(out / key / "evidence" / f"{representative.id}.json", package)
            return [premise] + [r.title for r in rows if r.title], bodies

        bundle_module._story_bodies = pick_bodies
        async with factory() as session:
            for cand in selected:  # source media for each pick: the existing image discovery, persisted in the scratch DB
                ev = await session.get(NewsEvent, cand.representative_event_id)
                src = await session.get(NewsSource, ev.source_id)
                try:
                    await run_shadow_discovery(event_id=ev.id, source_type=src.type, content=ev.content, article_url=ev.url, mode="shadow",
                                               event_title=ev.title, source_name=src.name, session=session)
                except Exception as exc:  # noqa: BLE001 - a story without media gets its graphic card
                    row.setdefault("media_errors", []).append(f"{ev.id}: {type(exc).__name__}")
            await session.commit()
            bundle = await build_instagram_recap_bundle(session, selected=selected)
            row.update(recap_selected=len(selected), recap_entering_downstream=len(bundle.stories) if bundle else 0,
                       recap_with_media=len(bundle.available_assets) if bundle else 0)
            if bundle is None:
                row.update(reason="recap_bundle_none", stage="OTHER")
            else:
                _write(out / key / "bundle.json", {"subjects": bundle.subjects, "evidence": bundle.evidence,
                                                   "stories": [{"key": s.key, "title": s.title, "has_image": bool(s.image_bytes)} for s in bundle.stories]})
                opportunity = ContentOpportunity(
                    id=weekly_recap_identity(datetime(2026, 8, 12, tzinfo=UTC)), source_type=OpportunitySourceType.NEWS,
                    story_id=weekly_recap_identity(datetime(2026, 8, 12, tzinfo=UTC)), news_value=1.0, audience_relevance=0.5,
                    product_mention_allowed=False, evidence=list(bundle.evidence), confidence=0.5)
                outcome = await evaluate_and_submit_instagram_opportunity(
                    session, AsyncMock(), opportunity=opportunity, opportunity_summary=RECAP_SUMMARY, gateway=layer.gateway,
                    prompt_repository=repo, phase_a_enabled=True, recap_bundle=bundle)
                await session.commit()
                row.update(reason=outcome.reason, stage=_stage(outcome.reason), gate=outcome.gate_decision, delivery=outcome.delivery_reason)
    except SafeStop as exc:
        row.update(reason=f"safe_stop: {exc}", stage="OTHER")
    except Exception as exc:  # noqa: BLE001
        row.update(reason=f"harness_exception: {type(exc).__name__}: {str(exc)[:300]}", stage="OTHER")
    _write(out / key / "vision_verdicts.json", verdicts)
    row.update(calls=[c for c in STATE["calls"] if c["post"] == key],
               slides=len(list((out / key / "slides").glob("*.png"))) if (out / key / "slides").exists() else 0, spent_so_far=str(STATE["spent"]))
    _write(out / key / "outcome.json", row)
    results.append(row)
    print(f"{key:40} {'-':10} {row.get('stage', '-'):14} {row.get('reason', '')[:60]:60} slides={row['slides']} spent=${STATE['spent']:.4f}")

    ledger = await diag.get(f"phase7:cost_ledger:{NAMESPACE}")
    kinds: dict = {}
    for c in STATE["calls"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    summary = {"cap_usd": str(CAP), "actual_cost_usd": str(STATE["spent"]), "diagnostic_ledger_usd": ledger, "provider_calls": len(STATE["calls"]),
               "calls_by_kind": kinds, "image_generation_mode": settings.instagram_image_generation_mode, "posts": results, "calls": STATE["calls"]}
    _write(out / "run_summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("actual_cost_usd", "diagnostic_ledger_usd", "provider_calls", "calls_by_kind")}, indent=1))
    await engine.dispose()
    await diag.aclose()


if __name__ == "__main__":
    asyncio.run(main())
