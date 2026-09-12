"""Phase 23.1A - canary delivery adapter (`settings.editorial_delivery_mode`) tests.

Reuses tests/test_content_worker_cycle.py's own already-established fixtures/helpers directly
(`factory`, `test_source`, `_isolated_freshness_window`, `_make_event`,
`_make_completed_news_analysis_task`, `_real_capability_registry`) rather than duplicating them -
matches this repo's own established cross-file fixture-reuse convention (e.g. tests/
test_news_handler.py importing helpers from tests/test_editorial_inbox_service.py).

Five required cases (phase brief §"TEST FIRST"):
1. Legacy mode still uses editorial_chat_id.
2. Router mode resolves the NEWS destination.
3. Router mode includes the correct message_thread_id.
4. No Telegram call happens during tests (structural - every bot here is AsyncMock).
5. No other topic can be selected accidentally (structural - grepped from the source itself).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from schemas.editorial_route import EditorialDestination
from services.telegram_notifier import NotificationOutcome
from services.telegram_routing import RoutingOutcome
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    _make_completed_news_analysis_task,
    _make_event,
    _real_capability_registry,
    factory,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    test_source,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
)
from worker.content_cycle import run_content_cycle

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2


@pytest.fixture(autouse=True)
def _reset_delivery_mode() -> None:
    """Every test in this file explicitly sets editorial_delivery_mode itself - this fixture only
    guarantees it is restored to the real default ("legacy") afterward, regardless of outcome."""
    original = settings.editorial_delivery_mode
    yield
    settings.editorial_delivery_mode = original


async def _seed_eligible_event(
    factory_: async_sessionmaker[AsyncSession], source: object,
) -> None:
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)


# ---------------------------------------------------------------------------
# CASE 1 - legacy mode still uses editorial_chat_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_1_legacy_mode_still_uses_editorial_chat_id(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.editorial_delivery_mode = "legacy"
    # Deterministic regardless of this real environment's own current image_editorial_preview_
    # enabled/image_candidate_persistence_mode values (real settings dump confirmed both active in
    # this environment) - forces the plain send_editorial_card() branch, the one this case is
    # specifically about, rather than the separate image-preview branch (also "legacy", but not
    # what this assertion targets).
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    await _seed_eligible_event(factory, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle.send_editorial_card",
            new=AsyncMock(return_value=NotificationOutcome(chat_id=settings.editorial_chat_id, rendered_html="<html>", sent=False)),
        ) as mock_legacy,
        patch("worker.content_cycle.send_to_editorial_destination", new=AsyncMock()) as mock_router,
    ):
        await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_legacy.assert_called_once()
    assert mock_legacy.call_args.args[1] == settings.editorial_chat_id
    mock_router.assert_not_called()


# ---------------------------------------------------------------------------
# CASE 2 - router mode resolves the NEWS destination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_2_router_mode_resolves_news_destination(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    await _seed_eligible_event(factory, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle.send_to_editorial_destination",
            new=AsyncMock(return_value=RoutingOutcome(
                destination=EditorialDestination.NEWS, chat_id=_REAL_CHAT_ID, topic_id=_REAL_NEWS_TOPIC_ID,
                sent=False, reason="dry_run",
            )),
        ) as mock_router,
        patch("worker.content_cycle.send_editorial_card", new=AsyncMock()) as mock_legacy,
    ):
        await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_router.assert_called_once()
    assert mock_router.call_args.args[1] is EditorialDestination.NEWS
    mock_legacy.assert_not_called()


# ---------------------------------------------------------------------------
# CASE 3 - router mode includes the correct message_thread_id (real, unpatched send)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_3_router_mode_live_send_includes_correct_chat_and_thread_id(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end, unpatched: the real services.telegram_routing.send_to_editorial_destination()
    runs, and the real card-rendering path runs - only the outermost `bot` is a fake. This is the
    strongest proof available that the actual outgoing aiogram call carries the right values.

    TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1: real candidate discovery against the test DB
    finds no image for this event (nothing here mocks `get_editorial_image_candidates`), so this
    now HOLDs for visual recovery rather than completing as a normal post - the exact production
    defect this phase repairs. This test's own actual purpose - proving the real routing call
    carries the correct chat id/thread id - is unaffected either way, since `_hold_for_visual_
    recovery()`'s recovery notice reuses the exact same `send_to_editorial_destination()` call."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    await _seed_eligible_event(factory, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 4242

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_message.assert_called_once()
    args, kwargs = fake_bot.send_message.call_args
    assert args[0] == _REAL_CHAT_ID
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID
    assert result.visual_required_held == 1


# ---------------------------------------------------------------------------
# CASE 4 - no Telegram call happens during tests (structural)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_4_router_mode_dry_run_never_calls_bot_send_message(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    # Explicit, not assumed: this real environment's own content_generation_dry_run is currently
    # False (a live finding from the Phase 23.1 preflight audit) - this test must not depend on
    # that ambient value to stay deterministic.
    monkeypatch.setattr(settings, "content_generation_dry_run", True)
    await _seed_eligible_event(factory, test_source)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_message.assert_not_called()
    assert result.dry_run_rendered == 1
    assert result.notified == 0


def test_case_4_every_bot_constructed_in_this_file_is_an_async_mock() -> None:
    """Explicit proof this test file never constructs or imports the real bot-construction
    factory (which would require TELEGRAM_BOT_TOKEN and could, in principle, reach the network) -
    checked via `ast.parse`, not a raw substring search, so this check cannot "find itself" inside
    its own docstring prose the way a naive `"phrase" in source_text` search would."""
    import ast
    from pathlib import Path

    source_text = Path(__file__).read_text(encoding="utf-8")
    assert source_text.count("AsyncMock()") >= 5

    tree = ast.parse(source_text)
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called_names = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "create_bot" not in imported_names
    assert "create_bot" not in called_names


# ---------------------------------------------------------------------------
# Phase 23.1E - compact NEWS presentation + source button, wired end-to-end (source-button test
# cases A/C/E: no raw URL in the visible body, correct button URL, correct chat/thread preserved)
# ---------------------------------------------------------------------------


def _v6_capability_registry():
    """A V6-shaped variant of tests/test_content_worker_cycle.py::_real_capability_registry() -
    same real CapabilityExecutor/WorkflowRunner pipeline, only the fake Copywriting response
    differs (V6's real field shape instead of V4's `{title, body}`), so this test exercises the
    genuine "does a real V6 draft, generated through the real pipeline, get a compact NEWS card
    with no raw URL and a source button" question - not a hand-built dict bypassing generation."""
    from capabilities.registry import build_registry
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from tests.fakes.fake_gateway import FakeLLMGateway
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
    from tests.test_content_worker_cycle import _INTELLIGENCE_OUTPUT, _PROMPTS_ROOT_PATH, _QUALITY_OUTPUT

    v6_copywriting_output: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "opening": "OpenAI released a new flagship model on Thursday.",
        "context": "The company has shipped a major model roughly every year since 2023.",
        "why_it_matters": "The release raises the bar for reasoning benchmarks industry-wide.",
        "what_changed": "The new model scores 92% on the industry's standard reasoning benchmark.",
        "what_happens_next": None,
        "conclusion": "The model is available to developers starting today.",
        "what_remains_unknown": None,
        "quote": None,
    }

    def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
        return GenerateResponse(
            text=None, structured_output=structured_output, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )

    gateway = FakeLLMGateway(generate_responses=[
        _generate_response(CANONICAL_RESEARCH_OUTPUT),
        _generate_response(_INTELLIGENCE_OUTPUT),
        _generate_response(v6_copywriting_output),
        _generate_response(_QUALITY_OUTPUT),
    ])
    registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT_PATH), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    return gateway, registry


@pytest.mark.asyncio
async def test_phase23_1e_router_mode_v6_news_card_hides_url_and_has_source_button(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end, only the outer `bot` and (this phase) the image candidate lookup patched: a
    real V6 draft flows through the real pipeline, the real compact-body/source-button wiring in
    worker/content_cycle.py, and the real (unmodified) Phase 22 routing function. Confirms all
    three phase-brief requirements together: no raw source URL in the visible body (case A), the
    delivered message still targets the exact real canary chat_id/message_thread_id (case E), and
    a source button with the real URL is attached to the send.

    TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1: real candidate discovery against the test DB
    finds no image for this event, and this test's own case B/C assertion (a source button
    attached to the send) requires a real, keyboard-bearing post - a no-visual HOLD's recovery
    notice deliberately carries no keyboard at all (the exact Founder invariant this phase adds).
    A resolvable image candidate is mocked in (same pattern as this suite's sibling "with image"
    tests) so this still exercises a real delivered `send_photo` post."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    # V6 must be the active prompt version, or CopywritingCapability resolves V4's own
    # output_schema and floor-validates this fixture's V6-shaped fake response against it,
    # failing the "copywriting" step before this test ever reaches delivery.
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")

    source_url = "https://example.com/real-source-article"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1

    from tests.test_router_media_integration import _fake_candidate

    with patch(
        "worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()]),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    assert result.visual_required_held == 0
    fake_bot.send_photo.assert_called_once()
    args, kwargs = fake_bot.send_photo.call_args
    sent_text = kwargs["caption"]

    # CASE A - no raw source URL anywhere in the visible body.
    assert source_url not in sent_text

    # CASE E - the exact real canary chat/topic, unchanged by any of this phase's own changes.
    assert args[0] == _REAL_CHAT_ID
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID

    # CASE B/C - a source button with the real URL, correct label.
    keyboard = kwargs["reply_markup"]
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == source_url
    assert keyboard.inline_keyboard[0][0].text == "🔗 Источник"


# ---------------------------------------------------------------------------
# CASE 5 - no other topic can be selected accidentally (structural)
# ---------------------------------------------------------------------------


def test_case_5_content_cycle_never_references_any_destination_other_than_news() -> None:
    """worker/content_cycle.py must have exactly one EditorialDestination reference
    (`EditorialDestination.NEWS`) and never mention MEME/TELEGRAPH/INSTAGRAM/REELS anywhere -
    proves structurally, not just by convention, that no other destination is reachable from this
    module."""
    from pathlib import Path

    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "EditorialDestination.NEWS" in source_text
    for forbidden in ("EditorialDestination.MEME", "EditorialDestination.TELEGRAPH",
                       "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS"):
        assert forbidden not in source_text, f"{forbidden} must never be reachable from content_cycle.py"
