"""VISUAL-DESIGN-AUTONOMY-1, spec §69/§72: the full design loop - PASS stops it, REWORK allows a
next attempt with real feedback fed back, BLOCK routes straight to HUMAN_REVIEW (never an automatic
retry), the attempt limit stops it, and a DirectorRun is only ever persisted when explicitly
enabled."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRun, DirectorType
from database.models.visual_design_attempt import VisualDesignAttempt, VisualDesignAttemptStatus, VisualFailureRootCause
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.telegram_art_director import ArtDirectorDecision, ArtDirectorIssueCode, ArtDirectorResult
from services.visual_design_director import PROMPT_NAME, StoryFactsInput
from services.visual_design_loop import RenderOutcome, run_visual_design_loop
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=PROMPT_NAME, version="1", system="you are the visual director", rules=["never draw the logo"],
        output_schema={"type": "object", "properties": {}, "required": []},
    ))
    return repository


def _direction_output(**overrides: object) -> dict:
    defaults: dict[str, object] = dict(
        creative_intent="a", visual_angle="a", composition="a", subject_priority="a", palette_direction="a",
        lighting_direction="a", background_direction="a", visual_density="a", negative_space_strategy="a",
        overlay_strategy="a", style_direction="a", media_strategy="generate_new",
        risks=[], reasoning=[], prompt_text="A calm editorial scene, cool tones.",
    )
    defaults.update(overrides)
    return defaults


def _gateway_response(output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=100, output_tokens=100),
    )


def _story() -> StoryFactsInput:
    return StoryFactsInput(story_id="11111111-1111-1111-1111-111111111111", title="Test story")


async def _render_fn(_direction) -> RenderOutcome:
    return RenderOutcome(rendered_bytes=b"fake-bytes", render_reference="ref-1", generation_model="fake-image-model", generation_cost=0.02)


def _art_director_fn_returning(decision: ArtDirectorDecision, *, issue_codes: list[ArtDirectorIssueCode] | None = None):
    async def _fn(_render_outcome) -> ArtDirectorResult:
        return ArtDirectorResult(decision=decision, severity="low" if issue_codes else "none", issue_codes=issue_codes or [], confidence=0.8)
    return _fn


@pytest.mark.asyncio
async def test_pass_stops_the_loop_after_one_attempt(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_director_fn_returning(ArtDirectorDecision.PASS),
    )
    assert result.final_status == VisualDesignAttemptStatus.PASSED
    assert len(result.attempts) == 1


@pytest.mark.asyncio
async def test_rework_allows_a_next_attempt_with_real_feedback(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_responses=[
        _gateway_response(_direction_output(composition="busy composition")),
        _gateway_response(_direction_output(composition="single clean subject")),
    ])
    decisions = iter([
        _art_director_fn_returning(ArtDirectorDecision.REWORK, issue_codes=[ArtDirectorIssueCode.VISUAL_TOO_BUSY]),
        _art_director_fn_returning(ArtDirectorDecision.PASS),
    ])

    async def _art_fn(render_outcome):
        return await next(decisions)(render_outcome)

    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_fn,
    )
    assert result.final_status == VisualDesignAttemptStatus.PASSED
    assert len(result.attempts) == 2
    assert result.attempts[0].status == VisualDesignAttemptStatus.REWORK
    assert result.attempts[0].root_cause == VisualFailureRootCause.DESIGN_DIRECTION
    # Real feedback actually reached the second Gateway call.
    second_request_text = str(gateway.received_requests[-1].messages[-1].content[0].text)
    assert "REWORK retry" in second_request_text
    assert "visual_too_busy" in second_request_text


@pytest.mark.asyncio
async def test_block_routes_straight_to_human_review_never_retries(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_director_fn_returning(ArtDirectorDecision.BLOCK, issue_codes=[ArtDirectorIssueCode.NUMBER_MISMATCH]),
    )
    assert result.final_status == VisualDesignAttemptStatus.HUMAN_REVIEW
    assert len(result.attempts) == 1  # never a second, wasted attempt after BLOCK


@pytest.mark.asyncio
async def test_attempt_limit_stops_the_loop_no_fourth_attempt_when_max_two(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_director_fn_returning(ArtDirectorDecision.REWORK, issue_codes=[ArtDirectorIssueCode.VISUAL_TOO_BUSY]),
    )
    # visual_max_attempts_default == 2 (core/config.py) - two REAL attempts are made (two actual
    # Gateway calls), and the budget gate stops the loop before ever calling the Gateway a third
    # time - the third persisted row is only the HUMAN_REVIEW bookkeeping marker, never a further
    # real generation attempt.
    assert len(gateway.received_requests) == 2
    assert len(result.attempts) == 3
    assert [a.status for a in result.attempts[:2]] == [VisualDesignAttemptStatus.REWORK, VisualDesignAttemptStatus.REWORK]
    assert result.attempts[-1].status == VisualDesignAttemptStatus.HUMAN_REVIEW
    assert result.final_status == VisualDesignAttemptStatus.HUMAN_REVIEW


@pytest.mark.asyncio
async def test_source_media_issue_classified_correctly(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn,
        art_director_fn=_art_director_fn_returning(ArtDirectorDecision.REWORK, issue_codes=[ArtDirectorIssueCode.MEDIA_LOW_QUALITY]),
    )
    assert result.attempts[0].root_cause == VisualFailureRootCause.SOURCE_MEDIA


@pytest.mark.asyncio
async def test_director_run_not_persisted_by_default(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_director_fn_returning(ArtDirectorDecision.PASS),
    )
    assert result.director_run_id is None
    count = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_director_run_persisted_when_enabled(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    result = await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_director_fn_returning(ArtDirectorDecision.PASS),
    )
    assert result.director_run_id is not None
    run = await db_session.get(DirectorRun, result.director_run_id)
    assert run is not None
    assert run.director_type == DirectorType.TELEGRAM_VISUAL_DESIGN
    assert run.status.value == "ok"


@pytest.mark.asyncio
async def test_attempts_are_persisted_with_real_cost(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway(generate_response=_gateway_response(_direction_output()))
    await run_visual_design_loop(
        db_session, gateway, _prompt_repository(), story=_story(), platform="telegram", presentation_type="NEWS",
        render_fn=_render_fn, art_director_fn=_art_director_fn_returning(ArtDirectorDecision.PASS),
    )
    stmt = select(VisualDesignAttempt).where(VisualDesignAttempt.platform == "telegram")
    rows = list((await db_session.execute(stmt)).scalars().all())
    assert len(rows) == 1
    assert rows[0].generation_cost == 0.02
    assert rows[0].total_cost == 0.02
    assert rows[0].generation_model == "fake-image-model"
