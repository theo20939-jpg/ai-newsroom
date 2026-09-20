"""Manual-only Phase B.5 reference analysis: ONE controlled vision call that turns the founder
reference board IMAGE into versioned, reviewable Visual DNA (docs/references/instagram/visual_dna/v1.json
+ .md) and a founder-review sheet. Reuses the existing reference-analysis boundary
(services/instagram_reference_analysis.py::analyze_reference_image) and the existing gateway, budget
guard and multimodal mechanism. Run once per reference - never per Instagram post.

Usage: python scripts/_instagram_phase_b5_analyze_reference.py <artifacts_reference_dir>"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw

from core.config import settings
from core.redis import get_redis_client
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.cost_tracker import compute_call_cost
from services.instagram_reference_analysis import analyze_reference_image
from services.instagram_visual_dna import DNA_DIR, REFERENCE_BOARD_PATH, InstagramVisualDNA, render_visual_dna_markdown
from services.instagram_visual_profiles import ig_font
from services.pricing_catalog import ModelRegistryPricingCatalog

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_WORST_CASE_USD = Decimal("0.45")  # one image call + structured output, priciest structured model


def _review_sheet(dna: InstagramVisualDNA) -> Image.Image:
    """REFERENCE + EXTRACTED PRINCIPLES, for founder review (the reference is shown only as the source
    the principles were read from; nothing here is a template)."""
    ref = Image.open(REFERENCE_BOARD_PATH).convert("RGB")
    width = 2400
    ref_h = round(ref.height * (1100 / ref.width))
    sheet = Image.new("RGB", (width, max(ref_h + 80, 2000)), (247, 248, 250))
    d = ImageDraw.Draw(sheet)
    d.text((40, 20), "REFERENCE (source the principles were read from)", font=ig_font(26, "black"), fill=(20, 20, 24))
    sheet.paste(ref.resize((1100, ref_h)), (40, 70))
    x0, y = 1240, 20
    d.text((x0, y), f"EXTRACTED VISUAL DNA v{dna.version} - rules, not a template", font=ig_font(26, "black"), fill=(200, 30, 38))
    y += 50
    font_h, font_b = ig_font(22, "black"), ig_font(19, "medium")

    def wrap(text: str, max_w: int) -> list[str]:
        lines, cur = [], ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if d.textlength(trial, font=font_b) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        return lines + ([cur] if cur else [])

    for title, items in (
        ("TYPOGRAPHY", dna.typography), ("SPATIAL SYSTEM", dna.spatial_system), ("IMAGE BEHAVIOR", dna.image_behavior),
        ("COMPOSITION RHYTHM", dna.composition_rhythm), ("ACCENT SYSTEM", dna.accent_system),
        ("BRAND INVARIANTS", dna.brand_invariants), ("NON-INVARIANTS (vary)", dna.non_invariants),
        ("MUST NOT COPY", dna.must_not_copy), ("ORIGINALITY", dna.originality_constraints),
    ):
        d.text((x0, y), title, font=font_h, fill=(20, 20, 24))
        y += 30
        for item in items:
            for i, line in enumerate(wrap(item, 1080)):
                d.text((x0 + (0 if i == 0 else 22), y), ("- " if i == 0 else "") + line, font=font_b, fill=(60, 64, 72))
                y += 25
        y += 12
    return sheet.crop((0, 0, width, min(sheet.height, max(y + 30, ref_h + 90))))


async def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    ns = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = await get_redis_client().get(f"phase7:cost_ledger:{ns}")
    spent = Decimal(str(raw)) if raw is not None else Decimal(0)
    budget = Decimal(str(settings.llm_daily_budget_usd))
    pre = {"ledger_namespace": ns, "spent_today_usd": str(spent), "daily_budget_usd": str(budget),
           "worst_case_usd": str(_WORST_CASE_USD), "mode": settings.llm_budget_mode, "safe": spent + _WORST_CASE_USD <= budget}
    (out_dir / "reference_analysis_budget_preflight.json").write_text(json.dumps(pre, indent=2), encoding="utf-8")
    print("BUDGET_PREFLIGHT", json.dumps(pre))
    if not pre["safe"]:
        print("SAFE_STOP: production budget cannot accommodate the reference-analysis call")
        return

    layer = assemble_ai_integration_layer(settings, FilePromptRepository(_PROMPTS))
    sink: list = []
    raw: list = []
    try:
        _decon, dna = await analyze_reference_image(
            layer.gateway, FilePromptRepository(_PROMPTS), reference_path=REFERENCE_BOARD_PATH,
            repo_relative_path="docs/references/instagram/instagram_visual_reference_board_v1.png", call_sink=sink, raw_sink=raw,
        )
    except Exception as exc:  # noqa: BLE001 - never lose a paid output
        if raw:
            (out_dir / "reference_analysis_raw_output_REJECTED.json").write_text(json.dumps(raw[0], ensure_ascii=False, indent=2), encoding="utf-8")
        print("ANALYSIS_FAILED", type(exc).__name__, str(exc)[:300])
        return
    call = sink[0]
    cost = compute_call_cost(call, ModelRegistryPricingCatalog(build_model_registry()))
    DNA_DIR.mkdir(parents=True, exist_ok=True)
    payload = dna.model_dump_json(indent=2)
    (DNA_DIR / "v1.json").write_text(payload, encoding="utf-8")
    md = render_visual_dna_markdown(dna)
    (DNA_DIR / "v1.md").write_text(md, encoding="utf-8")
    (out_dir / "reference_visual_dna.json").write_text(payload, encoding="utf-8")
    (out_dir / "reference_visual_dna.md").write_text(md, encoding="utf-8")
    _review_sheet(dna).save(out_dir / "reference_dna_review_sheet.png")
    print("DONE", json.dumps({"model": call.model_used, "cost_usd": str(cost), "input_tokens": call.usage.input_tokens,
                              "output_tokens": call.usage.output_tokens, "reference_sha256": dna.reference_sha256}))


if __name__ == "__main__":
    asyncio.run(main())
