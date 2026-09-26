"""Acceptance of the viral-carousel SEMANTIC EDITORIAL JUDGE (founder task 2026-09-26).

ZERO-COST mode (default, no provider call - the judge is a stub returning a fixed structured verdict):
  - the cost bound: worst-case judge input (7 slides at the schema's maxLength, 7 cited evidence lines, the caption) and output cap, priced;
  - the deterministic rules on the neutral fixtures 4-10 (scripts/_instagram_semantic_judge_fixtures.py);
  - the wiring on the exact final GTA output of the last live run (786ed3e): a stub verdict flows into ONE combined
    EditorialCorrectionRequired together with the deterministic findings, the judge is called exactly once per Director output;
  - golden DeepSeek / Hamster: with an empty verdict the validation returns the carousel (no false deterministic finding);
  - fail closed: gateway error, truncation, malformed structure -> SemanticJudgeUnavailableError (terminal), never a guessed verdict;
  - hard failures first: an invented quote raises CreativeFactSafetyError before the judge is ever called.
LIVE-JUDGE mode (--live-judge; OPENAI_API_KEY in the environment; separately capped ledger): the REAL judge, one call per case, on the exact
GTA final output, the two golden carousels and fixtures 4-10 - what a stub cannot prove. No Director call, no image, no pipeline run.
Usage: python scripts/_instagram_semantic_judge_replay.py <out dir> [--live-judge]
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
GTA_FINAL = ROOT / "artifacts/instagram_feed_product/thesis_uniqueness_20260926/live/post/calls/04_director.json"
LUNA_INPUT_PER_M, LUNA_OUTPUT_PER_M = 1.0, 6.0


def gta_final() -> tuple[dict, object]:
    from scripts._instagram_director_correction_replay import gta_director_input

    call = json.loads(GTA_FINAL.read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    evidence = [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]
    return call["response"]["structured_output"], replace(gta_director_input(), allowed_evidence=evidence)


def goldens() -> dict:
    import scripts._instagram_viral_copy_polish as polish

    return {name: (json.loads((ROOT / "artifacts/instagram_feed_product/viral_copy_polish_20260926" / name / "polished_director_output.json")
                              .read_text(encoding="utf-8")), polish._director_input(name, cfg)) for name, cfg in polish.STORIES.items()}


def _verdict(pairs=(), repeats=False, aphorism: str = "", interpretations=()) -> dict:
    return {"same_thesis_pairs": [{"slides": list(p), "reason": "stub"} for p in pairs],
            "caption_repeats_slides": {"present": repeats, "reason": "stub" if repeats else ""},
            "caption_aphorism": {"present": bool(aphorism), "sentence": aphorism, "reason": "stub" if aphorism else ""},
            "unsupported_interpretation": [{"where": w, "sentence": s, "reason": "stub"} for w, s in interpretations]}


class StubGateway:
    """Answers ONLY the judge's request with a fixed structured verdict (or a failure) and counts the calls."""

    def __init__(self, verdict: dict | None = None, *, fail: str | None = None):
        self.verdict, self.fail, self.calls = verdict, fail, 0

    async def generate(self, request, **_kw):
        from integrations.llm_gateway.protocol import GenerateResponse

        self.calls += 1
        assert "same_thesis_pairs" in (request.response_schema or {}).get("properties", {}), "the stub only answers the judge"
        if self.fail == "raise":
            raise RuntimeError("stub gateway down")
        output = {"unexpected": True} if self.fail == "malformed" else self.verdict
        return GenerateResponse.model_construct(text=json.dumps(output), structured_output=output,
                                                finish_reason="length" if self.fail == "length" else "stop", usage=None)


async def _validate(output: dict, director_input, gateway) -> dict:
    import services.instagram_creative_director as cd
    from integrations.prompts.file_repository import FilePromptRepository
    from services.instagram_viral_format import EditorialCorrectionRequired

    repo = FilePromptRepository(ROOT / "prompts")
    try:
        await cd._validate_viral_carousel(gateway, repo, copy.deepcopy(output), SimpleNamespace(), director_input=director_input,
                                          archetype="trend_generative")
        return {"result": "PASS"}
    except EditorialCorrectionRequired as exc:
        return {"result": "EditorialCorrectionRequired", "findings": exc.findings}
    except Exception as exc:  # noqa: BLE001
        return {"result": f"{type(exc).__name__}: {str(exc)[:300]}"}


def _patch_call_generate() -> None:
    """In zero-cost mode the judge's call_generate goes straight to the stub (no gateway stack, no budget ledger)."""
    import services.instagram_viral_editorial_judge as judge

    async def direct(gateway, request, *, runtime, sequence):
        try:
            response = await gateway.generate(request)
        except Exception as exc:  # noqa: BLE001
            return SimpleNamespace(error=exc, response=None, call=None)
        return SimpleNamespace(error=None, response=response, call=None)

    judge.call_generate = direct


async def zero_cost() -> dict:
    from integrations.prompts.file_repository import FilePromptRepository
    from scripts._instagram_semantic_judge_fixtures import FIXTURES
    from services.instagram_viral_editorial_judge import build_judge_input, worst_case_cost_usd
    from services.instagram_viral_format import viral_copy_findings

    _patch_call_generate()
    repo = FilePromptRepository(ROOT / "prompts")
    raw, gta_input = gta_final()
    report: dict = {"provider_calls": 0,
                    "cost_bound": worst_case_cost_usd(repo, input_per_million=LUNA_INPUT_PER_M, output_per_million=LUNA_OUTPUT_PER_M),
                    "gta_judge_input_chars": len(build_judge_input(raw["slides"], raw.get("final_caption") or "", list(gta_input.allowed_evidence))),
                    "gta_judge_input": build_judge_input(raw["slides"], raw.get("final_caption") or "", list(gta_input.allowed_evidence))}
    fixtures = {}
    for key, f in FIXTURES.items():
        found = viral_copy_findings(copy.deepcopy(f["slides"]), f["evidence"], caption=f["caption"])
        ok = {"pass": not found, "fail": bool(found), "judge_only": True}[f["deterministic"]]
        fixtures[key] = {"expected_deterministic": f["deterministic"], "findings": found, "ok": ok}
    report["deterministic_fixtures"] = fixtures

    aphorism = "Иногда патч для старой игры приходит совсем не от тех, кто её выпустил."
    stub = StubGateway(_verdict(pairs=[(1, 2)], aphorism=aphorism))
    gta = await _validate(raw, gta_input, stub)
    report["gta_stub_wiring"] = {**gta, "judge_calls": stub.calls}
    report["golden_stub_empty_verdict"] = {}
    for name, (output, director_input) in goldens().items():
        stub = StubGateway(_verdict())
        report["golden_stub_empty_verdict"][name] = {**await _validate(output, director_input, stub), "judge_calls": stub.calls}
    report["fail_closed"] = {mode: (await _validate(raw, gta_input, StubGateway(_verdict(), fail=mode)))["result"][:90]
                             for mode in ("raise", "length", "malformed")}
    quoted = copy.deepcopy(raw)
    quoted["slides"][1]["slide_body"] = "Моддер сказал: «это было проще, чем казалось»."
    stub = StubGateway(_verdict())
    hard = await _validate(quoted, gta_input, stub)
    report["hard_failure_first"] = {**hard, "judge_calls": stub.calls}

    checks = {
        "cost_bound_under_a_fifth_of_director_worst": report["cost_bound"]["worst_case_usd"] < 0.2 * (10737 * LUNA_OUTPUT_PER_M / 1e6 + 0.012),
        "deterministic_fixtures": all(v["ok"] for v in fixtures.values()),
        "gta_stub_findings_reach_one_combined_correction": gta["result"] == "EditorialCorrectionRequired"
        and any(f.startswith("semantic review: slides 1 and 2") for f in gta["findings"])
        and any("generalised moral" in f for f in gta["findings"]) and report["gta_stub_wiring"]["judge_calls"] == 1,
        "golden_pass_with_empty_verdict": all(v["result"] == "PASS" and v["judge_calls"] == 1 for v in report["golden_stub_empty_verdict"].values()),
        "fail_closed": all(v.startswith("SemanticJudgeUnavailableError") for v in report["fail_closed"].values()),
        "hard_failure_never_judged": hard["result"].startswith("CreativeFactSafetyError") and report["hard_failure_first"]["judge_calls"] == 0,
    }
    report["checks"], report["all_pass"] = checks, all(checks.values())
    return report


async def live_judge(out: Path) -> dict:
    """The REAL judge on each case, once. Separately capped (KAGE_E2E_CAP_USD) through the harness's model-pinned provider guard."""
    os.environ.setdefault("KAGE_E2E_CAP_USD", os.environ.get("KAGE_JUDGE_CAL_CAP_USD", "0.15"))
    import scripts._instagram_e2e_week as harness
    from core.config import settings

    import integrations.llm_gateway.boot as boot
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from redis.asyncio import Redis
    from scripts._instagram_semantic_judge_fixtures import FIXTURES
    from services.budget_guard import RedisBudgetGuard
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.instagram_viral_editorial_judge import judge_viral_copy
    from services.pricing_catalog import ModelRegistryPricingCatalog

    namespace = os.environ["KAGE_JUDGE_CAL_NAMESPACE"]
    diag = Redis.from_url(harness.DIAG_REDIS_URL, decode_responses=True)
    if await diag.get(f"phase7:cost_ledger:{namespace}"):
        raise SystemExit(f"ledger {namespace} already holds spend - never run twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(harness.CAP),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=namespace)
    repo = FilePromptRepository(ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    harness._install_provider_guard(pricing, CostEstimator(pricing), models, RedisCostTracker(diag, pricing, ledger_namespace=namespace))
    harness.STATE["post"], harness.STATE["post_dir"] = "calibration", out / "live_judge"

    raw, gta_input = gta_final()
    cases = {"gta_final": (raw["slides"], raw.get("final_caption") or "", list(gta_input.allowed_evidence), None)}
    for name, (output, director_input) in goldens().items():
        cases[f"golden_{name}"] = (output["slides"], output.get("final_caption") or "", list(director_input.allowed_evidence), None)
    for key, f in FIXTURES.items():
        cases[key] = (f["slides"], f["caption"], f["evidence"], f["expect"])
    results = {}
    for key, (slides, caption, evidence, _expect) in cases.items():
        try:
            verdict = await judge_viral_copy(layer.gateway, repo, slides=slides, caption=caption, allowed_evidence=evidence)
            results[key] = {"verdict": verdict.raw, "findings": verdict.findings()}
        except Exception as exc:  # noqa: BLE001
            results[key] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}

    def pairs(key: str) -> list[tuple[int, int]]:
        return [tuple(sorted(p["slides"])) for p in (results[key].get("verdict") or {}).get("same_thesis_pairs", [])]

    def flag(key: str, name: str) -> bool:
        return bool(((results[key].get("verdict") or {}).get(name) or {}).get("present"))

    checks = {"1_gta_slides_1_2_same_thesis": (1, 2) in pairs("gta_final"),
              "1_gta_caption_aphorism": flag("gta_final", "caption_aphorism")
              and "Иногда патч" in results["gta_final"]["verdict"]["caption_aphorism"]["sentence"],
              "2_golden_deepseek_pass": results["golden_deepseek"].get("findings") == [],
              "3_golden_hamster_pass": results["golden_hamster"].get("findings") == []}
    for key, f in FIXTURES.items():
        expect = f["expect"]
        ok = "error" not in results[key] and sorted(pairs(key)) == sorted(expect["pairs"]) and flag(key, "caption_aphorism") == expect["aphorism"]
        if "repeats" in expect:
            ok = ok and flag(key, "caption_repeats_slides") == expect["repeats"]
        checks[key] = ok
    calls = [c for c in harness.STATE["calls"] if c["post"] == "calibration"]
    return {"provider_calls": len(calls), "spent_usd": str(harness.STATE["spent"]), "calls": calls, "results": results,
            "checks": checks, "all_pass": all(checks.values())}


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    if "--live-judge" in sys.argv:
        report = asyncio.run(live_judge(out))
        (out / "live_judge_calibration.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    else:
        report = asyncio.run(zero_cost())
        (out / "semantic_judge_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("checks", "all_pass")} | {k: report[k] for k in ("cost_bound", "spent_usd") if k in report},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
