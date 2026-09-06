"""DIRECTOR-REFRESH-CALLBACK-1: real production hotfix regression tests.

Root cause (confirmed from real production logs): a genuine, detailed PrelaunchAdvisory
routinely exceeds Telegram's 4096-char message limit; `message.answer(render_prelaunch_advisory(...))`
raised `TelegramBadRequest("message is too long")` BEFORE `callback.answer()` was ever reached -
the exact observed "founder presses the button, nothing happens" symptom. Fixed by (1) using the
existing `_send_possibly_long()` paginator, (2) acknowledging the callback immediately, before
execution, (3) wrapping execution in try/except so ANY failure still produces a visible, safe
message, and (4) a per-process in-memory dedup guard so a frustrated double-tap on the same
still-open confirmation card can never double-execute."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers import director_console as module
from bot.handlers.director_console import handle_refresh_callback
from bot.keyboards.launch import encode_refresh_callback_data, parse_refresh_callback_data
from core.config import settings
from database.models.director_run import DirectorRun, DirectorType
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from tests.fakes.fake_gateway import FakeLLMGateway

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_FOUNDER = 5507703201
_STRANGER = 111222333
_CHAT_ID = -1004297182444
_TOPIC_ID = 5


def _advisory_output(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "current_state": "NINJA VPN, transitioning", "target_state": "NINJA PULSE, launched",
        "launch_objectives": ["establish PULSE identity"], "transition_tasks": ["rename channel"],
        "content_pillars": ["AI news"], "initial_content_sequence": ["intro post"],
        "cadence_hypothesis": "daily", "format_hypotheses": ["short posts"], "visual_direction": "clean",
        "profile_setup": ["update bio"], "pinned_intro_content": ["welcome post"],
        "first_learning_questions": ["what topics resonate?"], "measurement_plan": ["track views"],
        "risks": ["audience confusion during rebrand"],
    }
    base.update(overrides)
    return base


def _long_advisory_output() -> dict:
    """A realistic-shape advisory whose rendered text genuinely exceeds Telegram's 4096-char
    limit - this is the exact shape that broke production."""
    long_list = [f"item number {i}: a full, real sentence of strategic advisory content here" for i in range(60)]
    return _advisory_output(
        launch_objectives=long_list, transition_tasks=long_list, content_pillars=long_list,
        initial_content_sequence=long_list, format_hypotheses=long_list, profile_setup=long_list,
        pinned_intro_content=long_list, first_learning_questions=long_list, measurement_plan=long_list,
        risks=long_list,
    )


def _fake_gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=100, output_tokens=200),
    ))


def _callback(*, user_id: int, data: str, chat_id: int = _CHAT_ID, thread_id: int | None = _TOPIC_ID, message_id: int = 555) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = user_id
    message = MagicMock()
    message.chat.id = chat_id
    message.message_thread_id = thread_id
    message.message_id = message_id
    message.answer = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    callback.message = message
    callback.answer = AsyncMock()
    return callback


def _enable_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _CHAT_ID)
    monkeypatch.setattr(settings, "business_context_topic_id", _TOPIC_ID)
    monkeypatch.setattr(settings, "director_console_enabled", True)
    monkeypatch.setattr(settings, "social_advisory_execution_enabled", True)
    monkeypatch.setattr(settings, "business_context_role_map", {_FOUNDER: "founder"})


def _patch_gateway(monkeypatch: pytest.MonkeyPatch, gateway: FakeLLMGateway) -> None:
    fake_layer = MagicMock(gateway=gateway)
    monkeypatch.setattr(module, "assemble_ai_integration_layer", lambda *a, **k: fake_layer)
    monkeypatch.setattr(module, "FilePromptRepository", lambda *a, **k: FilePromptRepository(_PROMPTS_ROOT))


# --- A-D: callback_data contract ------------------------------------------------------------

def test_callback_data_contract_matches_for_every_target_and_action() -> None:
    for target in ("telegram", "instagram", "all"):
        data = encode_refresh_callback_data("confirm", target)
        assert data == f"directorsrefresh:confirm:{target}"
        assert parse_refresh_callback_data(data) == ("confirm", target)
    cancel_data = encode_refresh_callback_data("cancel", "all")
    assert cancel_data == "directorsrefresh:cancel:all"
    assert parse_refresh_callback_data(cancel_data) == ("cancel", "all")


# --- Real regression: the actual production bug ----------------------------------------------

@pytest.mark.asyncio
async def test_long_advisory_no_longer_crashes_and_callback_is_acknowledged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE real production repro: a genuinely long PrelaunchAdvisory must never raise
    TelegramBadRequest, and the callback must be acknowledged regardless."""
    _enable_settings(monkeypatch)
    _patch_gateway(monkeypatch, _fake_gateway(_long_advisory_output()))
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram")
    await handle_refresh_callback(callback)

    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.args[0] == "Запущено"
    # every chunk sent via message.answer() must respect Telegram's real limit
    for call in callback.message.answer.await_args_list:
        assert len(call.args[0]) <= 4096
    # a real, final visible completion message was sent
    assert any(call.args[0] == "Готово." for call in callback.message.answer.await_args_list)


@pytest.mark.asyncio
async def test_successful_confirm_executes_and_persists_director_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    _patch_gateway(monkeypatch, _fake_gateway(_advisory_output()))
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    before = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()
    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram")
    await handle_refresh_callback(callback)
    after = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()

    assert after == before + 1
    run = (await db_session.execute(select(DirectorRun).order_by(DirectorRun.generated_at.desc()))).scalars().first()
    assert run is not None
    assert run.director_type == DirectorType.TELEGRAM_PRELAUNCH
    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_non_founder_denied_no_execution(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_settings(monkeypatch)
    gateway = _fake_gateway(_advisory_output())
    _patch_gateway(monkeypatch, gateway)
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    callback = _callback(user_id=_STRANGER, data="directorsrefresh:confirm:telegram")
    await handle_refresh_callback(callback)

    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs.get("show_alert") is True
    callback.message.answer.assert_not_awaited()
    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_wrong_chat_denied(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_settings(monkeypatch)
    _patch_gateway(monkeypatch, _fake_gateway(_advisory_output()))
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram", chat_id=-999)
    await handle_refresh_callback(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_topic_is_accepted(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The General topic itself uses the canonical business_context_topic_id, exactly like /launch -
    never a separately-derived thread_id semantic for callbacks."""
    _enable_settings(monkeypatch)
    _patch_gateway(monkeypatch, _fake_gateway(_advisory_output()))
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram", thread_id=_TOPIC_ID)
    await handle_refresh_callback(callback)

    assert callback.answer.await_args.args[0] == "Запущено"


@pytest.mark.asyncio
async def test_budget_exhausted_zero_gateway_calls(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_settings(monkeypatch)
    monkeypatch.setattr(settings, "social_advisory_max_runs_per_day", 0)
    gateway = _fake_gateway(_advisory_output())
    _patch_gateway(monkeypatch, gateway)
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram")
    await handle_refresh_callback(callback)

    assert gateway.received_requests == []
    assert any("лимит запусков" in call.args[0].lower() for call in callback.message.answer.await_args_list)


@pytest.mark.asyncio
async def test_cancel_zero_gateway_calls_zero_director_runs(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_settings(monkeypatch)
    gateway = _fake_gateway(_advisory_output())
    _patch_gateway(monkeypatch, gateway)
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    before = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()
    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:cancel:telegram")
    await handle_refresh_callback(callback)
    after = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()

    assert after == before
    assert gateway.received_requests == []
    callback.answer.assert_awaited_once_with("Отменено")
    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_execution_exception_is_never_swallowed_silently(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _patch_gateway(monkeypatch, _fake_gateway(_advisory_output()))
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(module, "run_prelaunch_advisory", _boom)

    callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram")
    await handle_refresh_callback(callback)  # must never raise

    callback.answer.assert_awaited_once_with("Запущено")
    error_messages = [call.args[0] for call in callback.message.answer.await_args_list]
    assert any("не удалось" in msg.lower() for msg in error_messages)
    assert not any("RuntimeError" in msg or "Traceback" in msg for msg in error_messages)


@pytest.mark.asyncio
async def test_duplicate_callback_on_same_message_does_not_double_execute(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine duplicate delivery/tap on the SAME still-open confirmation card must never
    re-execute - the in-memory dedup guard must reject the second concurrent call outright."""
    _enable_settings(monkeypatch)
    monkeypatch.setattr(module, "async_session_factory", lambda: db_session_cm(db_session))
    module._IN_PROGRESS_REFRESH_KEYS.add((_CHAT_ID, 555))
    try:
        callback = _callback(user_id=_FOUNDER, data="directorsrefresh:confirm:telegram", message_id=555)
        await handle_refresh_callback(callback)
        callback.answer.assert_awaited_once()
        assert callback.answer.await_args.kwargs.get("show_alert") is True
        callback.message.answer.assert_not_awaited()
    finally:
        module._IN_PROGRESS_REFRESH_KEYS.discard((_CHAT_ID, 555))


class db_session_cm:
    """A tiny async-context-manager wrapper handing back the SAME test db_session every time -
    mirrors how `async_session_factory()` is used (`async with async_session_factory() as
    session`), but keeps every call in one test on the same real transaction/session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: Any) -> None:
        return None
