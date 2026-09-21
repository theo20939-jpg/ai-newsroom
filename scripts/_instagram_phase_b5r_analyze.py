"""Manual-only Phase B.5R: ONE additional multimodal reference-analysis call (prompt v3: sample-by-sample +
family clustering over the real board pixels and labelled sample montages) -> Visual DNA v2. The raw
model output is persisted BEFORE validation. Usage: python scripts/_instagram_phase_b5r_analyze.py <out_dir>"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from core.config import settings
from core.redis import get_redis_client
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.cost_tracker import compute_call_cost
from services.instagram_reference_analysis import analyze_reference_samples
from services.instagram_visual_dna import DNA_DIR, REFERENCE_BOARD_PATH
from services.instagram_visual_dna_v2 import render_visual_dna_v2_markdown
from services.pricing_catalog import ModelRegistryPricingCatalog

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_WORST_CASE_USD = Decimal("0.60")


async def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    ns = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_ledger = await get_redis_client().get(f"phase7:cost_ledger:{ns}")
    spent = Decimal(str(raw_ledger)) if raw_ledger is not None else Decimal(0)
    budget = Decimal(str(settings.llm_daily_budget_usd))
    pre = {"ledger_namespace": ns, "spent_today_usd": str(spent), "daily_budget_usd": str(budget),
           "worst_case_usd": str(_WORST_CASE_USD), "mode": settings.llm_budget_mode, "safe": spent + _WORST_CASE_USD <= budget}
    (out_dir / "budget_preflight.json").write_text(json.dumps(pre, indent=2), encoding="utf-8")
    print("BUDGET_PREFLIGHT", json.dumps(pre))
    if not pre["safe"]:
        print("SAFE_STOP: production budget cannot accommodate the reference-analysis call")
        return
    layer = assemble_ai_integration_layer(settings, FilePromptRepository(_PROMPTS))
    sink: list = []
    raw: list = []
    try:
        dna = await analyze_reference_samples(
            layer.gateway, FilePromptRepository(_PROMPTS), reference_path=REFERENCE_BOARD_PATH,
            repo_relative_path="docs/references/instagram/instagram_visual_reference_board_v1.png", call_sink=sink, raw_sink=raw,
        )
    except Exception as exc:  # noqa: BLE001 - never lose a paid output
        if raw:
            (out_dir / "reference_analysis_v3_raw_output.json").write_text(json.dumps(raw[0], ensure_ascii=False, indent=2), encoding="utf-8")
        if sink:
            c = sink[0]
            (out_dir / "call_meta.json").write_text(json.dumps({"model": c.model_used, "input_tokens": c.usage.input_tokens, "output_tokens": c.usage.output_tokens}), encoding="utf-8")
        print("ANALYSIS_FAILED", type(exc).__name__, str(exc)[:600])
        return
    call = sink[0]
    (out_dir / "reference_analysis_v3_raw_output.json").write_text(json.dumps(raw[0], ensure_ascii=False, indent=2), encoding="utf-8")
    cost = compute_call_cost(call, ModelRegistryPricingCatalog(build_model_registry()))
    meta = {"model": call.model_used, "cost_usd": str(cost), "input_tokens": call.usage.input_tokens, "output_tokens": call.usage.output_tokens}
    (out_dir / "call_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    DNA_DIR.mkdir(parents=True, exist_ok=True)
    (out_dir / "v2.json").write_text(dna.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "v2.md").write_text(render_visual_dna_v2_markdown(dna), encoding="utf-8")
    print("DONE", json.dumps(meta))


if __name__ == "__main__":
    asyncio.run(main())
