"""Phase B media execution at the existing Creative Director -> renderer boundary.

The Director chooses source, generated or typographic media. Paid generation is executed only
through BudgetedImageExecutor; the existing OpenAI adapter remains a low-level provider adapter.
Generated pixels never contain branding or text: current repository brand assets and audience
copy remain the deterministic renderer's responsibility.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from io import BytesIO
from typing import Any, Iterable

from PIL import Image, ImageStat

from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest
from integrations.llm_gateway.providers.openai_image_adapter import GPT_IMAGE_2, OpenAIImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from services.budgeted_image_execution import build_budgeted_image_executor
from services.image_pricing import ImageExecutionProfile


class InstagramMediaMode(str, Enum):
    SOURCE = "SOURCE"
    GENERATED = "GENERATED"
    GRAPHIC = "GRAPHIC"
    TYPOGRAPHIC = "TYPOGRAPHIC"


@dataclass(frozen=True)
class InstagramMediaExecutionAsset:
    asset_key: str
    media_mode: InstagramMediaMode
    status: str
    image: Image.Image | None
    asset_ref: str | None = None
    source_asset_ref: str | None = None
    generated_asset_ref: str | None = None
    generation_execution_id: str | None = None
    provider_request_id: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt: str | None = None
    prompt_sha256: str | None = None
    size: str | None = None
    quality: str | None = None
    reserved_cost_usd: str | None = None
    accounted_cost_usd: str | None = None
    raw_image_bytes: bytes | None = None
    composition_intent: str | None = None
    focal_subject: str | None = None
    source_treatment: str | None = None
    final_compositor_treatment: str | None = None
    # Phase B.4.2: resolver-owned, content-addressed identity of the actual pixels attached to
    # this asset (never LLM-authored) - see derive_image_identity().
    asset_identity: str | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "asset_key": self.asset_key,
            "media_mode": self.media_mode.value,
            "status": self.status,
            "asset_ref": self.asset_ref,
            "source_asset_ref": self.source_asset_ref,
            "generated_asset_ref": self.generated_asset_ref,
            "generation_execution_id": self.generation_execution_id,
            "provider_request_id": self.provider_request_id,
            "provider": self.provider,
            "model": self.model,
            "generation_prompt": self.prompt,
            "generation_prompt_sha256": self.prompt_sha256,
            "size": self.size,
            "quality": self.quality,
            "reserved_cost_usd": self.reserved_cost_usd,
            "accounted_cost_usd": self.accounted_cost_usd,
            "composition_intent": self.composition_intent,
            "focal_subject": self.focal_subject,
            "source_treatment": self.source_treatment,
            "final_compositor_treatment": self.final_compositor_treatment,
            "asset_identity": self.asset_identity,
        }


@dataclass(frozen=True)
class InstagramCreativeMediaResult:
    status: str
    image: Image.Image | None
    media_ref: str | None
    media_strategy: str
    generation_cost_usd: str | None = None
    generation_request_id: str | None = None
    assets: tuple[InstagramMediaExecutionAsset, ...] = ()

    def execution_metadata(self) -> dict[str, Any]:
        return {
            "strategy": self.media_strategy,
            "status": self.status,
            "generation_cost_usd": self.generation_cost_usd,
            "generation_request_id": self.generation_request_id,
            "assets": [asset.metadata() for asset in self.assets],
        }

    def slide_asset_identities(self) -> dict[int, str]:
        return {
            int(asset.asset_key): asset.asset_identity
            for asset in self.assets
            if asset.asset_key.isdigit() and asset.image is not None and asset.asset_identity
        }

    def slide_images(self) -> dict[int, Image.Image]:
        return {
            int(asset.asset_key): asset.image
            for asset in self.assets
            if asset.asset_key.isdigit() and asset.image is not None
        }


def derive_image_identity(image: Image.Image) -> str:
    """Content-addressed identity of the decoded pixels (resolver-owned, deterministic)."""
    digest = hashlib.sha256(f"{image.size[0]}x{image.size[1]}:{image.mode}".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class ResolvedSlideAsset:
    """A per-slide asset a real resolver already obtained (e.g. a NEWS_RECAP story's own stored
    image). `identity` is derived from the resolved bytes by that resolver, never by the model."""

    image: Image.Image
    ref: str
    identity: str


def _execution_plan(creative: Any) -> dict[str, Any]:
    plan = getattr(creative, "creative_execution_plan", None)
    return plan.model_dump() if plan is not None else {}


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


_VISUAL_PROFILE_VERSION = "instagram-reference-board-text-profile-v1"


def compile_instagram_generation_prompt(
    *,
    plan: dict[str, Any],
    opportunity_summary: str,
    evidence: list[str],
    content_format: str,
    slide: Any | None = None,
) -> str:
    """Compile approved intent into base-art instructions; exact copy and branding stay outside."""

    def value(name: str) -> str:
        if slide is None:
            return ""
        raw = slide.get(name) if isinstance(slide, dict) else getattr(slide, name, "")
        return str(raw or "")

    evidence_block = "\n".join(f"- {item}" for item in evidence)
    brief = value("generation_brief").strip()
    if brief:
        return _compile_slide_scene_prompt(
            brief=brief, plan=plan, opportunity_summary=opportunity_summary, evidence_block=evidence_block, content_format=content_format,
            family=value("visual_family"), function=value("media_function"), purpose=value("slide_purpose"),
        )
    return (
        f"VISUAL PROFILE VERSION\n{_VISUAL_PROFILE_VERSION}\n\n"
        f"SUBJECT\n{opportunity_summary}\nSupported facts only:\n{evidence_block}\n\n"
        f"CREATIVE IDEA\n{plan.get('main_idea') or opportunity_summary}\n"
        f"Slide purpose: {value('slide_purpose') or 'primary visual'}\n\n"
        f"VISUAL GENRE\n{plan.get('visual_treatment') or 'editorial conceptual visual'}\n\n"
        f"COMPOSITION\n{plan.get('composition_direction') or 'portrait composition with deliberate negative space'}\n"
        f"Per-asset direction: {value('visual_direction') or 'follow the primary composition'}\n"
        "Create foreground/background depth, one decisive focal point, and intentional negative "
        "space for typography. Do not make a presentation slide or UI card.\n\n"
        f"FOCAL SUBJECT\n{plan.get('focal_point') or opportunity_summary}\n\n"
        "CAMERA / PERSPECTIVE\nChoose a perspective that makes the focal subject dominant and "
        "stop-scroll at phone size.\n\n"
        "LIGHTING / MATERIAL / TEXTURE\nUse purposeful editorial lighting, believable depth, "
        "tactile surfaces, and controlled detail.\n\n"
        "COLOR DIRECTION\nDerive color relationships from the creative idea. Do not default to "
        "black, white and red.\n\n"
        "MOOD\nConfident, contemporary, specific, visually ambitious, never generic corporate AI art.\n\n"
        f"INSTAGRAM FORMAT\n{content_format} portrait base artwork, optimized for a 4:5 editorial "
        "composition. Keep the focal subject clear and reserve safe negative space for an exact "
        "Russian headline.\n\n"
        "REFERENCE-BOARD PRINCIPLES\nStrong focal hierarchy, cinematic/editorial/culture-led range, "
        "thoughtful density, depth, layering, image-text balance, and Instagram-native stop-scroll "
        "quality. The board's old branding is explicitly excluded.\n\n"
        "NEGATIVE CONSTRAINTS\nNO LOGOS. NO WORDMARKS. NO WATERMARKS. NO LARGE TEXT. NO READABLE "
        "TEXT. NO OUTDATED NNJ/NINJA BRANDING. NO FAKE UI. NO RANDOM INTERFACES. NO UNSUPPORTED "
        "PRODUCTS, FACTS, NUMBERS OR THIRD-PARTY MARKS. Do not bake the final headline into the "
        "image; the application adds exact Russian text and the current canonical logo after generation."
    )


_FAMILY_COMPOSITION = {
    "immersive_image_field": "a full-bleed scene with ONE large calm, low-detail area (plain wall, sky, fog, table surface or soft floor) in the upper third, kept free of detail so a headline can sit on it",
    "hero_object_stage": "ONE single object, whole and centred with generous margin, on a plain uniform studio ground (flat light grey or flat near-black); no clutter, no scene",
    "internet_culture_collage": "ONE clear subject on a simple uncluttered background, strong silhouette, easy to crop into several fragments at different scales",
}


def _compile_slide_scene_prompt(
    *, brief: str, plan: dict[str, Any], opportunity_summary: str, evidence_block: str, content_format: str,
    family: str, function: str, purpose: str,
) -> str:
    """Phase B.6: a contextual image for ONE slide, built from the approved plan's own scene brief. The image depicts the specific story concept; exact Russian copy and the
    canonical logo are added afterwards by the deterministic renderer."""
    composition = _FAMILY_COMPOSITION.get(family, "one decisive focal subject with depth and intentional negative space for a headline")
    return (
        f"VISUAL PROFILE VERSION\n{_VISUAL_PROFILE_VERSION}\n\n"
        f"STORY\n{opportunity_summary}\nSupported facts only:\n{evidence_block}\n\n"
        f"SPECIFIC SCENE TO DEPICT (approved plan for this slide)\n{brief}\n"
        f"Slide purpose: {purpose or 'primary visual'}. Media function: {function or 'hero'}.\n\n"
        f"OVERALL IDEA\n{plan.get('main_idea') or opportunity_summary}\n"
        f"Visual genre: {plan.get('visual_treatment') or 'editorial conceptual visual'}.\n\n"
        f"COMPOSITION FOR THIS SLIDE\n{composition}. Portrait 4:5 editorial framing, one decisive focal point, believable depth and material detail.\n\n"
        "SPECIFICITY\nDepict THIS story's concrete idea so the picture communicates the story before the reader reads the text. Do NOT produce a generic "
        "AI brain, glowing robot, random cyberpunk city, random laptop, hologram or corporate technology stock art unless this story is literally about it.\n\n"
        "COLOR / MOOD\nDerive colour from the idea; contemporary, specific, cinematic or editorial, never generic.\n\n"
        "NEGATIVE CONSTRAINTS\nNO LOGOS. NO WORDMARKS. NO WATERMARKS. NO LARGE TEXT. NO READABLE TEXT OR LETTERING OF ANY KIND. NO FAKE UI. NO RANDOM INTERFACES. NO "
        "UNSUPPORTED PRODUCTS, FACTS, NUMBERS OR THIRD-PARTY BRANDING. Do not bake any headline into the image; the application adds the exact Russian copy and the "
        "canonical logo after generation."
    )


def _evidence_for_slide(evidence: list[str], slide: Any | None) -> list[str]:
    """NEWS_RECAP: a story's image is generated from THAT story's evidence only ('[story_N] ...' lines), never the other stories' facts."""
    key = _slide_value(slide, "media_subject") if slide is not None else ""
    prefix = f"[{key}]"
    own = [line for line in evidence if key and line.startswith(prefix)]
    return own or list(evidence)


def _slide_value(slide: Any, name: str) -> str:
    raw = slide.get(name) if isinstance(slide, dict) else getattr(slide, name, "")
    return str(raw or "")


def _mode_for_item(*, strategy: str, slide: Any | None, index: int) -> InstagramMediaMode:
    if slide is None:
        return {
            "source_media": InstagramMediaMode.SOURCE,
            "generated_media": InstagramMediaMode.GENERATED,
            "typographic": InstagramMediaMode.TYPOGRAPHIC,
            "graphic": InstagramMediaMode.GRAPHIC,
        }.get(strategy, InstagramMediaMode.TYPOGRAPHIC)
    declared = _slide_value(slide, "media_source")
    if declared in {"source", "generated", "graphic"}:
        # Phase B.6 media-first: the plan states the slide's visual source explicitly. A media_need such as "minimal" or "text" can never turn it typographic.
        return {"source": InstagramMediaMode.SOURCE, "generated": InstagramMediaMode.GENERATED, "graphic": InstagramMediaMode.GRAPHIC}[declared]
    if getattr(slide, "must_match_story", False) and getattr(slide, "media_subject", None):
        return InstagramMediaMode.SOURCE  # the plan demands this story's own real asset
    need = _slide_value(slide, "media_need").lower()
    if any(token in need for token in ("исход", "source", "фото", "photo")):
        return InstagramMediaMode.SOURCE
    if any(token in need for token in ("граф", "diagram", "схем")):
        return InstagramMediaMode.GRAPHIC
    if any(token in need for token in ("типограф", "typograph", "минималь", "text")):
        return InstagramMediaMode.TYPOGRAPHIC
    if any(token in need for token in ("генер", "generated", "original visual", "ai visual")):
        return InstagramMediaMode.GENERATED
    if strategy == "generated_media":
        return InstagramMediaMode.GENERATED
    if strategy == "source_media" and index == 0:
        return InstagramMediaMode.SOURCE
    return InstagramMediaMode.TYPOGRAPHIC


def _execution_items(
    creative: Any, *, strategy: str, content_format: str,
) -> list[tuple[str, InstagramMediaMode, Any | None]]:
    if content_format != "carousel":
        return [("primary", _mode_for_item(strategy=strategy, slide=None, index=0), None)]
    slides: Iterable[Any] = getattr(creative, "slides", ()) or ()
    items = [
        (str(index), _mode_for_item(strategy=strategy, slide=slide, index=index), slide)
        for index, slide in enumerate(slides)
    ]
    return items or [("0", _mode_for_item(strategy=strategy, slide=None, index=0), None)]


async def _execute_generated_asset(
    *,
    asset_key: str,
    slide: Any | None,
    plan: dict[str, Any],
    opportunity_summary: str,
    evidence: list[str],
    content_format: str,
    creative_id: str,
    opportunity_id: str,
    effective_mode: str,
) -> InstagramMediaExecutionAsset:
    prompt = compile_instagram_generation_prompt(
        plan=plan,
        opportunity_summary=opportunity_summary,
        evidence=evidence,
        content_format=content_format,
        slide=slide,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    execution_id = f"instagram:{creative_id}:visual:{asset_key}:v2"
    profile = ImageExecutionProfile(
        provider="openai",
        model=GPT_IMAGE_2,
        quality="medium",
        size="1024x1536",
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
    )
    base = dict(
        asset_key=asset_key,
        media_mode=InstagramMediaMode.GENERATED,
        generation_execution_id=execution_id,
        provider="openai",
        model=GPT_IMAGE_2,
        prompt=prompt,
        prompt_sha256=prompt_hash,
        size="1024x1536",
        quality="medium",
        composition_intent=str(plan.get("composition_direction") or ""),
        focal_subject=str(plan.get("focal_point") or ""),
        source_treatment="generated_base_art",
        final_compositor_treatment="exact_russian_typography_canonical_logo_safe_zones",
    )
    if effective_mode == "off":
        return InstagramMediaExecutionAsset(status="generation_off", image=None, **base)
    if settings.openai_api_key is None:
        return InstagramMediaExecutionAsset(status="provider_not_configured", image=None, **base)

    request = ImageGenerationRequest(
        prompt=prompt,
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
        preferred_provider="openai",
        preferred_model=GPT_IMAGE_2,
        target_aspect_ratio="2:3",
        target_width=1024,
        target_height=1536,
        metadata={
            "purpose": "instagram_phase_b2",
            "opportunity_id": opportunity_id,
            "asset_key": asset_key,
            "prompt_sha256": prompt_hash,
        },
    )
    adapter = OpenAIImageAdapter(
        api_key=settings.openai_api_key.get_secret_value(),
        quality="medium",
        text_to_image_size="1024x1536",  # type: ignore[arg-type]
    )
    result = await build_budgeted_image_executor().execute(
        gateway=adapter,
        request=request,
        profile=profile,
        mode=effective_mode,  # type: ignore[arg-type]
        purpose="instagram_phase_b2",
        execution_id=execution_id,
        creative_id=f"instagram:{creative_id}",
        package_id=creative_id,
        opportunity_id=opportunity_id,
        max_attempts=1,
    )
    reserved = str(result.quote.worst_case_cost_usd) if result.quote is not None else None
    accounted = str(result.accounted_cost_usd) if result.accounted_cost_usd is not None else None
    if result.status != "generated" or result.response is None:
        return InstagramMediaExecutionAsset(
            status=f"generation_{result.status}",
            image=None,
            reserved_cost_usd=reserved,
            accounted_cost_usd=accounted,
            **base,
        )

    raw_bytes = result.response.image_bytes
    image = _decode_publishable_image(raw_bytes)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    stored = LocalImageStorage(settings.image_storage_root).store_validated_image(
        raw_bytes,
        sha256=digest,
        image_format="PNG",
        max_bytes=settings.instagram_generated_image_max_bytes,
    )
    generated_ref = f"generated:{stored.storage_key}"
    return InstagramMediaExecutionAsset(
        status="generated_media",
        image=image,
        asset_ref=generated_ref,
        generated_asset_ref=generated_ref,
        provider_request_id=result.response.request_id,
        reserved_cost_usd=reserved,
        accounted_cost_usd=accounted,
        raw_image_bytes=raw_bytes,
        **base,
    )


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
    slide_assets: dict[int, ResolvedSlideAsset] | None = None,
) -> InstagramCreativeMediaResult:
    """Execute explicit SOURCE/GENERATED/GRAPHIC/TYPOGRAPHIC assets, per slide when applicable."""
    plan = _execution_plan(creative)
    strategy = str(
        plan.get("media_strategy")
        or ("source_media" if content_format == "single" else "typographic")
    )
    if strategy not in {"source_media", "generated_media", "typographic", "graphic"}:
        return InstagramCreativeMediaResult(
            status="unknown_media_strategy",
            image=None,
            media_ref=None,
            media_strategy=strategy,
        )

    effective_mode = mode or settings.instagram_image_generation_mode
    assets: list[InstagramMediaExecutionAsset] = []
    for asset_key, media_mode, slide in _execution_items(
        creative, strategy=strategy, content_format=content_format,
    ):
        common = dict(
            asset_key=asset_key,
            media_mode=media_mode,
            composition_intent=(
                _slide_value(slide, "visual_direction")
                if slide is not None
                else str(plan.get("composition_direction") or "")
            ),
            focal_subject=str(plan.get("focal_point") or ""),
        )
        if media_mode is InstagramMediaMode.GENERATED and _slide_value(slide, "media_source") == "generated":
            assets.append(await _execute_generated_asset(
                asset_key=asset_key, slide=slide, plan=plan, opportunity_summary=opportunity_summary, evidence=_evidence_for_slide(evidence, slide),
                content_format=content_format, creative_id=creative_id, opportunity_id=opportunity_id, effective_mode=effective_mode,
            ))
        elif slide_assets is not None:
            # NEWS_RECAP: each slide may only consume ITS OWN resolved story asset; a slide with
            # none gets a deliberate graphic fallback - never another story's (or a shared) image.
            resolved = slide_assets.get(int(asset_key)) if asset_key.isdigit() else None
            if resolved is None:
                assets.append(InstagramMediaExecutionAsset(
                    status="graphic", image=None,
                    final_compositor_treatment="deliberate_no_media_graphic_fallback",
                    **{**common, "media_mode": InstagramMediaMode.GRAPHIC},
                ))
            else:
                assets.append(InstagramMediaExecutionAsset(
                    status="source_media", image=resolved.image, asset_ref=resolved.ref,
                    source_asset_ref=resolved.ref, source_treatment="recap_story_own_asset",
                    final_compositor_treatment="exact_russian_typography_canonical_logo_safe_zones",
                    asset_identity=resolved.identity, **common,
                ))
        elif media_mode is InstagramMediaMode.SOURCE:
            if source_image is None or source_ref is None:
                missing_status = "source_media_unavailable" if plan else "source_image_unavailable"
                assets.append(InstagramMediaExecutionAsset(
                    status=missing_status, image=None, **common,
                ))
            else:
                assets.append(InstagramMediaExecutionAsset(
                    status="source_media",
                    image=source_image,
                    asset_ref=source_ref,
                    source_asset_ref=source_ref,
                    source_treatment="creative_plan_selected_source",
                    final_compositor_treatment="exact_russian_typography_canonical_logo_safe_zones",
                    asset_identity=derive_image_identity(source_image),
                    **common,
                ))
        elif media_mode is InstagramMediaMode.GENERATED:
            assets.append(await _execute_generated_asset(
                asset_key=asset_key,
                slide=slide,
                plan=plan,
                opportunity_summary=opportunity_summary,
                evidence=evidence,
                content_format=content_format,
                creative_id=creative_id,
                opportunity_id=opportunity_id,
                effective_mode=effective_mode,
            ))
        else:
            assets.append(InstagramMediaExecutionAsset(
                status=media_mode.value.lower(),
                image=None,
                final_compositor_treatment=(
                    "deterministic_graphic_primitives"
                    if media_mode is InstagramMediaMode.GRAPHIC
                    else "deterministic_typography_canonical_logo_safe_zones"
                ),
                **common,
            ))

    assets = [
        replace(a, asset_identity=derive_image_identity(a.image)) if a.image is not None and not a.asset_identity else a
        for a in assets
    ]
    blocking_statuses = {
        "source_image_unavailable",
        "source_media_unavailable",
        "generation_off",
        "provider_not_configured",
        "generation_dry_run",
        "generation_duplicate",
        "generation_attempt_limit",
    }
    failure = next((asset for asset in assets if asset.status in blocking_statuses), None)
    first_image = next((asset for asset in assets if asset.image is not None), None)
    first_generated = next((
        asset for asset in assets if asset.media_mode is InstagramMediaMode.GENERATED
    ), None)
    if failure is not None:
        status = failure.status
    elif len(assets) == 1:
        status = assets[0].status
    else:
        status = "media_plan_ready"
    return InstagramCreativeMediaResult(
        status=status,
        image=first_image.image if first_image else None,
        media_ref=first_image.asset_ref if first_image else None,
        media_strategy=strategy,
        generation_cost_usd=first_generated.accounted_cost_usd if first_generated else None,
        generation_request_id=first_generated.provider_request_id if first_generated else None,
        assets=tuple(assets),
    )
