"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: `worker.content_cycle._run_instagram_product_lane` in
isolation - the `gate_gateway=None` safe no-op, and that it calls the real
`run_instagram_growth_strategist()`/`evaluate_and_submit_instagram_opportunity()` chain rather than
a hand-rolled opportunity. Mirrors tests/test_instagram_automatic_trigger_worker_wiring.py's own
conventions (monkeypatched module-level names, no real DB/LLM/Telegram call in this file)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

import worker.content_cycle as cc
from core.config import settings
from services.instagram_automatic_trigger import InstagramTriggerCandidateOutcome

pytestmark = pytest.mark.asyncio


def _enable_product_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", True)
    monkeypatch.setattr(settings, "instagram_product_lane_enabled", True)


@dataclass
class _FakeOpportunity:
    id: str
    product_id: str = "prod-1"


@dataclass
class _FakeStrategy:
    priority_opportunities: list


@dataclass
class _FakeResult:
    strategy: _FakeStrategy


class _FakeSession:
    async def commit(self) -> None:
        pass


def _session_factory():
    @asynccontextmanager
    async def _factory():
        yield _FakeSession()
    return _factory


async def test_gate_gateway_none_is_a_complete_safe_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_product_lane(monkeypatch)
    called = {"n": 0}

    async def _must_not_be_called(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must never be reached when gate_gateway is None")

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _must_not_be_called)
    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=None, gate_prompt_repository=None,
    )
    assert report.stories_evaluated == 0
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# CONTROLLED ROLLOUT (INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 closure): the dedicated
# instagram_product_lane_enabled runtime gate - default False, checked before gate_gateway/
# gate_prompt_repository, never falls through to another lane.
# ---------------------------------------------------------------------------


async def test_product_lane_disabled_by_default_is_a_complete_safe_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    assert settings.instagram_product_lane_enabled is False  # the real, un-monkeypatched default
    called = {"n": 0}

    async def _must_not_be_called(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must never be reached while instagram_product_lane_enabled is False")

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _must_not_be_called)
    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0
    assert called["n"] == 0


async def test_product_lane_disabled_takes_priority_over_a_real_gate_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with real gate_gateway/gate_prompt_repository (the NEWS lane's own, already-satisfied
    condition in production), the dedicated flag alone must be enough to keep this lane inert."""
    monkeypatch.setattr(settings, "instagram_product_lane_enabled", False)
    called = {"n": 0}

    async def _must_not_be_called(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must never be reached while instagram_product_lane_enabled is False")

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _must_not_be_called)
    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0
    assert called["n"] == 0


async def test_wires_through_growth_strategist_ranking_and_general_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves the PRODUCT lane is wired through generate_growth_strategy()'s real ranking output
    (via run_instagram_growth_strategist()), not a hand-rolled opportunity - the exact "wire
    generate_growth_strategy() into the real execution path" requirement."""
    _enable_product_lane(monkeypatch)
    opportunity = _FakeOpportunity(id="product_context:abc")

    async def _fake_growth_strategist(session, *, now):
        return _FakeResult(strategy=_FakeStrategy(priority_opportunities=[opportunity]))

    calls: list[str] = []

    async def _fake_submit(session, bot, *, opportunity, opportunity_summary, gateway, prompt_repository, source_url=None, phase_a_enabled=False):
        calls.append(opportunity.id)
        return InstagramTriggerCandidateOutcome(
            event_id=opportunity.id, accepted=True, reason="submitted", gate_decision="ready_for_editor", delivery_sent=True,
        )

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _fake_growth_strategist)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_opportunity", _fake_submit)

    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert calls == ["product_context:abc"]
    assert report.stories_evaluated == 1
    assert report.packages_delivered == 1


async def test_per_cycle_cap_bounds_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_product_lane(monkeypatch)
    opportunities = [_FakeOpportunity(id=f"product_context:{i}") for i in range(5)]

    async def _fake_growth_strategist(session, *, now):
        return _FakeResult(strategy=_FakeStrategy(priority_opportunities=opportunities))

    calls: list[str] = []

    async def _fake_submit(session, bot, *, opportunity, opportunity_summary, gateway, prompt_repository, source_url=None, phase_a_enabled=False):
        calls.append(opportunity.id)
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason="submitted", gate_decision="ready_for_editor", delivery_sent=True)

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _fake_growth_strategist)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_opportunity", _fake_submit)

    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert len(calls) == cc._INSTAGRAM_PRODUCT_LANE_MAX_PER_CYCLE
    assert report.stories_evaluated == cc._INSTAGRAM_PRODUCT_LANE_MAX_PER_CYCLE


async def test_ranking_failure_is_isolated_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_product_lane(monkeypatch)

    async def _boom(session, *, now):
        raise RuntimeError("simulated ranking failure")

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _boom)
    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0


async def test_per_candidate_failure_never_aborts_the_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_product_lane(monkeypatch)
    opportunity = _FakeOpportunity(id="product_context:flaky")

    async def _fake_growth_strategist(session, *, now):
        return _FakeResult(strategy=_FakeStrategy(priority_opportunities=[opportunity]))

    async def _flaky_submit(session, bot, *, opportunity, opportunity_summary, gateway, prompt_repository, source_url=None, phase_a_enabled=False):
        raise RuntimeError("simulated Telegram/DB failure")

    monkeypatch.setattr(cc, "run_instagram_growth_strategist", _fake_growth_strategist)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_opportunity", _flaky_submit)

    report = await cc._run_instagram_product_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0  # the one candidate failed, isolated, never propagated
