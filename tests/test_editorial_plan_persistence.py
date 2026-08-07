"""Phase 19 M3: proves persist_shadow_plan() actually runs the plan through
services.editorial_planning_safety.evaluate_plan_safety() rather than hardcoding
safety_passed=True - a real gap found during Phase 19 M3 validation (the deterministic
scaffold never fabricates by construction, but a future real, LLM-backed plan reusing this
same persistence path must not silently inherit an always-True safety_passed value).

Uses a minimal fake session (captures the one row passed to .add(), never touches a real
database) rather than the full db_session fixture, since persist_shadow_plan() never commits/
flushes - it only calls session.add().
"""
from __future__ import annotations

import uuid

import pytest

from services.editorial_plan_persistence import persist_shadow_plan


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


def _base_plan() -> dict:
    return {
        "central_fact": "Example Co launched a new product today.",
        "what_is_new": "A new product.",
        "why_it_matters": "It expands the market.",
        "headline_emphasis": None,
        "opening_emphasis": None,
        "verified_quote_text": None,
        "what_remains_unknown": None,
    }


@pytest.mark.asyncio
async def test_safe_plan_persists_safety_passed_true() -> None:
    session = _FakeSession()
    evidence_text = "Example Co launched a new product today, expanding the market."

    await persist_shadow_plan(
        session, event_id=uuid.uuid4(), plan=_base_plan(), evidence_text=evidence_text,
    )

    row = session.added[0]
    assert row.safety_passed is True
    assert row.safety_failed_checks is None


@pytest.mark.asyncio
async def test_unsafe_plan_persists_safety_passed_false_with_failed_checks() -> None:
    session = _FakeSession()
    plan = _base_plan()
    plan["what_is_new"] = "Our product outperforms the competition."

    await persist_shadow_plan(
        session, event_id=uuid.uuid4(), plan=plan, evidence_text="Unrelated evidence text.",
    )

    row = session.added[0]
    assert row.safety_passed is False
    assert "no_competitive_claims" in row.safety_failed_checks


@pytest.mark.asyncio
async def test_selected_editorial_text_hash_is_persisted_when_provided() -> None:
    session = _FakeSession()

    await persist_shadow_plan(
        session, event_id=uuid.uuid4(), plan=_base_plan(), evidence_text="Evidence.",
        selected_editorial_text_hash="abc123",
    )

    row = session.added[0]
    assert row.selected_editorial_text_hash == "abc123"
