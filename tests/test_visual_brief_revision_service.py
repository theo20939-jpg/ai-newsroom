"""VISUAL-DESIGN-AUTONOMY-1A, spec §23: brief revision service tests - the evidence gate blocks
the Gateway entirely for ANOMALY/POSSIBLE_SIGNAL/FROZEN/cooldown, a Gateway failure or malformed
output leaves ACTIVE unchanged, a Brand Core violation is rejected before persistence, a valid
candidate is persisted as CANDIDATE (never ACTIVE), and the existing regression/promotion pipeline
can consume the generated candidate unmodified."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_design_attempt import VisualDesignAttempt, VisualDesignAttemptStatus
from database.models.visual_designer_brief import VisualDesignerBriefStatus
from database.models.visual_regression import VisualRegressionOutcome
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.visual_brief_revision_generator import PROMPT_NAME
from services.visual_brief_revision_service import BriefRevisionStatus, request_brief_revision
from services.visual_designer_brief_service import create_initial_brief, freeze_brief, list_history
from services.visual_regression_service import evaluate_promotion_policy, run_regression_validation
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def test_real_prompt_yaml_loads_and_resolves() -> None:
    from integrations.prompts.file_repository import FilePromptRepository

    repository = FilePromptRepository(_PROMPTS_ROOT)
    prompt = repository.resolve(PROMPT_NAME, "1")
    assert prompt.name == PROMPT_NAME
    assert "candidate_brief_text" in prompt.output_schema["properties"]


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=PROMPT_NAME, version="1", system="you are revising the brief", rules=["never violate brand core"],
        output_schema={"type": "object", "properties": {}, "required": []},
    ))
    return repository


def _proposal_output(**overrides: object) -> dict:
    defaults: dict[str, object] = dict(
        candidate_brief_text="Favor calm, minimal compositions with a single clear focal subject for DATA posts.",
        change_summary="Reduce visual density on DATA posts to address repeated VISUAL_TOO_BUSY.",
        reasoning=["DATA posts have repeatedly triggered VISUAL_TOO_BUSY across many attempts"],
        target_failure_patterns=["visual_too_busy"], expected_effects=["fewer REWORK verdicts on DATA"],
        known_risks=["may read as too plain for high-stakes launches"], confidence=0.6,
    )
    defaults.update(overrides)
    return defaults


def _response(output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=300, output_tokens=200),
    )


async def _attempt_with_issue(db_session: AsyncSession, brief, issue_code: str, *, status: VisualDesignAttemptStatus = VisualDesignAttemptStatus.REWORK) -> None:
    db_session.add(VisualDesignAttempt(
        platform="telegram", presentation_type="DATA", brief_version_id=brief.id, attempt_number=1,
        issue_codes=[issue_code] if issue_code else None, status=status,
        art_decision=("rework" if status == VisualDesignAttemptStatus.REWORK else "pass"),
        total_cost=0.02,  # a real, known per-attempt cost - keeps the daily budget gate ALLOWED
    ))
    await db_session.flush()


async def _enable_adaptation(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "visual_brief_auto_adaptation_enabled", True)


@pytest.mark.asyncio
async def test_single_failure_never_calls_gateway(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.NOT_ELIGIBLE
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_possible_signal_never_calls_gateway(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(2):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.NOT_ELIGIBLE
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_frozen_scope_never_calls_gateway(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    await freeze_brief(db_session, "data", reason="founder request")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.BRIEF_FROZEN
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_cooldown_prevents_repeated_call(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    first = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert first.status == BriefRevisionStatus.CANDIDATE_CREATED
    assert len(gateway.received_requests) == 1

    second = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert second.status == BriefRevisionStatus.NOT_ELIGIBLE
    assert len(gateway.received_requests) == 1  # no second call


@pytest.mark.asyncio
async def test_repeated_pattern_triggers_eligibility_and_creates_candidate(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="Use bold busy compositions.")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.CANDIDATE_CREATED
    assert result.candidate is not None
    assert result.candidate.status == VisualDesignerBriefStatus.CANDIDATE  # never immediately ACTIVE


@pytest.mark.asyncio
async def test_candidate_substantially_rewrites_brief(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="Use maximal, dense, busy compositions with many elements.")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output(
        candidate_brief_text="Favor sparse, minimal, single-subject compositions with generous negative space.",
    )))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.CANDIDATE_CREATED
    assert result.candidate is not None
    assert result.candidate.brief_text != brief.brief_text
    assert "minimal" in result.candidate.brief_text


@pytest.mark.asyncio
async def test_gateway_failure_leaves_active_unchanged(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_error=RuntimeError("provider unavailable"))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.BRIEF_REVISION_UNAVAILABLE

    history = await list_history(db_session, "data")
    assert len(history) == 1  # no candidate row created
    assert history[0].status == VisualDesignerBriefStatus.ACTIVE


@pytest.mark.asyncio
async def test_malformed_output_leaves_active_unchanged(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output(candidate_brief_text="")))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.BRIEF_REVISION_UNAVAILABLE

    history = await list_history(db_session, "data")
    assert len(history) == 1
    assert history[0].status == VisualDesignerBriefStatus.ACTIVE


@pytest.mark.asyncio
async def test_candidate_asking_to_draw_logo_is_rejected(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output(
        candidate_brief_text="Always draw the NNJ logo prominently as part of the generated scene.",
    )))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.REJECTED_BY_BRAND_CORE

    history = await list_history(db_session, "data")
    assert len(history) == 1  # never persisted


@pytest.mark.asyncio
async def test_candidate_weakening_fact_rules_is_rejected(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output(
        candidate_brief_text="Numbers may now be approximated for dramatic effect when exact figures are unavailable.",
    )))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.REJECTED_BY_BRAND_CORE

    history = await list_history(db_session, "data")
    assert len(history) == 1


@pytest.mark.asyncio
async def test_daily_budget_unknown_fails_safe_no_gateway_call(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    # An attempt with an unknown total_cost anywhere today makes the daily sum unknown.
    db_session.add(VisualDesignAttempt(platform="telegram", presentation_type="DATA", attempt_number=1, total_cost=None))
    await db_session.flush()

    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.BUDGET_UNKNOWN
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_daily_budget_exhausted_no_gateway_call(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    db_session.add(VisualDesignAttempt(platform="telegram", presentation_type="DATA", attempt_number=1, total_cost=999.0))
    await db_session.flush()

    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.BUDGET_EXHAUSTED
    assert len(gateway.received_requests) == 0


@pytest.mark.asyncio
async def test_cost_recorded_when_known_and_unknown_otherwise(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.status == BriefRevisionStatus.CANDIDATE_CREATED
    assert result.candidate is not None
    evidence = result.candidate.evidence
    assert evidence is not None
    # No PricingCatalog integration in this phase - cost_usd stays explicitly None (unknown),
    # never a fabricated 0.0, but the field is present and real when a caller does know it.
    assert evidence["cost_usd"] is None
    assert "model_provider" in evidence


@pytest.mark.asyncio
async def test_existing_regression_validator_consumes_generated_candidate(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from services.visual_regression_service import active_cases

    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.candidate is not None

    from database.models.visual_regression import VisualRegressionCase

    case = VisualRegressionCase(scope="data", name="busy1", stress_condition="busy_photo", description="busy stress test")
    db_session.add(case)
    await db_session.flush()
    cases = await active_cases(db_session, "data")
    assert len(cases) == 1

    async def art_fn(_case, brief_version_id):
        if brief_version_id == brief.id:
            return VisualRegressionOutcome.REWORK, ["visual_too_busy"], 0.01
        return VisualRegressionOutcome.PASS, [], 0.01  # the newly generated candidate passes

    regression_result = await run_regression_validation(
        db_session, candidate_brief_version_id=result.candidate.id, baseline_brief_version_id=brief.id,
        cases=cases, art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(regression_result, target_issue_code="visual_too_busy")
    assert policy.may_promote is True


@pytest.mark.asyncio
async def test_failed_regression_rejects_candidate_promotion(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from database.models.visual_regression import VisualRegressionCase

    await _enable_adaptation(monkeypatch)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.candidate is not None

    case = VisualRegressionCase(scope="data", name="c0", stress_condition="factual", description="factual stress test")
    db_session.add(case)
    await db_session.flush()

    async def art_fn(_case, brief_version_id):
        if brief_version_id == brief.id:
            return VisualRegressionOutcome.PASS, [], 0.01
        return VisualRegressionOutcome.BLOCK, ["number_mismatch"], 0.01  # candidate regresses badly

    regression_result = await run_regression_validation(
        db_session, candidate_brief_version_id=result.candidate.id, baseline_brief_version_id=brief.id,
        cases=[case], art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(regression_result)
    assert policy.may_promote is False


@pytest.mark.asyncio
async def test_auto_promotion_flag_false_prevents_activation(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    await _enable_adaptation(monkeypatch)
    monkeypatch.setattr(settings, "visual_brief_auto_promotion_enabled", False)
    brief = await create_initial_brief(db_session, scope="data", brief_text="v1")
    for _ in range(5):
        await _attempt_with_issue(db_session, brief, "visual_too_busy")
    gateway = FakeLLMGateway(generate_response=_response(_proposal_output()))
    result = await request_brief_revision(db_session, gateway, _prompt_repository(), scope="data")
    assert result.candidate is not None
    # Even though nothing here evaluates a promotion, the produced row must never itself be ACTIVE.
    assert result.candidate.status == VisualDesignerBriefStatus.CANDIDATE
    assert not settings.visual_brief_auto_promotion_enabled
