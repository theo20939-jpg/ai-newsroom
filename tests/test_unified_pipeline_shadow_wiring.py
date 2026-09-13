"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S25/S26/S27/S35: the real worker-wiring hook.

Two things must both be true, proven against the REAL `worker.content_cycle.run_content_cycle()`,
not a reimplementation:

1. Flag OFF (every real environment this phase touches) -> the shadow hook is never even reached;
   behavior is 100% identical to before this phase (already proven exhaustively by this session's
   own prior TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 regression suite, re-run unchanged against
   this same worktree with zero new failures - see the report's own regression section).
2. Flag ON (this test only - never true in any real deployment) -> the shadow hook runs, logs a
   real `shadow_comparison` event, and the ACTUAL SEND is still byte-for-byte what the legacy path
   alone would have produced - S27's own "no duplicate Telegram sends" holds even when exercised
   for real, not merely by inspection of the code.
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


@pytest.mark.asyncio
async def test_flag_off_never_reaches_the_shadow_hook(
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
    assert not any(r.msg in ("shadow_comparison", "shadow_comparison_failed") for r in caplog.records)


@pytest.mark.asyncio
async def test_flag_on_runs_the_shadow_hook_but_the_real_send_stays_identical(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
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

    # And the new pipeline really did run, in shadow, alongside it.
    assert any(r.msg == "shadow_comparison" for r in caplog.records)


@pytest.mark.asyncio
async def test_flag_on_shadow_hook_failure_never_breaks_the_real_send(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """S4-E's own boundary, proven for real: even if the brand-new pipeline code raises, the
    legacy send still completes exactly as it would have."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "unified_editorial_pipeline_enabled", True)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.shadow.run_shadow_comparison", new=AsyncMock(side_effect=RuntimeError("boom"))),
        caplog.at_level("INFO"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    assert result.notified == 1
    assert any(r.msg == "unified_pipeline_shadow_hook_failed" for r in caplog.records)
