"""Focused source-image and entity-policy regressions for the Phase 23 hotfix."""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
from PIL import Image

import services.instagram_automatic_trigger as trigger
from services.instagram_art_validator import validate_instagram_art
from core.config import settings
from database.models.instagram_editorial_delivery import InstagramEditorialDelivery
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_package_presenter import present_single
from schemas.instagram_creative import InstagramSingleCreative


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (512, 512), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_ranked_candidate_recovery_reads_decodes_and_reaches_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    event_id = uuid4()
    bad = SimpleNamespace(id=uuid4(), candidate_id="rank-1", is_expired=False)
    good = SimpleNamespace(id=uuid4(), candidate_id="rank-2", is_expired=False)
    read_order = []
    pixels = _image_bytes()

    async def ranked(session, *, news_event_id, limit):
        assert news_event_id == event_id
        assert limit == 10
        return [bad, good]

    def read(candidate):
        read_order.append(candidate.candidate_id)
        return b"not an image" if candidate is bad else pixels

    monkeypatch.setattr(trigger, "get_editorial_image_candidates", ranked)
    monkeypatch.setattr(trigger, "read_candidate_bytes", read)
    source, selected, count, length = await trigger._resolve_single_source_image(object(), str(event_id))
    assert read_order == ["rank-1", "rank-2"]
    assert selected is good
    assert count == 2 and length == len(pixels)
    assert source is not None and source.size == (512, 512)

    opportunity = ContentOpportunity(id="fresh-opp", source_type=OpportunitySourceType.NEWS, story_id=str(event_id))
    shadow = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description="Company X announced Y",
        primary_objective="reach", audience_description="", recommended_format="single", hook_family=None,
        creative_concept_summary=None, alternative_format=None, alternative_objective=None,
        product_mention_allowed=False, evidence=["Company X announced Y"], confidence=0.5,
    )
    creative = InstagramSingleCreative(
        creative_angle="angle", visual_concept="use source image", on_image_copy="Company X",
        caption_direction="internal brief", final_caption="Company X announced Y. Here is what changed.",
        source_subject="Company X", evidence_used=["Company X announced Y"],
    )
    pkg = build_instagram_content_package(
        opportunity=opportunity, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=shadow, creative_outcome=CreativeGenerationOutcome(single=creative),
        source_image_ref=selected.candidate_id, media_candidate_id=str(selected.id),
    )
    render = render_instagram_feed_image(pkg, source_image=source)
    assert render.evidence.source_image_treatment != "none"
    assert validate_instagram_art(pkg, [render]).passed
    presentation = present_single(pkg, render, version=1)
    assert presentation.kind == "single"
    assert presentation.media == [render.image_bytes]
    assert presentation.media[0]


def test_external_news_entities_are_distinct_from_protected_product_policy() -> None:
    news = ContentOpportunity(id="news-opp", source_type=OpportunitySourceType.NEWS, story_id="story")
    hybrid = ContentOpportunity(id="hybrid-opp", source_type=OpportunitySourceType.HYBRID, story_id="story", product_id="protected")
    product = ContentOpportunity(id="product-opp", source_type=OpportunitySourceType.PRODUCT, product_id="protected")
    assert trigger._is_external_news(news)
    assert not trigger._is_external_news(hybrid)
    assert not trigger._is_external_news(product)

@pytest.mark.asyncio
async def test_general_news_delivery_records_real_story_id_not_opportunity_id(
    db_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    story_id = str(uuid4())
    opportunity = ContentOpportunity(
        id="fresh-delivery-opp", source_type=OpportunitySourceType.NEWS,
        story_id=story_id, news_value=0.9, evidence=["Company X announced Y"],
    )
    candidate = SimpleNamespace(id=uuid4(), candidate_id="real-image")

    async def image_source(session, incoming_story_id):
        assert incoming_story_id == story_id
        import random

        rng = random.Random(7)  # textured, photo-like: a flat solid square is an unsuitable flat card under the media contract
        return [(Image.frombytes("RGB", (512, 512), bytes(rng.randrange(256) for _ in range(512 * 512 * 3))), candidate, 2048)], 1

    async def creative_generation(director_input, fmt):
        assert director_input.external_news_entities_allowed
        return CreativeGenerationOutcome(single=InstagramSingleCreative(
            creative_angle="angle", visual_concept="source photo", on_image_copy="Company X",
            caption_direction="internal brief", final_caption="Company X announced Y.",
            source_subject="Company X", evidence_used=["Company X announced Y"],
        ))

    monkeypatch.setattr(trigger, "_decoded_source_candidates", image_source)
    monkeypatch.setattr(trigger, "build_default_regenerator", lambda gateway, prompts: creative_generation)
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -1002345678901)
    monkeypatch.setattr(settings, "instagram_topic_id", 40)
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 701
    bot.send_message.return_value.message_id = 702

    result = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, bot, opportunity=opportunity, opportunity_summary="Company X announced Y",
        gateway=None, prompt_repository=None,
    )
    assert result.delivery_sent
    delivery = await db_session.get(InstagramEditorialDelivery, UUID(result.delivery_id))
    assert delivery.source_story_id == story_id
    assert delivery.source_story_id != opportunity.id
    assert delivery.content_format == "single"
