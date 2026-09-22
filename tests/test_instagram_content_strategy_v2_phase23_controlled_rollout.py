"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 CONTROLLED ROLLOUT CLOSURE: the two narrow runtime
gates (instagram_product_lane_enabled, instagram_reel_execution_enabled - both default False,
core/config.py) and real format selection in `services.instagram_automatic_trigger::
evaluate_and_submit_instagram_opportunity()` (no more hardcoded SINGLE). Reuses the exact harness
tests/test_instagram_content_strategy_v2_phase2_product_lane.py already established (FakeLLMGateway/
FakePromptRepository, AsyncMock Bot, real db_session)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import services.instagram_automatic_trigger as trigger_module
from core.config import settings
from database.models.business_context_proposal import BusinessContextCommandType
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.business_context_proposal_service import confirm_proposal, create_proposal
from services.business_context_snapshot_service import get_business_context_snapshot
from services.director_execution_service import _product_opportunities_from_context
from services.instagram_automatic_trigger import evaluate_and_submit_instagram_opportunity
from services.instagram_creative_director import CAROUSEL_PROMPT_NAME, SINGLE_PROMPT_NAME
from services.instagram_format_director import ContentFormat, FormatDecision
from services.product_context_service import create_product
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository



@pytest.fixture(autouse=True)
def _pre_b6_carousel_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the pre-B.6 (v9-shaped) carousel contract through the live trigger; the media-first contract has its own tests (test_instagram_phase_b6_media_first.py)."""
    import services.instagram_automatic_trigger as _trigger

    monkeypatch.setattr(_trigger, "MEDIA_FIRST_CAROUSEL_VERSIONS", frozenset())

_SINGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "creative_angle": {"type": "string"}, "visual_concept": {"type": "string"},
        "on_image_copy": {"type": "string"}, "caption_direction": {"type": "string"},
        "cta": {"type": ["string", "null"]}, "asset_requirements": {"type": "array"},
        "evidence_used": {"type": "array"},
    },
    "required": ["creative_angle", "visual_concept", "on_image_copy", "caption_direction", "asset_requirements", "evidence_used"],
}
_SINGLE_OUTPUT = {
    "creative_angle": "a real confirmed feature", "visual_concept": "bold headline over dark gradient",
    "on_image_copy": "New: Production Mode", "caption_direction": "explain what it does and why it matters",
    "cta": "Learn more", "asset_requirements": [], "evidence_used": ["confirmed feature: Production Mode"],
}

_CAROUSEL_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "slides": {"type": "array", "items": {"type": "object", "properties": {
            "role": {"type": "string"}, "slide_copy": {"type": "string"}, "visual_direction": {"type": "string"},
        }}},
        "final_cta": {"type": ["string", "null"]}, "evidence_used": {"type": "array"},
    },
    "required": ["objective", "slides", "evidence_used"],
}
_CAROUSEL_OUTPUT = {
    "objective": "saves",
    "slides": [
        {"role": "hook", "slide_copy": "Two big confirmed updates", "visual_direction": "bold hook slide"},
        {"role": "body", "slide_copy": "Feature A is live", "visual_direction": "clean layout"},
        {"role": "cta", "slide_copy": "Learn more", "visual_direction": "brand footer"},
    ],
    "final_cta": "Learn more", "evidence_used": ["confirmed feature: Feature A", "confirmed feature: Feature B"],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=SINGLE_PROMPT_NAME, version="6", system="you are the creative director", rules=["never invent facts"],
        output_schema=_SINGLE_SCHEMA,
    ))
    repository.register(RenderedPrompt(
        name=CAROUSEL_PROMPT_NAME, version="10.4", system="you are the creative director", rules=["never invent facts"],
        output_schema=_CAROUSEL_SCHEMA,
    ))
    return repository


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=200, output_tokens=150),
    ))


@pytest.fixture(autouse=True)
def _topic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -1002345678901)
    monkeypatch.setattr(settings, "instagram_topic_id", 40)


async def _confirm_current_feature(db_session: AsyncSession, *, slug: str, feature: str):
    product = await create_product(db_session, slug=slug, name=f"Product {slug}")
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction=f"{feature} is live",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": slug,
            "raw_instruction": f"{feature} is live", "structured_context": {"current_features_add": [feature]},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)
    return product


# ---------------------------------------------------------------------------
# 1: runtime gate defaults
# ---------------------------------------------------------------------------


def test_product_lane_and_reel_execution_flags_default_false() -> None:
    assert settings.instagram_product_lane_enabled is False
    assert settings.instagram_reel_execution_enabled is False


# ---------------------------------------------------------------------------
# 2-3: real format selection - SINGLE (one confirmed fact) and CAROUSEL (two -> multi-step)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_confirmed_fact_selects_single_format(db_session: AsyncSession) -> None:
    await _confirm_current_feature(db_session, slug="p23single", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p23single")
    assert len(opportunity.evidence) == 1

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 801
    bot.send_message.return_value.message_id = 802
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(_SINGLE_OUTPUT), prompt_repository=_prompt_repository(),
    )
    assert outcome.reason == "source_image_unavailable"
    assert outcome.delivery_sent is False
    bot.send_photo.assert_not_called()  # the selected SINGLE has no real source asset


@pytest.mark.asyncio
async def test_two_confirmed_facts_selects_carousel_format(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="p23carousel", name="Carousel Product")
    for feature in ("Feature A", "Feature B"):
        proposal = await create_proposal(
            db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction=f"{feature} is live",
            proposed_change_set=[{
                "entity_type": "product_context_version", "product_slug": "p23carousel",
                "raw_instruction": f"{feature} is live", "structured_context": {"current_features_add": [feature]},
            }],
            created_by=1,
        )
        await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)

    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p23carousel")
    assert len(opportunity.evidence) == 2  # the real signal that drives has_multi_step_narrative=True

    bot = AsyncMock()
    bot.send_media_group.return_value = [MagicMock(message_id=810)]
    bot.send_message.return_value.message_id = 811
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(_CAROUSEL_OUTPUT), prompt_repository=_prompt_repository(),
    )
    assert outcome.reason == "submitted"
    assert outcome.gate_decision == "hold"  # carousel caption is still draft
    bot.send_media_group.assert_not_called()


# ---------------------------------------------------------------------------
# 4-5: REEL format decision + the execution gate (isolates the gate from real-signal REEL
# reachability, which is separately disclosed as not yet naturally reachable - no real
# has_video_asset signal exists for PRODUCT-truth opportunities today)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reel_decision_with_execution_disabled_is_deferred_never_silently_single(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "instagram_reel_execution_enabled", False)
    monkeypatch.setattr(
        trigger_module, "evaluate_format_shadow",
        lambda **kwargs: FormatDecision(recommended_format=ContentFormat.REEL, why="test fixture forces REEL"),
    )
    await _confirm_current_feature(db_session, slug="p23reelhold", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p23reelhold")

    bot = AsyncMock()
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(_SINGLE_OUTPUT), prompt_repository=_prompt_repository(),
    )
    assert outcome.accepted is True
    assert outcome.reason == "reel_execution_disabled"
    bot.send_photo.assert_not_called()
    bot.send_video.assert_not_called()  # never silently substituted with a SINGLE send


@pytest.mark.asyncio
async def test_reel_decision_with_execution_enabled_reaches_the_existing_reel_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "instagram_reel_execution_enabled", True)
    monkeypatch.setattr(
        trigger_module, "evaluate_format_shadow",
        lambda **kwargs: FormatDecision(recommended_format=ContentFormat.REEL, why="test fixture forces REEL"),
    )
    reel_schema = {
        "type": "object",
        "properties": {
            "objective": {"type": "string"}, "hook": {"type": "string"},
            "target_duration_seconds": {"type": "integer"}, "scene_sequence": {"type": "array"},
            "shot_list": {"type": "array"}, "voiceover_script": {"type": ["string", "null"]},
            "on_screen_text": {"type": "array"}, "pacing": {"type": "string"},
            "audio_direction": {"type": ["string", "null"]}, "cta": {"type": ["string", "null"]},
            "caption_direction": {"type": "string"}, "evidence_used": {"type": "array"},
        },
        "required": [
            "objective", "hook", "target_duration_seconds", "scene_sequence", "pacing",
            "caption_direction", "evidence_used",
        ],
    }
    reel_output = {
        "objective": "reach", "hook": "Production Mode is here", "target_duration_seconds": 20,
        "scene_sequence": ["0-3s: hook", "3-15s: explain", "15-20s: cta"], "shot_list": ["screen recording"],
        "voiceover_script": "Production Mode is now live.", "on_screen_text": ["Production Mode"],
        "pacing": "fast", "audio_direction": "upbeat", "cta": "Try it now",
        "caption_direction": "explain the launch clearly and invite people to try it",
        "evidence_used": ["confirmed feature: Production Mode"],
    }
    from services.instagram_creative_director import REEL_PROMPT_NAME
    prompt_repository = _prompt_repository()
    prompt_repository.register(RenderedPrompt(
        name=REEL_PROMPT_NAME, version="7", system="you are the creative director", rules=["never invent facts"],
        output_schema=reel_schema,
    ))

    await _confirm_current_feature(db_session, slug="p23reelgo", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p23reelgo")

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 820
    bot.send_message.return_value.message_id = 821
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(reel_output), prompt_repository=prompt_repository,
    )
    assert outcome.reason == "submitted"  # reached delivery - the existing Reel path ran end to end


# ---------------------------------------------------------------------------
# 6: no public Instagram write anywhere in this module (structural, re-affirmed for the rewritten
# function specifically)
# ---------------------------------------------------------------------------


def test_no_public_instagram_write_path_in_automatic_trigger() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(trigger_module))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "services.instagram_account_reader" not in imported
    assert "services.instagram_media_hosting" not in imported
    assert "services.instagram_publish_adapter" not in imported
