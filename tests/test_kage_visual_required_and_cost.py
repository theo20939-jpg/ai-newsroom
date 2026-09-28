"""KAGE visual-required delivery and one-ledger visual cost accounting (offline: fakes only).

- Every billable visual call reachable on the Telegram NEWS path sits inside the per-story envelope.
- A NEWS story with no usable visual HOLDS (durable VISUAL_HOLD); it is never sent text-only.
- Message 2865 (Google News logos only) replays to a hold; message 2864 keeps its photo delivery.
"""
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

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.kage_content_lineage_audit import KageContentLineageAudit
from database.models.story_telegram_delivery import StoryTelegramDelivery
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.llm_gateway.models.catalog import GPT_5_6_LUNA, GPT_5_6_TERRA
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from schemas.capability import CapabilityUsage
from schemas.content_draft import ContentDraftRead
from schemas.editorial_task import EditorialTaskCreate
from schemas.image_candidate import ImageCandidate
from schemas.workflow import WorkflowType
from scripts import _kage_telegram_atomic_natural_canary as canary
from scripts import _kage_telegram_bounded_natural_batch as batch
from services import editorial_recomposition, workflow_service
from services.editorial_treatment import STANDARD, EditorialTreatmentDecision
from services.image_relevance import evaluate_eligibility
from services.kage_content_lineage_audit import create_attempt_audit
from services.kage_publication_worker_gate import WorkerGateResult
from services.kage_telegram_canary_envelope import (
    CANARY_STAGE_ORDER, VISUAL_RECOMPOSITION_MODEL, VISUAL_RECOMPOSITION_STAGE, CanaryPreDispatchSafetyRejection,
    TelegramCanaryEnvelope, maximum_canary_cost, maximum_text_canary_cost, telegram_canary_envelope,
    visual_recomposition_worst_case,
)
from tests.test_content_worker_cycle import _make_event, factory, test_source  # noqa: F401
from tests.test_kage_telegram_canary_envelope import _request
from tests.test_router_media_integration import _fake_candidate
from worker.content_cycle import HOLD_FOR_VISUAL_STATUS, run_content_cycle

FIXTURES = Path(__file__).parent / "fixtures"
M2865 = json.loads((FIXTURES / "kage_lineage_msg2865.json").read_text(encoding="utf-8"))
M2864 = json.loads((FIXTURES / "kage_lineage_msg2864.json").read_text(encoding="utf-8"))
USEFUL_2865_BODY = ("Решение приняли после того, как её агенты неожиданным образом обращались "
                    "к сайтам американских госорганов.")
CHAT, TOPIC = -1004297182444, 2
NINJA_FOOTER_TEXT = "\U0001F977 KAGE"


# --- cost envelope ---------------------------------------------------------------------------------

def test_new_per_story_hard_max_is_text_plus_one_bounded_visual_dispatch():
    assert maximum_text_canary_cost() == Decimal("0.746389")
    # gemini-3.1-flash-image standard 1K edit: $0.067/image + 131,072 in x $0.50/M + 32,768 out x $3/M
    assert visual_recomposition_worst_case() == Decimal("0.067") + Decimal("0.065536") + Decimal("0.098304")
    assert maximum_canary_cost() == Decimal("0.977229")
    assert canary.MAX_COST == batch.PER_STORY_MAX_USD == maximum_canary_cost()


def test_five_fully_reserved_stories_need_a_larger_batch_cap_than_today():
    required = (5 * maximum_canary_cost()).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    assert required == Decimal("4.89") and batch.BATCH_HARD_CAP_USD == Decimal("3.74")  # cap deliberately unchanged


def _all_text_stages_worst_case(envelope: TelegramCanaryEnvelope) -> None:
    for stage in CANARY_STAGE_ORDER:
        request = _request(stage)
        envelope.begin_stage(request)
        for model in (GPT_5_6_LUNA, GPT_5_6_TERRA):
            envelope.authorize_dispatch(request, model)
        envelope.end_stage(stage)


def test_visual_dispatch_is_reserved_inside_the_same_per_story_ledger_after_worst_case_text():
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    _all_text_stages_worst_case(envelope)
    envelope.authorize_visual_dispatch(stage=VISUAL_RECOMPOSITION_STAGE, model_id=VISUAL_RECOMPOSITION_MODEL,
                                       reserved_usd=visual_recomposition_worst_case())
    assert envelope._spent_reserved == maximum_canary_cost() <= envelope.hard_cap_usd  # noqa: SLF001
    assert envelope.dispatch_records[-1]["stage"] == VISUAL_RECOMPOSITION_STAGE


@pytest.mark.parametrize("kwargs", [
    {"stage": "image_generation", "model_id": VISUAL_RECOMPOSITION_MODEL},
    {"stage": VISUAL_RECOMPOSITION_STAGE, "model_id": "gpt-image-2"},
])
def test_visual_calls_outside_the_bounded_stage_are_refused(kwargs):
    with pytest.raises(CanaryPreDispatchSafetyRejection):
        TelegramCanaryEnvelope().authorize_visual_dispatch(reserved_usd=visual_recomposition_worst_case(), **kwargs)


def test_second_visual_dispatch_and_oversized_reservation_are_refused():
    envelope = TelegramCanaryEnvelope()
    with pytest.raises(CanaryPreDispatchSafetyRejection):
        envelope.authorize_visual_dispatch(stage=VISUAL_RECOMPOSITION_STAGE, model_id=VISUAL_RECOMPOSITION_MODEL,
                                           reserved_usd=visual_recomposition_worst_case() + Decimal("0.01"))
    envelope.authorize_visual_dispatch(stage=VISUAL_RECOMPOSITION_STAGE, model_id=VISUAL_RECOMPOSITION_MODEL,
                                       reserved_usd=visual_recomposition_worst_case())
    with pytest.raises(CanaryPreDispatchSafetyRejection):
        envelope.authorize_visual_dispatch(stage=VISUAL_RECOMPOSITION_STAGE, model_id=VISUAL_RECOMPOSITION_MODEL,
                                           reserved_usd=visual_recomposition_worst_case())


def test_vision_subject_match_cannot_dispatch_inside_the_envelope():
    request = GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="classify")])],
        max_tokens=100, metadata={"capability_name": "media_subject_match"},
    )
    with pytest.raises(CanaryPreDispatchSafetyRejection):
        TelegramCanaryEnvelope().begin_stage(request)


# --- recomposition under the envelope ------------------------------------------------------------------

def _landscape_png() -> bytes:
    image = Image.new("RGB", (1600, 900))
    for x in range(1600):
        for y in range(0, 900, 30):
            image.putpixel((x, y), (x % 200 + 40, 90, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeImageGateway:
    def __init__(self, response=None, error: Exception | None = None):
        self.calls = 0
        self._response, self._error = response, error

    async def generate_image(self, request):
        self.calls += 1
        if self._error:
            raise self._error
        return self._response


def _response(cost: str | None) -> ImageGenerationResponse:
    return ImageGenerationResponse(image_bytes=_landscape_png(), mime_type="image/png",
                                   model_used="gemini-3.1-flash-image", provider="gemini",
                                   usage=CapabilityUsage(units=1, unit_type="image"), cost_usd=cost)


@pytest.fixture
def live_recomposition(monkeypatch):
    monkeypatch.setattr(settings, "editorial_recomposition_mode", "live")
    source = _landscape_png()
    assert editorial_recomposition.evaluate_eligibility(source).eligible
    return source


@pytest.mark.asyncio
async def test_recomposition_records_accounted_cost_in_the_story_ledger(live_recomposition):
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    gateway = _FakeImageGateway(_response("0.0701"))
    with telegram_canary_envelope(envelope):
        await editorial_recomposition.maybe_recompose(source_image_bytes=live_recomposition, gateway=gateway)
    record = envelope.dispatch_records[-1]
    assert gateway.calls == 1 and record["stage"] == VISUAL_RECOMPOSITION_STAGE
    assert record["actual_cost_usd"] == "0.0701" and record["status"] == "SUCCEEDED"


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway", [
    _FakeImageGateway(error=RuntimeError("provider exploded")),
])
async def test_visual_dispatch_without_cost_fails_closed_in_the_batch(live_recomposition, gateway):
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        result = await editorial_recomposition.maybe_recompose(source_image_bytes=live_recomposition, gateway=gateway)
    assert result.used_recomposed_image is False  # original source photo kept
    record = envelope.dispatch_records[-1]
    assert record["actual_cost_usd"] is None and record["status"] == "COST_UNKNOWN"
    cost, stages, gap = batch._story_cost({"provider_dispatches": envelope.dispatch_records})
    assert gap is True  # the batch stops with COST_ACCOUNTING_FAILURE, charging the full reservation
    assert cost == visual_recomposition_worst_case()


@pytest.mark.asyncio
async def test_missing_provider_cost_on_success_also_fails_closed(live_recomposition):
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    with telegram_canary_envelope(envelope):
        await editorial_recomposition.maybe_recompose(source_image_bytes=live_recomposition, gateway=_FakeImageGateway(_response(None)))
    assert envelope.dispatch_records[-1]["actual_cost_usd"] is None
    assert batch._story_cost({"provider_dispatches": envelope.dispatch_records})[2] is True


@pytest.mark.asyncio
async def test_envelope_refusal_means_no_paid_call(live_recomposition):
    envelope = TelegramCanaryEnvelope(hard_cap_usd=canary.MAX_COST)
    envelope._spent_reserved = envelope.hard_cap_usd  # noqa: SLF001 - no room left
    gateway = _FakeImageGateway(_response("0.07"))
    with telegram_canary_envelope(envelope):
        result = await editorial_recomposition.maybe_recompose(source_image_bytes=live_recomposition, gateway=gateway)
    assert gateway.calls == 0 and result.used_recomposed_image is False
    assert result.fallback_reason.startswith("cost_envelope_refused")


@pytest.mark.asyncio
async def test_outside_an_envelope_recomposition_is_unchanged(live_recomposition):
    gateway = _FakeImageGateway(_response("0.07"))
    result = await editorial_recomposition.maybe_recompose(source_image_bytes=live_recomposition, gateway=gateway)
    assert gateway.calls == 1 and result.used_recomposed_image is True


def test_manifest_records_the_visual_stage_cost():
    rows = [{"stage": "research", "model": "gpt-5.6-luna", "actual_cost_usd": "0.01", "reserved_max_cost_usd": "0.1"},
            {"stage": VISUAL_RECOMPOSITION_STAGE, "model": VISUAL_RECOMPOSITION_MODEL, "status": "SUCCEEDED",
             "actual_cost_usd": "0.0701", "reserved_max_cost_usd": "0.23084"}]
    cost, stages, gap = batch._story_cost({"provider_dispatches": rows})
    assert gap is False and cost == Decimal("0.0801")
    assert stages[1] == {"stage": VISUAL_RECOMPOSITION_STAGE, "model": VISUAL_RECOMPOSITION_MODEL,
                         "status": "SUCCEEDED", "actual_cost_usd": "0.0701", "charged_usd": "0.0701"}


# --- visual-required delivery through the real worker ------------------------------------------------

def test_message_2865_google_news_logos_remain_rejected():
    reasons = [evaluate_eligibility(ImageCandidate.model_validate(c))[1] for c in M2865["saved_image_candidates"]]
    assert reasons == ["generic_aggregator_asset", "not_technically_validated:rejected_metadata"]


async def _router_cycle(factory_, source, monkeypatch, fixture: dict, body: str, candidates: list):
    for key, value in (("copywriting_prompt_version", "11.10"), ("editorial_delivery_mode", "router"),
                       ("unified_editorial_pipeline_enabled", False), ("content_generation_dry_run", False),
                       ("telegram_story_reply_mode", "off"), ("instagram_automatic_generation_enabled", False),
                       ("newsroom_telegram_chat_id", CHAT), ("news_topic_id", TOPIC),
                       ("pulse_brand_enabled", False), ("editorial_recomposition_mode", "off")):
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
    gate_pass = WorkerGateResult(False, False, False, False, {"event_id": str(event.id)},
                                 {"gate_version": "1", "execution_id": "fixture", "structured_result": {
                                     "FACTUAL_SAFETY": "PASS", "HEADLINE_SAFETY": "PASS", "BODY_SAFETY": "PASS",
                                     "UNSUPPORTED_CLAIMS": []}})
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 2864
    fake_bot.send_photo.return_value.chat.id = CHAT
    fake_bot.send_message.return_value.message_id = 9999
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation",
              new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed",
              new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=AsyncMock(return_value=gate_pass)),
        patch("worker.content_cycle._classify_event_for_router_treatment",
              new=AsyncMock(return_value=EditorialTreatmentDecision(STANDARD, human_review_required=False, reason="t"))),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(AsyncMock(), fake_bot, session_factory=factory_,
                                         event_ids_override=[event.id], precomputed_outcomes={event.id: outcome})
    async with factory_() as session:
        task_row = await session.get(EditorialTask, task.id)
        draft_row = await session.get(ContentDraft, draft_id)
        receipts = await session.scalar(select(func.count()).select_from(StoryTelegramDelivery)
                                        .where(StoryTelegramDelivery.content_draft_id == draft_id))
        await session.execute(delete(KageContentLineageAudit).where(KageContentLineageAudit.task_id == task.id))
        await session.commit()
    return result, fake_bot, task_row.workflow["publication_outcome"], draft_row.status, receipts


@pytest.mark.asyncio
async def test_message_2865_replay_holds_instead_of_silent_text_only(factory, test_source, monkeypatch):
    result, bot, outcome, draft_status, receipts = await _router_cycle(
        factory, test_source, monkeypatch, M2865, USEFUL_2865_BODY, candidates=[])
    assert result.editorial_usefulness_block == 0 and result.factual_gate_pass == 1  # useful copy passed
    bot.send_message.assert_not_called()
    bot.send_photo.assert_not_called()
    assert outcome["status"] == "VISUAL_HOLD" and outcome["reason"] == "no_visual_resolved"
    assert draft_status == HOLD_FOR_VISUAL_STATUS and receipts == 0
    assert result.visual_required_held == 1 and result.notified == 0


@pytest.mark.asyncio
async def test_message_2864_replay_keeps_its_source_photo_delivery(factory, test_source, monkeypatch):
    copy = M2864["copywriting"]
    result, bot, outcome, draft_status, receipts = await _router_cycle(
        factory, test_source, monkeypatch, M2864, copy["main_body"], candidates=[_fake_candidate()])
    bot.send_message.assert_not_called()
    bot.send_photo.assert_called_once()
    args, kwargs = bot.send_photo.call_args
    assert args[0] == CHAT and kwargs["message_thread_id"] == TOPIC and kwargs["photo"] == "FAKE_FILE_ID_123"
    caption = kwargs["caption"]
    assert caption.endswith('\U0001F977 <a href="https://t.me/kage_journal">KAGE</a>')
    labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert labels == ["🔗 Источник", "😂 Сгенерировать мем"]
    assert outcome["status"] == "DELIVERED" and result.visual_required_held == 0


# --- release configuration: committed flags, reproducible worker env ----------------------------------

from scripts.kage_build_worker_env import FLAGS_PATH, build_worker_env, load_flags, main as build_env_main  # noqa: E402
from core.config import Settings  # noqa: E402

_HOST_ENV = """
TELEGRAM_BOT_TOKEN=secret-token-value
POSTGRES_PASSWORD=secret-db-password
CONTENT_GENERATION_ENABLED=true
UNIFIED_EDITORIAL_PIPELINE_ENABLED=true
REDIS_HOST=127.0.0.1
CONTENT_GENERATION_ENABLED=false
COPYWRITING_PROMPT_VERSION=8.8
"""


def test_release_flags_are_committed_explicit_and_secret_free():
    flags = load_flags()
    assert FLAGS_PATH.parts[-3:] == ("deploy", "kage_telegram", "content_worker.flags.env")
    assert flags["UNIFIED_EDITORIAL_PIPELINE_ENABLED"] == "false"  # explicit, not inherited
    assert flags["CONTENT_GENERATION_ENABLED"] == "false" and flags["REDIS_HOST"] == "redis"
    assert (flags["NEWSROOM_TELEGRAM_CHAT_ID"], flags["NEWS_TOPIC_ID"]) == ("-1004297182444", "2")
    assert flags["COPYWRITING_PROMPT_VERSION"] == "11.10"


def test_built_worker_env_has_every_key_once_and_committed_flags_win():
    lines = build_worker_env(_HOST_ENV, load_flags())
    keys = [line.split("=", 1)[0] for line in lines]
    assert len(keys) == len(set(keys))
    env = dict(line.split("=", 1) for line in lines)
    assert env["CONTENT_GENERATION_ENABLED"] == "false" and env["UNIFIED_EDITORIAL_PIPELINE_ENABLED"] == "false"
    assert env["REDIS_HOST"] == "redis" and env["COPYWRITING_PROMPT_VERSION"] == "11.10"
    assert env["TELEGRAM_BOT_TOKEN"] == "secret-token-value"  # host secrets carried, never committed


def test_a_newly_constructed_worker_settings_receive_the_committed_values(tmp_path, monkeypatch, capsys):
    host = tmp_path / "host.env"
    host.write_text(_HOST_ENV, encoding="utf-8")
    out = tmp_path / "content_worker.env"
    assert build_env_main(["--host-env", str(host), "--out", str(out)]) == 0
    assert "secret-token-value" not in capsys.readouterr().out  # values of secrets never printed
    assert build_env_main(["--host-env", str(host), "--out", str(out)]) == 2  # never overwritten
    for key in ("CONTENT_GENERATION_ENABLED", "UNIFIED_EDITORIAL_PIPELINE_ENABLED", "REDIS_HOST",
                "COPYWRITING_PROMPT_VERSION", "EDITORIAL_DELIVERY_MODE", "NEWS_TOPIC_ID", "NEWSROOM_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)
    worker = Settings(_env_file=str(out))
    assert worker.content_generation_enabled is False
    assert worker.unified_editorial_pipeline_enabled is False
    assert worker.redis_host == "redis" and worker.copywriting_prompt_version == "11.10"
    assert (worker.newsroom_telegram_chat_id, worker.news_topic_id) == (-1004297182444, 2)


def test_release_flags_refuse_secrets_and_duplicates(tmp_path):
    bad = tmp_path / "flags.env"
    bad.write_text("OPENAI_API_KEY=x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="secrets"):
        load_flags(bad)
    bad.write_text("REDIS_HOST=redis\nREDIS_HOST=127.0.0.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="more than once"):
        load_flags(bad)
