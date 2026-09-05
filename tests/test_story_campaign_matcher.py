"""SOCIAL-INTELLIGENCE-OPS-1, spec §60: StoryCampaignMatcher tests - the ONE shared matcher both
platforms are meant to consume."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.claim_policy import ClaimStatus
from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_planner import CampaignPlan
from services.campaign_service import create_campaign
from services.claim_policy_service import create_claim_policy
from services.instagram_semantic_matching import SEMANTIC_MATCH_PROMPT_NAME, SEMANTIC_MATCH_PROMPT_VERSION
from services.product_context_service import create_product
from services.story_campaign_matcher import (
    StoryCampaignMatchType,
    StoryInput,
    match_story_to_campaign,
    match_story_to_campaign_with_semantics,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository


def _plan(**overrides: object) -> CampaignPlan:
    defaults: dict[str, object] = dict(
        campaign_id="c1", product_id="p1", objective=None, phase="PROBLEM_FRAMING", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None, key_messages=["ai coding assistant", "developer productivity"],
    )
    defaults.update(overrides)
    return CampaignPlan(**defaults)  # type: ignore[arg-type]


async def _empty_snapshot(db_session: AsyncSession):
    return await get_business_context_snapshot(db_session, now=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_topic_overlap_produces_relevant_match(db_session: AsyncSession) -> None:
    story = StoryInput(story_id="s1", title="New AI coding assistant launches for developers", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    match = match_story_to_campaign(story, _plan(), snapshot=snapshot)
    assert match.topic_relevance > 0
    assert match.match_type in (StoryCampaignMatchType.RELEVANT, StoryCampaignMatchType.STRONG)


@pytest.mark.asyncio
async def test_entity_overlap_contributes_independently(db_session: AsyncSession) -> None:
    story = StoryInput(story_id="s2", title="Company news", entities=["developer", "productivity"], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    match = match_story_to_campaign(story, _plan(), snapshot=snapshot)
    assert match.entity_relevance > 0


@pytest.mark.asyncio
async def test_no_overlap_is_none_match(db_session: AsyncSession) -> None:
    story = StoryInput(story_id="s3", title="Local weather forecast update", entities=[], keywords=["weather"])
    snapshot = await _empty_snapshot(db_session)
    match = match_story_to_campaign(story, _plan(), snapshot=snapshot)
    assert match.match_type == StoryCampaignMatchType.NONE
    assert match.topic_relevance == 0.0
    assert match.entity_relevance == 0.0


@pytest.mark.asyncio
async def test_problem_framing_high_relevance_does_not_imply_product_mention(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="ai", name="NINJA AI")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="AI launch",
        structured_context={"status": "tentative", "date_confidence": "unknown"},
    )
    plan = _plan(campaign_id=str(campaign.id), product_id=str(product.id), phase="PROBLEM_FRAMING", status="tentative")
    story = StoryInput(story_id="s4", title="AI coding assistant developer productivity breakthrough", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    match = match_story_to_campaign(story, plan, snapshot=snapshot, product_slug="ai")
    assert match.match_type in (StoryCampaignMatchType.RELEVANT, StoryCampaignMatchType.STRONG)
    assert match.product_mention_allowed is False


@pytest.mark.asyncio
async def test_founder_directive_blocks_promotion_even_with_confirmed_campaign(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="store", name="NINJA Store")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Store launch",
        structured_context={"status": "confirmed", "date_confidence": "exact"},
    )
    plan = _plan(campaign_id=str(campaign.id), product_id=str(product.id), phase="LAUNCH", status="confirmed")
    story = StoryInput(story_id="s5", title="ai coding assistant developer productivity", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)

    directive = StrategicDirective(
        instruction="Store пока не продвигаем.", valid_from=datetime.now(timezone.utc), priority=1,
        products=["store"], platforms=[], status=DirectiveStatus.ACTIVE,
    )
    without_directive = match_story_to_campaign(story, plan, snapshot=snapshot, product_slug="store")
    assert without_directive.product_mention_allowed is True

    with_directive = match_story_to_campaign(story, plan, snapshot=snapshot, directives=[directive], product_slug="store")
    assert with_directive.product_mention_allowed is False
    assert any("Founder Directive" in e for e in with_directive.evidence)


@pytest.mark.asyncio
async def test_embargo_and_restricted_claims_propagate(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="embargotest", name="Embargo Test Product")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={"status": "confirmed", "date_confidence": "exact"},
    )
    await create_claim_policy(db_session, product_id=product.id, claim_text="exact price", status=ClaimStatus.RESTRICTED)
    await create_claim_policy(
        db_session, product_id=product.id, claim_text="secret feature", status=ClaimStatus.EMBARGOED,
        embargoed_until=datetime.now(timezone.utc) + timedelta(days=10),
    )
    plan = _plan(campaign_id=str(campaign.id), product_id=str(product.id), phase="LAUNCH", status="confirmed")
    story = StoryInput(story_id="s6", title="ai coding assistant developer productivity", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    match = match_story_to_campaign(story, plan, snapshot=snapshot, product_slug="embargotest")
    assert "exact price" in match.restricted_claims
    assert match.embargo_constraints
    assert match.product_mention_allowed is False  # still-active embargo blocks it


@pytest.mark.asyncio
async def test_deterministic_evidence_always_present(db_session: AsyncSession) -> None:
    story = StoryInput(story_id="s7", title="unrelated", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    match = match_story_to_campaign(story, _plan(), snapshot=snapshot)
    assert any("topic_relevance" in e for e in match.evidence)
    assert any("entity_relevance" in e for e in match.evidence)


# ---------------------------------------------------------------------------
# semantic supplement / fail-soft
# ---------------------------------------------------------------------------

_PROMPT = RenderedPrompt(
    name=SEMANTIC_MATCH_PROMPT_NAME, version=SEMANTIC_MATCH_PROMPT_VERSION, system="compare two subjects",
    rules=["never invent facts"], output_schema={"type": "object", "properties": {}, "required": []},
)


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=30, output_tokens=10),
    ))


@pytest.mark.asyncio
async def test_semantic_supplement_upgrades_low_lexical_overlap_match(db_session: AsyncSession) -> None:
    story = StoryInput(story_id="s8", title="OpenAI unveils a new autonomous coding agent", entities=["OpenAI"], keywords=["coding", "agent"])
    snapshot = await _empty_snapshot(db_session)
    plan = _plan(key_messages=["ai productivity tools"])

    deterministic_only = match_story_to_campaign(story, plan, snapshot=snapshot)
    assert deterministic_only.match_type == StoryCampaignMatchType.NONE

    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway({"is_related": True, "relatedness": 0.85, "rationale": "same theme", "shared_concepts": ["AI productivity"]})
    with_semantics = await match_story_to_campaign_with_semantics(
        story, plan, snapshot=snapshot, gateway=gateway, prompt_repository=prompt_repository,
    )
    assert with_semantics.semantic_relevance == 0.85
    assert with_semantics.match_type != StoryCampaignMatchType.NONE
    # deterministic evidence retained, never erased
    assert with_semantics.topic_relevance == deterministic_only.topic_relevance


@pytest.mark.asyncio
async def test_gateway_failure_falls_back_to_deterministic_result(db_session: AsyncSession) -> None:
    from integrations.llm_gateway.errors import AllProvidersFailedError

    story = StoryInput(story_id="s9", title="ai coding assistant developer productivity", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    plan = _plan()

    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_error=AllProvidersFailedError("down", reason="all_candidates_failed"))

    deterministic_only = match_story_to_campaign(story, plan, snapshot=snapshot)
    with_failure = await match_story_to_campaign_with_semantics(
        story, plan, snapshot=snapshot, gateway=gateway, prompt_repository=prompt_repository,
    )
    assert with_failure.semantic_relevance is None
    assert with_failure.match_type == deterministic_only.match_type
    assert with_failure.topic_relevance == deterministic_only.topic_relevance


@pytest.mark.asyncio
async def test_no_gateway_supplied_is_deterministic_only(db_session: AsyncSession) -> None:
    story = StoryInput(story_id="s10", title="ai coding assistant developer productivity", entities=[], keywords=[])
    snapshot = await _empty_snapshot(db_session)
    match = await match_story_to_campaign_with_semantics(story, _plan(), snapshot=snapshot)
    assert match.semantic_relevance is None
