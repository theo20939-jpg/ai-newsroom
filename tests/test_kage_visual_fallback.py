"""KAGE Telegram NEWS visual hierarchy V1: source photo -> generated image -> typography card -> hold.

Offline only: fake image gateways and a fake bot. Real saved lineages for messages 2864/2865."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import delete, func, select

from core.config import Settings, settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.kage_content_lineage_audit import KageContentLineageAudit
from database.models.story_telegram_delivery import StoryTelegramDelivery
from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationResponse
from schemas.capability import CapabilityUsage
from schemas.content_draft import ContentDraftRead
from schemas.editorial_task import EditorialTaskCreate
from schemas.image_candidate import ImageCandidate
from schemas.workflow import WorkflowType
from scripts import _kage_telegram_atomic_natural_canary as canary
from scripts import _kage_telegram_bounded_natural_batch as batch
from services import kage_visual_fallback as vf
from services import workflow_service
from services.editorial_treatment import STANDARD, EditorialTreatmentDecision
from services.image_relevance import evaluate_eligibility
from services.kage_content_lineage_audit import create_attempt_audit
from services.kage_publication_worker_gate import WorkerGateResult
from services.kage_telegram_canary_envelope import (
    VISUAL_GENERATION_STAGE, VISUAL_RECOMPOSITION_MODEL, VISUAL_RECOMPOSITION_STAGE, CanaryPreDispatchSafetyRejection,
    TelegramCanaryEnvelope, maximum_canary_cost, telegram_canary_envelope, visual_recomposition_worst_case,
)
from tests.test_content_worker_cycle import _make_event, factory, test_source  # noqa: F401
from tests.test_router_media_integration import _fake_candidate
from worker.content_cycle import HOLD_FOR_VISUAL_STATUS, run_content_cycle

FIXTURES = Path(__file__).parent / "fixtures"
M2865 = json.loads((FIXTURES / "kage_lineage_msg2865.json").read_text(encoding="utf-8"))
M2864 = json.loads((FIXTURES / "kage_lineage_msg2864.json").read_text(encoding="utf-8"))
TITLE_2865 = M2865["copywriting"]["title"]
USEFUL_2865_BODY = ("Решение приняли после того, как её агенты неожиданным образом обращались "
                    "к сайтам американских госорганов.")
CHAT, TOPIC = -1004297182444, 2
FOOTER_HTML = '\U0001F977 <a href="https://t.me/kage_journal">KAGE</a>'


def _photo(width: int = 1600, height: int = 900, fmt: str = "JPEG", flat: bool = False) -> bytes:
    image = Image.new("RGB", (width, height), (40, 60, 90))
    if not flat:
        for x in range(0, width, 7):
            for y in range(0, height, 11):
                image.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, 120))
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


class FakeGateway:
    def __init__(self, image: bytes | None = None, error: Exception | None = None, cost: str | None = "0.0702"):
        self.calls, self.requests = 0, []
        self.image, self.error, self.cost = image, error, cost

    async def generate_image(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.error:
            raise self.error
        return ImageGenerationResponse(image_bytes=self.image, mime_type="image/jpeg", model_used=VISUAL_RECOMPOSITION_MODEL,
                                       provider="gemini", usage=CapabilityUsage(units=1, unit_type="image"), cost_usd=self.cost)


# --- generation brief -------------------------------------------------------------------------------

def _brief(fixture=M2865, title=TITLE_2865, body=USEFUL_2865_BODY):
    return vf.build_generation_brief(title=title, body=body, research=fixture["research"],
                                     intelligence=fixture["intelligence"], source_headline=fixture["source_headline"])


def test_brief_uses_only_the_headline_and_verified_contract_facts():
    brief = _brief()
    facts = M2865["research"]["facts"]
    assert brief["fact_ids"] == [1, 2]
    assert f"- {facts[0]}" in brief["prompt"] and f"- {facts[1]}" in brief["prompt"]
    assert "news.google.com" not in brief["prompt"] and "<a href" not in brief["prompt"]  # no raw source noise
    assert M2865["source_headline"] not in brief["prompt"]


def test_brief_forbids_fabricated_evidence_and_text():
    prompt = _brief()["prompt"]
    for rule in ("No text, letters, numbers", "Never depict screenshots, app or product interfaces",
                 "documents, charts, graphs", "quotes", "breaking-news graphics",
                 "Never depict a real, identifiable person or a lookalike", "never invent product details"):
        assert rule in prompt


def test_named_real_person_is_masked_and_depiction_avoided():
    research = {"facts": ["Сэм Альтман заявил, что OpenAI приостановила обучение моделей.",
                          "Причиной стали агенты, неожиданно искавшие на сайтах правительства США."]}
    intelligence = {"angle": "агенты неожиданно искали на сайтах правительства США", "recommendation": "PUBLISH"}
    brief = vf.build_generation_brief(title="Сэм Альтман: OpenAI поставила обучение на паузу",
                                      body="Причиной стали агенты на сайтах правительства США.",
                                      research=research, intelligence=intelligence)
    assert brief["named_person_detected"] is True
    assert "Альтман" not in brief["prompt"] and "Сэм" not in brief["prompt"]
    assert "show no person at all" in brief["prompt"]


def test_company_names_are_kept():
    assert "OpenAI" in _brief()["prompt"] and _brief()["named_person_detected"] is False


# --- Tier 2 / Tier 3 ladder ---------------------------------------------------------------------------

async def _ladder(gateway, *, title=TITLE_2865, allow_generation=True):
    return await vf.resolve_visual_fallback(
        title=title, body=USEFUL_2865_BODY, research=M2865["research"], intelligence=M2865["intelligence"],
        source_headline=M2865["source_headline"], gateway=gateway, editorial_code="NP-0001",
        allow_generation=allow_generation)


@pytest.mark.asyncio
async def test_generation_is_text_to_image_16x9_and_called_exactly_once():
    gateway = FakeGateway(_photo())
    result = await _ladder(gateway)
    assert result.tier == vf.TIER_GENERATED and gateway.calls == 1 == vf.GENERATION_MAX_DISPATCHES
    request = gateway.requests[0]
    assert request.operation == ImageGenerationOperation.TEXT_TO_IMAGE and request.target_aspect_ratio == "16:9"
    assert request.reference_images == ()
    with Image.open(io.BytesIO(result.image_bytes)) as im:  # KAGE-branded hero of the generated image
        assert im.size == (1600, 900)


@pytest.mark.asyncio
@pytest.mark.parametrize("image, error, reason", [
    (_photo(640, 640), None, "generated_invalid:not_landscape_editorial"),
    (_photo(800, 450), None, "generated_invalid:resolution_too_low"),
    (_photo(flat=True), None, "generated_invalid:blank_or_uniform"),
    (b"not an image", None, "generated_invalid:undecodable"),
    (None, RuntimeError("provider down"), "generation_error:RuntimeError"),
], ids=["square", "too_small", "blank", "undecodable", "provider_error"])
async def test_invalid_or_failed_generation_falls_to_the_typography_card_without_retry(image, error, reason):
    gateway = FakeGateway(image, error=error)
    result = await _ladder(gateway)
    assert gateway.calls == 1  # never regenerated
    assert result.tier == vf.TIER_TYPOGRAPHY and result.generation_reason == reason
    assert result.image_bytes and result.image_bytes.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_typography_failure_after_generation_failure_holds():
    with patch.object(vf, "render_typography_card", return_value=None):
        result = await _ladder(FakeGateway(error=RuntimeError("x")))
    assert result.tier == vf.TIER_HOLD and result.reason == vf.HOLD_REASON_VISUAL_FALLBACK_EXHAUSTED
    assert result.image_bytes is None and result.typography_reason == "headline_does_not_fit"


@pytest.mark.asyncio
async def test_dry_run_never_makes_the_paid_generation_call():
    gateway = FakeGateway(_photo())
    result = await _ladder(gateway, allow_generation=False)
    assert gateway.calls == 0 and result.tier == vf.TIER_TYPOGRAPHY


# --- typography card ----------------------------------------------------------------------------------

def test_typography_card_is_deterministic_telegram_sized_and_carries_only_the_headline():
    first, second = vf.render_typography_card(TITLE_2865), vf.render_typography_card(TITLE_2865)
    assert first == second and first.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(first)) as im:
        assert im.size == (1280, 720)
    lines, size = vf.fit_headline(TITLE_2865)
    assert " ".join(lines) == " ".join(TITLE_2865.split()) and size >= 48  # whole headline, no ellipsis


def test_typography_card_refuses_a_headline_that_cannot_fit():
    too_long = " ".join(["Заголовок"] * 60)
    assert vf.fit_headline(too_long) is None and vf.render_typography_card(too_long) is None
    assert vf.render_typography_card("Сверхдлинноеслово" * 12) is None  # never split mid-word
    assert vf.render_typography_card("   ") is None


# --- cost envelope --------------------------------------------------------------------------------------

def test_visual_branches_are_mutually_exclusive_so_the_hard_max_does_not_double_reserve():
    assert visual_recomposition_worst_case() == Decimal("0.230840")  # edit and text-to-image priced alike
    assert maximum_canary_cost() == Decimal("0.977229") == canary.MAX_COST == batch.PER_STORY_MAX_USD
    assert (5 * maximum_canary_cost()).quantize(Decimal("0.01"), rounding=ROUND_CEILING) == Decimal("4.89")
    envelope = TelegramCanaryEnvelope()
    envelope.authorize_visual_dispatch(stage=VISUAL_RECOMPOSITION_STAGE, model_id=VISUAL_RECOMPOSITION_MODEL,
                                       reserved_usd=visual_recomposition_worst_case())
    with pytest.raises(CanaryPreDispatchSafetyRejection):  # never both paid visuals on one story
        envelope.authorize_visual_dispatch(stage=VISUAL_GENERATION_STAGE, model_id=VISUAL_RECOMPOSITION_MODEL,
                                           reserved_usd=visual_recomposition_worst_case())


@pytest.mark.asyncio
async def test_generation_cost_is_reserved_and_recorded_in_the_story_ledger():
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        await vf.generate_editorial_image("brief", gateway=FakeGateway(_photo(), cost="0.0702"))
    record = envelope.dispatch_records[-1]
    assert record["stage"] == VISUAL_GENERATION_STAGE and record["actual_cost_usd"] == "0.0702"
    assert record["reserved_max_cost_usd"] == str(visual_recomposition_worst_case())


@pytest.mark.asyncio
@pytest.mark.parametrize("image, error, cost", [(_photo(), None, None), (None, RuntimeError("x"), "0.07")],
                         ids=["success_without_cost", "provider_error"])
async def test_missing_generation_cost_fails_closed(image, error, cost):
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        await vf.generate_editorial_image("brief", gateway=FakeGateway(image, error=error, cost=cost))
    assert envelope.dispatch_records[-1]["actual_cost_usd"] is None
    assert batch._story_cost({"provider_dispatches": envelope.dispatch_records})[2] is True  # batch stops


@pytest.mark.asyncio
async def test_envelope_refusal_means_no_generation_call():
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    envelope._spent_reserved = envelope.hard_cap_usd  # noqa: SLF001
    gateway = FakeGateway(_photo())
    with telegram_canary_envelope(envelope):
        image, reason = await vf.generate_editorial_image("brief", gateway=gateway)
    assert image is None and gateway.calls == 0 and reason.startswith("cost_envelope_refused")


def test_typography_is_a_visual_stage_with_zero_provider_cost():
    envelope = TelegramCanaryEnvelope()
    envelope.record_local_visual(stage="news_typography_card", detail="ok")
    row = envelope.dispatch_records[-1]
    assert row["provider_call"] is False and row["actual_cost_usd"] == "0"
    cost, stages, gap = batch._story_cost({"provider_dispatches": envelope.dispatch_records})
    assert cost == 0 and gap is False and stages[0]["stage"] == "news_typography_card"


# --- the real worker: message 2865 / 2864 replays ----------------------------------------------------------

def test_message_2865_google_news_logos_remain_rejected():
    reasons = [evaluate_eligibility(ImageCandidate.model_validate(c))[1] for c in M2865["saved_image_candidates"]]
    assert reasons == ["generic_aggregator_asset", "not_technically_validated:rejected_metadata"]


async def _cycle(factory_, source, monkeypatch, fixture, body, candidates, *, generated=None, generation_error=None,
                 typography=True, mode="live"):
    for key, value in (("copywriting_prompt_version", "11.10"), ("editorial_delivery_mode", "router"),
                       ("unified_editorial_pipeline_enabled", False), ("content_generation_dry_run", False),
                       ("telegram_story_reply_mode", "off"), ("instagram_automatic_generation_enabled", False),
                       ("newsroom_telegram_chat_id", CHAT), ("news_topic_id", TOPIC), ("pulse_brand_enabled", False),
                       ("editorial_recomposition_mode", "off"), ("kage_news_visual_fallback_mode", mode)):
        monkeypatch.setattr(settings, key, value)
    title = fixture["copywriting"]["title"]
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        event.title, event.url = fixture["source_headline"], "https://example.com/article"
        task = await workflow_service.create_task(session, EditorialTaskCreate(
            event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B))
        await create_attempt_audit(session, task_id=task.id, event_id=event.id, story_id=None, source_snapshot={})
        draft_id = uuid4()
        session.add(ContentDraft(id=draft_id, task_id=task.id, type=ContentType.POST, title=title, body=body,
                                 status="draft", version=1))
        await session.commit()
    now = datetime.now(timezone.utc)
    outcome = SimpleNamespace(
        task_id=task.id, content_draft=ContentDraftRead(id=draft_id, task_id=task.id, type=ContentType.POST, title=title,
                                                        body=body, hashtags=None, version=1, status="draft",
                                                        created_at=now, updated_at=now),
        copywriting_output={"title": title, "main_body": body, "ending": None},
        research_output=fixture["research"], intelligence_output=fixture["intelligence"],
        quality_output={"passed": True}, fact_safety_status=None,
    )
    gate = AsyncMock(return_value=WorkerGateResult(
        False, False, False, False, {"event_id": str(event.id)},
        {"gate_version": "1", "execution_id": "fixture", "structured_result": {
            "FACTUAL_SAFETY": "PASS", "HEADLINE_SAFETY": "PASS", "BODY_SAFETY": "PASS", "UNSUPPORTED_CLAIMS": []}}))
    generate = AsyncMock(return_value=(generated, "ok") if generated else (None, generation_error or "generation_error:X"))
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 7001
    fake_bot.send_photo.return_value.chat.id = CHAT
    patches = [
        patch("worker.content_cycle.evaluate_origin_before_generation",
              new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed",
              new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=gate),
        patch("worker.content_cycle._classify_event_for_router_treatment",
              new=AsyncMock(return_value=EditorialTreatmentDecision(STANDARD, human_review_required=False, reason="t"))),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
        patch("services.kage_visual_fallback.generate_editorial_image", new=generate),
    ]
    if not typography:
        patches.append(patch("services.kage_visual_fallback.render_typography_card", return_value=None))
    for item in patches:
        item.start()
    try:
        result = await run_content_cycle(AsyncMock(), fake_bot, session_factory=factory_,
                                         event_ids_override=[event.id], precomputed_outcomes={event.id: outcome})
    finally:
        for item in patches:
            item.stop()
    async with factory_() as session:
        task_row = await session.get(EditorialTask, task.id)
        draft_row = await session.get(ContentDraft, draft_id)
        lineage = (await session.get(KageContentLineageAudit, task.id)).audit
        receipts = await session.scalar(select(func.count()).select_from(StoryTelegramDelivery)
                                        .where(StoryTelegramDelivery.content_draft_id == draft_id))
        await session.execute(delete(KageContentLineageAudit).where(KageContentLineageAudit.task_id == task.id))
        await session.commit()
    return SimpleNamespace(result=result, bot=fake_bot, gate=gate, generate=generate, lineage=lineage,
                           outcome=task_row.workflow["publication_outcome"], draft_status=draft_row.status,
                           receipts=receipts)


def _assert_photo_post(run):
    run.bot.send_message.assert_not_called()
    run.bot.send_photo.assert_called_once()
    args, kwargs = run.bot.send_photo.call_args
    assert args[0] == CHAT and kwargs["message_thread_id"] == TOPIC
    assert kwargs["caption"].endswith(FOOTER_HTML)
    assert [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row] == ["🔗 Источник", "😂 Сгенерировать мем"]
    assert run.outcome["status"] == "DELIVERED" and run.gate.await_count == 1
    return kwargs["photo"]


@pytest.mark.asyncio
async def test_2865_no_source_photo_generated_image_is_sent_as_photo(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2865, USEFUL_2865_BODY, [], generated=_photo())
    photo = _assert_photo_post(run)
    assert run.generate.await_count == 1
    assert photo.filename == "kage-generated_image.jpg"
    audit = run.lineage["stages"]["visual_fallback"]
    assert audit["tier"] == vf.TIER_GENERATED and audit["brief_fact_ids"] == [1, 2]


@pytest.mark.asyncio
async def test_2865_generation_failure_sends_the_typography_card(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2865, USEFUL_2865_BODY, [],
                       generation_error="generation_error:RuntimeError")
    photo = _assert_photo_post(run)
    assert photo.filename == "kage-typography_card.png" and photo.data == vf.render_typography_card(TITLE_2865)
    audit = run.lineage["stages"]["visual_fallback"]
    assert audit["tier"] == vf.TIER_TYPOGRAPHY and audit["typography_provider_cost_usd"] == "0"
    assert audit["generation_reason"] == "generation_error:RuntimeError"


@pytest.mark.asyncio
async def test_2865_every_visual_tier_failing_holds_without_any_send(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2865, USEFUL_2865_BODY, [], typography=False)
    run.bot.send_message.assert_not_called()
    run.bot.send_photo.assert_not_called()
    assert run.outcome["status"] == "VISUAL_HOLD" and run.outcome["reason"] == vf.HOLD_REASON_VISUAL_FALLBACK_EXHAUSTED
    assert run.draft_status == HOLD_FOR_VISUAL_STATUS and run.receipts == 0
    assert run.lineage["stages"]["visual_fallback"]["tier"] == vf.TIER_HOLD


@pytest.mark.asyncio
async def test_2865_old_headline_restatement_is_still_blocked_before_any_visual_work(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2865, M2865["copywriting"]["main_body"], [],
                       generated=_photo())
    assert run.result.editorial_usefulness_block == 1 and run.generate.await_count == 0
    run.bot.send_message.assert_not_called()
    run.bot.send_photo.assert_not_called()
    assert run.outcome["status"] == "BLOCKED_EDITORIAL_USEFULNESS"


@pytest.mark.asyncio
async def test_2864_valid_source_photo_wins_with_no_generation_or_typography(factory, test_source, monkeypatch):
    with patch("services.kage_visual_fallback.render_typography_card") as typography:
        run = await _cycle(factory, test_source, monkeypatch, M2864, M2864["copywriting"]["main_body"],
                           [_fake_candidate()], generated=_photo())
    photo = _assert_photo_post(run)
    assert photo == "FAKE_FILE_ID_123"  # the real source photo, untouched
    assert run.generate.await_count == 0 and typography.call_count == 0
    assert "visual_fallback" not in run.lineage["stages"]


@pytest.mark.asyncio
async def test_fallback_mode_off_keeps_the_plain_hold_and_never_generates(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2865, USEFUL_2865_BODY, [], generated=_photo(), mode="off")
    assert run.generate.await_count == 0
    run.bot.send_message.assert_not_called()
    run.bot.send_photo.assert_not_called()
    assert run.outcome["status"] == "VISUAL_HOLD" and run.outcome["reason"] == "no_visual_resolved"


def test_fallback_default_is_off_and_release_flags_enable_it():
    from scripts.kage_build_worker_env import load_flags

    assert Settings.model_fields["kage_news_visual_fallback_mode"].default == "off"
    flags = load_flags()
    assert flags["KAGE_NEWS_VISUAL_FALLBACK_MODE"] == "live" and flags["UNIFIED_EDITORIAL_PIPELINE_ENABLED"] == "false"


# --- the last text-only escape hatch: photo-caption overflow -----------------------------------------

def _overflowing_2864_body() -> str:
    fact = M2864["research"]["facts"][0]
    body = " ".join([fact] * 8)
    assert len(body) > 1024  # far beyond Telegram's 1024-unit photo caption
    return body


@pytest.mark.asyncio
async def test_source_photo_with_an_overflowing_caption_holds_and_never_sends_text(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2864, _overflowing_2864_body(), [_fake_candidate()],
                       generated=_photo())
    run.bot.send_message.assert_not_called()
    run.bot.send_photo.assert_not_called()
    assert run.outcome["status"] == "VISUAL_HOLD" and run.outcome["reason"] == "photo_caption_overflow"
    assert run.draft_status == HOLD_FOR_VISUAL_STATUS and run.receipts == 0
    assert run.generate.await_count == 0  # a real source photo existed; no generation attempted


@pytest.mark.asyncio
async def test_no_source_and_overflowing_caption_holds_before_any_paid_generation(factory, test_source, monkeypatch):
    run = await _cycle(factory, test_source, monkeypatch, M2864, _overflowing_2864_body(), [], generated=_photo())
    run.bot.send_message.assert_not_called()
    run.bot.send_photo.assert_not_called()
    assert run.generate.await_count == 0
    assert run.outcome["status"] == "VISUAL_HOLD" and run.outcome["reason"] == "photo_caption_overflow"


def test_every_news_text_send_branch_is_gone_or_unreachable_for_kage():
    """Structural enumeration of worker/content_cycle.py's Telegram send calls."""
    import ast

    source = Path(__file__).resolve().parents[1].joinpath("worker", "content_cycle.py").read_text(encoding="utf-8")
    calls: dict[str, int] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in {"send_to_editorial_destination", "send_editorial_card", "send_message",
                        "send_photo_to_editorial_destination", "send_media_group_to_editorial_destination",
                        "send_video_to_editorial_destination", "run_unified_telegram_delivery"}:
                calls[name] = calls.get(name, 0) + 1
    # Router NEWS branch: photo / media group / video / fallback photo only - no text send at all.
    assert "send_to_editorial_destination" not in calls and "send_message" not in calls
    assert calls["send_photo_to_editorial_destination"] == 2  # source photo + Tier 2/3 fallback photo
    # The two remaining text-capable branches are unreachable for a KAGE worker (startup refuses).
    assert calls["send_editorial_card"] == 1 and calls["run_unified_telegram_delivery"] == 1
    from worker import content_main

    for overrides in ({"editorial_delivery_mode": "legacy"},
                      {"editorial_delivery_mode": "router", "unified_editorial_pipeline_enabled": True}):
        with patch.object(content_main, "settings", Settings(_env_file=None, **overrides)):
            with pytest.raises(RuntimeError):
                content_main._configure_telegram_copywriting_default()
