"""INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1 §16.D/I/J/N: the worker-side glue
(`worker.content_cycle._run_instagram_automatic_trigger`) in isolation - the per-cycle rollout cap,
the `gate_gateway=None` safe no-op, and per-story crash isolation. `_classify_event_for_router_
treatment`/`evaluate_and_submit_instagram_candidate` are monkeypatched at the `worker.content_cycle`
module level (both are plain, directly-imported names there) - no real DB/LLM/Telegram call in this
file."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import worker.content_cycle as cc
from core.config import settings
from services.editorial_treatment import MAJOR, EditorialTreatmentDecision
from services.instagram_automatic_trigger import InstagramTriggerCandidateOutcome

pytestmark = pytest.mark.asyncio


class _FakeSession:
    def __init__(self, event_row) -> None:
        self._event_row = event_row

    async def get(self, model, ident):
        return self._event_row

    async def scalar(self, stmt):
        return None  # no NEWS_ANALYSIS task found -> facts=[] - fine, not under test here

    async def commit(self) -> None:
        pass


def _session_factory_for(event_row):
    @asynccontextmanager
    async def _factory():
        yield _FakeSession(event_row)
    return _factory


class _FakeEventRow:
    def __init__(self, title: str = "A real story") -> None:
        self.title = title
        self.url = None


async def test_d_and_j_gate_gateway_none_is_a_complete_safe_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """§J (worker-level): no gateway configured -> zero evaluation, never a crash, never a partial
    attempt - also the concrete mechanism behind "does not require Instagram credentials/an LLM
    gateway to exist" at the automatic-trigger call site itself."""
    called = {"n": 0}

    async def _must_not_be_called(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must never be reached when gate_gateway is None")

    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_candidate", _must_not_be_called)
    report = await cc._run_instagram_automatic_trigger(
        _session_factory_for(_FakeEventRow()), AsyncMock(), [uuid4(), uuid4()],
        gate_gateway=None, gate_prompt_repository=None,
    )
    assert report.stories_evaluated == 0
    assert called["n"] == 0


async def test_n_per_cycle_cap_bounds_evaluation_even_with_more_eligible_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """§9/§10/§16.N: even if `_select_eligible_events()` (or an override) returns many eligible
    ids, the automatic trigger only evaluates up to `_INSTAGRAM_TRIGGER_MAX_PER_CYCLE` per cycle -
    never a first-deploy flood."""
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", True)
    seen: list[str] = []

    async def _fake_classify(session, event_id):
        return EditorialTreatmentDecision(treatment=MAJOR, human_review_required=False, reason="test")

    async def _fake_submit(session, bot, *, event_id, event_title, treatment, research_facts, gateway, prompt_repository, source_url=None, phase_a_enabled=False):
        seen.append(event_id)
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=True, reason="submitted", gate_decision="ready_for_editor", delivery_sent=True)

    monkeypatch.setattr(cc, "_classify_event_for_router_treatment", _fake_classify)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_candidate", _fake_submit)

    many_ids = [uuid4() for _ in range(10)]
    report = await cc._run_instagram_automatic_trigger(
        _session_factory_for(_FakeEventRow()), AsyncMock(), many_ids,
        gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == cc._INSTAGRAM_TRIGGER_MAX_PER_CYCLE
    assert len(seen) == cc._INSTAGRAM_TRIGGER_MAX_PER_CYCLE


async def test_i_a_per_story_failure_never_aborts_the_remaining_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8/§16.I crash safety: one story's unexpected exception (simulating a Telegram send
    failure, a DB hiccup, or a Creative Director crash) must not stop the remaining candidates in
    the same cycle from being evaluated."""
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", True)
    calls: list[str] = []

    async def _fake_classify(session, event_id):
        return EditorialTreatmentDecision(treatment=MAJOR, human_review_required=False, reason="test")

    async def _flaky_submit(session, bot, *, event_id, event_title, treatment, research_facts, gateway, prompt_repository, source_url=None, phase_a_enabled=False):
        calls.append(event_id)
        if len(calls) == 1:
            raise RuntimeError("simulated Telegram/DB failure for the first candidate")
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=True, reason="submitted", gate_decision="ready_for_editor", delivery_sent=True)

    monkeypatch.setattr(cc, "_classify_event_for_router_treatment", _fake_classify)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_candidate", _flaky_submit)

    ids = [uuid4(), uuid4()]
    report = await cc._run_instagram_automatic_trigger(
        _session_factory_for(_FakeEventRow()), AsyncMock(), ids,
        gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert len(calls) == 2  # the second candidate was still attempted after the first raised
    assert report.stories_evaluated == 1  # only the surviving one is counted
    assert report.packages_delivered == 1
