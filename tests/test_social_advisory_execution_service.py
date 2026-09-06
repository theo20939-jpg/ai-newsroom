"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §44: SocialAdvisoryExecutionService - bounded Gateway calls,
DirectorRun persisted with a real launch_context_fingerprint, staleness on launch-context change,
no publication authority anywhere in this module."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorType
from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchPlatform,
)
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.director_run_service import get_latest_run, is_run_context_stale
from services.social_advisory_budget_service import SocialAdvisoryBudgetDecision
from services.social_advisory_execution_service import run_prelaunch_advisory
from services.social_launch_context_service import compute_launch_context_fingerprint, create_next_version
from tests.fakes.fake_gateway import FakeLLMGateway

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_FOUNDER = 5507703201
_NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def _advisory_output(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "current_state": "NINJA VPN, transitioning", "target_state": "NINJA PULSE, launched",
        "launch_objectives": ["establish PULSE identity"], "transition_tasks": ["rename channel"],
        "content_pillars": ["AI news"], "initial_content_sequence": ["intro post"],
        "cadence_hypothesis": "daily", "format_hypotheses": ["short posts"], "visual_direction": "clean",
        "profile_setup": ["update bio"], "pinned_intro_content": ["welcome post"],
        "first_learning_questions": ["what topics resonate?"], "measurement_plan": ["track views"],
        "risks": ["audience confusion during rebrand"],
    }
    base.update(overrides)
    return base


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=100, output_tokens=200),
    ))


@pytest.mark.asyncio
async def test_run_persists_a_director_run_with_launch_context_fingerprint(db_session: AsyncSession) -> None:
    context = await create_next_version(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, target_identity="NINJA PULSE",
        current_identity="NINJA VPN", launch_state=LaunchState.TRANSITION, planned_launch_at=None,
        launch_date_status=LaunchDateStatus.TENTATIVE, baseline_policy=LearningBaselinePolicy.FROM_FIRST_POST_AFTER_LAUNCH,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="rebrand", confirmed_structure={}, created_by=_FOUNDER,
    )
    gateway = _gateway(_advisory_output())
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)

    result = await run_prelaunch_advisory(db_session, gateway, prompt_repository, platform=SocialLaunchPlatform.TELEGRAM, now=_NOW)

    assert result.budget_decision == SocialAdvisoryBudgetDecision.ALLOWED
    assert result.advisory is not None
    assert result.run is not None
    assert result.run.director_type == DirectorType.TELEGRAM_PRELAUNCH
    assert result.run.launch_context_fingerprint == compute_launch_context_fingerprint(context)
    # CapabilityCall.provider is a real-routing concept the FakeLLMGateway never populates;
    # model_name (from GenerateResponse.model_used) is the signal a real Gateway call actually
    # happened, unlike the deterministic directors which never set either field.
    assert result.run.model_name == "fake-model-v1"

    persisted = await get_latest_run(db_session, DirectorType.TELEGRAM_PRELAUNCH)
    assert persisted is not None
    assert persisted.id == result.run.id


@pytest.mark.asyncio
async def test_no_launch_context_still_produces_an_advisory_but_status_waiting_for_data(db_session: AsyncSession) -> None:
    """spec §10: COLD_START with genuinely no context configured is still a normal state to
    advise on - never a hard failure."""
    gateway = _gateway(_advisory_output(current_state="no context configured yet"))
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    result = await run_prelaunch_advisory(db_session, gateway, prompt_repository, platform=SocialLaunchPlatform.INSTAGRAM, now=_NOW)
    assert result.advisory is not None
    assert result.run is not None
    assert result.run.launch_context_fingerprint is None


@pytest.mark.asyncio
async def test_launch_context_change_makes_a_prior_run_stale(db_session: AsyncSession) -> None:
    """spec §16/§44: launch-context change makes old advisory stale."""
    v1 = await create_next_version(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, target_identity="NINJA PULSE", current_identity="NINJA VPN",
        launch_state=LaunchState.PRE_LAUNCH, planned_launch_at=None, launch_date_status=LaunchDateStatus.UNSCHEDULED,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_POST_AFTER_LAUNCH,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="initial", confirmed_structure={}, created_by=_FOUNDER,
    )
    gateway = _gateway(_advisory_output())
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    result = await run_prelaunch_advisory(db_session, gateway, prompt_repository, platform=SocialLaunchPlatform.TELEGRAM, now=_NOW)
    run = result.run
    assert run is not None

    # Founder changes the launch state - a real, later founder decision.
    v2 = await create_next_version(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, target_identity="NINJA PULSE", current_identity="NINJA VPN",
        launch_state=LaunchState.TRANSITION, planned_launch_at=None, launch_date_status=LaunchDateStatus.CONFIRMED,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_POST_AFTER_LAUNCH,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="date confirmed", confirmed_structure={}, created_by=_FOUNDER,
    )
    new_fingerprint = compute_launch_context_fingerprint(v2)
    assert new_fingerprint != compute_launch_context_fingerprint(v1)

    stale = await is_run_context_stale(
        db_session, run, now=_NOW, current_launch_context_fingerprint=new_fingerprint,
    )
    assert stale is True


@pytest.mark.asyncio
async def test_unchanged_launch_context_is_not_stale(db_session: AsyncSession) -> None:
    await create_next_version(
        db_session, platform=SocialLaunchPlatform.INSTAGRAM, target_identity="NINJA PULSE", current_identity=None,
        launch_state=LaunchState.PRE_LAUNCH, planned_launch_at=None, launch_date_status=LaunchDateStatus.UNSCHEDULED,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_PUBLICATION, historical_content_policy=HistoricalContentPolicy.IGNORE,
        raw_instruction="empty account", confirmed_structure={}, created_by=_FOUNDER,
    )
    gateway = _gateway(_advisory_output())
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    result = await run_prelaunch_advisory(db_session, gateway, prompt_repository, platform=SocialLaunchPlatform.INSTAGRAM, now=_NOW)
    run = result.run
    assert run is not None

    same_fingerprint = run.launch_context_fingerprint
    stale = await is_run_context_stale(db_session, run, now=_NOW, current_launch_context_fingerprint=same_fingerprint)
    assert stale is False


def test_execution_module_has_no_publication_or_platform_write_symbol() -> None:
    import inspect

    import services.social_advisory_execution_service as module

    source = inspect.getsource(module).lower()
    for forbidden in ("publish_", "send_message", "graph.facebook", "telegram_surface_registry", "rename_channel"):
        assert forbidden not in source, f"unexpected symbol in execution service: {forbidden!r}"
