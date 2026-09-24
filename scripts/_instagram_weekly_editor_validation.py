"""KAGE WEEKLY RECAP EDITOR validation (founder-authorized): ONE editor call on the frozen 5-11 Aug 2026 week.

Inputs are the same real, read-only replay artifacts as the selection-finalization phase: the extracted week of events, the production
Story identity replayed with the real `story_memory.match_story()`, and that phase's final daily feed (the enriched b9733c2 picks) as
this week's daily posts. The candidate set is built by the production code (`build_editor_candidates`), the request by the production
request builder, the answer checked by the production validator.

Cost control:
  - preflight: the EXACT request priced with the gateway's own estimator AND with a conservative token count (Cyrillic 1 token per
    2 characters, everything else 1 per 3, the JSON schema included) at the costliest model the router may pick; the larger figure must
    stay under the cap or the script stops before any provider call;
  - live: the provider adapter is wrapped so a second provider request raises before it is sent (retries 0, the OpenAI SDK's own
    retries are switched off too), and a dedicated diagnostic ledger's budget guard (enforce mode, cap as the daily budget) refuses a
    call that would exceed the cap.

Usage: python scripts/_instagram_weekly_editor_validation.py <window.json> <identity.json> <feed_replay.json> <out dir> preflight|live
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings  # noqa: E402
from integrations.prompts.file_repository import FilePromptRepository  # noqa: E402
from scripts._instagram_v107_cd_validation import _eligible_models, request_worst_case  # noqa: E402
from services.instagram_weekly_recap import RecapStory, consolidate, select_weekly_recap_items  # noqa: E402
from services.instagram_weekly_recap_editor import (  # noqa: E402
    EDITOR_PREFERRED_MODEL,
    EDITOR_PROMPT_NAME,
    EDITOR_PROMPT_VERSION,
    WeeklyRecapEditorError,
    attach_evidence,
    build_editor_candidates,
    build_editor_request,
    render_editor_input,
    run_weekly_recap_editor,
)

ROOT = Path(__file__).resolve().parent.parent
CAP = Decimal(os.environ.get("KAGE_EDITOR_CAP_USD", "0.08"))
RUN_TAG = os.environ.get("KAGE_EDITOR_RUN_TAG", f"v{EDITOR_PROMPT_VERSION}")  # one ledger (and one call) per authorized run
NAMESPACE = f"kage_weekly_recap_editor_validation_{RUN_TAG}"
DIAG_REDIS_URL = os.environ.get("KAGE_EDITOR_DIAG_REDIS_URL", "redis://localhost:6379/13")
WEEK_LABEL = "5-11 August 2026"
_AGGREGATORS = ("Google News", "arXiv")
_CONFIRMED = ("story_update", "supporting_source", "semantic_duplicate")
_CYR = re.compile(r"[Ѐ-ӿ]")


RAW_DIR = Path(".")


class SafeStop(RuntimeError):
    pass


def _week(window: Path, identity: Path, replay: Path):
    events = {e["id"]: e for e in json.loads(window.read_text(encoding="utf-8"))["events"]}
    ident = json.loads(identity.read_text(encoding="utf-8"))
    units: dict[str, list[dict]] = collections.defaultdict(list)
    for event_id, link in ident["links"].items():
        story = ident["stories"][link["story_id"]]
        confirmed = story["first_event_id"] == event_id or link["outcome"] in _CONFIRMED
        units[link["story_id"] if confirmed else f"event:{event_id}"].append(events[event_id])
    stories, evidence = [], {}
    for unit_id, members in units.items():
        members.sort(key=lambda e: e["created_at"])
        stories.append(RecapStory(
            story_id=unit_id, titles=tuple(e["title"] for e in members),
            sources=frozenset(e["source_name"] for e in members if not e["source_name"].startswith(_AGGREGATORS)),
            first_seen=datetime.fromisoformat(members[0]["created_at"]), category=members[0].get("category") or "",
        ))
        bodies = [e.get("content") or "" for e in members]
        evidence[unit_id] = max(bodies, key=len) if any(bodies) else ""
    items = consolidate(stories)
    item_of = {sid: item for item in items for sid in item.story_ids}
    daily_premise_by_story: dict[str, str] = {}
    daily_posts: list[dict] = []
    for day in json.loads(replay.read_text(encoding="utf-8"))["days"]:
        for post in day["enriched"]["posts"]:
            daily_posts.append({"day": day["day"], "format": post["format"], "title": post["title"], "story_id": post["story_id"]})
            for sid in item_of[post["story_id"]].story_ids:
                daily_premise_by_story.setdefault(sid, post["title"])
    return items, evidence, daily_premise_by_story, daily_posts


def conservative_tokens(text: str) -> int:
    cyrillic = len(_CYR.findall(text))
    return cyrillic // 2 + (len(text) - cyrillic) // 3 + 1


def preflight(request) -> dict:
    estimator = {k: Decimal(v) for k, v in request_worst_case(request).items()}
    text = "".join(part.text or "" for m in request.messages for part in m.content) + json.dumps(request.response_schema)
    tokens_in = conservative_tokens(text) + 200  # message framing / structured-output wrapper
    _, models = _eligible_models()
    conservative = {}
    for model in models:
        tier = next(t for t in model.pricing_tiers if t.condition == "standard")
        conservative[model.model_id] = (Decimal(tokens_in) * tier.input_price_per_million
                                        + Decimal(request.max_tokens) * tier.output_price_per_million) / Decimal(1_000_000)
    # exactly one provider request can be sent and the live wrapper refuses any model but the preferred one, so the preferred model's
    # worst case is the gate; with no preference, the costliest model the router may pick
    gate = [request.preferred_model] if request.preferred_model else list(estimator)
    worst = max(max(estimator[m], conservative[m]) for m in gate)
    return {"estimator_worst_case_usd": {k: str(v) for k, v in estimator.items()},
            "conservative_input_tokens": tokens_in, "max_output_tokens": request.max_tokens,
            "conservative_worst_case_usd": {k: str(v.quantize(Decimal("0.0001"))) for k, v in conservative.items()},
            "model": request.preferred_model, "reasoning_effort": request.reasoning_effort,
            "preflight_worst_case_usd": str(worst.quantize(Decimal("0.0001"))), "cap_usd": str(CAP), "within_cap": worst <= CAP}


async def live_call(candidates, daily_premises, repo) -> dict:
    import integrations.llm_gateway.boot as boot
    from redis.asyncio import Redis

    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter
    from services.budget_guard import RedisBudgetGuard
    from services.cost_tracker import RedisCostTracker, compute_call_cost
    from services.pricing_catalog import ModelRegistryPricingCatalog

    if DIAG_REDIS_URL == settings.redis_url:
        raise SafeStop("the diagnostic ledger must not be the application's Redis")
    diag = Redis.from_url(DIAG_REDIS_URL, decode_responses=True)
    ledger_key = f"phase7:cost_ledger:{NAMESPACE}"
    if await diag.get(ledger_key):
        raise SafeStop("the diagnostic ledger already holds spend - this validation's single call already ran")
    pricing = ModelRegistryPricingCatalog(build_model_registry())
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(CAP),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=NAMESPACE)
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    tracker = RedisCostTracker(diag, pricing, ledger_namespace=NAMESPACE)

    provider_requests = {"n": 0}
    real_generate = OpenAIAdapter.generate
    raw_path = RAW_DIR / f"raw_provider_response_{RUN_TAG}.json"

    async def one_request_only(self, request):
        provider_requests["n"] += 1
        if provider_requests["n"] > 1:
            raise SafeStop("a second provider request was attempted - the authorization is ONE call, retries 0")
        if EDITOR_PREFERRED_MODEL and self._resolve_model_id(request) != EDITOR_PREFERRED_MODEL:
            raise SafeStop(f"the router picked {self._resolve_model_id(request)}, not {EDITOR_PREFERRED_MODEL} - refused before sending")
        self._client = self._client.with_options(max_retries=0)
        try:
            response = await real_generate(self, request)
        except Exception as exc:  # the provider's own failure: kept as the artifact, then re-raised (never retried)
            raw_path.write_text(json.dumps({"provider_error": f"{type(exc).__name__}: {str(exc)[:800]}"}, indent=1), encoding="utf-8")
            raise
        # the response artifact is kept BEFORE any parsing / validation, whatever its shape: finish_reason, usage, text, structured output
        raw_path.write_text(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8")
        return response

    OpenAIAdapter.generate = one_request_only
    try:
        result, call = await run_weekly_recap_editor(layer.gateway, repo, candidates=candidates, daily_premises=daily_premises,
                                                     week_label=WEEK_LABEL)
    except WeeklyRecapEditorError as exc:
        if exc.call is not None:  # a failed answer is still paid for: record it before reporting the failure
            await tracker.record(uuid4(), EDITOR_PROMPT_NAME, exc.call)
            exc.args = (f"{exc.args[0]} | provider_requests={provider_requests['n']} model={getattr(exc.call, 'model_used', None)} "
                        f"usage={getattr(exc.call, 'usage', None)} cost_usd={compute_call_cost(exc.call, pricing)}",)
        raise
    finally:
        OpenAIAdapter.generate = real_generate
    cost = compute_call_cost(call, pricing)
    await tracker.record(uuid4(), EDITOR_PROMPT_NAME, call)
    ledger = await diag.get(ledger_key)
    await diag.aclose()
    return {"result": result, "call": call, "cost": cost, "ledger": ledger, "provider_requests": provider_requests["n"]}


def _pick_json(pick) -> dict:
    return {"rank": pick.rank, "weekly_premise": pick.weekly_premise, "category": pick.category,
            "primary_candidate_id": pick.primary.candidate_id, "candidate_ids": [c.candidate_id for c in pick.merged],
            "coverage": pick.coverage, "languages": sorted(set().union(*(c.item.languages for c in pick.merged))),
            "outlets": sorted(set().union(*(c.item.sources for c in pick.merged))),
            "story_ids": sorted(set().union(*(c.item.story_ids for c in pick.merged))),
            "cited_headlines": {c.candidate_id: c.headline for c in pick.merged},
            "daily_overlap": pick.daily_overlap, "why_this_made_the_week": pick.why_this_made_the_week, "why_now": pick.why_now,
            "strongest_alternative_beaten": pick.strongest_alternative_beaten}


def main() -> None:
    global RAW_DIR
    window, identity, replay, out = (Path(a) for a in sys.argv[1:5])
    mode = sys.argv[5]
    out.mkdir(parents=True, exist_ok=True)
    RAW_DIR = out
    items, evidence, daily_by_story, daily_posts = _week(window, identity, replay)
    candidates = attach_evidence(build_editor_candidates(items, daily_premise_by_story=daily_by_story), evidence)
    daily_premises = [p["title"] for p in daily_posts]
    repo = FilePromptRepository(ROOT / "prompts")
    request = build_editor_request(repo.resolve(EDITOR_PROMPT_NAME, EDITOR_PROMPT_VERSION), candidates,
                                   daily_premises=daily_premises, week_label=WEEK_LABEL)
    (out / "editor_input.txt").write_text(render_editor_input(candidates, daily_premises=daily_premises, week_label=WEEK_LABEL),
                                          encoding="utf-8")
    old = select_weekly_recap_items(items, daily_story_ids=list(daily_by_story), daily_titles=daily_premises)
    price = preflight(request)
    report = {"week": WEEK_LABEL, "prompt": f"{EDITOR_PROMPT_NAME} v{EDITOR_PROMPT_VERSION}", "candidates": len(candidates),
              "candidate_chars": sum(len(m.content[0].text) for m in request.messages), "preflight": price,
              "daily_posts": daily_posts,
              "deterministic_old_recap": [{"headline": p.item.headline, "category": p.category, "coverage": p.item.coverage,
                                           "languages": sorted(p.item.languages)} for p in old],
              "candidate_index": {c.candidate_id: {"headline": c.headline, "hint": c.category_hint, "coverage": c.item.coverage,
                                                   "languages": sorted(c.item.languages), "fragments": len(c.item.stories),
                                                   "daily": c.daily_premise} for c in candidates}}
    print(json.dumps({k: report[k] for k in ("candidates", "candidate_chars", "preflight")}, indent=1))
    if mode == "live":
        if not price["within_cap"]:
            raise SafeStop(f"preflight worst case {price['preflight_worst_case_usd']} exceeds the cap {CAP} - no provider call")
        try:
            live = asyncio.run(live_call(candidates, daily_premises, repo))
        except Exception as exc:  # noqa: BLE001 - recorded, never retried
            report["live"] = {"status": "FAILED", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        else:
            result, call = live["result"], live["call"]
            report["live"] = {
                "status": "OK", "provider_requests": live["provider_requests"], "model": getattr(call, "model_used", None),
                "input_tokens": getattr(call.usage, "input_tokens", None), "output_tokens": getattr(call.usage, "output_tokens", None),
                "actual_cost_usd": str(live["cost"]), "diagnostic_ledger_usd": live["ledger"],
                "picks": [_pick_json(p) for p in result.picks], "dropped": list(result.dropped),
                "daily_overlap_exclusions": [{"candidate_ids": list(ids), "reason": reason} for ids, reason in result.daily_exclusions]}
        print(json.dumps(report["live"], ensure_ascii=False, indent=1))
    (out / f"weekly_editor_{mode}_{RUN_TAG}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
