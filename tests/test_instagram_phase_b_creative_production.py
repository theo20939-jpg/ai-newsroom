from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
from pydantic import SecretStr
import pytest

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramCreativeExecutionPlan
from services.budgeted_image_execution import BudgetedImageResult
import services.instagram_creative_media as media


def _creative(strategy):
    return SimpleNamespace(creative_execution_plan=InstagramCreativeExecutionPlan(
        main_idea="clear idea", focal_point="main subject", media_strategy=strategy,
        media_rationale="best fit for the evidence", composition_direction="portrait with negative space",
        branding_treatment="canonical renderer asset", visual_treatment="editorial collage",
        avoid_recent_treatment="avoid repeated dark card",
    ))


def _png():
    image = Image.new("RGB", (512, 768), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 255, 767), fill="navy")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_source_and_typographic_strategies_do_not_need_paid_generation():
    source = Image.new("RGB", (640, 800), "navy")
    source_result = await media.execute_instagram_creative_media(
        creative=_creative("source_media"), source_image=source, source_ref="candidate-1",
        opportunity_summary="story", evidence=["fact"], content_format="single",
        creative_id="creative-1", opportunity_id="opp-1", mode="live",
    )
    type_result = await media.execute_instagram_creative_media(
        creative=_creative("typographic"), source_image=None, source_ref=None,
        opportunity_summary="story", evidence=["fact"], content_format="single",
        creative_id="creative-2", opportunity_id="opp-2", mode="live",
    )
    assert source_result.status == "source_media"
    assert source_result.image is source
    assert source_result.media_ref == "candidate-1"
    assert type_result.status == "typographic"
    assert type_result.image is None


@pytest.mark.asyncio
async def test_generated_strategy_off_never_constructs_paid_adapter(monkeypatch):
    monkeypatch.setattr(media, "OpenAIImageAdapter", lambda **kwargs: pytest.fail("paid adapter constructed"))
    result = await media.execute_instagram_creative_media(
        creative=_creative("generated_media"), source_image=None, source_ref=None,
        opportunity_summary="story", evidence=["fact"], content_format="carousel",
        creative_id="creative-3", opportunity_id="opp-3", mode="off",
    )
    assert result.status == "generation_off"


@pytest.mark.asyncio
async def test_live_instagram_generation_uses_shared_budget_boundary(monkeypatch, tmp_path):
    calls = []

    class Executor:
        async def execute(self, **kwargs):
            calls.append(kwargs)
            return BudgetedImageResult(
                status="generated",
                response=ImageGenerationResponse(
                    image_bytes=_png(), provider="openai", model_used="gpt-image-2",
                    usage=CapabilityUsage(input_tokens=120, output_tokens=2733, units=1, unit_type="image"),
                    request_id="request-1",
                ),
                accounted_cost_usd=Decimal("0.04130"), cost_semantics="configured_token_estimate", attempt=1,
            )

    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: Executor())
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    result = await media.execute_instagram_creative_media(
        creative=_creative("generated_media"), source_image=None, source_ref=None,
        opportunity_summary="story", evidence=["fact"], content_format="single",
        creative_id="creative-4", opportunity_id="opp-4", mode="live",
    )
    assert result.status == "generated_media"
    assert result.media_ref.startswith("generated:images/")
    assert result.generation_cost_usd == "0.04130"
    assert len(calls) == 1
    call = calls[0]
    assert call["purpose"] == "instagram_phase_b"
    assert call["execution_id"] == "instagram:creative-4:visual:v1"
    assert call["opportunity_id"] == "opp-4"
    assert call["profile"].model == "gpt-image-2"
    assert call["profile"].size == "1024x1536"


def test_phase_b_prompt_schemas_match_strict_contracts():
    repository = FilePromptRepository(Path("prompts"))
    single = repository.resolve("instagram_creative_director_single", "6").output_schema
    carousel = repository.resolve("instagram_creative_director_carousel", "5").output_schema
    reel = repository.resolve("instagram_creative_director_reel", "7").output_schema
    assert single["properties"]["evidence_used"] == {"type": "array", "items": {"type": "string"}}
    assert "creative_execution_plan" in single["required"]
    slide = carousel["properties"]["slides"]["items"]
    assert {"slide_purpose", "media_need"} <= set(slide["required"])
    assert {"final_caption", "creative_execution_plan"} <= set(carousel["required"])
    assert "creative_execution_plan" in reel["required"]
