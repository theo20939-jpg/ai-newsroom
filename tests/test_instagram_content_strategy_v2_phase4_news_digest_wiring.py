"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4: `worker.content_cycle._run_instagram_news_digest_lane`
in isolation, plus the structural regression proving the old per-story MAJOR-treatment NEWS
trigger is no longer called from the live `run_content_cycle()` path ("do NOT leave both paths
live"). Mirrors tests/test_instagram_content_strategy_v2_phase2_worker_wiring.py's own
conventions - monkeypatched module-level names, no real DB/LLM/Telegram call in this file."""
from __future__ import annotations

import ast
import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

import worker.content_cycle as cc
from services.instagram_automatic_trigger import InstagramTriggerCandidateOutcome


@dataclass
class _FakeCandidate:
    event_id: object
    title: str = "Story"
    score: int = 90
    facts: list = None

    def __post_init__(self):
        if self.facts is None:
            self.facts = []


class _FakeSession:
    async def commit(self) -> None:
        pass


def _session_factory():
    @asynccontextmanager
    async def _factory():
        yield _FakeSession()
    return _factory


# ---------------------------------------------------------------------------
# Structural regression: the old NEWS trigger is unreachable from the live cycle
# ---------------------------------------------------------------------------


def test_old_news_major_trigger_is_never_called_from_run_content_cycle() -> None:
    """"do NOT leave both paths live" - an AST-based check (never fooled by the string merely
    appearing inside a comment/docstring, unlike a plain substring search) that run_content_
    cycle()'s own body contains no CALL to _run_instagram_automatic_trigger."""
    tree = ast.parse(inspect.getsource(cc.run_content_cycle))
    called_names = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_run_instagram_automatic_trigger" not in called_names
    assert "_run_instagram_news_digest_lane" in called_names


def test_old_news_trigger_function_still_exists_as_a_documented_unit() -> None:
    """Not deleted - kept as an independently-testable unit (its own 14+3 tests still pass) - just
    unreachable from the live cycle."""
    assert hasattr(cc, "_run_instagram_automatic_trigger")


def test_content_cycle_result_no_longer_populates_the_old_news_trigger_report_field() -> None:
    tree = ast.parse(inspect.getsource(cc.run_content_cycle))
    assigns_old_field = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "instagram_trigger_report" for t in node.targets)
        for node in ast.walk(tree)
    )
    assert assigns_old_field is False


# ---------------------------------------------------------------------------
# _run_instagram_news_digest_lane(): wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_gateway_none_is_a_complete_safe_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def _must_not_be_called(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must never be reached when gate_gateway is None")

    monkeypatch.setattr(cc, "is_digest_due", _must_not_be_called)
    report = await cc._run_instagram_news_digest_lane(
        _session_factory(), AsyncMock(), gate_gateway=None, gate_prompt_repository=None,
    )
    assert report.stories_evaluated == 0
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_not_due_yet_never_selects_stories_or_submits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _not_due(session, *, now):
        return False

    called = {"n": 0}

    async def _must_not_be_called(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must never be reached when not due")

    monkeypatch.setattr(cc, "is_digest_due", _not_due)
    monkeypatch.setattr(cc, "select_digest_stories", _must_not_be_called)
    report = await cc._run_instagram_news_digest_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_due_but_no_strong_stories_still_advances_the_schedule_never_submits(monkeypatch: pytest.MonkeyPatch) -> None:
    mark_calls: list[str] = []

    async def _due(session, *, now):
        return True

    async def _no_stories(session, *, now):
        return []

    async def _mark(session, *, now):
        mark_calls.append("marked")

    submit_calls: list[str] = []

    async def _must_not_submit(*args, **kwargs):
        submit_calls.append("submitted")
        raise AssertionError("must never submit with zero strong stories")

    monkeypatch.setattr(cc, "is_digest_due", _due)
    monkeypatch.setattr(cc, "select_digest_stories", _no_stories)
    monkeypatch.setattr(cc, "mark_digest_run", _mark)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_opportunity", _must_not_submit)

    report = await cc._run_instagram_news_digest_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0
    assert mark_calls == ["marked"]  # schedule still advances - never retries the same weak window
    assert submit_calls == []


@pytest.mark.asyncio
async def test_due_with_strong_stories_submits_a_carousel_opportunity(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    stories = [_FakeCandidate(event_id=uuid4(), title="Story A"), _FakeCandidate(event_id=uuid4(), title="Story B")]

    async def _due(session, *, now):
        return True

    async def _select(session, *, now):
        return stories

    async def _mark(session, *, now):
        pass

    submit_kwargs: dict = {}

    async def _fake_submit(session, bot, *, opportunity, opportunity_summary, gateway, prompt_repository, source_url=None, has_multi_step_narrative=False, has_video_asset=False):
        submit_kwargs["has_multi_step_narrative"] = has_multi_step_narrative
        submit_kwargs["opportunity_id"] = opportunity.id
        return InstagramTriggerCandidateOutcome(
            event_id=opportunity.id, accepted=True, reason="submitted", gate_decision="ready_for_editor", delivery_sent=True,
        )

    monkeypatch.setattr(cc, "is_digest_due", _due)
    monkeypatch.setattr(cc, "select_digest_stories", _select)
    monkeypatch.setattr(cc, "mark_digest_run", _mark)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_opportunity", _fake_submit)

    report = await cc._run_instagram_news_digest_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert submit_kwargs["has_multi_step_narrative"] is True  # CAROUSEL, never SINGLE, for a digest
    assert report.stories_evaluated == 1  # ONE opportunity (the whole digest), never one per story
    assert report.packages_delivered == 1


@pytest.mark.asyncio
async def test_candidate_failure_is_isolated_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    stories = [_FakeCandidate(event_id=uuid4(), title=f"Story {i}") for i in range(5)]

    async def _due(session, *, now):
        return True

    async def _select(session, *, now):
        return stories

    async def _mark(session, *, now):
        pass

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated Telegram/DB failure")

    monkeypatch.setattr(cc, "is_digest_due", _due)
    monkeypatch.setattr(cc, "select_digest_stories", _select)
    monkeypatch.setattr(cc, "mark_digest_run", _mark)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_opportunity", _boom)

    report = await cc._run_instagram_news_digest_lane(
        _session_factory(), AsyncMock(), gate_gateway=object(), gate_prompt_repository=object(),
    )
    assert report.stories_evaluated == 0
