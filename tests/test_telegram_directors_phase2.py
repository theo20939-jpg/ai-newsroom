"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §27: required test coverage
for real passive performance collection, real Channel Director shadow wiring, real Art Director
vision inspection, and the Growth/Strategy/Platform Director real advisory logic."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.telegram_channel_memory import StoryRole, TelegramChannelMemory
from database.models.telegram_experiment import ExperimentStatus
from database.models.telegram_post_performance import SnapshotWindow, TelegramPostPerformanceSnapshot
from database.models.telegram_visual_failure import ArtDirectorDecisionEnum, TelegramVisualFailure
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.telegram_art_director import (
    ArtDirectorDecision,
    ArtDirectorIssueCode,
    ArtDirectorResult,
    PixelInputContract,
)
from services.telegram_art_director_vision import VISION_PROMPT_NAME, VISION_PROMPT_VERSION, evaluate_art_direction_vision
from services.telegram_channel_director_shadow import run_channel_director_shadow
from services.telegram_experiment_service import create_experiment, record_experiment_result
from services.telegram_feed_state import compute_feed_state
from services.telegram_growth_director import derive_growth_director_advisory
from services.telegram_own_channel import is_own_channel, owned_chat_id
from services.telegram_performance_memory import (
    TELEGRAM_PLATFORM_CAPABILITIES,
    CapabilityStatus,
    EvidenceStage,
    PerformancePattern,
)
from services.telegram_performance_normalization import (
    forward_rate_per_hour,
    reaction_per_view_ratio,
    same_window_snapshots,
    views_velocity_per_hour,
)
from services.telegram_strategy_director import derive_strategy_advisory, describe_platform_capability
from services.telegram_visual_failure_persistence import persist_visual_failure_shadow
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository


# --- §3/§4: own-channel capability classification + non-confusion ----------------------------

def test_own_channel_capabilities_use_the_five_value_scale_not_fabricated() -> None:
    assert TELEGRAM_PLATFORM_CAPABILITIES["views"].status == CapabilityStatus.AVAILABLE_WITH_EXISTING_MTPROTO
    assert TELEGRAM_PLATFORM_CAPABILITIES["reactions"].status == CapabilityStatus.AVAILABLE_WITH_EXISTING_MTPROTO
    assert TELEGRAM_PLATFORM_CAPABILITIES["subscriber_count"].status == CapabilityStatus.AVAILABLE
    assert TELEGRAM_PLATFORM_CAPABILITIES["publication_timestamp"].status == CapabilityStatus.AVAILABLE
    assert TELEGRAM_PLATFORM_CAPABILITIES["link_clicks"].status == CapabilityStatus.UNAVAILABLE
    for capability in TELEGRAM_PLATFORM_CAPABILITIES.values():
        assert capability.evidence


def test_own_channel_identity_never_confused_with_a_source_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -1001111)
    monkeypatch.setattr(settings, "telegram_owned_channel_id", None)
    assert owned_chat_id() == -1001111
    assert is_own_channel(-1001111) is True
    assert is_own_channel(-1009999) is False  # an externally-monitored source channel's chat_id


def test_platform_capability_report_exposes_limitations_requirements_confidence() -> None:
    report = describe_platform_capability("views")
    assert report is not None
    assert report.requirements
    assert 0.0 <= report.confidence <= 1.0
    assert report.evidence


# --- §5/§6: performance snapshot persistence, "unavailable != zero" ---------------------------

@pytest.mark.asyncio
async def test_performance_snapshot_persists_with_nulls_not_guessed_zeros(db_session: AsyncSession) -> None:
    snapshot = TelegramPostPerformanceSnapshot(
        id=uuid4(), channel_memory_id=None, telegram_message_id=555,
        window=SnapshotWindow.H1, captured_at=datetime.now(timezone.utc), age_seconds=3600,
        views=100, forwards=None, reactions_total=None, comments_total=None,
        subscriber_count=None, subscriber_delta=None,
        capability_version="test-v1", collector="test",
    )
    db_session.add(snapshot)
    await db_session.flush()

    row = (await db_session.execute(
        select(TelegramPostPerformanceSnapshot).where(TelegramPostPerformanceSnapshot.id == snapshot.id)
    )).scalar_one()
    assert row.views == 100
    assert row.forwards is None  # never a guessed 0
    assert row.reactions_total is None


# --- §8: time-window normalization -------------------------------------------------------------

def test_time_normalized_rates_never_compare_a_24h_post_to_a_15m_post_as_equal() -> None:
    fresh = TelegramPostPerformanceSnapshot(
        id=uuid4(), telegram_message_id=1, window=SnapshotWindow.M5,
        captured_at=datetime.now(timezone.utc), age_seconds=300, views=300, forwards=3,
        reactions_total=None, comments_total=None, capability_version="v", collector="c",
    )
    old = TelegramPostPerformanceSnapshot(
        id=uuid4(), telegram_message_id=1, window=SnapshotWindow.H24,
        captured_at=datetime.now(timezone.utc), age_seconds=86400, views=300, forwards=3,
        reactions_total=None, comments_total=None, capability_version="v", collector="c",
    )
    # Same raw view count, wildly different velocity once time-normalized.
    assert views_velocity_per_hour(fresh) == pytest.approx(3600.0)
    assert views_velocity_per_hour(old) == pytest.approx(12.5)
    assert views_velocity_per_hour(fresh) != views_velocity_per_hour(old)
    assert forward_rate_per_hour(fresh) is not None

    no_views = TelegramPostPerformanceSnapshot(
        id=uuid4(), telegram_message_id=1, window=SnapshotWindow.H1,
        captured_at=datetime.now(timezone.utc), age_seconds=3600, views=None, forwards=None,
        reactions_total=5, comments_total=None, capability_version="v", collector="c",
    )
    assert views_velocity_per_hour(no_views) is None  # missing metric, never a fabricated 0.0
    assert reaction_per_view_ratio(no_views) is None  # views missing - ratio undefined, not 0.0

    assert same_window_snapshots([fresh, old], window="5m") == [fresh]


# --- §12: FeedState extended dimensions ---------------------------------------------------------

async def _post(db_session: AsyncSession, *, published_at, **kwargs) -> TelegramChannelMemory:
    row = TelegramChannelMemory(published_at=published_at, **kwargs)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_feed_state_extended_dimensions(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await _post(
        db_session, published_at=now - timedelta(minutes=10), campaign_id=uuid4(),
        content_objective="commercial", story_role=StoryRole.UPDATE, visual_family="fam_a",
    )
    await _post(
        db_session, published_at=now - timedelta(minutes=20), campaign_id=None,
        content_objective="news", story_role=StoryRole.RECAP, visual_family="fam_a",
    )
    await _post(
        db_session, published_at=now - timedelta(minutes=30), campaign_id=None,
        content_objective="news", story_role=StoryRole.FIRST, visual_family="fam_b",
    )

    feed_state = await compute_feed_state(db_session, now=now)
    assert feed_state.campaign_content_share == pytest.approx(1 / 3)
    assert feed_state.commercial_content_share == pytest.approx(1 / 3)
    assert feed_state.recent_update_recap_density == pytest.approx(2 / 3)
    assert feed_state.story_role_mix.get("update") == 1
    assert feed_state.story_role_mix.get("recap") == 1
    assert feed_state.visual_family_streak == 2  # two most-recent posts both "fam_a"


# --- §9-11: Channel Director real shadow wiring, no runtime side effect ------------------------

@pytest.mark.asyncio
async def test_channel_director_shadow_noop_when_flag_disabled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegram_channel_director_shadow_enabled", False)
    result = await run_channel_director_shadow(db_session, news_importance=0.9, now=datetime.now(timezone.utc))
    assert result is None


@pytest.mark.asyncio
async def test_channel_director_shadow_real_input_contract_and_no_side_effect(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §9-11: assembles FeedState/EditorialNeed/BusinessContextSnapshot for real, returns a
    ChannelDirectorResult, and touches the database in a read-only way - no row is added/modified
    by the shadow call itself."""
    monkeypatch.setattr(settings, "telegram_channel_director_shadow_enabled", True)
    pending_before = len(db_session.new) + len(db_session.dirty) + len(db_session.deleted)

    result = await run_channel_director_shadow(db_session, news_importance=0.85, now=datetime.now(timezone.utc))

    assert result is not None
    assert result.organic_relevance == pytest.approx(0.85)
    assert result.business_campaign_relevance == 0.0  # no active campaigns in this bare test DB
    pending_after = len(db_session.new) + len(db_session.dirty) + len(db_session.deleted)
    assert pending_after == pending_before  # no runtime side effect - nothing written


# --- §13-18: Art Director real vision inspection ------------------------------------------------

_FAKE_BYTES = b"fake-final-rendered-png-bytes"

_VISION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string"},
        "severity": {"type": "string"},
        "issues": {"type": "array"},
        "overall_confidence": {"type": "number"},
    },
    "required": ["decision", "severity", "issues", "overall_confidence"],
}


def _vision_prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=VISION_PROMPT_NAME, version=VISION_PROMPT_VERSION,
            system="You are a fake Art Director for tests.", rules=["Use only provided codes."],
            output_schema=_VISION_OUTPUT_SCHEMA,
        )
    )
    return repository


def _pixel_input(**overrides: object) -> PixelInputContract:
    defaults: dict[str, object] = dict(
        rendered_bytes=_FAKE_BYTES, caption="Breaking: test story", presentation_type="NEWS",
        renderer_version="v1",
    )
    defaults.update(overrides)
    return PixelInputContract(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_art_director_vision_receives_the_real_decoded_image_bytes() -> None:
    """Spec §13/§14: the vision call must carry the ACTUAL rendered bytes, not a placeholder."""
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={"decision": "pass", "severity": "none", "issues": [], "overall_confidence": 0.8},
        finish_reason="stop", model_used="fake-vision-v1", usage=CapabilityUsage(input_tokens=50, output_tokens=20),
    ))

    await evaluate_art_direction_vision(gateway, _vision_prompt_repository(), pixel_input=_pixel_input())

    request = gateway.received_requests[0]
    assert "image" in request.modalities
    user_message = next(m for m in request.messages if m.role == "user")
    artifact_parts = [p for p in user_message.content if p.type == "artifact_ref"]
    assert len(artifact_parts) == 1
    artifact_ref = artifact_parts[0].artifact_ref
    assert artifact_ref is not None
    decoded = base64.b64decode(artifact_ref.split(",", 1)[1])
    assert decoded == _FAKE_BYTES


@pytest.mark.asyncio
async def test_art_director_vision_safe_no_overlay_is_not_auto_flagged_as_failure() -> None:
    """Spec §17/§46: the model is TOLD about safe degradation via the task text, and even if it
    still passes back a clean result, that must not be misclassified upstream as a failure."""
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={"decision": "pass_with_notes", "severity": "low", "issues": [], "overall_confidence": 0.7},
        finish_reason="stop", model_used="fake-vision-v1", usage=CapabilityUsage(input_tokens=50, output_tokens=20),
    ))
    pixel_input = _pixel_input(renderer_decision_metadata={"tier": "none"})

    result = await evaluate_art_direction_vision(gateway, _vision_prompt_repository(), pixel_input=pixel_input)

    request = gateway.received_requests[0]
    task_text_part = next(p for p in request.messages[1].content if p.type == "text")
    assert task_text_part.text is not None
    assert "safe_no_overlay_degradation: True" in task_text_part.text
    assert result.decision == ArtDirectorDecision.PASS_WITH_NOTES
    assert ArtDirectorIssueCode.LOGO_TOO_SMALL not in result.issue_codes


@pytest.mark.asyncio
async def test_art_director_vision_parses_structured_issues_with_unknown_code_fallback() -> None:
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "decision": "rework", "severity": "medium",
            "issues": [
                {"code": "text_overlap", "description": "headline overlaps subject", "confidence": 0.8, "recommended_action": "rerender"},
                {"code": "not_a_real_code", "description": "something odd", "confidence": 0.4, "recommended_action": "review"},
            ],
            "overall_confidence": 0.6,
        },
        finish_reason="stop", model_used="fake-vision-v1", usage=CapabilityUsage(input_tokens=50, output_tokens=20),
    ))

    result = await evaluate_art_direction_vision(gateway, _vision_prompt_repository(), pixel_input=_pixel_input())

    assert result.decision == ArtDirectorDecision.REWORK
    assert ArtDirectorIssueCode.TEXT_OVERLAP in result.issue_codes
    assert ArtDirectorIssueCode.UNKNOWN_VISUAL_FAILURE in result.issue_codes  # invalid code, never dropped silently
    assert result.confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_art_director_vision_failure_fails_soft_to_a_safe_outcome() -> None:
    """Spec §27: a vision call failure must never silently PASS with full confidence, and must
    never BLOCK/REWORK based on a judgment that was never actually made."""
    gateway = FakeLLMGateway(generate_error=RuntimeError("simulated provider outage"))

    result = await evaluate_art_direction_vision(gateway, _vision_prompt_repository(), pixel_input=_pixel_input())

    assert result.decision == ArtDirectorDecision.PASS_WITH_NOTES
    assert result.action == "HUMAN_REVIEW"
    assert result.confidence == 0.0


# --- §19/§20: VisualFailure persistence + Revision Router proposal-only ------------------------

@pytest.mark.asyncio
async def test_visual_failure_persists_with_proposed_action_only(db_session: AsyncSession) -> None:
    result = ArtDirectorResult(
        decision=ArtDirectorDecision.REWORK, severity="medium",
        issue_codes=[ArtDirectorIssueCode.TEXT_OVERLAP], confidence=0.6,
    )
    row = await persist_visual_failure_shadow(
        db_session, result=result, presentation_type="NEWS", renderer_version="v1", revision_round=0,
    )
    await db_session.flush()

    assert row is not None
    assert row.revision_action is not None  # a PROPOSED action was recorded...
    assert row.resolved is False  # ...but nothing was executed - still unresolved

    persisted = (await db_session.execute(
        select(TelegramVisualFailure).where(TelegramVisualFailure.id == row.id)
    )).scalar_one()
    assert persisted.art_director_decision == ArtDirectorDecisionEnum.REWORK


@pytest.mark.asyncio
async def test_clean_pass_is_not_persisted_as_a_visual_failure(db_session: AsyncSession) -> None:
    result = ArtDirectorResult(decision=ArtDirectorDecision.PASS, severity="none", issue_codes=[])
    row = await persist_visual_failure_shadow(db_session, result=result)
    assert row is None


@pytest.mark.asyncio
async def test_revision_router_still_caps_at_two_rounds_when_wired_through_persistence(
    db_session: AsyncSession,
) -> None:
    result = ArtDirectorResult(
        decision=ArtDirectorDecision.REWORK, severity="medium",
        issue_codes=[ArtDirectorIssueCode.TEXT_OVERLAP], confidence=0.6,
    )
    row = await persist_visual_failure_shadow(db_session, result=result, revision_round=2)
    assert row is not None
    assert row.revision_action == "human_review"


# --- §22: Growth Director insufficient-evidence behavior ---------------------------------------

def test_growth_director_states_insufficient_evidence_when_no_patterns_exist() -> None:
    advisory = derive_growth_director_advisory([])
    assert advisory.confidence == 0.0
    assert any("insufficient evidence" in w for w in advisory.warnings)
    assert advisory.signals == []
    assert advisory.amplification_candidates == []


def test_growth_director_never_amplifies_a_single_anomaly() -> None:
    anomaly = PerformancePattern(
        description="one viral post", stage=EvidenceStage.ANOMALY, sample_size=1, effect_size=0.9,
        confidence=0.9, repeatability=1, baseline=0.1, recency_days=1,
    )
    advisory = derive_growth_director_advisory([anomaly])
    assert advisory.amplification_candidates == []
    assert any("anomaly only" in w for w in advisory.warnings)


def test_growth_director_surfaces_a_real_repeated_pattern() -> None:
    repeated = PerformancePattern(
        description="DATA presentation outperforms NEWS on weekday mornings",
        stage=EvidenceStage.REPEATED_PATTERN, sample_size=12, effect_size=0.4, confidence=0.7,
        repeatability=4, baseline=0.2, recency_days=14,
    )
    advisory = derive_growth_director_advisory([repeated])
    assert advisory.amplification_candidates
    assert advisory.confidence == pytest.approx(0.7)


# --- §23: Strategy Director insufficient-evidence behavior --------------------------------------

@pytest.mark.asyncio
async def test_strategy_director_states_insufficient_evidence_with_no_history(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    feed_state = await compute_feed_state(db_session, now=now)
    advisory = derive_strategy_advisory(feed_state, patterns=[])
    assert any("insufficient evidence" in n for n in advisory.content_balance_notes)
    assert any("insufficient evidence" in n for n in advisory.avoidance_fatigue_notes)
    assert advisory.priority_themes == []


# --- §25: experiment persistence -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_experiment_persistence_and_idempotent_terminal_state(db_session: AsyncSession) -> None:
    experiment = await create_experiment(
        db_session, hypothesis="DATA cards outperform NEWS cards for market topics",
        dimension="presentation_type", variant="DATA", baseline="NEWS", sample_target=30,
    )
    await db_session.flush()
    assert experiment.status == ExperimentStatus.PLANNED

    updated = await record_experiment_result(
        db_session, experiment.id, result="confirmed", confidence=0.8, status=ExperimentStatus.COMPLETED,
    )
    assert updated is not None
    assert updated.status == ExperimentStatus.COMPLETED

    # Idempotent: a second attempt to record a different result must not overwrite the terminal row.
    second_attempt = await record_experiment_result(
        db_session, experiment.id, result="different result", confidence=0.1, status=ExperimentStatus.ABANDONED,
    )
    assert second_attempt is not None
    assert second_attempt.result == "confirmed"
    assert second_attempt.status == ExperimentStatus.COMPLETED


# --- feature flags default false ------------------------------------------------------------------

def test_phase2_feature_flags_default_false() -> None:
    assert settings.telegram_performance_collection_enabled is False
    assert settings.telegram_channel_director_shadow_enabled is False
    assert settings.telegram_art_director_shadow_enabled is False
    assert settings.telegram_art_director_enforcement_enabled is False
    assert settings.telegram_revision_router_enabled is False
    assert settings.telegram_owned_channel_id is None
