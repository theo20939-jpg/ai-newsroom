"""Phase 19 M14: scripts.phase19_m14_cost_quality_analysis - pure catalog-simulation logic only
(no DB, no network). Uses the real model catalog (never invented model names/prices)."""
from __future__ import annotations

from decimal import Decimal

from scripts.phase19_m14_cost_quality_analysis import (
    _HistoricalGroup,
    _real_benchmark_not_run_note,
    _simulate_catalog_prices,
)


def test_known_model_produces_a_simulated_cost() -> None:
    group = _HistoricalGroup(
        capability="RESEARCH", model="gpt-5.6-luna", call_count=1, total_input_tokens=1_000_000,
        total_output_tokens=1_000_000, total_cost_usd="1.00", average_cost_per_call_usd="1.00",
    )
    results = _simulate_catalog_prices([group])
    assert len(results) == 1
    assert results[0].simulated_current_catalog_cost_usd is not None
    assert Decimal(results[0].simulated_current_catalog_cost_usd) > 0


def test_unknown_model_produces_no_simulation_never_raises() -> None:
    group = _HistoricalGroup(
        capability="RESEARCH", model="not-a-real-model-id", call_count=1, total_input_tokens=100,
        total_output_tokens=100, total_cost_usd="0.01", average_cost_per_call_usd="0.01",
    )
    results = _simulate_catalog_prices([group])
    assert results[0].simulated_current_catalog_cost_usd is None
    assert results[0].drift_usd is None


def test_drift_is_zero_when_catalog_price_matches_recorded_cost_exactly() -> None:
    """A drift of zero is a legitimate, expected outcome (prices haven't changed) - not itself a
    bug or a sign the simulation is broken."""
    group = _HistoricalGroup(
        capability="RESEARCH", model="gpt-5.6-luna", call_count=1, total_input_tokens=0,
        total_output_tokens=0, total_cost_usd="0", average_cost_per_call_usd="0",
    )
    results = _simulate_catalog_prices([group])
    assert Decimal(results[0].drift_usd) == 0


def test_real_benchmark_note_is_explicitly_labeled_not_run() -> None:
    note = _real_benchmark_not_run_note()
    assert "NOT RUN" in note["status"]
    assert "REQUIRES PAID AUTHORIZATION" in note["status"]


def test_empty_input_produces_empty_output() -> None:
    assert _simulate_catalog_prices([]) == []
