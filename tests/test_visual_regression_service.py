"""VISUAL-DESIGN-AUTONOMY-1, spec §75: regression validation - ACTIVE vs CANDIDATE comparison,
outcomes retained separately (never one aggregate score), a candidate fixing one case but
worsening the regression set overall is rejected, and unknown validation cost fails safe."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_regression import VisualRegressionCase, VisualRegressionOutcome
from services.visual_designer_brief_service import create_candidate_brief, create_initial_brief
from services.visual_regression_service import (
    active_cases,
    evaluate_promotion_policy,
    run_regression_validation,
)


async def _case(db_session: AsyncSession, *, scope: str, stress_condition: str, name: str) -> VisualRegressionCase:
    case = VisualRegressionCase(scope=scope, name=name, stress_condition=stress_condition, description=f"{stress_condition} stress test")
    db_session.add(case)
    await db_session.flush()
    return case


async def _candidate_and_baseline(db_session: AsyncSession, scope: str):
    baseline = await create_initial_brief(db_session, scope=scope, brief_text="baseline text")
    candidate = await create_candidate_brief(db_session, scope=scope, brief_text="candidate text", reason="test")
    return candidate.id, baseline.id


@pytest.mark.asyncio
async def test_active_cases_only_returns_active_ones(db_session: AsyncSession) -> None:
    await _case(db_session, scope="news", stress_condition="busy_photo", name="busy1")
    inactive = await _case(db_session, scope="news", stress_condition="dark_photo", name="dark1")
    inactive.active = False
    await db_session.flush()
    cases = await active_cases(db_session, "news")
    assert len(cases) == 1
    assert cases[0].stress_condition == "busy_photo"


@pytest.mark.asyncio
async def test_outcomes_retained_separately_never_one_score(db_session: AsyncSession) -> None:
    case_a = await _case(db_session, scope="data", stress_condition="number_heavy", name="a")
    case_b = await _case(db_session, scope="data", stress_condition="screenshot", name="b")
    candidate_id, _ = await _candidate_and_baseline(db_session, "data")

    async def art_fn(case, brief_version_id):
        if case.id == case_a.id:
            return VisualRegressionOutcome.PASS, [], 0.01
        return VisualRegressionOutcome.REWORK, ["visual_too_busy"], 0.01

    result = await run_regression_validation(
        db_session, candidate_brief_version_id=candidate_id, baseline_brief_version_id=None,
        cases=[case_a, case_b], art_director_fn=art_fn,
    )
    assert result.candidate_outcome_counts == {"pass": 1, "rework": 1}
    assert len(result.runs) == 2


@pytest.mark.asyncio
async def test_candidate_fixing_one_case_but_worsening_overall_is_rejected(db_session: AsyncSession) -> None:
    cases = [await _case(db_session, scope="news", stress_condition=f"case_{i}", name=f"c{i}") for i in range(5)]
    candidate_id, baseline_id = await _candidate_and_baseline(db_session, "news")

    async def art_fn(case, brief_version_id):
        index = cases.index(case)
        if brief_version_id == baseline_id:
            # baseline: only case 0 fails (the target failure REPEATED_PATTERN evidence pointed at)
            return (VisualRegressionOutcome.REWORK if index == 0 else VisualRegressionOutcome.PASS), (["visual_too_busy"] if index == 0 else []), 0.01
        # candidate: fixes case 0, but now regresses on cases 1-3
        if index == 0:
            return VisualRegressionOutcome.PASS, [], 0.01
        if index in (1, 2, 3):
            return VisualRegressionOutcome.REWORK, ["subject_crop_bad"], 0.01
        return VisualRegressionOutcome.PASS, [], 0.01

    result = await run_regression_validation(
        db_session, candidate_brief_version_id=candidate_id, baseline_brief_version_id=baseline_id,
        cases=cases, art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(result, target_issue_code="visual_too_busy")
    assert policy.may_promote is False
    assert any("REWORK rate worsened" in r for r in policy.reasons)


@pytest.mark.asyncio
async def test_candidate_that_genuinely_improves_may_promote(db_session: AsyncSession) -> None:
    cases = [await _case(db_session, scope="news", stress_condition=f"case_{i}", name=f"c{i}") for i in range(5)]
    candidate_id, baseline_id = await _candidate_and_baseline(db_session, "news")

    async def art_fn(case, brief_version_id):
        index = cases.index(case)
        if brief_version_id == baseline_id:
            return (VisualRegressionOutcome.REWORK if index == 0 else VisualRegressionOutcome.PASS), (["visual_too_busy"] if index == 0 else []), 0.01
        return VisualRegressionOutcome.PASS, [], 0.01  # candidate passes everything

    result = await run_regression_validation(
        db_session, candidate_brief_version_id=candidate_id, baseline_brief_version_id=baseline_id,
        cases=cases, art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(result, target_issue_code="visual_too_busy")
    assert policy.may_promote is True


@pytest.mark.asyncio
async def test_block_count_increase_blocks_promotion(db_session: AsyncSession) -> None:
    case = await _case(db_session, scope="news", stress_condition="factual", name="c0")
    candidate_id, baseline_id = await _candidate_and_baseline(db_session, "news")

    async def art_fn(_case, brief_version_id):
        if brief_version_id == baseline_id:
            return VisualRegressionOutcome.PASS, [], 0.01
        return VisualRegressionOutcome.BLOCK, ["number_mismatch"], 0.01

    result = await run_regression_validation(
        db_session, candidate_brief_version_id=candidate_id, baseline_brief_version_id=baseline_id,
        cases=[case], art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(result)
    assert policy.may_promote is False
    assert any("BLOCK count increased" in r for r in policy.reasons)


@pytest.mark.asyncio
async def test_unknown_validation_cost_fails_safe(db_session: AsyncSession) -> None:
    case = await _case(db_session, scope="news", stress_condition="busy_photo", name="c0")
    candidate_id, _ = await _candidate_and_baseline(db_session, "news")

    async def art_fn(_case, _brief_version_id):
        return VisualRegressionOutcome.PASS, [], None  # cost unknown

    result = await run_regression_validation(
        db_session, candidate_brief_version_id=candidate_id, baseline_brief_version_id=None,
        cases=[case], art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(result)
    assert policy.may_promote is False
    assert "unknown" in policy.reasons[0]


@pytest.mark.asyncio
async def test_validation_cost_over_limit_blocks_promotion(db_session: AsyncSession) -> None:
    case = await _case(db_session, scope="news", stress_condition="busy_photo", name="c0")
    candidate_id, _ = await _candidate_and_baseline(db_session, "news")

    async def art_fn(_case, _brief_version_id):
        return VisualRegressionOutcome.PASS, [], 5.0

    result = await run_regression_validation(
        db_session, candidate_brief_version_id=candidate_id, baseline_brief_version_id=None,
        cases=[case], art_director_fn=art_fn,
    )
    policy = evaluate_promotion_policy(result, max_validation_cost=1.0)
    assert policy.may_promote is False
    assert "exceeds limit" in policy.reasons[0]
