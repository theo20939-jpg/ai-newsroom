"""Phase B media execution at the existing Creative Director -> renderer boundary.

The Director chooses source, generated or typographic media. Paid generation is executed only
through BudgetedImageExecutor; the existing OpenAI adapter remains a low-level provider adapter.
Generated pixels never contain branding or text: current repository brand assets and audience
copy remain the deterministic renderer's responsibility.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, ImageStat

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest
from integrations.llm_gateway.providers.openai_image_adapter import GPT_IMAGE_2, OpenAIImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from services.budgeted_image_execution import build_budgeted_image_executor
from services.image_pricing import ImageExecutionProfile


@dataclass(frozen=True)
class InstagramCreativeMediaResult:
    status: str
    image: Image.Image | None
    media_ref: str | None
    media_strategy: str
    generation_cost_usd: str | None = None
    generation_request_id: str | None = None


def _execution_plan(creative: Any) -> dict[str, Any]:
    plan = getattr(creative, "creative_execution_plan", None)
    return plan.model_dump() if plan is not None else {}


def _generation_prompt(
    *, plan: dict[str, Any], opportunity_summary: str, evidence: list[str], content_format: str,
) -> str:
    evidence_block = "\n".join(f"- {item}" for item in evidence)
    return (
        "Create a professional Instagram editorial base visual for NINJA.\n"
        f"FORMAT: {content_format} portrait composition.\n"
        f"STORY: {opportunity_summary}\n"
        f"MAIN IDEA: {plan.get('main_idea')}\n"
        f"FOCAL POINT: {plan.get('focal_point')}\n"
        f"COMPOSITION: {plan.get('composition_direction')}\n"
        f"VISUAL TREATMENT: {plan.get('visual_treatment')}\n"
        f"FACTUAL EVIDENCE:\n{evidence_block}\n"
        "Quality direction: stop-scroll, Instagram-native, editorially specific, strong focal "
        "point, deliberate negative space, professional photography/collage/product treatment. "
        "Do not default to a generic dark futuristic AI background. Do not invent products, "
        "interfaces, facts, numbers or third-party marks not supported above. CRITICAL: create "
        "base art only. No logo, no wordmark, no watermark, no readable text, no typography. "
        "The application will add current canonical NINJA branding and copy after generation."
    )


def _decode_publishable_image(data: bytes) -> Image.Image:
    if len(data) > settings.instagram_generated_image_max_bytes:
        raise ValueError("generated image exceeds configured byte limit")
    with Image.open(BytesIO(data)) as probe:
        probe.verify()
    with Image.open(BytesIO(data)) as decoded:
        image = decoded.convert("RGB")
    if min(image.size) < 512:
        raise ValueError("generated image dimensions are too small")
    grayscale = image.convert("L").resize((64, 64))
    if ImageStat.Stat(grayscale).stddev[0] < 2.0:
        raise ValueError("generated image is blank or near-blank")
    return image


async def execute_instagram_creative_media(
    *,
    creative: Any,
    source_image: Image.Image | None,
    source_ref: str | None,
    opportunity_summary: str,
    evidence: list[str],
    content_format: str,
    creative_id: str,
    opportunity_id: str,
    mode: str | None = None,
) -> InstagramCreativeMediaResult:
    plan = _execution_plan(creative)
    strategy = str(
        plan.get("media_strategy")
        or ("source_media" if content_format == "single" else "typographic")
    )

    if strategy == "source_media":
        if source_image is None or source_ref is None:
            missing_status = (
                "source_media_unavailable" if plan else "source_image_unavailable"
            )
            return InstagramCreativeMediaResult(
                status=missing_status, image=None, media_ref=None,
                media_strategy=strategy,
            )
        return InstagramCreativeMediaResult(
            status="source_media", image=source_image, media_ref=source_ref,
            media_strategy=strategy,
        )

    if strategy == "typographic":
        return InstagramCreativeMediaResult(
            status="typographic", image=None, media_ref=None, media_strategy=strategy,
        )

    if strategy != "generated_media":
        return InstagramCreativeMediaResult(
            status="unknown_media_strategy", image=None, media_ref=None,
            media_strategy=strategy,
        )

    effective_mode = mode or settings.instagram_image_generation_mode
    if effective_mode == "off":
        return InstagramCreativeMediaResult(
            status="generation_off", image=None, media_ref=None, media_strategy=strategy,
        )
    if settings.openai_api_key is None:
        return InstagramCreativeMediaResult(
            status="provider_not_configured", image=None, media_ref=None,
            media_strategy=strategy,
        )

    request = ImageGenerationRequest(
        prompt=_generation_prompt(
            plan=plan, opportunity_summary=opportunity_summary, evidence=evidence,
            content_format=content_format,
        ),
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
        preferred_provider="openai",
        preferred_model=GPT_IMAGE_2,
        target_aspect_ratio="2:3",
        target_width=1024,
        target_height=1536,
        metadata={"purpose": "instagram_phase_b", "opportunity_id": opportunity_id},
    )
    adapter = OpenAIImageAdapter(
        api_key=settings.openai_api_key.get_secret_value(),
        quality="medium",
        text_to_image_size="1024x1536",  # type: ignore[arg-type]
    )
    profile = ImageExecutionProfile(
        provider="openai", model=GPT_IMAGE_2, quality="medium", size="1024x1536",
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
    )
    result = await build_budgeted_image_executor().execute(
        gateway=adapter,
        request=request,
        profile=profile,
        mode=effective_mode,  # type: ignore[arg-type]
        purpose="instagram_phase_b",
        execution_id=f"instagram:{creative_id}:visual:v1",
        creative_id=f"instagram:{creative_id}",
        opportunity_id=opportunity_id,
        max_attempts=settings.instagram_image_generation_max_attempts,
    )
    if result.status != "generated" or result.response is None:
        return InstagramCreativeMediaResult(
            status=f"generation_{result.status}", image=None, media_ref=None,
            media_strategy=strategy,
            generation_cost_usd=str(result.accounted_cost_usd) if result.accounted_cost_usd is not None else None,
        )

    image = _decode_publishable_image(result.response.image_bytes)
    digest = hashlib.sha256(result.response.image_bytes).hexdigest()
    stored = LocalImageStorage(settings.image_storage_root).store_validated_image(
        result.response.image_bytes,
        sha256=digest,
        image_format="PNG",
        max_bytes=settings.instagram_generated_image_max_bytes,
    )
    return InstagramCreativeMediaResult(
        status="generated_media",
        image=image,
        media_ref=f"generated:{stored.storage_key}",
        media_strategy=strategy,
        generation_cost_usd=str(result.accounted_cost_usd),
        generation_request_id=result.response.request_id,
    )
