"""DIRECTOR-CONTROL-PLANE-1 §49: required editorial gate tests."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_editorial_decision import EditorialGateDecision, EditorialGateReasonCode
from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from services.director_editorial_gate import (
    GATE_FALLBACK_MODE_DETERMINISTIC_BASELINE,
    EditorialGateInput,
    context_fingerprint,
    evaluate_editorial_gate,
    run_editorial_gate_fail_soft,
)
from services.director_editorial_gate_persistence import (
    apply_founder_override,
    list_hold_queue,
    persist_gate_decision,
)


def _base_input(**overrides: object) -> EditorialGateInput:
    defaults: dict[str, object] = dict(
        story_id=str(uuid4()), event_id=str(uuid4()), platform="telegram", category="ai",
        topic_keywords=["ai", "model"], story_facts_summary="A new AI model was released with real benchmarks.",
        has_sufficient_facts=True, source_confidence=0.85, novelty_score=0.8, is_duplicate_of_recent=False,
        recency_hours=1.0, active_directives=[], active_campaign_relevant=False, launch_state="pre_launch",
        feed_topic_distribution={}, recent_posting_cadence_per_hour=1.0, is_potential_breaking=False,
        factual_risk_flagged=False,
    )
    defaults.update(overrides)
    return EditorialGateInput(**defaults)  # type: ignore[arg-type]


def test_high_fit_ai_story_sends_to_editor_or_priority() -> None:
    outcome = evaluate_editorial_gate(_base_input())
    assert outcome.decision in (EditorialGateDecision.SEND_TO_EDITOR, EditorialGateDecision.PRIORITY)
    assert EditorialGateReasonCode.HIGH_STRATEGIC_FIT in outcome.reason_codes


def test_recent_duplicate_drops_or_holds() -> None:
    outcome = evaluate_editorial_gate(_base_input(is_duplicate_of_recent=True))
    assert outcome.decision in (EditorialGateDecision.DROP, EditorialGateDecision.HOLD)
    assert EditorialGateReasonCode.DUPLICATE_TOPIC in outcome.reason_codes


def test_weak_source_sensational_claim_holds_or_drops() -> None:
    outcome = evaluate_editorial_gate(_base_input(source_confidence=0.1, novelty_score=0.9))
    assert outcome.decision in (EditorialGateDecision.HOLD, EditorialGateDecision.DROP)
    assert EditorialGateReasonCode.SOURCE_WEAK in outcome.reason_codes


def test_finance_story_without_strategic_importance_is_deprioritized() -> None:
    outcome = evaluate_editorial_gate(_base_input(category="finance", novelty_score=0.3, topic_keywords=["stocks"]))
    assert outcome.decision == EditorialGateDecision.HOLD
    assert EditorialGateReasonCode.TOO_FINANCE_HEAVY in outcome.reason_codes


def test_major_tech_industry_finance_event_still_eligible() -> None:
    """A genuinely major event (high novelty) in a rare-tier category must still reach the editor,
    never be dropped outright - spec §49's own explicit carve-out."""
    outcome = evaluate_editorial_gate(_base_input(category="finance", novelty_score=0.9))
    assert outcome.decision in (EditorialGateDecision.SEND_TO_EDITOR, EditorialGateDecision.PRIORITY)
    assert EditorialGateReasonCode.MAJOR_INDUSTRY_EVENT in outcome.reason_codes


def test_campaign_relevant_story_gets_priority_uplift() -> None:
    baseline = evaluate_editorial_gate(_base_input(active_campaign_relevant=False))
    uplifted = evaluate_editorial_gate(_base_input(active_campaign_relevant=True))
    assert uplifted.priority > baseline.priority
    assert EditorialGateReasonCode.CAMPAIGN_RELEVANT in uplifted.reason_codes


def test_founder_directive_overrides_default_topic_tier() -> None:
    directive = StrategicDirective(
        id=uuid4(), priority=100, valid_from=datetime.now(timezone.utc),
        instruction="Gaming news is now a PRIMARY focus category for the channel.", status=DirectiveStatus.ACTIVE,
    )
    outcome = evaluate_editorial_gate(_base_input(category="gaming", active_directives=[directive]))
    assert EditorialGateReasonCode.FOUNDER_DIRECTIVE_MATCH in outcome.reason_codes
    assert EditorialGateReasonCode.HIGH_STRATEGIC_FIT in outcome.reason_codes


def test_insufficient_facts_holds_never_drops_silently() -> None:
    outcome = evaluate_editorial_gate(_base_input(has_sufficient_facts=False))
    assert outcome.decision == EditorialGateDecision.HOLD
    assert EditorialGateReasonCode.INSUFFICIENT_FACTS in outcome.reason_codes


def test_breaking_signal_produces_breaking_decision() -> None:
    outcome = evaluate_editorial_gate(_base_input(is_potential_breaking=True))
    assert outcome.decision == EditorialGateDecision.BREAKING


def test_context_fingerprint_is_deterministic() -> None:
    gate_input = _base_input()
    assert context_fingerprint(gate_input) == context_fingerprint(gate_input)
    assert context_fingerprint(gate_input) != context_fingerprint(_base_input(category="finance"))


@pytest.mark.asyncio
async def test_llm_unavailable_falls_back_to_deterministic_baseline_never_empties_queue() -> None:
    async def _broken_escalate(_gate_input: EditorialGateInput):
        raise RuntimeError("gateway down")

    outcome = await run_editorial_gate_fail_soft(_base_input(), llm_escalate=_broken_escalate, is_ambiguous=True)
    assert outcome.decision in (EditorialGateDecision.SEND_TO_EDITOR, EditorialGateDecision.PRIORITY)
    assert outcome.fallback_mode == GATE_FALLBACK_MODE_DETERMINISTIC_BASELINE


@pytest.mark.asyncio
async def test_non_ambiguous_never_calls_llm_escalate() -> None:
    calls = []

    async def _escalate(gate_input: EditorialGateInput):
        calls.append(1)
        raise AssertionError("should never be called")

    await run_editorial_gate_fail_soft(_base_input(), llm_escalate=_escalate, is_ambiguous=False)
    assert calls == []


@pytest.mark.asyncio
async def test_founder_override_persisted_and_respected(db_session: AsyncSession) -> None:
    gate_input = _base_input(is_duplicate_of_recent=True)
    outcome = evaluate_editorial_gate(gate_input)
    assert outcome.decision == EditorialGateDecision.DROP

    row = await persist_gate_decision(db_session, gate_input=gate_input, outcome=outcome)
    await db_session.flush()

    overridden = await apply_founder_override(
        db_session, row.id, new_decision=EditorialGateDecision.SEND_TO_EDITOR, overridden_by=12345,
    )
    assert overridden is not None
    assert overridden.founder_overridden is True
    assert overridden.founder_override_decision == EditorialGateDecision.SEND_TO_EDITOR
    assert overridden.decision == EditorialGateDecision.DROP  # original decision never mutated


@pytest.mark.asyncio
async def test_director_cannot_silently_supersede_a_founder_override(db_session: AsyncSession) -> None:
    gate_input = _base_input(is_duplicate_of_recent=True)
    outcome = evaluate_editorial_gate(gate_input)
    row = await persist_gate_decision(db_session, gate_input=gate_input, outcome=outcome)
    await db_session.flush()

    first = await apply_founder_override(db_session, row.id, new_decision=EditorialGateDecision.SEND_TO_EDITOR, overridden_by=1)
    second = await apply_founder_override(db_session, row.id, new_decision=EditorialGateDecision.DROP, overridden_by=2)
    assert first is not None and second is not None
    assert second.founder_override_decision == EditorialGateDecision.SEND_TO_EDITOR  # unchanged by the second call
    assert second.founder_override_by == 1


@pytest.mark.asyncio
async def test_hold_queue_lists_only_live_holds(db_session: AsyncSession) -> None:
    gate_input = _base_input(has_sufficient_facts=False)
    outcome = evaluate_editorial_gate(gate_input)
    assert outcome.decision == EditorialGateDecision.HOLD
    row = await persist_gate_decision(db_session, gate_input=gate_input, outcome=outcome)
    await db_session.flush()

    hold_queue = await list_hold_queue(db_session)
    assert any(r.id == row.id for r in hold_queue)


def test_editorial_gate_flag_defaults_false() -> None:
    assert settings.telegram_editorial_gate_enabled is False
