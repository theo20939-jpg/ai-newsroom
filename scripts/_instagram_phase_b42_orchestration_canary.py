"""Manual-only Phase B.4.2 orchestration canary. Runs each archetype through the REAL live trigger
(`services.instagram_automatic_trigger.evaluate_and_submit_instagram_opportunity`, the function
worker/content_cycle.py calls when INSTAGRAM_AUTOMATIC_GENERATION_ENABLED=true) against an isolated,
throwaway Postgres (rolled back at the end) with:

- the LLM transport FAKED (zero provider calls; response shaped like the real v6 output_schema),
- Telegram delivery replaced by a recorder (zero publication),
- the flag itself left untouched (the trigger function is invoked directly).

NEWS_RECAP uses real, already-stored story media listed in a manifest produced by a read-only
query of existing image candidates (`RECAP_MANIFEST`); NEWS_INSIGHT uses the real B.2 RAW asset;
AI_HACK / TREND_GENERATIVE use clearly-labelled local fixture images. Usage:
  python scripts/_instagram_phase_b42_orchestration_canary.py <out_dir> <recap_manifest.json>"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import scripts._instagram_phase_b4_archetype_diagnostic as diag
import services.instagram_automatic_trigger as trigger
from core.config import settings
from integrations.prompts.file_repository import FilePromptRepository
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from schemas.capability import CapabilityUsage



class RoutingFakeGateway:
    """Fake LLM transport (zero provider calls): answers the editorial-decision call and the
    carousel call, keyed on the response schema each real prompt sends."""

    def __init__(self, decision: dict, carousel: dict) -> None:
        self.decision, self.carousel = decision, carousel

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        props = (request.response_schema or {}).get("properties", {})
        out = self.decision if "opportunity_type" in props else self.carousel
        return GenerateResponse(text=None, structured_output=out, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_COMPOSED = ("full_bleed_media", "contained_media", "screenshot_ui", "collage", "split_compare")

_DECISIONS = {
    "ai_hack": dict(opportunity_type="EVERGREEN", angle_intent="HOW_TO", origin="EVERGREEN", purpose="VALUE"),
    "news_insight": dict(opportunity_type="NEWS", angle_intent="EXPLAINER", origin="NEWS", purpose="ENGAGEMENT"),
    "news_recap": dict(opportunity_type="NEWS", angle_intent="EXPLAINER", origin="NEWS", purpose="REACH"),
    "trend_generative": dict(
        opportunity_type="NEWS_X_TREND", angle_intent="MEME", origin="TREND", purpose="REACH",
        trend_rationale="Механика «ожидание и реальность» уже знакома аудитории; берём только приём, не чужой материал.",
    ),
}


def _decision(archetype: str) -> dict:
    base = {
        "source_summary": "Канареечный материал", "why_now": "Есть свежий повод", "audience_value": "Понять главное",
        "angle": "Один ясный угол", "topic": "Канарейка B.4.2", "recommended_format": "carousel",
        "format_reason": "Последовательность читается лучше одного кадра", "creative_direction": "Показать и объяснить",
        "product_connection": None, "trend_rationale": None, "trend_signal_type": None,
        "trend_signal_provenance": None, "supplementary_story_idea": None, "evidence_used": [],
    }
    base.update(_DECISIONS[archetype])
    return base


def _output_from(creative, *, evidence_used: list[str]) -> dict:
    data = creative.model_dump(mode="json")
    for slide in data["slides"]:
        if slide.get("composition") in _COMPOSED and not slide.get("media_need"):
            slide["media_need"] = "photo"
    data["evidence_used"] = evidence_used
    data["final_cta"] = data.get("final_cta")
    if data.get("creative_execution_plan"):
        # The diagnostic's plan asks for paid generated media; this canary has zero provider calls,
        # so the already-stored RAW asset is supplied as the source instead.
        data["creative_execution_plan"]["media_strategy"] = "source_media"
        for slide in data["slides"]:
            slide["media_need"] = "photo"
    data["creative_execution_plan"] = data.get("creative_execution_plan") or {
        "main_idea": "canary", "focal_point": "the subject", "media_strategy": "source_media",
        "media_rationale": "r", "composition_direction": "vary crop and hierarchy", "branding_treatment": "logo",
        "visual_treatment": "clean editorial", "avoid_recent_treatment": None,
    }
    return data


async def _run(archetype: str, session: AsyncSession, out_dir: Path, manifest: list[dict]) -> dict:
    opportunity = ContentOpportunity(
        id=f"canary-{archetype}-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()),
        news_value=1.0, audience_relevance=0.5, product_mention_allowed=False, evidence=[], confidence=0.5,
    )
    bundle = None
    source_image = None
    if archetype == "news_recap":
        storage_root = Path(settings.image_storage_root)
        stories, seen = [], set()
        for item in manifest:
            data = (storage_root / item["storage_key"]).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            i = len(stories) + 1
            stories.append(RecapStory(
                key=f"story_{i}", story_id=item["story_id"], event_id=item["event_id"], title=item["title"],
                evidence=[f"[story_{i}] {item['title']}"], image_bytes=data, source_ref=item["candidate_id"],
            ))
            if len(stories) == 4:
                break
        bundle = InstagramRecapBundle(stories=tuple(stories))
        slides = [{"role": "hook", "slide_copy": "Главное за неделю", "visual_direction": "v", "source_evidence": None,
                   "slide_purpose": "open", "media_need": None, "composition": None, "media_position": None,
                   "media_scale": None, "overlay_mode": None, "media_subject": None, "must_match_story": False}]
        positions = ["top", "top", "top", "top"]
        for i, story in enumerate(stories, start=1):
            slides.append({
                "role": "story", "slide_copy": story.title[:120], "visual_direction": "v",
                "source_evidence": story.evidence[0], "slide_purpose": f"story {i}", "media_need": "photo",
                "composition": "contained_media", "media_position": positions[i - 1], "media_scale": 0.5,
                "overlay_mode": "none", "media_subject": story.key, "must_match_story": True,
            })
        slides.append({"role": "takeaway", "slide_copy": "Это главное — остальное подождёт", "visual_direction": "v",
                       "source_evidence": None, "slide_purpose": "close", "media_need": None, "composition": None,
                       "media_position": None, "media_scale": None, "overlay_mode": None, "media_subject": None,
                       "must_match_story": False})
        output = {
            "objective": "reach", "slides": slides, "final_cta": None, "evidence_used": bundle.evidence,
            "final_caption": "Итоги недели: четыре истории, у каждой свой кадр.", "content_archetype": None,
            "creative_execution_plan": {
                "main_idea": "weekly recap", "focal_point": "each story's own image", "media_strategy": "source_media",
                "media_rationale": "each story uses its own stored image", "composition_direction": "uniform story cards",
                "branding_treatment": "logo", "visual_treatment": "clean editorial", "avoid_recent_treatment": None,
            },
        }
    else:
        creative = diag._ARCHETYPES[archetype][0]()
        output = _output_from(creative, evidence_used=[])
        if archetype == "news_insight":
            source_image = diag._load_news_insight_raw(None)
        else:
            source_image = diag._fixture((30, 30, 35), f"{archetype} fixture source")

    async def fake_source(_session, _story_id):
        if source_image is None:
            return None, None, 0, 0
        return source_image, SimpleNamespace(id=uuid4(), candidate_id=f"canary-{archetype}"), 1, 1

    captured: dict = {}
    real_render = trigger.render_instagram_carousel
    real_snapshot = trigger.build_package_snapshot

    def spy_render(pkg, **kwargs):
        results = real_render(pkg, **kwargs)
        captured["renders"] = results
        return results

    def spy_snapshot(**kwargs):
        captured["package"] = kwargs["package"]
        return real_snapshot(**kwargs)

    gateway = RoutingFakeGateway(_decision(archetype), output)
    delivery = AsyncMock(return_value=SimpleNamespace(sent=False, reason="canary_no_publication", delivery_id=None))
    trigger.render_instagram_carousel, trigger.build_package_snapshot = spy_render, spy_snapshot
    trigger._resolve_single_source_image, trigger.deliver_instagram_package = fake_source, delivery
    try:
        outcome = await trigger.evaluate_and_submit_instagram_opportunity(
            session, AsyncMock(), opportunity=opportunity, opportunity_summary="Канареечный материал",
            gateway=gateway, prompt_repository=FilePromptRepository(_PROMPTS), phase_a_enabled=True,
            recap_bundle=bundle,
        )
    finally:
        trigger.render_instagram_carousel, trigger.build_package_snapshot = real_render, real_snapshot

    target = out_dir / archetype
    target.mkdir(parents=True, exist_ok=True)
    slide_images = []
    for index, result in enumerate(captured.get("renders", []), start=1):
        image = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
        image.save(target / f"slide_{index:02d}.png")
        slide_images.append(image)
    if slide_images:
        diag._build_contact_sheet(slide_images).save(target / "contact_sheet.png")
    observability = (captured.get("package").media_plan.get("b4_observability") if captured.get("package") else None)
    record = {
        "archetype": archetype, "outcome_reason": outcome.reason, "gate_decision": outcome.gate_decision,
        "provider_calls": 0, "publication_calls": 0, "delivery_recorder_calls": delivery.await_count,
        "b4_observability": observability,
    }
    (target / "manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


async def main() -> None:
    out_dir = Path(sys.argv[1])
    manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    engine = create_async_engine(settings.test_database_url)
    summary = []
    async with engine.connect() as connection:
        await connection.begin()
        async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            for archetype in ("ai_hack", "news_insight", "news_recap", "trend_generative"):
                summary.append(await _run(archetype, session, out_dir, manifest))
        await connection.rollback()
    await engine.dispose()
    for record in summary:
        obs = record["b4_observability"] or {}
        print(json.dumps({
            "archetype": record["archetype"], "reason": record["outcome_reason"], "gate": record["gate_decision"],
            "art_passed": obs.get("art_validation_passed"), "prompt_version": obs.get("prompt_version"),
            "content_archetype": obs.get("content_archetype"), "slides": obs.get("slide_count"),
            "composition_executed": obs.get("structured_composition_executed"),
            "identities": [s.get("resolved_asset_identity") for s in obs.get("slides", [])],
            "fallback_subjects": obs.get("deliberate_fallback_subjects"), "blocking": obs.get("art_blocking_issues"),
        }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
