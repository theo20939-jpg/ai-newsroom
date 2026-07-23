"""Tests for worker.main.main() - the enabled loop, disabled-idle model, and cancellation
semantics (Contract §13/§14). run_automation_cycle is mocked at the worker.main module
boundary; no real collection/triage/DB is exercised here (that belongs to the offline
integration test, tests/test_automation_integration.py)."""
import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

import worker.cycle
from core.config import settings
from worker.main import main


@pytest.mark.asyncio
async def test_enabled_loop_runs_cycles_and_respects_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "news_collection_enabled", True)
    monkeypatch.setattr(settings, "news_collection_interval_seconds", 0.01)

    call_count = 0

    async def fake_cycle() -> None:
        nonlocal call_count
        call_count += 1

    with patch("worker.main.run_automation_cycle", side_effect=fake_cycle):
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
    monkeypatch.setattr(settings, "news_collection_enabled", True)
    monkeypatch.setattr(settings, "news_collection_interval_seconds", 0.01)

    call_count = 0

    async def flaky_cycle() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")

    with patch("worker.main.run_automation_cycle", side_effect=flaky_cycle):
        task = asyncio.create_task(main())
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert call_count >= 2, "loop must survive an ordinary Exception and run a later cycle"


@pytest.mark.asyncio
async def test_cancellation_during_cycle_propagates_and_stops_the_loop() -> None:
    hang = asyncio.Event()

    async def hanging_cycle() -> None:
        await hang.wait()

    with patch("worker.main.run_automation_cycle", side_effect=hanging_cycle):
        with patch.object(settings, "news_collection_enabled", True):
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
    monkeypatch.setattr(settings, "news_collection_enabled", True)
    monkeypatch.setattr(settings, "news_collection_interval_seconds", 30)  # long - will be sleeping

    with patch("worker.main.run_automation_cycle", new=AsyncMock(return_value=None)):
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
    monkeypatch.setattr(settings, "news_collection_enabled", False)
    mocked_cycle = AsyncMock()

    with patch("worker.main.run_automation_cycle", mocked_cycle):
        task = asyncio.create_task(main())
        await asyncio.sleep(0.1)
        assert not task.done(), "disabled worker must remain alive, not exit"
        mocked_cycle.assert_not_called()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1.0)

    mocked_cycle.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_mode_logs_idle_state_exactly_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # worker.main.main() calls core.logging.setup_logging(), which uses
    # logging.basicConfig(force=True) - this replaces the root logger's handlers each call,
    # including pytest's own caplog handler, so stdout capture (what setup_logging() actually
    # streams to) is used here instead of caplog.
    monkeypatch.setattr(settings, "news_collection_enabled", False)

    with patch("worker.main.run_automation_cycle", new=AsyncMock()):
        task = asyncio.create_task(main())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    captured = capsys.readouterr()
    idle_lines = [line for line in captured.out.splitlines() if "automation worker idling" in line]
    assert len(idle_lines) == 1


def test_no_bare_or_baseexception_catch_in_worker_modules() -> None:
    """Static proof the frozen except-Exception-only rule (Contract §13) holds."""
    main_module = inspect.getmodule(main)
    assert main_module is not None

    for module in (main_module, worker.cycle):
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
    worker startup on this development machine's platform (win32 here; Linux/Docker is the
    actual, fully-supported production target - see worker/main.py's own comment)."""
    monkeypatch.setattr(settings, "news_collection_enabled", False)

    task = asyncio.create_task(main())
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
