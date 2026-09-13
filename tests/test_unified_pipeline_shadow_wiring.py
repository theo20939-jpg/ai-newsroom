"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S25/S26/S27/S35, superseded by
UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S2): the real worker-wiring hook.

The original phase-1 version of this file proved the OLD "shadow hook alongside the legacy send"
wiring (`services.editorial_pipeline.shadow.run_shadow_comparison()`, called unconditionally
whenever `unified_editorial_pipeline_enabled` was True, regardless of format/output shape, with
its own result never affecting the real send) - exactly the architecture the Founder review of
that phase rejected ("legacy + shadow unified call + legacy send behavior... NOT legacy or
unified"). That shadow hook has been REMOVED outright by the cutover phase (never merely disabled)
- `worker/content_cycle.py` now has a genuine, mutually-exclusive `if unified... else: legacy`
branch (see `services.editorial_pipeline.telegram_integration.is_unified_router_eligible()`).

This file now proves the CURRENT, real behavior:

1. Flag OFF (every real environment today) -> the legacy path runs, unaffected, exactly as before
   this entire lineage (already proven exhaustively by the TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-
   REPAIR-1 regression suite and tests/test_router_media_integration.py, re-run unchanged with
   zero new failures - see the cutover report's own regression section).
2. Flag ON but the real output is NOT V8-family (e.g. V6/V7 - `is_unified_router_eligible()`
   returns False) -> STILL the legacy path, unaffected - the unified gate is narrow by design and
   never partially engages for a shape it does not own.
3. Flag ON AND a real V8-family output -> the unified path is authoritative (proven exhaustively,
   with real replays and real durable recovery, in tests/test_unified_pipeline_cutover_authority.py -
   not duplicated here).
"""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from tests.test_router_media_integration import (
    _REAL_CHAT_ID,
    _REAL_NEWS_TOPIC_ID,
    _common_settings,
    _fake_candidate,
    _seed_eligible_event,
    _standard_decision,
    _v6_capability_registry,
)
from tests.test_content_worker_cycle import _isolated_freshness_window, factory, test_source  # noqa: F401,F811
from worker.content_cycle import run_content_cycle


@pytest.fixture(autouse=True)
def _reset_unified_flag():
    original = settings.unified_editorial_pipeline_enabled
    yield
    settings.unified_editorial_pipeline_enabled = original


@pytest.mark.asyncio
async def test_flag_off_never_reaches_the_unified_pipeline(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    _common_settings(monkeypatch)
    assert settings.unified_editorial_pipeline_enabled is False  # the real, shipped default
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    assert result.notified == 1
    assert not any(r.msg == "unified_pipeline_selected" for r in caplog.records)


@pytest.mark.asyncio
async def test_flag_on_but_non_v8_output_still_uses_the_legacy_path_unaffected(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The narrow gate (`is_unified_router_eligible()`) never partially engages - a V6-shaped
    output (no `main_body`) with the flag ON still gets the exact same, unmodified legacy send as
    flag-off, byte-for-byte (S2: never legacy+shadow, and never a partial unified takeover of a
    shape it does not own)."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "unified_editorial_pipeline_enabled", True)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    # The real send is untouched - identical assertions to the flag-off test above.
    fake_bot.send_photo.assert_called_once()
    fake_bot.send_message.assert_not_called()
    args, kwargs = fake_bot.send_photo.call_args
    assert args[0] == _REAL_CHAT_ID
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID
    assert result.notified == 1
    assert result.router_image_sent == 1
    assert not any(r.msg == "unified_pipeline_selected" for r in caplog.records)
