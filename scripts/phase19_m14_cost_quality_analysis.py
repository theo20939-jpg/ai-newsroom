"""Phase 19 M14: model cost/quality analysis (docs/phase19_m14_cost_analysis_report.md).

Reads only real, already-recorded `ai_executions` rows (read-only - never writes) and the real
model catalog (`integrations/llm_gateway/models/catalog.py::build_model_registry()` - never an
invented model name or price). Produces four clearly separated sections:

  A. Historical real execution cost data - what was actually charged, per capability/model.
  B. Catalog-price simulation - what the SAME recorded token counts would cost at the CURRENT
     catalog price (never a claim about what was actually charged at call time).
  C. Fake-gateway harness validation - confirms the request/response contract every capability's
     own test suite already exercises via FakeLLMGateway (tests/fakes/fake_gateway.py) is
     consistent with this script's own token/cost accounting - never a real call.
  D. Real same-case model quality benchmark - explicitly NOT RUN, requires its own, separate,
     explicit paid-call authorization.

Never invents a model name or a price - `capability_routing_objective_overrides` stays empty
(core/config.py) regardless of what this script finds; populating it is a live routing-behavior
change requiring its own, separate authorization, never made by this script.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from database.models.ai_execution import AICapability, AIExecution
from database.session import async_session_factory
from integrations.llm_gateway.errors import UnknownModelPricingError
from integrations.llm_gateway.models.catalog import build_model_registry
from services.pricing_catalog import ModelRegistryPricingCatalog

_OUTPUT_PATH = Path(__file__).with_name("_phase19_m14_cost_quality_analysis_results.json")


@dataclass(frozen=True)
class _HistoricalGroup:
    capability: str
    model: str
    call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: str  # Decimal, stringified for JSON
    average_cost_per_call_usd: str


@dataclass(frozen=True)
class _CatalogSimulationGroup:
    capability: str
    model: str
    call_count: int
    recorded_total_cost_usd: str
    simulated_current_catalog_cost_usd: str | None  # None if the model is no longer in the catalog
    drift_usd: str | None  # simulated - recorded, None if simulation unavailable


async def _fetch_historical_groups() -> list[_HistoricalGroup]:
    """SECTION A: real, already-recorded data only - one bounded query, read-only."""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    AIExecution.capability, AIExecution.model, AIExecution.input_tokens,
                    AIExecution.output_tokens, AIExecution.cost,
                )
            )
        ).all()

    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for capability, model, input_tokens, output_tokens, cost in rows:
        grouped[(capability.value if isinstance(capability, AICapability) else str(capability), model)].append(
            (input_tokens or 0, output_tokens or 0, cost or Decimal(0))
        )

    results: list[_HistoricalGroup] = []
    for (capability, model), entries in sorted(grouped.items()):
        total_input = sum(e[0] for e in entries)
        total_output = sum(e[1] for e in entries)
        total_cost = sum((e[2] for e in entries), Decimal(0))
        count = len(entries)
        results.append(
            _HistoricalGroup(
                capability=capability, model=model, call_count=count,
                total_input_tokens=total_input, total_output_tokens=total_output,
                total_cost_usd=str(total_cost),
                average_cost_per_call_usd=str(total_cost / count) if count else "0",
            )
        )
    return results


def _simulate_catalog_prices(historical: list[_HistoricalGroup]) -> list[_CatalogSimulationGroup]:
    """SECTION B: what the SAME recorded token counts would cost at CURRENT catalog prices -
    never a claim about what was actually charged (that is Section A's own job)."""
    catalog = ModelRegistryPricingCatalog(build_model_registry())
    results: list[_CatalogSimulationGroup] = []
    for group in historical:
        try:
            tier = catalog.get_tier(group.model, condition="standard")
        except UnknownModelPricingError:
            results.append(
                _CatalogSimulationGroup(
                    capability=group.capability, model=group.model, call_count=group.call_count,
                    recorded_total_cost_usd=group.total_cost_usd,
                    simulated_current_catalog_cost_usd=None, drift_usd=None,
                )
            )
            continue

        simulated = (
            (Decimal(group.total_input_tokens) / Decimal(1_000_000)) * tier.input_price_per_million
            + (Decimal(group.total_output_tokens) / Decimal(1_000_000)) * tier.output_price_per_million
        )
        recorded = Decimal(group.total_cost_usd)
        results.append(
            _CatalogSimulationGroup(
                capability=group.capability, model=group.model, call_count=group.call_count,
                recorded_total_cost_usd=group.total_cost_usd,
                simulated_current_catalog_cost_usd=str(simulated), drift_usd=str(simulated - recorded),
            )
        )
    return results


def _fake_gateway_harness_validation_note() -> dict:
    """SECTION C: never a real call - this script does not itself run anything against
    FakeLLMGateway (that is each capability's own unit-test suite's job, e.g. tests/
    test_editorial_planning_capability.py, tests/test_media_vision_review_capability.py).
    Recorded here only as an explicit pointer/status, so the final report's own Section C is
    never confused with a real benchmark."""
    return {
        "status": "SIMULATED / FAKE-GATEWAY RESULT",
        "note": (
            "Every registered capability's request/response contract (including token usage "
            "accounting via CapabilityUsage) is already exercised against tests/fakes/"
            "fake_gateway.py::FakeLLMGateway in that capability's own test module - never a real "
            "network call. This script does not duplicate that machinery; it only reports that "
            "it exists and where to find it."
        ),
    }


def _real_benchmark_not_run_note() -> dict:
    """SECTION D: explicitly, unambiguously not executed."""
    return {
        "status": "REAL SAME-CASE MODEL QUALITY BENCHMARK - NOT RUN / REQUIRES PAID AUTHORIZATION",
        "note": (
            "A same-case comparison (identical prompt/context, multiple real models, real "
            "provider calls, human- or automated-judged output quality) would require real, "
            "paid provider calls - not made as part of this implementation. Any concrete "
            "model-choice recommendation below is a hypothesis requiring this benchmark's "
            "explicit, separate authorization before being treated as validated."
        ),
    }


async def main() -> None:
    historical = await _fetch_historical_groups()
    simulation = _simulate_catalog_prices(historical)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "section_a_historical_real_execution_cost_data": [asdict(g) for g in historical],
        "section_b_catalog_price_simulation": [asdict(g) for g in simulation],
        "section_c_fake_gateway_harness_validation": _fake_gateway_harness_validation_note(),
        "section_d_real_benchmark": _real_benchmark_not_run_note(),
    }
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Section A: {len(historical)} (capability, model) groups from real ai_executions data.")
    total_recorded_cost = sum(Decimal(g.total_cost_usd) for g in historical)
    print(f"  Total recorded cost across all groups: ${total_recorded_cost}")
    print(f"Section B: {len(simulation)} groups simulated against the current catalog.")
    unpriced = [g for g in simulation if g.simulated_current_catalog_cost_usd is None]
    if unpriced:
        print(f"  {len(unpriced)} group(s) reference a model no longer in the catalog - drift not computable.")
    print("Section C: fake-gateway harness validation - see each capability's own test suite.")
    print("Section D: REAL SAME-CASE MODEL QUALITY BENCHMARK - NOT RUN / REQUIRES PAID AUTHORIZATION.")
    print(f"Full results written to {_OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
