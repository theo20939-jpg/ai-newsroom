"""Phase 17 M6.1 - cutover readiness tests (docs/
phase17_m6_1_production_cutover_readiness_report.md).

Pure unit tests (rollout policy schema) plus a real, read-only invocation of the preflight script
against the actual current repository state (no LLM, no Telegram send, no mutation).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.phase17_rollout_policy import (
    ROLLOUT_POLICY_SCHEMA_VERSION,
    FallbackBehavior,
    RolloutPolicy,
    RolloutStage,
)


def _policy(**overrides) -> RolloutPolicy:
    defaults = dict(
        rollout_version="2026.08",
        stage=RolloutStage.STAGE_0_ALL_OFF,
        enabled_components=[],
        candidate_percentage=0,
        allowed_scope_description="none",
        fallback=FallbackBehavior(fail_open=True, fallback_prompt_version="3", max_consecutive_fallbacks_before_pause=5),
        minimum_confidence="high",
    )
    defaults.update(overrides)
    return RolloutPolicy(**defaults)  # type: ignore[arg-type]


def test_rollout_policy_schema_version() -> None:
    policy = _policy()
    assert policy.schema_version == ROLLOUT_POLICY_SCHEMA_VERSION


def test_stage_0_is_all_off_by_default() -> None:
    policy = _policy()
    assert policy.stage == RolloutStage.STAGE_0_ALL_OFF
    assert policy.enabled_components == []
    assert policy.candidate_percentage == 0


def test_stage_transitions_are_ordered() -> None:
    stages = list(RolloutStage)
    assert stages == sorted(stages)
    assert RolloutStage.STAGE_5_RELEVANCE_ENFORCEMENT > RolloutStage.STAGE_0_ALL_OFF


def test_candidate_percentage_bounds() -> None:
    with pytest.raises(ValidationError):
        _policy(candidate_percentage=101)
    with pytest.raises(ValidationError):
        _policy(candidate_percentage=-1)


def test_fallback_requires_positive_pause_threshold() -> None:
    with pytest.raises(ValidationError):
        FallbackBehavior(fail_open=True, fallback_prompt_version="3", max_consecutive_fallbacks_before_pause=0)


def test_fallback_fail_open_configurable() -> None:
    policy = _policy(fallback=FallbackBehavior(fail_open=False, fallback_prompt_version="3", max_consecutive_fallbacks_before_pause=1))
    assert policy.fallback.fail_open is False


def test_no_mutable_default_sharing() -> None:
    a = _policy()
    b = _policy()
    assert a.enabled_components is not b.enabled_components
    assert a.rollback_trigger_thresholds is not b.rollback_trigger_thresholds


@pytest.mark.asyncio
async def test_preflight_checks_pass_on_real_repository_state() -> None:
    """Runs the real preflight check functions (no subprocess) against this actual repo/DB -
    read-only, no LLM, no Telegram send. Skipped gracefully if the DB is unreachable in this
    test environment (a real DB connectivity failure is not what this test targets)."""
    from scripts.phase17_cutover_preflight import run

    checks = await run()
    names = {c.name for c in checks}
    assert "feature_modes_safe_default" in names
    assert "prompt_files_present" in names
    assert "fallback_copywriting_prompt_exists" in names
    non_db_checks = [c for c in checks if c.name != "db_connectivity"]
    assert all(c.passed for c in non_db_checks), [
        (c.name, c.detail) for c in non_db_checks if not c.passed
    ]


def test_preflight_never_imports_llm_gateway_or_telegram_send() -> None:
    import scripts.phase17_cutover_preflight as module

    source_names = {getattr(obj, "__module__", "") for obj in vars(module).values()}
    forbidden = ("llm_gateway", "bot.handlers", "bot.main", "aiogram")
    for name in source_names:
        for f in forbidden:
            assert f not in name.lower(), f"unexpected import touching {f!r}: {name}"
