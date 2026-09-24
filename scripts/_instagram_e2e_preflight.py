"""ZERO-COST end-to-end cost preflight for the frozen 5-11 Aug 2026 KAGE week, from the REAL evidence packages (readiness json).

Nothing is sent to any provider. Calls are priced at the router's deterministic first pick (LOWEST_COST: gpt-5.6-luna) with every
fallback blocked by the validation harness (one provider request per logical call - the established paid-validation discipline):
  - Phase A decision: the REAL request (production prompt + user-text builder + the post's package evidence; DB-derived contexts padded
    by CONTEXT_PAD_CHARS) at the new explicit max_tokens;
  - Creative Director: production max_tokens (16,000) and input = real past CD input (12.5k tokens) + this post's extra evidence;
  - vision suitability: one check per available source image (max_tokens 400, image ~1.5k tokens);
  - image generation: 0 (instagram_image_generation_mode stays off).
BASE worst case = every call at its full output bound; WITH EXISTING RETRY adds the Creative Director's single built-in contract retry
per post (optional spend, never assumed). Input tokens use the conservative 2-characters-per-token rate.

Usage: python scripts/_instagram_e2e_preflight.py <evidence_readiness.json> <out.json>
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.instagram_creative_director as cd  # noqa: E402
from integrations.llm_gateway.models.catalog import build_model_registry  # noqa: E402
from integrations.prompts.file_repository import FilePromptRepository  # noqa: E402
from services.instagram_director_context import load_instagram_director_context  # noqa: E402

MODEL = "gpt-5.6-luna"
CONTEXT_PAD_CHARS = 4000  # account / product / recent-history contexts the offline build leaves empty
CD_BASE_INPUT_TOKENS = 12_500
VISION_INPUT_TOKENS, VISION_MAX_TOKENS = 1_500, 400
M = Decimal(1_000_000)


def main() -> None:
    readiness = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = next(t for t in {m.model_id: m for m in build_model_registry().all_models()}[MODEL].pricing_tiers if t.condition == "standard")
    price_in, price_out = tier.input_price_per_million, tier.output_price_per_million
    prompt = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts").resolve(
        cd.EDITORIAL_DECISION_PROMPT_NAME, cd._EDITORIAL_DECISION_PROMPT_VERSION)
    system_chars = len(prompt.system) + sum(len(r) for r in prompt.rules) + len(json.dumps(prompt.output_schema))
    brand = load_instagram_director_context()

    posts = [p for p in readiness["daily"] if "steps" in p]  # dedup-blocked item is priced separately below
    recap = readiness["recap"]
    rows, base, expected, retry = [], Decimal(0), Decimal(0), Decimal(0)

    def evidence_lines(p) -> list[str]:
        return [p["premise"]] + [f"{i['kind']}: {i['text']}" for i in p["steps"] + p["facts"] + p["limitations"]]

    def decision(evidence: list[str], title: str) -> tuple[Decimal, Decimal]:
        di = cd.InstagramEditorialDecisionInput(source_type="news", source_summary=title, allowed_evidence=evidence, brand_context=brand)
        chars = system_chars + len(cd._build_decision_user_text(di)) + CONTEXT_PAD_CHARS
        tokens_in = Decimal(chars // 2)
        worst = (tokens_in * price_in + Decimal(cd._EDITORIAL_DECISION_MAX_TOKENS) * price_out) / M
        typical = (tokens_in * price_in * Decimal("0.7") + Decimal(3000) * price_out) / M
        return worst, typical

    def creative(extra_chars: int) -> tuple[Decimal, Decimal]:
        tokens_in = Decimal(CD_BASE_INPUT_TOKENS + extra_chars // 2)
        worst = (tokens_in * price_in + Decimal(cd._CREATIVE_DIRECTOR_MAX_TOKENS) * price_out) / M
        typical = (tokens_in * price_in * Decimal("0.8") + Decimal(6000) * price_out) / M
        return worst, typical

    vision_worst = (Decimal(VISION_INPUT_TOKENS) * price_in + Decimal(VISION_MAX_TOKENS) * price_out) / M
    calls = {"phase_a_decisions": 0, "creative_director": 0, "creative_director_existing_retry_max": 0, "vision": 0, "image_generation": 0}
    for p in posts:
        ev = evidence_lines(p)
        d_w, d_t = decision(ev, p["title"])
        c_w, c_t = creative(sum(len(x) for x in ev))
        v = vision_worst if p["media"]["status"] == "AVAILABLE" else Decimal(0)
        calls["phase_a_decisions"] += 1
        calls["creative_director"] += 1
        calls["creative_director_existing_retry_max"] += 1
        calls["vision"] += int(v > 0)
        base += d_w + c_w + v
        expected += d_t + c_t + v / 2
        retry += c_w
        rows.append({"post": f"{p['day']} #{p['slot']} {p['format']}", "evidence_quality": p["quality"], "decision_worst": str(d_w.quantize(Decimal('0.0001'))),
                     "creative_worst": str(c_w.quantize(Decimal('0.0001'))), "vision_worst": str(v.quantize(Decimal('0.0001')))})
    # the Tuesday gym copy: one Phase A decision whose frozen dedup verdict is part of what the E2E proves (no Creative Director)
    monday_gym = next(p for p in posts if p["day"] == "2026-08-10" and p["slot"] == 2)  # same event: its evidence size is the proxy
    gym_w, gym_t = decision(evidence_lines(monday_gym), "AI agent hacks gym to get its owner spot in pilates class")
    calls["phase_a_decisions"] += 1
    base += gym_w
    expected += gym_t
    # the weekly recap: one decision + one Creative Director over ALL story evidence; one vision check per recap story image (all of them)
    recap_ev = [line for r in recap for line in evidence_lines(r)[:4]]
    r_dw, r_dt = decision(recap_ev, "Weekly recap")
    r_cw, r_ct = creative(sum(len(x) for x in recap_ev))
    calls["phase_a_decisions"] += 1
    calls["creative_director"] += 1
    calls["creative_director_existing_retry_max"] += 1
    calls["vision"] += len(recap)
    base += r_dw + r_cw + vision_worst * len(recap)
    expected += r_dt + r_ct + vision_worst * len(recap) / 2
    retry += r_cw
    q = Decimal("0.01")
    report = {"model_priced": MODEL, "calls": calls, "provider_calls_base": calls["phase_a_decisions"] + calls["creative_director"] + calls["vision"],
              "phase_a_max_tokens": cd._EDITORIAL_DECISION_MAX_TOKENS, "creative_director_max_tokens": cd._CREATIVE_DIRECTOR_MAX_TOKENS,
              "base_worst_case_usd": str(base.quantize(q)), "worst_case_with_existing_retry_usd": str((base + retry).quantize(q)),
              "expected_usd": str(expected.quantize(q)), "rows": rows}
    Path(sys.argv[2]).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
