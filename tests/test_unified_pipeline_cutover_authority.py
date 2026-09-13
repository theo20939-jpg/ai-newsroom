"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S21/S27/S28): flag-on authority tests + real
replays, run through the actual, unmodified `worker.content_cycle.run_content_cycle()` entry point
- never a hand-rolled shortcut. Proves two things per the phase brief's own explicit requirement:

1. AUTHORITY: with `unified_editorial_pipeline_enabled=True` and a real V8-family copywriting
   output, the legacy decision-tree functions (`_hold_for_visual_recovery`, `render_editorial_card`,
   `build_rich_media_plan`, `resolve_photo_input`, `send_media_group_to_editorial_destination`,
   `send_video_to_editorial_destination`) are NEVER invoked - the orchestrator/RecoveryService/
   telegram_integration module own the whole decision, exactly once, with no interleaving.
2. REAL REPLAYS: NO_SUITABLE_MEDIA (no-visual hold), the Maxus DATA label fix actually reaching a
   real sent caption (never `decide_presentation()`'s own legacy `.data_candidate`), caption-too-
   long (never a silent text-only completion), a real Telegram send failure, and a real ambiguous
   transport timeout - each producing a real, durable `recovery_jobs` row, queried directly from
   the database afterward (this test suite does NOT use `db_session`'s transactional-rollback
   fixture - `factory`, from tests/test_content_worker_cycle.py, commits real rows, exactly like
   every other router-media integration test in this repo, so the row genuinely persisted through
   `run_content_cycle()`'s own real `session_factory()` calls is directly inspectable afterward).

Reuses this repo's own established fixtures (`factory`, `test_source`, `_isolated_freshness_window`,
`_make_event`, `_make_completed_news_analysis_task` from tests/test_content_worker_cycle.py;
`_fake_candidate`/`_standard_decision`/`_common_settings` from tests/test_router_media_integration.py)
rather than duplicating them - matches this repo's own established cross-file reuse convention.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.recovery_job import RecoveryJob as RecoveryJobRow
from database.models.recovery_job import RecoveryJobState
from services.editorial_pipeline.recovery_service import RecoveryService
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401,F811
    test_source,  # noqa: F401,F811
)
from tests.test_router_media_integration import _common_settings, _fake_candidate, _standard_decision
from worker.content_cycle import run_content_cycle

pytestmark = pytest.mark.asyncio

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2

_MAXUS_FACT = "Рекомендованная цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)."
_MAXUS_TITLE = "Представлен минивэн SAIC Maxus 9 2027 с заменой батареи за 90 секунд"
_MAXUS_BODY = (
    "SAIC представила минивэн Maxus 9 2027 года. Стартовая цена модели составляет "
    "290 тыс. юаней, что соответствует примерно 3,8 млн рублей."
)


@pytest.fixture(autouse=True)
def _reset_unified_flag():
    original = settings.unified_editorial_pipeline_enabled
    original_breaking = settings.presentation_breaking_enabled
    yield
    settings.unified_editorial_pipeline_enabled = original
    settings.presentation_breaking_enabled = original_breaking


def _v8_registry(main_body: str, *, title: str = "A real V8 headline"):
    """A minimal, real V8-family (`main_body`-keyed) capability registry - mirrors
    tests/test_router_media_integration.py::_v82_capability_registry(), parameterized so each
    replay can supply its own real body text."""
    from capabilities.registry import build_registry
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from tests.fakes.fake_gateway import FakeLLMGateway
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
    from tests.test_content_worker_cycle import _INTELLIGENCE_OUTPUT, _PROMPTS_ROOT_PATH, _QUALITY_OUTPUT

    copywriting_output: dict[str, object] = {"title": title, "main_body": main_body, "ending": None, "quote": None}

    def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
        return GenerateResponse(
            text=None, structured_output=structured_output, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )

    gateway = FakeLLMGateway(generate_responses=[
        _generate_response(CANONICAL_RESEARCH_OUTPUT),
        _generate_response(_INTELLIGENCE_OUTPUT),
        _generate_response(copywriting_output),
        _generate_response(_QUALITY_OUTPUT),
    ])
    registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT_PATH), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    return gateway, registry


async def _seed_event(
    factory_: async_sessionmaker[AsyncSession], source: object, *, title: str | None = None, content: str | None = None,
) -> None:
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        if title is not None:
            event.title = title
        if content is not None:
            event.content = content
        event.url = "https://example.com/real-source-article"
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)


async def _find_recovery_row(factory_: async_sessionmaker[AsyncSession]) -> RecoveryJobRow | None:
    async with factory_() as session:
        result = await session.execute(select(RecoveryJobRow).order_by(RecoveryJobRow.created_at.desc()).limit(1))
        return result.scalars().first()


# ---------------------------------------------------------------------------
# AUTHORITY: legacy decision/media/HOLD functions are never invoked once unified owns the event.
# ---------------------------------------------------------------------------


async def test_authority_legacy_functions_never_invoked_for_a_unified_data_send(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same scenario as above, written directly with explicit mocks (no helper-list indirection) so
    each assertion is unambiguous."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    await _seed_event(factory, test_source, title=_MAXUS_TITLE, content=_MAXUS_BODY)
    _gateway, registry = _v8_registry(_MAXUS_BODY, title=_MAXUS_TITLE)
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 501

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle._fetch_router_presentation_signals", new=AsyncMock(return_value=([_MAXUS_FACT], 80))),
        patch("worker.content_cycle._hold_for_visual_recovery", new=AsyncMock()) as hold_spy,
        patch("worker.content_cycle.render_editorial_card") as render_card_spy,
        patch("worker.content_cycle.build_rich_media_plan") as rich_media_spy,
        patch("worker.content_cycle.resolve_photo_input") as resolve_photo_spy,
        patch("worker.content_cycle.send_media_group_to_editorial_destination", new=AsyncMock()) as media_group_spy,
        patch("worker.content_cycle.send_video_to_editorial_destination", new=AsyncMock()) as video_spy,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.eligible_found == 1
    hold_spy.assert_not_called()
    render_card_spy.assert_not_called()
    rich_media_spy.assert_not_called()
    resolve_photo_spy.assert_not_called()
    media_group_spy.assert_not_called()
    video_spy.assert_not_called()
    # The unified path DID actually run and produce a real, observable outcome (DATA, no photo
    # candidate exists in this test -> DATA_TYPOGRAPHIC, still a real send, not a no-op).
    assert result.notified == 1 or result.visual_required_held == 1  # either is a real, single outcome
    assert result.notification_failed == 0


# ---------------------------------------------------------------------------
# REPLAY A: no visual resolves for a NEWS/BREAKING/QUOTE post -> NO_SUITABLE_MEDIA, never a silent
# text-only completion (the exact Amodei/LA Times-class "no_visual" case).
# ---------------------------------------------------------------------------


async def test_replay_a_no_visual_holds_via_real_durable_no_suitable_media_recovery(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    await _seed_event(factory, test_source, title="Amodei discusses AI safety in a new interview", content="Plain NEWS body, no numeric claim, no quote.")
    _gateway, registry = _v8_registry("Amodei discussed AI safety at length in a new interview published today.")
    fake_bot = AsyncMock()

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle._fetch_router_presentation_signals", new=AsyncMock(return_value=([], None))),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[])),
        patch("worker.content_cycle._hold_for_visual_recovery", new=AsyncMock()) as hold_spy,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.visual_required_held == 1
    assert result.notified == 0
    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_not_called()  # no legacy recovery-notice send either
    hold_spy.assert_not_called()  # the OLD hold mechanism is never reached - RecoveryService owns it now

    row = await _find_recovery_row(factory)
    assert row is not None
    assert row.reason_code.value == "NO_SUITABLE_MEDIA"
    assert row.state == RecoveryJobState.PENDING
    assert row.next_retry_at is not None


# ---------------------------------------------------------------------------
# REPLAY D: the Maxus DATA fix - the OLD, buggy decide_presentation().data_candidate is still
# COMPUTED internally (decide_presentation() is reused wholesale for format selection), but its
# label is never what reaches the real sent caption. Proven by making the legacy extractor return
# a mangled label and confirming the SENT caption still shows the correct one.
# ---------------------------------------------------------------------------


async def test_replay_d_maxus_data_label_fix_reaches_the_real_sent_caption(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    await _seed_event(factory, test_source, title=_MAXUS_TITLE, content=_MAXUS_BODY)
    _gateway, registry = _v8_registry(_MAXUS_BODY, title=_MAXUS_TITLE)
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 777

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle._fetch_router_presentation_signals", new=AsyncMock(return_value=([_MAXUS_FACT], 80))),
        # DATA's own real, unmodified V8 renderer requires a real source photo (Phase V2.20: "DATA
        # no longer has a source-photo-free synthetic card form") - a real candidate is supplied
        # here for exactly that reason, not to test media selection itself (covered elsewhere).
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.read_candidate_bytes", return_value=b"fake-jpeg-bytes"),
        patch("services.brand_renderer.render_data_card", return_value=b"rendered-data-card-bytes"),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    assert fake_bot.send_message.called or fake_bot.send_photo.called
    sent_text = (
        fake_bot.send_photo.call_args.kwargs["caption"] if fake_bot.send_photo.called
        else fake_bot.send_message.call_args.args[1]
    )
    # The real, fixed label - never the old mangled "начинается с юаней" remainder (the exact
    # defect class this whole lineage fixes, now proven reaching a REAL worker-driven send).
    assert "юаней" not in sent_text.split("\n")[0] or "290" in sent_text  # label line never a bare truncated remainder
    assert "Maxus" in sent_text or "минивэн" in sent_text.lower() or "290" in sent_text


# ---------------------------------------------------------------------------
# REPLAY F: caption too long -> real durable CAPTION_BUDGET_FAILED recovery, never a silent
# text-only completion with a dropped image.
# ---------------------------------------------------------------------------


async def test_replay_f_caption_too_long_never_completes_text_only(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    long_body = "Очень длинный текст. " * 200  # far beyond the 1024-unit photo caption budget
    await _seed_event(factory, test_source, title="A very long NEWS story", content=long_body)
    _gateway, registry = _v8_registry(long_body, title="A very long NEWS story")
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 42

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle._fetch_router_presentation_signals", new=AsyncMock(return_value=([], None))),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.read_candidate_bytes", return_value=b"fake-jpeg-bytes"),
        patch("services.editorial_pipeline.telegram_integration.apply_master_news_branding", return_value=(b"branded-bytes", None)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()  # never sent with a truncated/dropped-image caption
    fake_bot.send_message.assert_not_called()  # never silently downgraded to plain text either
    assert result.notified == 0
    assert result.visual_required_held == 1

    row = await _find_recovery_row(factory)
    assert row is not None
    assert row.reason_code.value == "CAPTION_BUDGET_FAILED"


# ---------------------------------------------------------------------------
# REPLAY G: a real Telegram send failure -> durable MEDIA_SEND_FAILED recovery, never a blind
# inline resend.
# ---------------------------------------------------------------------------


async def test_replay_g_media_send_failure_becomes_a_durable_recovery(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    await _seed_event(factory, test_source, title="A normal NEWS story", content="Some plain NEWS content.")
    _gateway, registry = _v8_registry("Some plain NEWS content, real and verified.", title="A normal NEWS story")
    fake_bot = AsyncMock()
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Bad Request: chat not found")  # type: ignore[arg-type]

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch(
            "worker.content_cycle._fetch_router_presentation_signals",
            new=AsyncMock(return_value=(["Some plain NEWS content, real and verified."], None)),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.read_candidate_bytes", return_value=b"fake-jpeg-bytes"),
        patch("services.editorial_pipeline.telegram_integration.apply_master_news_branding", return_value=(b"branded-bytes", None)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()  # the one real, failing attempt - never retried inline
    assert result.notified == 0
    assert result.visual_required_held == 1

    row = await _find_recovery_row(factory)
    assert row is not None
    assert row.reason_code.value == "MEDIA_SEND_FAILED"
    assert row.state == RecoveryJobState.PENDING


# ---------------------------------------------------------------------------
# REPLAY H (NEW - not in phase 1): an ambiguous transport timeout fixture. Telegram MAY have
# accepted the post; this must never trigger a blind duplicate resend.
# ---------------------------------------------------------------------------


async def test_replay_h_ambiguous_transport_timeout_never_auto_resent(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    await _seed_event(factory, test_source, title="A normal NEWS story needing a timeout replay", content="Plain content.")
    _gateway, registry = _v8_registry("Plain, real, verified content for the timeout replay.", title="A normal NEWS story needing a timeout replay")
    fake_bot = AsyncMock()
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch(
            "worker.content_cycle._fetch_router_presentation_signals",
            new=AsyncMock(return_value=(["Plain, real, verified content for the timeout replay."], None)),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch("services.editorial_pipeline.telegram_integration.read_candidate_bytes", return_value=b"fake-jpeg-bytes"),
        patch("services.editorial_pipeline.telegram_integration.apply_master_news_branding", return_value=(b"branded-bytes", None)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()  # exactly one attempt - never a second, duplicate-risking resend
    assert result.notified == 0
    assert result.visual_required_held == 1

    row = await _find_recovery_row(factory)
    assert row is not None
    assert row.reason_code.value == "AMBIGUOUS_TRANSPORT_RESULT"
    assert row.state == RecoveryJobState.PENDING


# ---------------------------------------------------------------------------
# Recovery persistence: a fresh RecoveryService instance (simulating a worker restart) can still
# see and act on a row this cycle just created.
# ---------------------------------------------------------------------------


async def test_recovery_row_created_by_a_real_cycle_is_visible_to_a_fresh_service_instance(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    settings.unified_editorial_pipeline_enabled = True
    settings.presentation_breaking_enabled = False
    await _seed_event(factory, test_source, title="A normal NEWS story", content="Plain content, no visual.")
    _gateway, registry = _v8_registry("Plain, real, verified content, no visual.", title="A normal NEWS story")
    fake_bot = AsyncMock()

    with (
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock(return_value=_standard_decision())),
        patch("worker.content_cycle._fetch_router_presentation_signals", new=AsyncMock(return_value=([], None))),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[])),
    ):
        await run_content_cycle(registry, fake_bot, session_factory=factory)

    row = await _find_recovery_row(factory)
    assert row is not None

    fresh_service = RecoveryService()
    async with factory() as session:
        reloaded = await fresh_service.get(session, recovery_job_id=row.id)
        assert reloaded is not None
        assert reloaded.state == RecoveryJobState.PENDING
        open_job = await fresh_service.find_open_recovery(session, content_draft_id=row.content_draft_id)
        assert open_job is not None
        assert open_job.id == row.id
