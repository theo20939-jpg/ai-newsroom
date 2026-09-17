"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: PRODUCT opportunities without a mandatory
LaunchCampaign, and the new general `evaluate_and_submit_instagram_opportunity()` entrypoint -
`services.instagram_automatic_trigger`'s NEW sibling to the NEWS-only
`evaluate_and_submit_instagram_candidate()`, exercised the same way
tests/test_instagram_automatic_trigger.py already does (FakeLLMGateway/FakePromptRepository,
AsyncMock Bot, real db_session)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image

import services.instagram_automatic_trigger as trigger_module

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.business_context_proposal import BusinessContextCommandType
from database.models.product import ProductStatus
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.business_context_proposal_service import confirm_proposal, create_proposal
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_service import create_campaign
from services.director_execution_service import _product_opportunities_from_context, run_instagram_growth_strategist
from services.instagram_automatic_trigger import evaluate_and_submit_instagram_opportunity
from services.instagram_content_opportunity import OpportunitySourceType
from services.instagram_creative_director import SINGLE_PROMPT_NAME
from services.product_context_service import create_product
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

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

_GOOD_OUTPUT = {
    "creative_angle": "a real confirmed feature", "visual_concept": "bold headline over dark gradient",
    "on_image_copy": "New: Production Mode", "caption_direction": "explain what it does and why it matters",
    "cta": "Learn more", "asset_requirements": [], "evidence_used": ["confirmed feature: Production Mode"],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=SINGLE_PROMPT_NAME, version="6", system="you are the creative director", rules=["never invent facts"],
        output_schema=_SINGLE_SCHEMA,
    ))
    return repository


def _gateway(output: dict = _GOOD_OUTPUT) -> FakeLLMGateway:
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


async def _confirm_planned_feature(db_session: AsyncSession, *, slug: str, feature: str, status: ProductStatus = ProductStatus.IDEA):
    product = await create_product(db_session, slug=slug, name=f"Product {slug}", status=status)
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction=f"{feature} is planned",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": slug,
            "raw_instruction": f"{feature} is planned", "structured_context": {"planned_features_add": [feature]},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)
    return product


# ---------------------------------------------------------------------------
# _product_opportunities_from_context(): campaign-free PRODUCT opportunities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_product_with_confirmed_feature_and_no_campaign_produces_an_opportunity(db_session: AsyncSession) -> None:
    await _confirm_current_feature(db_session, slug="p2ai", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    matching = [c for c in contexts if c.product_slug == "p2ai"]
    assert len(matching) == 1
    assert matching[0].opportunity.source_type == OpportunitySourceType.PRODUCT
    assert matching[0].opportunity.campaign_id is None
    assert "confirmed feature: Production Mode" in matching[0].opportunity.evidence


@pytest.mark.asyncio
async def test_product_with_zero_confirmed_features_produces_nothing(db_session: AsyncSession) -> None:
    await create_product(db_session, slug="p2empty", name="Empty Product")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    assert not any(c.product_slug == "p2empty" for c in contexts)


@pytest.mark.asyncio
async def test_campaign_backed_product_is_never_double_counted(db_session: AsyncSession) -> None:
    product = await _confirm_current_feature(db_session, slug="p2dual", feature="Some Feature")
    now = datetime.now(timezone.utc)
    await create_campaign(
        db_session, product_id=product.id, name="p2dual launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    snapshot = await get_business_context_snapshot(db_session, now=now)
    context_only_ids = [c.opportunity.id for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2dual"]
    assert context_only_ids == []  # covered by the campaign-backed function instead, never both


@pytest.mark.asyncio
async def test_growth_strategist_ranks_campaign_backed_and_campaign_free_together(db_session: AsyncSession) -> None:
    await _confirm_current_feature(db_session, slug="p2contextonly", feature="Standalone Feature")
    product2 = await create_product(db_session, slug="p2campaign", name="Campaign Product")
    now = datetime.now(timezone.utc)
    await create_campaign(
        db_session, product_id=product2.id, name="p2campaign launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    result = await run_instagram_growth_strategist(db_session, now=now)
    opportunity_ids = {o.id for o in result.strategy.priority_opportunities}
    assert any(oid.startswith("product_context:") for oid in opportunity_ids)
    assert any(oid.startswith("campaign:") for oid in opportunity_ids)


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 MINIMAL FIXES (FIX B): _product_opportunities_from_
# context() eligibility - PLANNED facts now count too (were excluded before, CONFIRMED-only),
# state-aware evidence labeling, and DEPRECATED (whole-product-retired) exclusion.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_product_with_only_planned_feature_produces_an_opportunity(db_session: AsyncSession) -> None:
    await _confirm_planned_feature(db_session, slug="p2planned", feature="Voice Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    matching = [c for c in contexts if c.product_slug == "p2planned"]
    assert len(matching) == 1
    assert matching[0].opportunity.source_type == OpportunitySourceType.PRODUCT
    assert "planned feature: Voice Mode" in matching[0].opportunity.evidence
    assert "confirmed feature: Voice Mode" not in matching[0].opportunity.evidence


@pytest.mark.asyncio
async def test_product_with_confirmed_and_planned_features_labels_each_correctly(db_session: AsyncSession) -> None:
    product = await _confirm_current_feature(db_session, slug="p2mixed", feature="Production Mode")
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="Voice Mode is planned",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": "p2mixed",
            "raw_instruction": "Voice Mode is planned", "structured_context": {"planned_features_add": ["Voice Mode"]},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)

    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    matching = [c for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2mixed"]
    assert len(matching) == 1
    evidence = matching[0].opportunity.evidence
    assert "confirmed feature: Production Mode" in evidence
    assert "planned feature: Voice Mode" in evidence
    assert len(evidence) == 2  # the real signal that drives has_multi_step_narrative=True downstream


@pytest.mark.asyncio
async def test_paused_product_never_produces_an_opportunity_even_with_planned_features(db_session: AsyncSession) -> None:
    await _confirm_planned_feature(db_session, slug="p2paused", feature="Voice Mode", status=ProductStatus.PAUSED)
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    assert not any(c.product_slug == "p2paused" for c in contexts)


@pytest.mark.asyncio
async def test_sunset_product_never_produces_an_opportunity_even_with_confirmed_features(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="p2sunset", name="Sunset Product", status=ProductStatus.SUNSET)
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="Legacy Mode is live",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": "p2sunset",
            "raw_instruction": "Legacy Mode is live", "structured_context": {"current_features_add": ["Legacy Mode"]},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)

    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    assert not any(c.product_slug == "p2sunset" for c in contexts)


@pytest.mark.asyncio
async def test_two_planned_features_selects_carousel_format(db_session: AsyncSession) -> None:
    """Multi-step-narrative selection (>1 evidence bullet) must work identically for PLANNED
    evidence as it already does for CONFIRMED evidence - the label changes, the pipeline does not."""
    product = await create_product(db_session, slug="p2planmulti", name="Multi Planned Product")
    for feature in ("Feature A", "Feature B"):
        proposal = await create_proposal(
            db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction=f"{feature} is planned",
            proposed_change_set=[{
                "entity_type": "product_context_version", "product_slug": "p2planmulti",
                "raw_instruction": f"{feature} is planned", "structured_context": {"planned_features_add": [feature]},
            }],
            created_by=1,
        )
        await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)

    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2planmulti")
    assert len(opportunity.evidence) == 2
    assert all(item.startswith("planned feature:") for item in opportunity.evidence)


@pytest.mark.asyncio
async def test_product_with_only_undecided_facts_produces_nothing(db_session: AsyncSession) -> None:
    """`undecided_facts` lives in a different identity space (canonical fact keys, not feature
    names) and must never be read here - a product with only an undecided fact and zero
    current/planned features is indistinguishable from a fully-unknown product for this collector."""
    product = await create_product(db_session, slug="p2undecided", name="Undecided Product")
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="billing model not decided yet",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": "p2undecided",
            "raw_instruction": "billing model not decided yet",
            "structured_context": {"undecided_facts_add": ["pricing.billing_model"]},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=1)
    await db_session.refresh(product)

    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    assert not any(c.product_slug == "p2undecided" for c in contexts)


@pytest.mark.asyncio
async def test_campaign_backed_product_with_only_planned_features_is_never_double_counted(db_session: AsyncSession) -> None:
    product = await _confirm_planned_feature(db_session, slug="p2dualplanned", feature="Voice Mode")
    now = datetime.now(timezone.utc)
    await create_campaign(
        db_session, product_id=product.id, name="p2dualplanned launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    snapshot = await get_business_context_snapshot(db_session, now=now)
    context_only_ids = [c.opportunity.id for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2dualplanned"]
    assert context_only_ids == []  # covered by the campaign-backed function instead, never both


@pytest.mark.asyncio
async def test_planned_only_opportunity_flows_through_the_full_pipeline_to_delivery(db_session: AsyncSession) -> None:
    """End-to-end proof that the eligibility fix actually reaches PRODUCT_OPPORTUNITY_CREATED, not
    just the collector function in isolation."""
    await _confirm_planned_feature(db_session, slug="p2plandeliver", feature="Voice Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2plandeliver")

    planned_output = dict(_GOOD_OUTPUT, evidence_used=["planned feature: Voice Mode"])
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 704
    bot.send_message.return_value.message_id = 705
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="NINJA AI Voice Mode is planned",
        gateway=_gateway(planned_output), prompt_repository=_prompt_repository(),
    )
    assert outcome.accepted is True
    assert outcome.reason == "source_image_unavailable"
    assert outcome.delivery_sent is False
    bot.send_photo.assert_not_called()


# ---------------------------------------------------------------------------
# evaluate_and_submit_instagram_opportunity(): the new general entrypoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_general_entrypoint_delivers_a_product_opportunity_to_the_configured_topic(db_session: AsyncSession) -> None:
    await _confirm_current_feature(db_session, slug="p2deliver", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    contexts = _product_opportunities_from_context(snapshot)
    opportunity = next(c.opportunity for c in contexts if c.product_slug == "p2deliver")

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 701
    bot.send_message.return_value.message_id = 702
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="NINJA AI Production Mode is live",
        gateway=_gateway(), prompt_repository=_prompt_repository(),
    )
    assert outcome.accepted is True
    assert outcome.reason == "source_image_unavailable"
    assert outcome.delivery_sent is False
    bot.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_general_entrypoint_is_idempotent_across_calls(db_session: AsyncSession) -> None:
    await _confirm_current_feature(db_session, slug="p2dup", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2dup")

    bot1 = AsyncMock()
    bot1.send_photo.return_value.message_id = 703
    first = await evaluate_and_submit_instagram_opportunity(
        db_session, bot1, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(), prompt_repository=_prompt_repository(),
    )
    assert first.reason == "source_image_unavailable"
    assert first.delivery_sent is False

    bot2 = AsyncMock()
    second = await evaluate_and_submit_instagram_opportunity(
        db_session, bot2, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(), prompt_repository=_prompt_repository(),
    )
    assert second.reason == "source_image_unavailable"  # no delivery persisted; retry is safe
    bot2.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_general_entrypoint_survives_creative_director_fact_safety_rejection(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The SAME fact-safety mechanism the NEWS path relies on applies here too - a claim outside
    `allowed_evidence` fails closed, never crashing the caller."""
    await _confirm_current_feature(db_session, slug="p2hold", feature="Production Mode")
    snapshot = await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))
    opportunity = next(c.opportunity for c in _product_opportunities_from_context(snapshot) if c.product_slug == "p2hold")

    async def available_source(session, story_id):
        return Image.new("RGB", (512, 512), "navy"), SimpleNamespace(id=uuid4(), candidate_id="fixture-source"), 1, 2048

    monkeypatch.setattr(trigger_module, "_resolve_single_source_image", available_source)
    bad_output = dict(_GOOD_OUTPUT, evidence_used=["a fact never in allowed_evidence"])
    bot = AsyncMock()
    outcome = await evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="x",
        gateway=_gateway(bad_output), prompt_repository=_prompt_repository(),
    )
    assert outcome.reason.startswith("creative_director_failed")
    bot.send_photo.assert_not_called()


def test_general_entrypoint_never_imports_credentials_or_media_hosting_or_publish() -> None:
    """Same structural guarantee tests/test_instagram_automatic_trigger.py already asserts for the
    whole module - re-affirmed explicitly here since this test file exercises the NEW function."""
    import ast
    import inspect

    import services.instagram_automatic_trigger as trigger_module

    tree = ast.parse(inspect.getsource(trigger_module))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "services.instagram_account_reader" not in imported
    assert "services.instagram_media_hosting" not in imported
    assert "services.instagram_publish_adapter" not in imported
