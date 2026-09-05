"""NINJA Social Intelligence Foundation, Part III §107: required Telegram Directors foundation
tests. Contract-level coverage matching this phase's own honest scope (deterministic shadow
evaluators, not learned/LLM-based directors - see each module's own docstring)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.telegram_channel_memory import TelegramChannelMemory
from services.campaign_planner import CampaignPlan
from services.telegram_art_director import (
    ArtDirectorDecision,
    ArtDirectorIssueCode,
    PixelInputContract,
    evaluate_art_direction_shadow,
)
from services.telegram_channel_director import ChannelDirectorDecision, evaluate_channel_fit_shadow
from services.telegram_editorial_need import derive_editorial_need
from services.telegram_feed_state import compute_feed_state
from services.telegram_performance_memory import (
    TELEGRAM_PLATFORM_CAPABILITIES,
    CapabilityStatus,
    EvidenceStage,
    PerformancePattern,
    advance_evidence_stage,
)
from services.telegram_revision_router import MAX_REVISION_ROUNDS, RevisionAction, route_revision


async def _post(db_session: AsyncSession, *, published_at: datetime, **kwargs) -> TelegramChannelMemory:
    row = TelegramChannelMemory(published_at=published_at, **kwargs)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_feed_state_calculation(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await _post(db_session, published_at=now - timedelta(minutes=30), topics=["ai"], source="techcrunch")
    await _post(db_session, published_at=now - timedelta(hours=3), topics=["ai"], source="techcrunch")
    await _post(db_session, published_at=now - timedelta(hours=20), topics=["gadgets"], source="verge")

    feed_state = await compute_feed_state(db_session, now=now)
    assert feed_state.posts_1h == 1
    assert feed_state.posts_6h == 2
    assert feed_state.posts_24h == 3
    assert feed_state.topic_distribution["ai"] == 2
    assert feed_state.topic_streak == 2  # two most-recent posts both "ai"


@pytest.mark.asyncio
async def test_business_campaign_relevance_separated_from_news_importance(db_session: AsyncSession) -> None:
    """Spec §43: organic news value and campaign relevance must be reported as distinct fields,
    never merged into one score."""
    now = datetime.now(timezone.utc)
    feed_state = await compute_feed_state(db_session, now=now)
    editorial_need = derive_editorial_need(feed_state)
    plan = CampaignPlan(
        campaign_id="x", product_id="y", objective=None, phase="PROBLEM_FRAMING", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )
    result = evaluate_channel_fit_shadow(
        news_importance=0.9, feed_state=feed_state, editorial_need=editorial_need, campaign_plan=plan,
        campaign_mention_explicitly_allowed=False,
    )
    assert result.organic_relevance == 0.9
    assert result.business_campaign_relevance > 0
    assert result.organic_relevance != result.business_campaign_relevance
    assert any("does not allow product mention" in w for w in result.warnings)
    assert result.decision == ChannelDirectorDecision.PUBLISH_NOW


def test_art_director_safe_no_overlay_is_not_a_failure() -> None:
    """Spec §46: a deliberate safety-degradation decision (no visible brand mark) must never be
    classified as a visual failure."""
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-bytes", caption="test", presentation_type="DATA", renderer_version="v1",
        renderer_decision_metadata={"tier": "none"},
    )
    result = evaluate_art_direction_shadow(pixel_input)
    assert result.decision == ArtDirectorDecision.PASS
    assert result.issue_codes == []


def test_art_director_empty_bytes_is_a_real_failure() -> None:
    pixel_input = PixelInputContract(
        rendered_bytes=b"", caption="test", presentation_type="NEWS", renderer_version="v1",
    )
    result = evaluate_art_direction_shadow(pixel_input)
    assert result.decision == ArtDirectorDecision.BLOCK
    assert ArtDirectorIssueCode.VISUAL_EMPTY in result.issue_codes


def test_revision_router_max_rounds_is_two() -> None:
    assert MAX_REVISION_ROUNDS == 2
    from services.telegram_art_director import ArtDirectorResult

    failing_result = ArtDirectorResult(
        decision=ArtDirectorDecision.REWORK, severity="medium", issue_codes=[ArtDirectorIssueCode.TEXT_OVERLAP],
    )
    assert route_revision(failing_result, attempt_count=0) == RevisionAction.RERENDER
    assert route_revision(failing_result, attempt_count=1) == RevisionAction.RERENDER
    assert route_revision(failing_result, attempt_count=2) == RevisionAction.HUMAN_REVIEW
    assert route_revision(failing_result, attempt_count=99) == RevisionAction.HUMAN_REVIEW


def test_visual_failure_memory_evidence_stage_progression() -> None:
    """Spec §83: no promotion on a single strong sample - the gate is deterministic and code-
    enforced, not a docstring promise."""
    thin = PerformancePattern(
        description="test", stage=EvidenceStage.ANOMALY, sample_size=1, effect_size=0.9,
        confidence=0.9, repeatability=1, baseline=0.1, recency_days=1,
    )
    assert advance_evidence_stage(thin) == EvidenceStage.ANOMALY

    repeated = PerformancePattern(
        description="test", stage=EvidenceStage.ANOMALY, sample_size=10, effect_size=0.5,
        confidence=0.6, repeatability=5, baseline=0.2, recency_days=10,
    )
    assert advance_evidence_stage(repeated) == EvidenceStage.REPEATED_PATTERN

    stable = PerformancePattern(
        description="test", stage=EvidenceStage.ANOMALY, sample_size=50, effect_size=0.5,
        confidence=0.8, repeatability=10, baseline=0.2, recency_days=30,
    )
    assert advance_evidence_stage(stable) == EvidenceStage.STABLE_WORKING_RULE


def test_platform_capabilities_unknown_is_preserved_not_fabricated() -> None:
    """Spec §50/§3 (Phase 2 re-classification): never fabricate availability - views/reactions/
    reposts/comments are honestly AVAILABLE_WITH_EXISTING_MTPROTO (the read mechanism and its auth
    both already exist, proven for external channels; only wiring + channel membership are
    missing - not "unknown" and not a plain "available"), link_clicks is honestly UNAVAILABLE (no
    such Telegram API exists at all)."""
    assert TELEGRAM_PLATFORM_CAPABILITIES["views"].status == CapabilityStatus.AVAILABLE_WITH_EXISTING_MTPROTO
    assert TELEGRAM_PLATFORM_CAPABILITIES["link_clicks"].status == CapabilityStatus.UNAVAILABLE
    for capability in TELEGRAM_PLATFORM_CAPABILITIES.values():
        assert capability.evidence, f"{capability.name} capability must carry real evidence, never a bare guess"


def test_telegram_director_feature_flags_default_false() -> None:
    assert settings.telegram_channel_director_shadow_enabled is False
    assert settings.telegram_art_director_shadow_enabled is False
    assert settings.telegram_growth_memory_enabled is False
    assert settings.telegram_strategy_director_enabled is False
    assert settings.telegram_revision_router_enabled is False
    assert settings.telegram_art_director_enforcement_enabled is False
