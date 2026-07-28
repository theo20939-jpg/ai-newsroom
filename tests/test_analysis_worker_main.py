"""Tests for worker.analysis_main.main() - the enabled loop, disabled-idle model, and
cancellation semantics (Phase 13 M4). Mirrors tests/test_worker_main.py's own established
8-test shape exactly, adapted for the extra boot step (assemble_ai_integration_layer(), also
mocked at the module boundary - no real provider/Redis/network is ever touched here)."""
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import worker.analysis_cycle
from core.config import settings
from worker.analysis_main import main

_FAKE_AI_LAYER = SimpleNamespace(capability_registry=object(), cost_tracker=object())


@pytest.mark.asyncio
async def test_enabled_loop_runs_cycles_and_respects_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "news_analysis_enabled", True)
    monkeypatch.setattr(settings, "news_analysis_poll_interval_seconds", 0.01)

    call_count = 0

    async def fake_cycle(*args, **kwargs) -> None:
        nonlocal call_count
        call_count += 1

    with patch("worker.analysis_main.assemble_ai_integration_layer", return_value=_FAKE_AI_LAYER):
        with patch("worker.analysis_main.run_analysis_cycle", side_effect=fake_cycle):
            task = asyncio.create_task(main())
            await asyncio.sleep(0.15)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert call_count >= 2, "expected more than one cycle across several short intervals"


@pytest.mark.asyncio
async def test_enabled_loop_survives_ordinary_exception_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "news_analysis_enabled", True)
    monkeypatch.setattr(settings, "news_analysis_poll_interval_seconds", 0.01)

    call_count = 0

    async def flaky_cycle(*args, **kwargs) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")

    with patch("worker.analysis_main.assemble_ai_integration_layer", return_value=_FAKE_AI_LAYER):
        with patch("worker.analysis_main.run_analysis_cycle", side_effect=flaky_cycle):
            task = asyncio.create_task(main())
            await asyncio.sleep(0.15)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert call_count >= 2, "loop must survive an ordinary Exception and run a later cycle"


@pytest.mark.asyncio
async def test_cancellation_during_cycle_propagates_and_stops_the_loop() -> None:
    hang = asyncio.Event()

    async def hanging_cycle(*args, **kwargs) -> None:
        await hang.wait()

    with patch("worker.analysis_main.assemble_ai_integration_layer", return_value=_FAKE_AI_LAYER):
        with patch("worker.analysis_main.run_analysis_cycle", side_effect=hanging_cycle):
            with patch.object(settings, "news_analysis_enabled", True):
                task = asyncio.create_task(main())
                await asyncio.sleep(0.05)
                assert not task.done()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.done()


@pytest.mark.asyncio
async def test_cancellation_during_interval_sleep_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "news_analysis_enabled", True)
    monkeypatch.setattr(settings, "news_analysis_poll_interval_seconds", 30)  # long - will be sleeping

    with patch("worker.analysis_main.assemble_ai_integration_layer", return_value=_FAKE_AI_LAYER):
        with patch("worker.analysis_main.run_analysis_cycle", new=AsyncMock(return_value=None)):
            task = asyncio.create_task(main())
            await asyncio.sleep(0.05)  # let the one immediate cycle finish; now sleeping
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_disabled_mode_runs_zero_cycles_and_touches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "news_analysis_enabled", False)
    mocked_cycle = AsyncMock()
    mocked_boot = AsyncMock()

    with patch("worker.analysis_main.assemble_ai_integration_layer", mocked_boot):
        with patch("worker.analysis_main.run_analysis_cycle", mocked_cycle):
            task = asyncio.create_task(main())
            await asyncio.sleep(0.1)
            assert not task.done(), "disabled worker must remain alive, not exit"
            mocked_cycle.assert_not_called()
            mocked_boot.assert_not_called()  # no AI layer assembled while disabled

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1.0)

    mocked_cycle.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_mode_logs_idle_state_exactly_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # worker.analysis_main.main() calls core.logging.setup_logging(), which uses
    # logging.basicConfig(force=True) - this replaces the root logger's handlers each call,
    # including pytest's own caplog handler, so stdout capture is used here instead of caplog
    # (mirrors tests/test_worker_main.py's own identical rationale).
    monkeypatch.setattr(settings, "news_analysis_enabled", False)

    with patch("worker.analysis_main.assemble_ai_integration_layer", new=AsyncMock()):
        with patch("worker.analysis_main.run_analysis_cycle", new=AsyncMock()):
            task = asyncio.create_task(main())
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    captured = capsys.readouterr()
    idle_lines = [line for line in captured.out.splitlines() if "analysis worker idling" in line]
    assert len(idle_lines) == 1


def test_no_bare_or_baseexception_catch_in_worker_modules() -> None:
    """Static proof the frozen except-Exception-only rule holds, mirroring
    tests/test_worker_main.py's own identical check."""
    main_module = inspect.getmodule(main)
    assert main_module is not None

    for module in (main_module, worker.analysis_cycle):
        source = inspect.getsource(module)
        assert "except:" not in source, f"{module.__name__} must not use a bare except"
        assert "except BaseException" not in source, (
            f"{module.__name__} must not catch BaseException"
        )


@pytest.mark.asyncio
async def test_main_starts_without_crashing_on_this_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the NotImplementedError guard around loop.add_signal_handler() does not crash
    worker startup on this development machine's platform - mirrors
    tests/test_worker_main.py's own identical proof."""
    monkeypatch.setattr(settings, "news_analysis_enabled", False)

    task = asyncio.create_task(main())
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cycle_level_infrastructure_failure_logs_and_waits_for_next_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§18's MINOR-2 correction: a cycle-level infrastructure failure (the cycle's own outer
    call raises) is logged via analysis_cycle_failed and the loop does not crash - it waits for
    the next poll interval rather than retrying immediately, exactly like worker/main.py's own
    already-proven ordinary-exception-survival behavior."""
    monkeypatch.setattr(settings, "news_analysis_enabled", True)
    monkeypatch.setattr(settings, "news_analysis_poll_interval_seconds", 0.01)

    call_count = 0

    async def always_raises(*args, **kwargs) -> None:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("simulated DB unavailable")

    with patch("worker.analysis_main.assemble_ai_integration_layer", return_value=_FAKE_AI_LAYER):
        with patch("worker.analysis_main.run_analysis_cycle", side_effect=always_raises):
            with patch("worker.analysis_main.logger") as mock_logger:
                task = asyncio.create_task(main())
                await asyncio.sleep(0.1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    assert call_count >= 2, "loop must continue past a cycle-level infrastructure failure"
    assert mock_logger.exception.called
    assert mock_logger.exception.call_args[0][0] == "analysis_cycle_failed"
