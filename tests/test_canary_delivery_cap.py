"""Phase 23.1L Part G - required hard-delivery-cap test cases (docs/
phase23_1l_runtime_isolation_final_canary_report.md).

Pure unit tests plus a small number of real `run_content_cycle()` integration cases (using the
already-established `factory`/`independent_session_factory`/`_v6_capability_registry` fixtures,
now pointed at the isolated `ai_newsroom_test` database per Phase 23.1L Part B/C) - no real
Telegram calls anywhere (fake `Bot`/`AsyncMock`, matching every other test in this suite).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from scripts._canary_delivery_cap import DeliveryCapExhaustedError, HardDeliveryCap, wrap_bot_with_hard_cap
from services.editorial_treatment import STANDARD, EditorialTreatmentDecision
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401,F811
    test_source,  # noqa: F401,F811
)
from tests.test_editorial_delivery_mode import _v6_capability_registry
from worker.content_cycle import run_content_cycle

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2


@pytest.fixture(autouse=True)
def _reset_delivery_mode() -> None:
    """Phase 23.1L Part H fix: the integration test below sets settings.editorial_delivery_mode
    directly (not via monkeypatch) - without this restore, that mutation leaks into every test
    that runs afterward in the same pytest process (settings is a module-level singleton),
    exactly matching tests/test_router_media_integration.py's own established
    `_reset_delivery_mode` convention. A real, evidence-confirmed cause of several tests/
    test_content_cycle_story_delivery.py failures when this file was first added - fixed here,
    not dismissed as unrelated "DB pollution"."""
    original = settings.editorial_delivery_mode
    yield
    settings.editorial_delivery_mode = original


# ---------------------------------------------------------------------------
# Pure unit tests - the cap mechanism itself, no bot/DB involved
# ---------------------------------------------------------------------------


def test_case_1_cap_allows_exactly_max_deliveries_attempts() -> None:
    cap = HardDeliveryCap(max_deliveries=5)
    for _ in range(5):
        cap.try_consume()
    assert cap.attempted == 5
    with pytest.raises(DeliveryCapExhaustedError):
        cap.try_consume()
    assert cap.attempted == 5  # the rejected 6th attempt never increments


def test_case_2_cap_of_one_allows_exactly_one_attempt() -> None:
    cap = HardDeliveryCap(max_deliveries=1)
    cap.try_consume()
    with pytest.raises(DeliveryCapExhaustedError):
        cap.try_consume()
    assert cap.attempted == 1


def test_case_3_cap_of_zero_allows_zero_attempts() -> None:
    cap = HardDeliveryCap(max_deliveries=0)
    with pytest.raises(DeliveryCapExhaustedError):
        cap.try_consume()
    assert cap.attempted == 0


def test_case_4_partial_remaining_allowance_only_permits_the_remaining_count() -> None:
    """delivered=4, batch=5, max=5 -> only the first (5th overall) permitted delivery occurs."""
    cap = HardDeliveryCap(max_deliveries=5)
    for _ in range(4):
        cap.try_consume()
    assert cap.remaining == 1
    cap.try_consume()  # the 5th - allowed
    assert cap.remaining == 0
    with pytest.raises(DeliveryCapExhaustedError):
        cap.try_consume()  # the would-be 6th - refused


def test_case_7_no_sixth_send_can_occur_after_a_successful_fifth_in_the_same_batch() -> None:
    cap = HardDeliveryCap(max_deliveries=5)
    results = []
    for i in range(7):
        try:
            cap.try_consume(label=f"attempt-{i}")
            results.append("sent")
        except DeliveryCapExhaustedError:
            results.append("refused")
    assert results == ["sent"] * 5 + ["refused"] * 2
    assert cap.attempted == 5


def test_case_6_a_failed_send_still_consumes_the_cap_by_design() -> None:
    """Documents the deliberate semantic: try_consume() runs BEFORE the real send attempt, so a
    subsequent failure (real Telegram error) does not refund the budget - the cap bounds "at most
    N real calls reach the Telegram API", not "at most N successful deliveries". A refunding
    design would let an unbounded number of failing attempts bypass the cap entirely."""
    cap = HardDeliveryCap(max_deliveries=2)
    cap.try_consume()  # attempt 1 - imagine this one goes on to fail in the real send
    # no refund call exists anywhere in this module - the budget is already spent
    assert cap.attempted == 1
    assert cap.remaining == 1
    cap.try_consume()  # attempt 2
    assert cap.remaining == 0
    with pytest.raises(DeliveryCapExhaustedError):
        cap.try_consume()  # attempt 3 - refused, even though attempt 1 "failed" hypothetically


@pytest.mark.asyncio
async def test_wrapped_bot_send_message_is_gated_by_the_cap_before_reaching_the_real_method() -> None:
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1
    cap = HardDeliveryCap(max_deliveries=2)
    wrap_bot_with_hard_cap(fake_bot, cap)

    await fake_bot.send_message(123, "hello")
    await fake_bot.send_message(123, "world")
    with pytest.raises(DeliveryCapExhaustedError):
        await fake_bot.send_message(123, "refused")

    assert cap.attempted == 2


@pytest.mark.asyncio
async def test_wrapped_bot_send_photo_is_also_gated_independently_toward_the_same_shared_cap() -> None:
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    fake_bot.send_message.return_value.message_id = 2
    cap = HardDeliveryCap(max_deliveries=2)
    wrap_bot_with_hard_cap(fake_bot, cap)

    await fake_bot.send_photo(123, photo="file-id")
    await fake_bot.send_message(123, "text")  # shares the SAME cap as send_photo
    with pytest.raises(DeliveryCapExhaustedError):
        await fake_bot.send_photo(123, photo="file-id-2")

    assert cap.attempted == 2


# ---------------------------------------------------------------------------
# Integration-level proof: a real run_content_cycle() call, wrapped bot, exactly the Phase 23.1K
# incident shape (more eligible drafts than the remaining allowance) - proves the fix at the
# actual call site, not just the cap object in isolation.
# ---------------------------------------------------------------------------


def _standard_decision() -> EditorialTreatmentDecision:
    return EditorialTreatmentDecision(STANDARD, human_review_required=False, reason="test")


@pytest.mark.asyncio
async def test_case_1_integration_six_eligible_drafts_produce_exactly_five_real_sends(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CASE 1 (Part G): max_deliveries=5, 6 eligible drafts -> exactly 5 bot sends."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")
    monkeypatch.setattr(settings, "content_generation_batch_size", 6)
    monkeypatch.setattr(settings, "content_generation_scan_limit", 10)

    async with factory() as session:
        for _ in range(6):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            session.add(event)
            await session.commit()
            await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1
    underlying_mock = fake_bot.send_message  # captured before wrap_bot_with_hard_cap replaces
    # fake_bot.send_message with a plain function - still the same AsyncMock the wrapper's
    # `original_send_message` closes over, so its own call_count keeps counting real delegated
    # calls (5), never the refused 6th (which raises before delegating).
    cap = HardDeliveryCap(max_deliveries=5)
    wrap_bot_with_hard_cap(fake_bot, cap)

    # _v6_capability_registry()'s FakeLLMGateway only queues one event's worth (4) of
    # Research/Intelligence/Copywriting/Quality responses; it repeats the LAST one (Quality)
    # forever once exhausted rather than raising, which breaks later events' Research/
    # Intelligence steps (wrong shape). Six events need six full cycles queued up front.
    _gateway, registry = _v6_capability_registry()
    _gateway._generate_responses = _gateway._generate_responses * 6  # type: ignore[attr-defined]
    try:
        await run_content_cycle(registry, fake_bot, session_factory=factory)
    except Exception:
        pass  # the 6th candidate's send raises DeliveryCapExhaustedError inside the cycle - the
        # assertions below are what actually matters, not whether run_content_cycle() itself
        # surfaces or swallows that specific exception.

    assert underlying_mock.call_count == 5
    assert cap.attempted == 5
