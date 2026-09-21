"""Phase B.4.2: production-orchestration closure. Drives the REAL live trigger
(`services.instagram_automatic_trigger.evaluate_and_submit_instagram_opportunity`) - the function
`worker/content_cycle.py` calls when INSTAGRAM_AUTOMATIC_GENERATION_ENABLED=true - with only the LLM
transport faked, the real v6 prompt file, and a real Postgres session for the DB-backed tests. The
automatic-generation flag itself stays false; the trigger function is invoked directly."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import services.instagram_automatic_trigger as trigger
import services.instagram_creative_plan_service as plan_service
from database.models.instagram_creative_plan import InstagramCreativeDraft
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramCarouselCreative, InstagramCreativeExecutionPlan
from schemas.instagram_creative import InstagramCarouselSlideCreative as Slide
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_creative_director import (
    CAROUSEL_PROMPT_VERSION,
    CreativeDirectorInput,
    _build_user_text,
    _parse_editorial_decision,
    derive_content_archetype,
)
from services.instagram_creative_media import ResolvedSlideAsset, derive_image_identity, execute_instagram_creative_media
from services.instagram_creative_plan_service import (
    RecentCarouselFingerprint,
    build_carousel_fatigue_note,
    create_creative_draft,
    create_creative_plan,
    fetch_recent_carousel_fingerprints,
    record_creative_draft,
)
from services.instagram_platform_renderer import derive_asset_identity
from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory, build_instagram_recap_bundle
import services.instagram_recap_bundle as bundle_module

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_EVIDENCE = "confirmed feature: NINJA drafts Instagram carousels on its own"

_DECISION = {
    "source_summary": "NINJA drafts carousels", "opportunity_type": "NEWS", "why_now": "Функция только что вышла",
    "audience_value": "Понять, что изменилось", "angle": "Как это работает изнутри", "angle_intent": "EXPLAINER",
    "topic": "carousel autonomy", "purpose": "ENGAGEMENT", "origin": "NEWS", "recommended_format": "carousel",
    "format_reason": "Последовательность читается лучше одного кадра", "creative_direction": "Показать, объяснить, пригласить",
    "product_connection": None, "trend_rationale": None, "trend_signal_type": None,
    "trend_signal_provenance": None, "supplementary_story_idea": None, "evidence_used": [],
}


def _png(color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (1200, 1500), color)
    ImageDraw.Draw(img).rectangle([600, 800, 1200, 1500], fill=(230, 40, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _slide(role: str, copy: str, purpose: str, **b4) -> dict:
    base = {
        "role": role, "slide_copy": copy, "visual_direction": "v", "source_evidence": None, "slide_purpose": purpose,
        "media_need": None, "composition": None, "media_position": None, "media_scale": None,
        "media_subject": None, "must_match_story": False,
    }
    base.update(b4)
    return base


def _carousel_output(slides: list[dict], evidence_used: list[str], *, strategy: str = "source_media") -> dict:
    return {
        "objective": "saves", "slides": slides, "final_cta": "Смотри в профиле", "evidence_used": evidence_used,
        "final_caption": "Готовая подпись для карусели на русском языке.", "content_archetype": "ai_hack",
        "creative_execution_plan": {
            "main_idea": "idea", "focal_point": "the subject", "media_strategy": strategy, "media_rationale": "r",
            "composition_direction": "vary", "branding_treatment": "logo", "visual_treatment": "clean",
            "avoid_recent_treatment": None,
        },
    }


class RoutingFakeGateway:
    """Answers the editorial-decision call and the carousel call the way the real gateway would,
    keyed on the response schema each real prompt sends."""

    def __init__(self, carousel: dict) -> None:
        self.carousel = carousel
        self.requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        props = (request.response_schema or {}).get("properties", {})
        out = _DECISION if "opportunity_type" in props else self.carousel
        return GenerateResponse(text=None, structured_output=out, finish_reason="stop", model_used="fake", usage=CapabilityUsage())

    def carousel_request(self) -> GenerateRequest:
        return next(r for r in self.requests if "slides" in (r.response_schema or {}).get("properties", {}))


def _user_text(request: GenerateRequest) -> str:
    return request.messages[1].content[0].text


def _news_output() -> dict:
    return _carousel_output(
        [
            _slide("hook", "Ты это видел?", "stop the scroll", media_need="hero photo"),
            _slide(
                "context", "Вот что теперь умеет NINJA", "explain", source_evidence=_EVIDENCE, media_need="photo",
                composition="contained_media", media_position="left", media_scale=0.5,
            ),
            _slide("takeaway", "Смотри сам в профиле", "close"),
        ],
        [_EVIDENCE],
    )


def _patch_delivery(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}
    real_snapshot = trigger.build_package_snapshot

    def spy_snapshot(**kwargs):
        captured["package"] = kwargs["package"]
        captured["director_input"] = kwargs["director_input"]
        return real_snapshot(**kwargs)

    monkeypatch.setattr(trigger, "build_package_snapshot", spy_snapshot)
    monkeypatch.setattr(
        trigger, "deliver_instagram_package",
        AsyncMock(return_value=SimpleNamespace(sent=False, reason="test", delivery_id=None)),
    )
    return captured


# ---------------------------------------------------------------------------
# No-DB proofs
# ---------------------------------------------------------------------------


def test_live_editorial_decision_payload_with_bookkeeping_keys_still_derives_archetype() -> None:
    """The live trigger stores the decision plus extra keys (duplication_decision, ...) - the strict
    model used to reject that, silently leaving content_archetype unset in production."""
    import json

    live = {**_DECISION, "duplication_decision": "ALLOW", "recent_history_count": 2, "output_language": "ru"}
    decision = _parse_editorial_decision(json.dumps(live))
    assert decision is not None
    assert derive_content_archetype(decision) == "news_insight"


def test_fatigue_note_and_recap_keys_reach_the_prompt_input() -> None:
    text = _build_user_text(CreativeDirectorInput(
        objective="saves", format="carousel", opportunity_summary="s",
        fatigue_note="composition 'contained_media' used 6x", recap_subjects=["story_1", "story_2"],
    ))
    assert "CREATIVE FATIGUE NOTE: composition 'contained_media' used 6x" in text
    assert "story_1, story_2" in text
    plain = _build_user_text(CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s"))
    assert "RECAP STORY KEYS" not in plain


class _FakeBundleSession:
    def __init__(self, titles: dict) -> None:
        self.titles = titles

    async def get(self, _model, event_id):
        return SimpleNamespace(id=event_id, title=self.titles[event_id])

    async def scalar(self, _stmt):
        return None


@pytest.mark.asyncio
async def test_recap_bundle_bridge_gives_each_story_its_own_media_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [SimpleNamespace(story_id=uuid4(), representative_event_id=uuid4()) for _ in range(4)]
    titles = {c.representative_event_id: f"Story {i}" for i, c in enumerate(candidates, 1)}
    pixels = {candidates[0].representative_event_id: _png((10, 20, 30)), candidates[1].representative_event_id: _png((90, 20, 30)),
              candidates[2].representative_event_id: _png((10, 120, 30))}

    async def fake_candidates(session, *, news_event_id, limit):
        return [SimpleNamespace(id=uuid4(), candidate_id=f"cand-{news_event_id}", is_expired=False, event=news_event_id)] if news_event_id in pixels else []

    monkeypatch.setattr(bundle_module, "get_editorial_image_candidates", fake_candidates)
    monkeypatch.setattr(bundle_module, "read_candidate_bytes", lambda c: pixels[c.event])

    bundle = await build_instagram_recap_bundle(_FakeBundleSession(titles), selected=candidates)
    assert bundle is not None and bundle.subjects == ["story_1", "story_2", "story_3", "story_4"]
    assert set(bundle.available_assets) == {"story_1", "story_2", "story_3"}  # story_4 has no media
    assert len({derive_asset_identity(b) for b in bundle.available_assets.values()}) == 3
    assert bundle.evidence[0] == "[story_1] Story 1"
    assert await build_instagram_recap_bundle(_FakeBundleSession(titles), selected=candidates[:3]) is None


@pytest.mark.asyncio
async def test_recap_bundle_preserves_editorial_order_even_when_only_the_last_story_has_media(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [SimpleNamespace(story_id=uuid4(), representative_event_id=uuid4()) for _ in range(5)]
    titles = {c.representative_event_id: f"Story {i}" for i, c in enumerate(candidates, 1)}
    last = candidates[-1].representative_event_id

    async def fake_candidates(session, *, news_event_id, limit):
        return [SimpleNamespace(id=uuid4(), candidate_id="c", is_expired=False)] if news_event_id == last else []

    monkeypatch.setattr(bundle_module, "get_editorial_image_candidates", fake_candidates)
    monkeypatch.setattr(bundle_module, "read_candidate_bytes", lambda c: _png((1, 2, 3)))
    bundle = await build_instagram_recap_bundle(_FakeBundleSession(titles), selected=candidates)
    assert bundle is not None
    assert [s.title for s in bundle.stories] == [f"Story {i}" for i in range(1, 6)]  # selection order untouched
    assert set(bundle.available_assets) == {"story_5"}  # media adapts afterward; it never re-ranks


@pytest.mark.asyncio
async def test_media_executor_never_shares_a_story_asset_and_falls_back_per_story() -> None:
    slides = [
        Slide(role="hook", slide_copy="Hook", visual_direction="v", slide_purpose="a"),
        Slide(role="story", slide_copy="A", visual_direction="v", slide_purpose="b", media_subject="story_1", must_match_story=True),
        Slide(role="story", slide_copy="B", visual_direction="v", slide_purpose="c", media_subject="story_2", must_match_story=True),
        Slide(role="takeaway", slide_copy="End", visual_direction="v", slide_purpose="d"),
    ]
    creative = InstagramCarouselCreative(
        objective="saves", slides=slides, final_caption="Подпись",
        creative_execution_plan=InstagramCreativeExecutionPlan(
            main_idea="i", focal_point="f", media_strategy="source_media", media_rationale="r",
            composition_direction="c", branding_treatment="b", visual_treatment="v",
        ),
    )
    image = Image.open(io.BytesIO(_png((5, 5, 5)))).convert("RGB")
    result = await execute_instagram_creative_media(
        creative=creative, source_image=None, source_ref=None, opportunity_summary="s", evidence=[],
        content_format="carousel", creative_id="c", opportunity_id="o",
        slide_assets={1: ResolvedSlideAsset(image, "ref-a", derive_image_identity(image))},
    )
    assert set(result.slide_images()) == {1}  # slide 2 (no asset) got a graphic fallback, not slide 1's image
    assert set(result.slide_asset_identities()) == {1}
    statuses = {a.asset_key: a.status for a in result.assets}
    assert statuses["2"] == "graphic" and statuses["1"] == "source_media"


# ---------------------------------------------------------------------------
# DB-backed cross-post repetition proofs (A-G)
# ---------------------------------------------------------------------------


def _payload(composition: str | None, archetype: str | None = "news_insight") -> dict:
    return {
        "slides": [
            {"role": "hook", "slide_copy": "h", "visual_direction": "v", "composition": None, "overlay_mode": None},
            {"role": "takeaway", "slide_copy": "t", "visual_direction": "v", "composition": composition,
             "overlay_mode": "subtle" if composition else None},
        ],
        "content_archetype": archetype,
    }


async def _draft(session: AsyncSession, payload: dict, *, fmt: str = "carousel", when: datetime | None = None):
    plan = await create_creative_plan(session, content_opportunity_id=f"opp-{uuid4()}", objective="saves", format=fmt)
    return await create_creative_draft(
        session, creative_plan_id=plan.id, format=fmt, payload=payload, generated_at=when or datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_A_B_C_valid_fingerprints_read_legacy_skipped_archetypes_counted(db_session: AsyncSession) -> None:
    await _draft(db_session, _payload("contained_media"))
    await _draft(db_session, _payload("contained_media"))
    await _draft(db_session, _payload("split_compare", archetype="trend_generative"))
    await _draft(db_session, {"slides": [{"role": "hook", "slide_copy": "h", "visual_direction": "v"}]})  # legacy
    await _draft(db_session, {"hook": "reel"}, fmt="reel")
    fingerprints = await fetch_recent_carousel_fingerprints(db_session)
    assert len(fingerprints) == 3  # legacy + reel ignored, nothing fabricated
    assert sorted(fp.content_archetype for fp in fingerprints) == ["news_insight", "news_insight", "trend_generative"]
    assert sorted(c for fp in fingerprints for c in fp.compositions) == ["contained_media", "contained_media", "split_compare"]


@pytest.mark.asyncio
async def test_D_evaluate_fatigue_state_is_the_function_actually_used(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []
    real = plan_service.evaluate_fatigue_state

    def spy(*, dimension, repetition_count, window_days):
        calls.append((dimension, repetition_count))
        return real(dimension=dimension, repetition_count=repetition_count, window_days=window_days)

    monkeypatch.setattr(plan_service, "evaluate_fatigue_state", spy)
    for _ in range(6):
        await _draft(db_session, _payload("contained_media"))
    note = build_carousel_fatigue_note(await fetch_recent_carousel_fingerprints(db_session))
    assert ("composition", 6) in calls and ("content_archetype", 6) in calls
    assert "fatigued" in note


@pytest.mark.asyncio
async def test_F_draft_history_is_repetition_only_never_performance(db_session: AsyncSession) -> None:
    await _draft(db_session, _payload("contained_media"))
    fp = (await fetch_recent_carousel_fingerprints(db_session))[0]
    assert set(RecentCarouselFingerprint.__dataclass_fields__) == {
        "draft_id", "generated_at", "content_archetype", "compositions", "layout_traits",
    }
    note = build_carousel_fatigue_note([fp] * 6).lower()
    assert not any(word in note for word in ("perform", "winner", "success", "engagement", "best"))
    assert "avoid unless this content genuinely calls for it" in note  # advisory, content fit wins


@pytest.mark.asyncio
async def test_G_query_is_bounded_and_deterministic(db_session: AsyncSession) -> None:
    same_moment = datetime.now(timezone.utc)
    for _ in range(5):
        await _draft(db_session, _payload("contained_media"), when=same_moment)
    await _draft(db_session, _payload("split_compare"), when=same_moment - timedelta(days=30))
    limited = await fetch_recent_carousel_fingerprints(db_session, limit=3)
    assert len(limited) == 3
    everything = await fetch_recent_carousel_fingerprints(db_session, window_days=14)
    assert len(everything) == 5 and all(fp.compositions == ("contained_media",) for fp in everything)  # 30-day-old excluded
    again = await fetch_recent_carousel_fingerprints(db_session, window_days=14)
    assert [fp.draft_id for fp in everything] == [fp.draft_id for fp in again]
    assert [fp.draft_id for fp in everything] == sorted((fp.draft_id for fp in everything), reverse=True)  # id tie-break


# ---------------------------------------------------------------------------
# The REAL live trigger, LLM transport faked
# ---------------------------------------------------------------------------


def _news_opportunity() -> ContentOpportunity:
    return ContentOpportunity(
        id=f"opp-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()),
        news_value=1.0, audience_relevance=0.5, product_mention_allowed=False, evidence=[_EVIDENCE], confidence=0.5,
    )


@pytest.mark.asyncio
async def test_E_live_trigger_uses_v6_archetype_structured_composition_fatigue_and_records_draft(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(6):
        await record_creative_draft(
            db_session, content_opportunity_id="hist", objective="saves", format="carousel", payload=_payload("contained_media"),
        )
    source = Image.open(io.BytesIO(_png((40, 70, 120)))).convert("RGB")

    async def fake_source(session, story_id):
        return source, SimpleNamespace(id=uuid4(), candidate_id="cand-live"), 1, 100

    monkeypatch.setattr(trigger, "_resolve_single_source_image", fake_source)
    captured = _patch_delivery(monkeypatch)
    gateway = RoutingFakeGateway(_news_output())

    outcome = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, AsyncMock(), opportunity=_news_opportunity(), opportunity_summary="NINJA drafts carousels",
        gateway=gateway, prompt_repository=FilePromptRepository(_PROMPTS_ROOT), phase_a_enabled=True,
    )
    assert outcome.accepted is True and outcome.reason == "submitted", outcome.reason

    request = gateway.carousel_request()
    assert "content_archetype" in request.response_schema["properties"]  # real v6 contract was sent
    assert "CREATIVE FATIGUE NOTE: composition 'contained_media' appeared in 6 of the last 14d posts" in _user_text(request)
    assert "CONTENT ARCHETYPE (derived, plan for it): news_insight" in _user_text(request)
    assert "MEDIA AVAILABLE FOR THIS POST" in _user_text(request) and "subject key 'source'" in _user_text(request)
    assert "fatigued" in captured["director_input"].fatigue_note

    observability = captured["package"].media_plan["b4_observability"]
    assert observability["prompt_version"] == CAROUSEL_PROMPT_VERSION == "9.1"
    assert observability["content_archetype"] == "news_insight"  # derived, not the model's stale "ai_hack"
    assert observability["structured_composition_present"] is True
    assert observability["structured_composition_executed"] is True
    assert observability["slide_count"] == 3
    assert observability["overlay_operations_executed_total"] == 0
    assert all("overlay_mode" not in slide for slide in captured["package"].media_plan["slides"])
    assert observability["slides"][1]["role_fallback_used"] is False and observability["slides"][0]["role_fallback_used"] is True
    assert observability["art_validation_passed"] is True, observability["art_blocking_issues"]
    assert captured["package"].media_plan["slides"][1]["composition"] == "contained_media"  # fatigue advisory: fit still wins

    drafts = (await db_session.execute(select(InstagramCreativeDraft))).scalars().all()
    assert len(drafts) == 7 and any(d.payload.get("slides", [{}, {}])[1].get("media_position") == "left" for d in drafts)


@pytest.mark.asyncio
async def test_live_trigger_news_recap_gives_each_story_its_own_asset_and_a_deliberate_fallback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    colors = [(10, 20, 30), (90, 20, 30), (10, 120, 30)]
    stories = tuple(
        RecapStory(
            key=f"story_{i}", story_id=str(uuid4()), event_id=str(uuid4()), title=f"Story {i}",
            evidence=[f"[story_{i}] Story {i}"], image_bytes=_png(colors[i - 1]) if i <= 3 else None,
            source_ref=f"ref-{i}" if i <= 3 else None,
        )
        for i in range(1, 5)
    )
    bundle = InstagramRecapBundle(stories=stories)
    slides = [_slide("hook", "Итоги недели", "open")]
    for i in range(1, 5):
        slides.append(_slide(
            "story", f"Новость номер {i}", f"story {i}", source_evidence=f"[story_{i}] Story {i}", media_need="photo",
            composition="contained_media", media_position="top", media_scale=0.5,
            media_subject=f"story_{i}", must_match_story=True,
        ))
    slides.append(_slide("takeaway", "Это главное за неделю", "close"))
    gateway = RoutingFakeGateway(_carousel_output(slides, bundle.evidence))
    captured = _patch_delivery(monkeypatch)

    outcome = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, AsyncMock(), opportunity=_news_opportunity(), opportunity_summary="Итоги недели",
        gateway=gateway, prompt_repository=FilePromptRepository(_PROMPTS_ROOT), phase_a_enabled=True, recap_bundle=bundle,
    )
    assert outcome.accepted is True and outcome.reason == "submitted", outcome.reason
    assert "story_1, story_2, story_3, story_4" in _user_text(gateway.carousel_request())

    observability = captured["package"].media_plan["b4_observability"]
    assert observability["content_archetype"] == "news_recap"
    by_index = {s["index"]: s for s in observability["slides"]}
    identities = [by_index[i]["resolved_asset_identity"] for i in (1, 2, 3)]
    assert identities == [derive_asset_identity(_png(c)) for c in colors]  # resolver-owned byte identity
    assert len(set(identities)) == 3
    assert by_index[4]["resolved_asset_identity"] is None  # story 4: no media -> deliberate graphic fallback
    assert observability["deliberate_fallback_subjects"] == ["story_4"]
    assert by_index[0]["resolved_asset_identity"] is None and by_index[5]["resolved_asset_identity"] is None
    assert observability["art_validation_passed"] is True, observability["art_blocking_issues"]
