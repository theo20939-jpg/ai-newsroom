"""Zero-cost checks for the actual Telegram send boundary and frozen gate adapter."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.config import Settings, settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.story import Story
from database.models.story_telegram_delivery import StoryTelegramDelivery
from schemas.content_draft import ContentDraftRead
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services.kage_publication_worker_gate import WorkerGateResult, evaluate_worker_publication_gate
from services.kage_delivery_truth import count_terminal_outcomes, record_terminal_outcome
from services.content_draft_service import _draft_status_for
from services import workflow_service
from services.telegram_notifier import NotificationOutcome
from tests.test_content_worker_cycle import _make_event, factory, test_source  # noqa: F401
from services.editorial_treatment import STANDARD
from worker.content_cycle import run_content_cycle
from worker import content_main
from services.news_telegram_presentation import render_v8_news_card_html
from services.nnj_master_news_mark import rasterize_kage_watermark
from services.brand_renderer import load_brand_mark
from bot.keyboards.image_preview import build_source_only_keyboard
from PIL import Image, ImageChops


def test_content_worker_default_and_explicit_override(monkeypatch):
    default = Settings(_env_file=None)
    assert default.copywriting_prompt_version == "4"  # unrelated workflows retain their default
    monkeypatch.setattr(content_main, "settings", default)
    assert content_main._configure_telegram_copywriting_default() == "11.10"
    assert default.copywriting_prompt_version == "11.10"
    explicit = Settings(_env_file=None, copywriting_prompt_version="8.9")
    monkeypatch.setattr(content_main, "settings", explicit)
    with pytest.raises(RuntimeError, match="11.10"):
        content_main._configure_telegram_copywriting_default()


def test_kage_publication_cta_and_source_button_remain_separate():
    rendered = render_v8_news_card_html({"title": "Заголовок", "main_body": "Текст", "ending": None})
    assert '<a href="https://t.me/kage_journal">KAGE</a>' in rendered
    source = build_source_only_keyboard("https://news.example/story", label="🔗 Источник")
    button = source.inline_keyboard[0][0]
    assert (button.text, button.url) == ("🔗 Источник", "https://news.example/story")
    assert "news.example" not in rendered


def test_kage_watermark_is_the_supplied_transparent_asset_and_scales_proportionally():
    path = Path("assets/brand/kage_watermark.png")
    with Image.open(path) as opened:
        source = opened.convert("RGBA")
    rendered = rasterize_kage_watermark(target_width=627)
    assert rendered.size == (627, 627)
    assert source.getchannel("A").getbbox() is not None
    assert source.getchannel("A").getextrema()[0] == 0
    assert rendered.getchannel("A").getbbox() is not None
    assert ImageChops.difference(source, load_brand_mark()).getbbox() is None


def test_brand_asset_defaults_point_to_canonical_kage_watermark():
    brand_path = "assets/brand/kage_watermark.png"
    configured = Settings(_env_file=None)
    assert configured.brand_asset_path == brand_path
    assert configured.brand_red_asset_path == brand_path
    assert configured.brand_raster_fallback_path == brand_path
    compose = __import__("yaml").safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["content_worker"]["environment"]["COPYWRITING_PROMPT_VERSION"] == "11.10"


def test_kage_legacy_fact_safety_is_history_not_publication_authority(monkeypatch):
    monkeypatch.setattr(settings, "copywriting_prompt_version", "11.10")
    monkeypatch.setattr(settings, "fact_safety_mode", "enforce")
    assert _draft_status_for("block") == "draft"
    assert _draft_status_for("review") == "draft"


@pytest.mark.asyncio
async def test_actual_worker_startup_resolves_1110_without_override(monkeypatch):
    worker_settings = Settings(_env_file=None)
    monkeypatch.setattr(content_main, "settings", worker_settings)
    layer = SimpleNamespace(capability_registry=object(), cost_tracker=None, gateway=object())
    with (
        patch("worker.content_main.assemble_ai_integration_layer", return_value=layer),
        patch("worker.content_main.create_bot", return_value=object()),
        patch("worker.content_main.ModelRegistryPricingCatalog", return_value=object()),
        patch("worker.content_main.run_content_cycle", new=AsyncMock(side_effect=asyncio.CancelledError)) as cycle,
    ):
        with pytest.raises(asyncio.CancelledError):
            await content_main._run_enabled_loop()
    assert worker_settings.copywriting_prompt_version == "11.10"
    assert cycle.await_count == 1
    assert cycle.await_args.kwargs["gate_gateway"] is layer.gateway


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario, expected_send", [
    ("pass", 1), ("gate_fail", 0), ("guard_fail", 0), ("both_fail", 0),
    ("provider_error", 0), ("truncated", 0), ("invalid", 0), ("missing", 0),
    ("legacy_safe_gate_fail", 0), ("legacy_block_gate_pass", 1),
    ("quality_fail_gate_pass", 1),
    ("quality_pass_gate_fail", 0), ("quality_pass_guard_fail", 0),
    ("send_failure", 1),
])
async def test_real_content_cycle_send_boundary(
    scenario, expected_send, factory, test_source, monkeypatch,
):
    monkeypatch.setattr(settings, "copywriting_prompt_version", "11.10")
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    monkeypatch.setattr(settings, "unified_editorial_pipeline_enabled", False)
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "off")
    monkeypatch.setattr(settings, "fact_safety_mode", "enforce")
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        draft_id = uuid4()
        session.add(ContentDraft(id=draft_id, task_id=task.id, type=ContentType.POST,
                                 title="Проверка", body="Проверочный текст.",
                                 status="draft", version=1))
        await session.commit()
    task_id = task.id
    now = datetime.now(timezone.utc)
    draft = ContentDraftRead(
        id=draft_id, task_id=task_id, type=ContentType.POST, title="Проверка",
        body="Проверочный текст.", hashtags=None, version=1, status="draft",
        created_at=now, updated_at=now,
    )
    quality_failed = scenario == "quality_fail_gate_pass"
    outcome = SimpleNamespace(
        task_id=task_id, content_draft=draft, copywriting_output={"title": draft.title, "main_body": draft.body, "ending": None},
        research_output={"facts": []}, intelligence_output={},
        quality_output={"passed": not quality_failed},
        fact_safety_status=("pass" if scenario == "legacy_safe_gate_fail" else
                            "block" if scenario == "legacy_block_gate_pass" else None),
    )
    technical = scenario in {"provider_error", "truncated", "invalid", "missing"}
    factual = scenario in {"gate_fail", "both_fail", "legacy_safe_gate_fail", "quality_pass_gate_fail"}
    guard = scenario in {"guard_fail", "both_fail", "quality_pass_guard_fail"}
    blocked = technical or factual or guard
    gate_result = WorkerGateResult(
        blocked, technical, factual, guard,
        {"event_id": str(event.id), "draft_id": str(draft_id), "final_publication_block": blocked},
    )
    notify = AsyncMock(return_value=NotificationOutcome(
        chat_id=1, rendered_html="<b>ok</b>", sent=scenario != "send_failure",
        message_id=None if scenario == "send_failure" else 23,
    ))
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation", new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed", new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=AsyncMock(return_value=gate_result)) as gate,
        patch("worker.content_cycle.send_editorial_card", new=notify),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[event.id], precomputed_outcomes={event.id: outcome},
        )
    assert gate.await_count == 1
    assert notify.await_count == expected_send
    assert result.final_publication_pass == expected_send
    assert result.gate_technical_block == int(technical)
    assert result.local_guard_block == int(guard)
    assert result.both_block == int((factual or technical) and guard)
    async with factory() as session:
        persisted = await session.get(ContentDraft, draft_id)
        assert persisted.status == ("draft_blocked_fact_safety" if blocked else "draft")
        persisted_task = await session.get(EditorialTask, task_id)
        terminal = persisted_task.workflow["publication_outcome"]
        expected_terminal = (
            "GATE_TECHNICAL_BLOCK" if technical else
            "BLOCKED_BOTH" if factual and guard else
            "BLOCKED_FACTUAL_GATE" if factual else
            "BLOCKED_LOCAL_GUARD" if guard else
            "DELIVERY_FAILED" if scenario == "send_failure" else "DELIVERED"
        )
        assert terminal["status"] == expected_terminal
        assert terminal["message_id"] == (23 if expected_terminal == "DELIVERED" else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked, held", [(False, False), (True, False), (False, True)])
async def test_router_unified_delivery_is_behind_same_gate(blocked, held, factory, test_source, monkeypatch):
    monkeypatch.setattr(settings, "copywriting_prompt_version", "11.10")
    monkeypatch.setattr(settings, "editorial_delivery_mode", "router")
    monkeypatch.setattr(settings, "unified_editorial_pipeline_enabled", True)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "off")
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        draft_id = uuid4()
        session.add(ContentDraft(id=draft_id, task_id=task.id, type=ContentType.POST,
                                 title="Проверка", body="Проверочный текст.",
                                 status="draft", version=1))
        await session.commit()
    now = datetime.now(timezone.utc)
    draft = ContentDraftRead(
        id=draft_id, task_id=task.id, type=ContentType.POST, title="Проверка", body="Проверочный текст.",
        hashtags=None, version=1, status="draft", created_at=now, updated_at=now,
    )
    outcome = SimpleNamespace(
        task_id=draft.task_id, content_draft=draft,
        copywriting_output={"title": draft.title, "main_body": draft.body, "ending": None},
        research_output={}, intelligence_output={}, quality_output={"passed": True},
        fact_safety_status="pass",
    )
    gate = WorkerGateResult(blocked, False, blocked, False,
                            {"event_id": str(event.id), "draft_id": str(draft.id),
                             "final_publication_block": blocked})
    unified = AsyncMock(return_value=SimpleNamespace(
        presentation_type="NEWS", held=held, dry_run=False, sent=not held,
        sent_message_id=None if held else 23, sent_chat_id=None if held else 1, had_photo=False,
    ))
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation", new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=SimpleNamespace(treatment=STANDARD))),
        patch("worker.content_cycle.check_duplicate_story_delivery", new=AsyncMock(return_value=SimpleNamespace(blocked=False))),
        patch("worker.content_cycle.check_update_would_fail_closed", new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=AsyncMock(return_value=gate)),
        patch("worker.content_cycle.is_unified_router_eligible", return_value=True),
        patch("worker.content_cycle._fetch_router_presentation_signals", new=AsyncMock(return_value=([], None))),
        patch("worker.content_cycle.run_unified_telegram_delivery", new=unified),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[event.id], precomputed_outcomes={event.id: outcome},
        )
    assert unified.await_count == int(not blocked)
    assert result.notified == int(not blocked and not held)
    async with factory() as session:
        persisted_task = await session.get(EditorialTask, task.id)
        assert persisted_task.workflow["publication_outcome"]["status"] == (
            "BLOCKED_FACTUAL_GATE" if blocked else "VISUAL_HOLD" if held else "DELIVERED"
        )


@pytest.mark.asyncio
async def test_kage_generation_failure_is_terminal(factory, test_source, monkeypatch):
    monkeypatch.setattr(settings, "copywriting_prompt_version", "11.10")
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        await session.commit()
    outcome = SimpleNamespace(task_id=task.id, content_draft=None)
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation", new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed", new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.send_editorial_card", new=AsyncMock()) as send,
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[event.id], precomputed_outcomes={event.id: outcome},
        )
    assert result.failed == 1
    send.assert_not_awaited()
    async with factory() as session:
        persisted = await session.get(EditorialTask, task.id)
        assert persisted.workflow["publication_outcome"]["status"] == "GENERATION_FAILED"


@pytest.mark.asyncio
async def test_kage_terminal_outcome_is_one_per_attempt(factory, test_source):
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        await session.commit()
    async with factory() as session:
        first = await record_terminal_outcome(session, task_id=task.id, status="GENERATION_FAILED")
        await session.commit()
    async with factory() as session:
        again = await record_terminal_outcome(session, task_id=task.id, status="GENERATION_FAILED")
        assert again == first
        with pytest.raises(ValueError, match="conflicting terminal outcome"):
            await record_terminal_outcome(session, task_id=task.id, status="DELIVERY_FAILED")
        await session.rollback()
    async with factory() as session:
        totals = await count_terminal_outcomes(
            session, window_start=event.collected_at - timedelta(seconds=1),
            window_end=event.collected_at + timedelta(seconds=1),
        )
        assert totals["GENERATION_FAILED"] >= 1


@pytest.mark.asyncio
async def test_kage_real_boundary_persists_story_receipt_and_skips_duplicate(
    factory, test_source, monkeypatch,
):
    monkeypatch.setattr(settings, "copywriting_prompt_version", "11.10")
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    monkeypatch.setattr(settings, "unified_editorial_pipeline_enabled", False)
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "off")
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        story = Story(title=event.title, category=event.category, topic_bucket="test",
                      first_event_id=event.id, event_count=1)
        session.add(story)
        await session.flush()
        draft_id = uuid4()
        session.add(ContentDraft(id=draft_id, task_id=task.id, type=ContentType.POST,
                                 title="Проверка", body="Проверочный текст.",
                                 status="draft", version=1))
        session.add(ContentDraftStoryLink(content_draft_id=draft_id, story_id=story.id,
                                          source_event_id=event.id, is_story_update=False))
        await session.commit()
    now = datetime.now(timezone.utc)
    draft = ContentDraftRead(id=draft_id, task_id=task.id, type=ContentType.POST,
                             title="Проверка", body="Проверочный текст.", hashtags=None,
                             version=1, status="draft", created_at=now, updated_at=now)
    outcome = SimpleNamespace(task_id=task.id, content_draft=draft,
                              copywriting_output={"title": draft.title, "main_body": draft.body,
                                                  "ending": None}, research_output={"facts": []},
                              intelligence_output={}, quality_output={"passed": True},
                              fact_safety_status="pass")
    gate = WorkerGateResult(False, False, False, False, {"final_publication_block": False})
    notify = AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="ok",
                                                         sent=True, message_id=927))
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation", new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed", new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=AsyncMock(return_value=gate)),
        patch("worker.content_cycle.send_editorial_card", new=notify),
    ):
        for _ in range(2):
            await run_content_cycle(AsyncMock(), AsyncMock(), session_factory=factory,
                                    event_ids_override=[event.id],
                                    precomputed_outcomes={event.id: outcome})
    assert notify.await_count == 1
    async with factory() as session:
        task_row = await session.get(EditorialTask, task.id)
        assert task_row.workflow["publication_outcome"]["status"] == "DELIVERED"
        assert task_row.workflow["publication_outcome"]["message_id"] == 927
        receipts = (await session.execute(
            select(StoryTelegramDelivery).where(StoryTelegramDelivery.content_draft_id == draft_id)
        )).scalars().all()
        assert len(receipts) == 1
        assert receipts[0].telegram_message_id == 927
        counts = await count_terminal_outcomes(
            session, window_start=event.collected_at - timedelta(seconds=1),
            window_end=event.collected_at + timedelta(seconds=1),
        )
        assert counts["DELIVERED"] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage, expected", [
    ("before_send", "OTHER_TERMINAL_FAILURE"),
    ("at_send", "DELIVERY_UNCONFIRMED"),
])
async def test_kage_unexpected_exception_is_not_silent(
    stage, expected, factory, test_source, monkeypatch,
):
    monkeypatch.setattr(settings, "copywriting_prompt_version", "11.10")
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "off")
    monkeypatch.setattr(settings, "quote_telegram_rendering_mode",
                        "enforce" if stage == "before_send" else "off")
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B),
        )
        draft_id = uuid4()
        session.add(ContentDraft(id=draft_id, task_id=task.id, type=ContentType.POST,
                                 title="Проверка", body="Проверочный текст.",
                                 status="draft", version=1))
        await session.commit()
    now = datetime.now(timezone.utc)
    draft = ContentDraftRead(id=draft_id, task_id=task.id, type=ContentType.POST,
                             title="Проверка", body="Проверочный текст.", hashtags=None,
                             version=1, status="draft", created_at=now, updated_at=now)
    outcome = SimpleNamespace(task_id=task.id, content_draft=draft,
                              copywriting_output={"title": draft.title, "main_body": draft.body,
                                                  "ending": None}, research_output={},
                              intelligence_output={}, quality_output={"passed": True},
                              fact_safety_status="pass")
    gate = WorkerGateResult(False, False, False, False, {"final_publication_block": False})
    send = AsyncMock(side_effect=RuntimeError("simulated send boundary interruption"))
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation", new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed", new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=AsyncMock(return_value=gate)),
        patch("worker.content_cycle.get_quote_for_draft", new=AsyncMock(side_effect=RuntimeError("simulated lookup interruption"))),
        patch("worker.content_cycle.send_editorial_card", new=send),
    ):
        with pytest.raises(RuntimeError, match="simulated"):
            await run_content_cycle(AsyncMock(), AsyncMock(), session_factory=factory,
                                    event_ids_override=[event.id],
                                    precomputed_outcomes={event.id: outcome})
    assert send.await_count == int(stage == "at_send")
    async with factory() as session:
        task_row = await session.get(EditorialTask, task.id)
        terminal = task_row.workflow["publication_outcome"]
        assert terminal["status"] == expected
        assert terminal["message_id"] is None
