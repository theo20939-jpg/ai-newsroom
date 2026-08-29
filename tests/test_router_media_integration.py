"""Phase 23.1H - router media integration tests (docs/phase23_1h_text_image_canary_report.md).

Reuses tests/test_content_worker_cycle.py's own established fixtures/helpers
(`factory`, `test_source`, `_isolated_freshness_window`, `_make_event`,
`_make_completed_news_analysis_task`) and tests/test_editorial_delivery_mode.py's own
`_v6_capability_registry()` (a real V6-shaped CONTENT_GENERATION pipeline) - matches this repo's
own established cross-file fixture-reuse convention, never duplicated.

Strategy: the Editorial Treatment decision and the image-candidate lookup are both patched at
their exact call sites in worker/content_cycle.py (`_classify_event_for_router_treatment`,
`get_editorial_image_candidates`, `resolve_photo_input`) rather than deep-seeding
NEWS_ANALYSIS/ImageCandidateRecord rows for every case - `services/editorial_treatment.py`'s own
decision logic is already covered by tests/test_editorial_treatment.py; these tests exist to prove
the *wiring* (does content_cycle.py actually honor a SKIP/BRIEF/STANDARD/MAJOR decision and a
resolved/unresolved image candidate the way the phase brief requires), not to re-derive realistic
underlying significance/evidence data for every scenario.

Required cases (phase brief Part B): A (valid image -> send_photo), B (no image -> send_message),
C (invalid image -> safe text-only fallback), D (SKIP with image -> zero Telegram calls), E (BRIEF
+ image -> image never changes text/treatment), F (STANDARD + image -> normal compact caption),
G (MAJOR near caption limit -> safe fallback, no truncation), H (missing source URL -> works
without a broken button), I (router isolation - exact chat/topic), J (legacy regression), K (other
destinations unchanged), L (no real Telegram calls in tests - structural).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from aiogram.types import InputMediaVideo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.content_draft_quote import ContentDraftQuote
from services.editorial_treatment import BRIEF, MAJOR, SKIP, STANDARD, EditorialTreatmentDecision
from services.image_persistence import EditorialImageCandidate
from services.telegram_notifier import NotificationOutcome
from services.video_discovery_persistence import EligibleVideoCandidate
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
    test_source,  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
)
from tests.test_editorial_delivery_mode import _v6_capability_registry
from worker.content_cycle import run_content_cycle

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2


@pytest.fixture(autouse=True)
def _reset_delivery_mode() -> None:
    original = settings.editorial_delivery_mode
    yield
    settings.editorial_delivery_mode = original


async def _seed_eligible_event(
    factory_: async_sessionmaker[AsyncSession], source: object, *,
    url: str | None = "https://example.com/article", title: str | None = None,
) -> None:
    async with factory_() as session:
        event = await _make_event(session, source, published_at=datetime.now(timezone.utc))
        event.url = url
        if title is not None:
            event.title = title
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)


def _fake_candidate(
    *, resolvable: bool = True, is_expired: bool = False, candidate_id: str = "cand-1",
    rank: int = 1, quality_score: int = 90, relevance_score: int = 90,
    width: int | None = 1200, height: int | None = 800, warnings: list | None = None,
    sha256: str | None = None, perceptual_hash: str | None = None, final_url: str | None = None,
) -> EditorialImageCandidate:
    return EditorialImageCandidate(
        id=uuid4(), candidate_id=candidate_id, rank=rank, relevance_score=relevance_score, quality_score=quality_score,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=width, height=height, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key="fake/key.jpg",
        telegram_file_id="FAKE_FILE_ID_123" if resolvable else None,
        editor_decision=None,
        source_url=f"https://example.com/{candidate_id}.jpg" if candidate_id != "cand-1" else "https://example.com/img.jpg",
        article_url="https://example.com/article",
        warnings=warnings, is_expired=is_expired,
        sha256=sha256, perceptual_hash=perceptual_hash, final_url=final_url,
    )


def _standard_decision() -> EditorialTreatmentDecision:
    return EditorialTreatmentDecision(STANDARD, human_review_required=False, reason="test")


def _common_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")


# ---------------------------------------------------------------------------
# CASE A / F - NEWS with a valid image -> send_photo (STANDARD)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_a_valid_image_sends_photo_with_caption_and_source_button(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    fake_bot.send_message.assert_not_called()
    args, kwargs = fake_bot.send_photo.call_args
    assert args[0] == _REAL_CHAT_ID
    assert kwargs["photo"] == "FAKE_FILE_ID_123"
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID
    keyboard = kwargs["reply_markup"]
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == "https://example.com/article"
    assert result.notified == 1
    assert result.router_image_sent == 1


# ---------------------------------------------------------------------------
# CASE B - NEWS without an image -> send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_b_no_image_candidates_sends_text_only(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 222

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[])),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_message.assert_called_once()
    fake_bot.send_photo.assert_not_called()
    args, kwargs = fake_bot.send_message.call_args
    assert args[0] == _REAL_CHAT_ID
    assert kwargs["reply_markup"] is not None
    assert result.notified == 1
    assert result.router_image_sent == 0


# ---------------------------------------------------------------------------
# CASE C - an image candidate exists but cannot be resolved -> safe text-only fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_c_unresolvable_image_falls_back_to_text_only_without_crashing(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 333

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate(resolvable=False)]),
        ),
        patch("worker.content_cycle.resolve_photo_input", return_value=None),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_called_once()
    assert result.notified == 1
    assert result.notification_failed == 0


# ---------------------------------------------------------------------------
# CASE D - SKIP with an image available -> zero Telegram calls, no content generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_d_skip_decision_makes_zero_telegram_calls_and_skips_content_generation(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    skip_decision = EditorialTreatmentDecision(SKIP, human_review_required=False, reason="weak evidence + negative recommendation")

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=skip_decision),
        ),
        patch(
            "worker.content_cycle.run_content_generation_for_event", new=AsyncMock(),
        ) as mock_content_gen,
        patch(
            "worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()]),
        ) as mock_images,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_not_called()
    mock_content_gen.assert_not_called()  # no Copywriting call - treatment gates BEFORE generation
    mock_images.assert_not_called()  # no ContentDraft ever existed to look up image candidates for
    assert result.treatment_skipped == 1
    assert result.notified == 0
    assert result.completed == 0


# ---------------------------------------------------------------------------
# CASE E - BRIEF with an image present must not change the text/treatment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_e_image_presence_never_changes_brief_text(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    brief_decision = EditorialTreatmentDecision(BRIEF, human_review_required=False, reason="test")

    async def _run_once(with_image: bool) -> str:
        await _seed_eligible_event(factory, test_source, title="Fixed title for case E comparison")
        _gateway, registry = _v6_capability_registry()
        fake_bot = AsyncMock()
        fake_bot.send_photo.return_value.message_id = 1
        fake_bot.send_message.return_value.message_id = 1
        candidates = [_fake_candidate()] if with_image else []
        with (
            patch(
                "worker.content_cycle._classify_event_for_router_treatment",
                new=AsyncMock(return_value=brief_decision),
            ),
            patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
        ):
            await run_content_cycle(registry, fake_bot, session_factory=factory)
        if with_image:
            return fake_bot.send_photo.call_args.kwargs["caption"]
        return fake_bot.send_message.call_args.args[1]

    text_without_image = await _run_once(False)
    text_with_image = await _run_once(True)
    assert text_without_image == text_with_image


# ---------------------------------------------------------------------------
# CASE G - MAJOR content too long for a photo caption -> safe fallback, no truncation
# ---------------------------------------------------------------------------


def _long_v6_capability_registry():
    """Mirrors tests/test_editorial_delivery_mode.py::_v6_capability_registry() but with enough
    distinct V6 section content that the rendered card (header + title + MAJOR-tier body) exceeds
    Telegram's 1024-code-unit photo-caption limit while staying well under the 4096 plain-message
    limit - the exact scenario CASE G requires."""
    from capabilities.registry import build_registry
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from tests.fakes.fake_gateway import FakeLLMGateway
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
    from tests.test_content_worker_cycle import _INTELLIGENCE_OUTPUT, _PROMPTS_ROOT_PATH, _QUALITY_OUTPUT

    # Phase 23.1I Part E "Importance-Aware Brevity V2" reduced MAJOR's own paragraph cap (6->4)
    # and added a real ~900-character ceiling - the "two-paragraph default" (opening + why_it_
    # matters, always kept regardless of ceiling) must, ON ITS OWN, already exceed Telegram's
    # 1024-code-unit photo-caption limit (once header/title overhead is added) for this fixture to
    # still exercise CASE G's caption-overflow fallback - a shorter MAJOR post (Brevity V2's own
    # intended, desired outcome) would otherwise simply fit the caption now, which is correct
    # behavior, not a fixture bug, but defeats this specific test's purpose. `context`/`what_
    # changed`/`what_happens_next` stay distinct but are no longer load-bearing for the overflow
    # itself, since MAJOR's own two-paragraph default is what must already be long enough.
    v6_copywriting_output: dict[str, object] = {
        "title": "A major story with a lot of distinct, verified detail",
        "opening": (
            "Компания объявила о запуске нового завода по производству аккумуляторов "
            "мощностью пятьдесят гигаватт-часов в год, создав более трёх тысяч рабочих мест "
            "в регионе уже к концу следующего года согласно официальному заявлению, которое "
            "было сделано на пресс-конференции с участием представителей местной администрации "
            "и профильного министерства промышленности региона в присутствии журналистов, "
            "иностранных инвесторов и представителей отраслевых объединений производителей "
            "аккумуляторов и электромобилей со всего региона, включая соседние страны."
        ),
        "context": (
            "Строительство началось два года назад после получения разрешений от местных "
            "властей и завершения экологической экспертизы проекта, которая заняла почти "
            "восемнадцать месяцев из-за протестов жителей соседних населённых пунктов."
        ),
        "why_it_matters": (
            "Для отрасли электромобилей это означает существенное снижение зависимости от "
            "импортных батарей и потенциальное удешевление конечных автомобилей примерно на "
            "двенадцать процентов уже в течение первых двух лет полноценной эксплуатации, что "
            "может заметно повлиять на конкурентоспособность местных производителей на "
            "внутреннем и внешнем рынках в условиях растущего спроса на электротранспорт, "
            "особенно на фоне ужесточения экологических требований и роста цен на сырьё "
            "для аккумуляторов в большинстве стран-импортёров этой продукции."
        ),
        "what_changed": (
            "Ранее компания импортировала все аккумуляторные ячейки из-за рубежа, что "
            "создавало логистические риски и увеличивало итоговую стоимость производства "
            "транспортных средств почти на четверть по сравнению с локальным производством."
        ),
        "what_happens_next": (
            "Вторая очередь завода должна открыться через восемнадцать месяцев и увеличит "
            "производственную мощность вдвое, до ста гигаватт-часов ежегодно."
        ),
        "conclusion": (
            "Аналитики называют этот запуск одним из крупнейших промышленных проектов "
            "региона за последнее десятилетие с прямыми инвестициями свыше двух миллиардов."
        ),
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
async def test_case_g_major_over_caption_limit_falls_back_to_text_only_without_truncation(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _long_v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 444
    major_decision = EditorialTreatmentDecision(MAJOR, human_review_required=False, reason="test")

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=major_decision),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()  # too long for a caption - safe fallback used instead
    fake_bot.send_message.assert_called_once()
    sent_text = fake_bot.send_message.call_args.args[1]
    assert "…" not in sent_text  # no word-boundary squeeze/truncation marker anywhere
    assert result.notified == 1
    assert result.router_image_sent == 0


# ---------------------------------------------------------------------------
# CASE H - missing source URL: delivery still works, no broken button
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_h_missing_source_url_still_delivers_with_no_keyboard(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source, url=None)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 555

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    assert fake_bot.send_photo.call_args.kwargs["reply_markup"] is None
    assert result.notified == 1
    assert result.notification_failed == 0


# ---------------------------------------------------------------------------
# CASE I - router isolation: exact real canary chat_id/message_thread_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_i_router_isolation_targets_the_exact_canary_chat_and_topic(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 666

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        await run_content_cycle(registry, fake_bot, session_factory=factory)

    args, kwargs = fake_bot.send_photo.call_args
    assert args[0] == _REAL_CHAT_ID == -1004297182444
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID == 2


# ---------------------------------------------------------------------------
# CASE J - legacy mode regression: unchanged, none of this phase's new code paths run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_j_legacy_mode_never_touches_treatment_or_photo_routing(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.editorial_delivery_mode = "legacy"
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle.send_editorial_card",
            new=AsyncMock(return_value=NotificationOutcome(chat_id=settings.editorial_chat_id, rendered_html="<html>", sent=False)),
        ) as mock_legacy,
        patch("worker.content_cycle._classify_event_for_router_treatment", new=AsyncMock()) as mock_treatment,
        patch("worker.content_cycle.send_photo_to_editorial_destination", new=AsyncMock()) as mock_send_photo,
    ):
        await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_legacy.assert_called_once()
    mock_treatment.assert_not_called()
    mock_send_photo.assert_not_called()


# ---------------------------------------------------------------------------
# CASE K - other editorial destinations remain unreachable from content_cycle.py (structural)
# ---------------------------------------------------------------------------


def test_case_k_content_cycle_never_references_any_destination_other_than_news() -> None:
    from pathlib import Path

    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "EditorialDestination.NEWS" in source_text
    for forbidden in ("EditorialDestination.MEME", "EditorialDestination.TELEGRAPH",
                       "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS"):
        assert forbidden not in source_text, f"{forbidden} must never be reachable from content_cycle.py"


# ---------------------------------------------------------------------------
# CASE L - no real Telegram calls in this test file (structural)
# ---------------------------------------------------------------------------


def test_case_l_every_bot_constructed_in_this_file_is_an_async_mock() -> None:
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
# Phase 23.1K - router dispatch to the V8-family renderer (docs/
# phase23_1k_v82_live_canary_report.md §2). V8.2 shares V8.1's exact schema (title/main_body/
# ending/quote) - these tests prove worker/content_cycle.py's own new dispatch logic, not the
# presentation functions themselves (already covered by tests/test_news_telegram_presentation_
# v81.py, which is schema-based, not version-based, so already covers v8.2 output for free).
# ---------------------------------------------------------------------------


def _v82_capability_registry():
    """Mirrors tests/test_editorial_delivery_mode.py::_v6_capability_registry() but with a
    V8.2-shaped fake Copywriting response (title/main_body/ending/quote - no expandable_details,
    no seven-section long-form shape)."""
    from capabilities.registry import build_registry
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from tests.fakes.fake_gateway import FakeLLMGateway
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
    from tests.test_content_worker_cycle import _INTELLIGENCE_OUTPUT, _PROMPTS_ROOT_PATH, _QUALITY_OUTPUT

    v82_copywriting_output: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "main_body": "OpenAI released a new flagship model on Thursday, scoring 92% on the industry's standard reasoning benchmark.",
        "ending": None,
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
        _generate_response(v82_copywriting_output),
        _generate_response(_QUALITY_OUTPUT),
    ])
    registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT_PATH), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    return gateway, registry


@pytest.mark.asyncio
async def test_v82_output_renders_via_the_v8_family_card_not_the_legacy_template(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end, nothing patched except the outer `bot`: a real V8.2 draft flows through the
    real pipeline and the real dispatch logic in worker/content_cycle.py. Confirms the sent text
    uses the simplified V8-family template (bold headline directly followed by the body, no
    "📰 CATEGORY · date" header row and no separate original-news-title line the legacy template
    always includes) and still carries the correct source button."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")

    source_url = "https://example.com/real-source-article"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    args, kwargs = fake_bot.send_message.call_args
    sent_text = args[1]

    assert "📰" not in sent_text  # no legacy category/date header row
    assert "OpenAI released a new flagship model" in sent_text
    assert source_url not in sent_text  # no raw URL - source button only

    keyboard = kwargs["reply_markup"]
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == source_url
    assert keyboard.inline_keyboard[0][0].text == "🔗 Источник"

    assert args[0] == _REAL_CHAT_ID
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID


@pytest.mark.asyncio
async def test_v6_output_still_uses_the_legacy_template_unchanged(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: V6 output must never be accidentally routed through the V8-family
    dispatch. Phase V2.7 §3-5 forensic + fix: V6 (and V4/V7) output previously fell through to
    `render_editorial_card()` - the internal `/news` editorial-inbox-preview template, with its
    "📰 CATEGORY · date" header row and raw source-language title - a real, disclosed reader-
    facing regression, not an intended contract. It now renders via the same clean, header-free
    card `render_v81_news_card_html()` already established for V8
    (`render_compact_news_card_html()`, Phase V2.7's own fix) - this test's own purpose (proving
    V6 is not silently treated as V8) is preserved by asserting the body text came through
    unmodified, while the 📰 header/date row - never an intended part of any real reader-facing
    send - must no longer appear."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    sent_text = fake_bot.send_message.call_args.args[1]
    assert "📰" not in sent_text  # Phase V2.7 fix: the inbox-preview header never leaks into a real send
    assert sent_text.startswith("<b>")  # the clean render_compact_news_card_html() shape: headline first
    assert " · " not in sent_text  # the category/date separator the old inbox card used


@pytest.mark.asyncio
async def test_v82_output_with_image_sends_photo_with_the_v8_family_caption(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image-caption regression (phase brief Part D, case 9): a resolvable image candidate
    combined with V8-family output must send a photo whose caption is the SAME `html` the
    V8-family dispatch branch built (render_v81_news_card_html output), not a caption re-derived
    from the legacy card/render_editorial_card() path - proves the shared caption-vs-text `html`
    variable (worker/content_cycle.py line ~505) is genuinely shared across both the V6 and
    V8-family branches, not accidentally bypassed for the photo-caption code path specifically."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")

    source_url = "https://example.com/real-source-article-image"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    fake_bot.send_message.assert_not_called()
    args, kwargs = fake_bot.send_photo.call_args
    caption = kwargs.get("caption")
    assert caption is not None
    assert "📰" not in caption  # V8-family caption, not the legacy header row
    assert "OpenAI released a new flagship model" in caption
    keyboard = kwargs["reply_markup"]
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == source_url
    assert result.notified == 1
    assert result.router_image_sent == 1


# ---------------------------------------------------------------------------
# Phase V2.12L - Phase 23.1Q's decision to enable the NINJA PULSE caption footer for real
# router-mode NEWS delivery is the final, approved contract (V2.12G's temporary removal and
# V2.12I's restoration are both superseded by this settled state): the footer (text + link)
# appears exactly once in the final text/HTML, alongside the unchanged source-only "🔗 Источник"
# keyboard (no separate subscription button). tests/test_news_telegram_presentation_v81.py's own
# renderer-level tests (test_ninja_pulse_footer_is_disabled_by_default_for_v81/test_ninja_pulse_
# footer_can_still_be_explicitly_enabled) still cover the renderer's own optional capability,
# unchanged - these two tests cover only the real call-site/integration behavior: does worker/
# content_cycle.py's real router-mode NEWS path actually include it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ninja_pulse_cta_present_once_in_photo_caption_with_source_only_keyboard(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")

    source_url = "https://example.com/real-source-article-footer"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    _, kwargs = fake_bot.send_photo.call_args
    caption = kwargs["caption"]
    assert caption.count("NINJA PULSE. Подписаться 🥷") == 1
    assert '<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>' in caption
    # Source button (a completely separate mechanism - the inline keyboard) must be unaffected.
    keyboard = kwargs["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 1
    assert keyboard.inline_keyboard[0][0].url == source_url
    assert keyboard.inline_keyboard[0][0].text == "🔗 Источник"
    assert result.notified == 1


@pytest.mark.asyncio
async def test_ninja_pulse_cta_present_once_in_text_only_delivery(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No image candidates -> plain text send_message path - CTA must still be present exactly
    once here too."""
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[])),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_message.assert_called_once()
    sent_text = fake_bot.send_message.call_args.args[1]
    assert sent_text.count("NINJA PULSE. Подписаться 🥷") == 1
    assert '<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>' in sent_text
    assert result.notified == 1


def _long_v82_capability_registry():
    """Mirrors _long_v6_capability_registry()'s own established purpose, adapted for V8-family
    shape: a MAJOR-tier main_body long enough that header+title+body ALONE (before the footer is
    even added) already exceeds Telegram's 1024-code-unit photo-caption limit, so this fixture
    reliably exercises the caption-overflow-with-footer fallback regardless of the footer's own
    (small, ~50-character) contribution."""
    from capabilities.registry import build_registry
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from tests.fakes.fake_gateway import FakeLLMGateway
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
    from tests.test_content_worker_cycle import _INTELLIGENCE_OUTPUT, _PROMPTS_ROOT_PATH, _QUALITY_OUTPUT

    # main_body alone (never truncated by this module - only `ending`'s inclusion is ceiling-
    # gated) is deliberately padded well past MAJOR's own ceiling so that headline + body + footer
    # together comfortably exceed CAPTION_SAFE_LIMIT (1024 UTF-16 code units) regardless of
    # whether `ending` is included - avoids the fixture's overflow depending on the ceiling math.
    long_body = (
        "OpenAI released a new flagship model on Thursday, scoring 92% on the industry's standard "
        "reasoning benchmark, a result the company describes as a meaningful jump over its own "
        "prior generation and every publicly benchmarked competitor model released so far this "
        "year, according to figures the company published alongside the announcement itself today. "
        "The company also disclosed a series of additional evaluation results across coding, "
        "mathematics, and multi-step planning tasks, each accompanied by comparison figures against "
        "the same set of publicly available competitor models it referenced in its main results, "
        "and said it plans to publish a fuller technical report describing its training methodology "
        "and evaluation protocol in the coming weeks so outside researchers can attempt to reproduce "
        "the headline benchmark figures independently before the model reaches general availability. "
        "Several industry analysts said the results, if independently reproduced, would meaningfully "
        "narrow the gap that has separated the company's models from its closest competitors."
    )
    v82_long_copywriting_output: dict[str, object] = {
        "title": "OpenAI releases a new model with a long, detailed body",
        "main_body": long_body,
        "ending": None,
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
        _generate_response(v82_long_copywriting_output),
        _generate_response(_QUALITY_OUTPUT),
    ])
    registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT_PATH), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    return gateway, registry


@pytest.mark.asyncio
async def test_ninja_pulse_footer_survives_caption_overflow_fallback_to_text(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A V8-family MAJOR post long enough to exceed the photo-caption limit must fall back to the
    existing plain-text send path (never truncated, never a second ad-hoc truncation system) and
    the footer must still be present in that fallback text - the footer is appended to the same
    `html` string this fallback decision measures, so it is included in the length calculation by
    construction, not via any new mechanism."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _long_v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1
    major_decision = EditorialTreatmentDecision(MAJOR, human_review_required=False, reason="test")

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=major_decision),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()  # too long for a caption - safe fallback used instead
    fake_bot.send_message.assert_called_once()
    sent_text = fake_bot.send_message.call_args.args[1]
    assert "…" not in sent_text  # no truncation marker - the existing "never truncate" guarantee holds
    assert sent_text.count("NINJA PULSE. Подписаться 🥷") == 1
    assert result.notified == 1


# ---------------------------------------------------------------------------
# Phase 23.1Q - Media Roadmap Recovery step 1: multi-image wiring (rank_media_candidates() +
# build_rich_media_plan(), Phase 19 M11/M12, reused verbatim - see docs/media_wiring_checkpoint_1
# for the full before/after call path). These tests cover the router branch's own new selection
# logic; renderer-level quote/footer behavior is already covered by tests/test_news_telegram_
# presentation_v81.py and the existing single-image tests above - not duplicated here.
# ---------------------------------------------------------------------------


def _fake_media_messages(count: int, *, start_id: int = 300):
    from unittest.mock import MagicMock
    return [MagicMock(message_id=start_id + i) for i in range(count)]


@pytest.mark.asyncio
async def test_three_useful_ranked_images_send_as_a_media_group(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(3)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=80, relevance_score=80),
        _fake_candidate(candidate_id="c", rank=3, quality_score=70, relevance_score=70),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_not_called()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 3
    assert kwargs["message_thread_id"] == _REAL_NEWS_TOPIC_ID
    assert result.router_media_group_sent == 1
    assert result.notified == 1
    # Case 7 - a NEW post (no story link at all) must remain standalone.
    assert kwargs["reply_to_message_id"] is None


@pytest.mark.asyncio
async def test_five_candidates_selects_at_most_three(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(3)
    candidates = [
        _fake_candidate(candidate_id=f"c{i}", rank=i, quality_score=90 - i, relevance_score=90 - i)
        for i in range(1, 6)
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 3  # capped at _MAX_ROUTER_IMAGES, never all 5
    assert result.notified == 1


@pytest.mark.asyncio
async def test_first_candidate_fails_second_and_third_succeed_media_still_delivered(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 4 - a single broken image must not kill the whole media opportunity. The
    highest-ranked candidate fails to resolve (no telegram_file_id, no storage bytes); the two
    next-ranked candidates do resolve - build_rich_media_plan() (unmodified) already skips the
    failed one and continues, exactly as required."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    candidates = [
        _fake_candidate(candidate_id="broken", rank=1, quality_score=95, relevance_score=95, resolvable=False),
        _fake_candidate(candidate_id="ok1", rank=2, quality_score=85, relevance_score=85),
        _fake_candidate(candidate_id="ok2", rank=3, quality_score=80, relevance_score=80),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    fake_bot.send_message.assert_not_called()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2  # the broken candidate was skipped, not fatal
    assert result.router_media_group_sent == 1
    assert result.notified == 1


@pytest.mark.asyncio
async def test_all_candidates_fail_to_resolve_falls_back_to_text_only(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 6 - every ranked candidate fails to resolve -> the existing text-only fallback, never
    a crash, never an empty media-group call."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value.message_id = 1
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, resolvable=False),
        _fake_candidate(candidate_id="b", rank=2, resolvable=False),
        _fake_candidate(candidate_id="c", rank=3, resolvable=False),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()
    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_called_once()
    assert result.notified == 1
    assert result.router_media_group_sent == 0
    assert result.router_image_sent == 0


@pytest.mark.asyncio
async def test_media_group_caption_includes_quote_and_footer_but_no_inline_source_link(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 9/10 (media-quality corrective phase): quote and NINJA PULSE footer must survive
    multi-image delivery inside the caption; the source link must NOT be folded into the caption
    text anymore (that was the rejected interim fix) - it is restored as a real inline-keyboard
    button via bot.edit_message_reply_markup() instead (see the dedicated button tests below)."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "quote_telegram_rendering_mode", "enforce")
    source_url = "https://example.com/real-source-article-media-group"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
    ]
    fake_quote = ContentDraftQuote(
        content_draft_id=uuid4(), quote_text="We built this because reasoning matters more than raw speed.",
        translated_text=None, speaker="A Company Spokesperson",
    )

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
        patch("worker.content_cycle.get_quote_for_draft", new=AsyncMock(return_value=fake_quote)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    first_item_caption = kwargs["media"][0].caption
    assert "<blockquote>We built this because reasoning matters more than raw speed.</blockquote>" in first_item_caption
    # Quote (above) must render before the footer (below) in the caption.
    assert first_item_caption.index("<blockquote>") < first_item_caption.index("NINJA PULSE. Подписаться 🥷")
    assert first_item_caption.count("NINJA PULSE. Подписаться 🥷") == 1
    assert "Источник" not in first_item_caption  # no in-caption source-link fallback anymore
    assert source_url not in first_item_caption
    # Only the first media-group item carries the caption (Telegram's own real behavior).
    assert kwargs["media"][1].caption is None
    assert result.notified == 1

    # The real button is attached outside the caption, via edit_message_reply_markup on the
    # group's first message (dedicated coverage of the exact message_id/keyboard contents lives
    # in test_media_group_source_button_attached_via_keyboard_edit_on_first_message below).
    fake_bot.edit_message_reply_markup.assert_called_once()
    edit_kwargs = fake_bot.edit_message_reply_markup.call_args.kwargs
    assert edit_kwargs["reply_markup"].inline_keyboard[0][0].url == source_url


# ---------------------------------------------------------------------------
# Media-quality corrective phase - Part 1: real [Источник] button restoration for media-group
# posts via bot.edit_message_reply_markup() on the group's first message (replaces the rejected
# in-caption-link interim fix above).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_media_group_source_button_attached_via_keyboard_edit_on_first_message(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    source_url = "https://example.com/real-source-article-button"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2, start_id=700)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    fake_bot.edit_message_reply_markup.assert_called_once()
    edit_kwargs = fake_bot.edit_message_reply_markup.call_args.kwargs
    assert edit_kwargs["chat_id"] == _REAL_CHAT_ID
    assert edit_kwargs["message_id"] == 700  # the group's FIRST message, not any other item
    keyboard = edit_kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url == source_url
    assert keyboard.inline_keyboard[0][0].text == "🔗 Источник"
    # Exactly one Telegram-visible post - no second/companion message of any kind.
    fake_bot.send_message.assert_not_called()
    fake_bot.send_photo.assert_not_called()
    assert result.notified == 1
    assert result.router_media_group_sent == 1


@pytest.mark.asyncio
async def test_media_group_keyboard_edit_failure_does_not_duplicate_or_resend_the_post(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If bot.edit_message_reply_markup() itself raises a TelegramAPIError, the post has ALREADY
    been sent successfully - the failure must be swallowed (logged, not raised), and the caller
    must never re-send/duplicate the post merely because attaching the button afterward failed."""
    from aiogram.exceptions import TelegramAPIError

    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    source_url = "https://example.com/real-source-article-edit-failure"
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.url = source_url
        session.add(event)
        await session.commit()
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2, start_id=800)
    fake_bot.edit_message_reply_markup.side_effect = TelegramAPIError(method=None, message="edit failed")  # type: ignore[arg-type]
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()  # never called twice / retried
    fake_bot.edit_message_reply_markup.assert_called_once()
    fake_bot.send_message.assert_not_called()  # no fallback re-send of any kind
    fake_bot.send_photo.assert_not_called()
    assert result.notified == 1  # the post itself is still counted as successfully delivered
    assert result.router_media_group_sent == 1


# ---------------------------------------------------------------------------
# Media-quality corrective phase - Part 2: tightened multi-image eligibility (existing signals
# only - dimensions via resolution_band(), branding_risk via rank_media_candidates() itself).
# Calibrated against real forensic evidence (docs/media_quality_checkpoint.md): confirmed-bad
# 96x96 avatar, 140x74 icon, 128x128 branded screenshot must all be excluded as ADDITIONAL album
# images; confirmed-good 3000x1500/1920x1005 heroes must stay eligible.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hero_plus_tiny_avatar_selects_only_the_hero(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    candidates = [
        _fake_candidate(candidate_id="hero", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500),
        _fake_candidate(candidate_id="avatar", rank=2, quality_score=60, relevance_score=60, width=96, height=96),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()  # only one eligible candidate - single photo, not a group
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1
    assert result.notified == 1


@pytest.mark.asyncio
async def test_hero_plus_tiny_icon_selects_only_the_hero(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real 140x74 forensic example carried NO possible_* warning tokens at all - proving
    branding_risk alone cannot catch it; resolution_band() (dimensions) is what excludes it."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    candidates = [
        _fake_candidate(candidate_id="hero", rank=1, quality_score=90, relevance_score=90, width=1920, height=1005),
        _fake_candidate(
            candidate_id="icon", rank=2, quality_score=55, relevance_score=55, width=140, height=74, warnings=[],
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1


@pytest.mark.asyncio
async def test_hero_plus_branded_screenshot_excludes_the_branded_image(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real 128x128 forensic example carried possible_branded_screenshot (branding_risk=25)
    AND was WEAK-band by dimensions - either signal alone would exclude it as a second image."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    candidates = [
        _fake_candidate(candidate_id="hero", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500),
        _fake_candidate(
            candidate_id="branded", rank=2, quality_score=60, relevance_score=60, width=128, height=128,
            warnings=["possible_branded_screenshot"],
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1


@pytest.mark.asyncio
async def test_hero_plus_genuinely_useful_second_image_both_stay_eligible(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real, high-resolution, unbranded second image must NOT be excluded by the tightened bar -
    the corrective phase must not over-tighten past legitimate secondary images."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    candidates = [
        _fake_candidate(candidate_id="hero", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500),
        _fake_candidate(candidate_id="second", rank=2, quality_score=75, relevance_score=70, width=1600, height=900),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2
    assert result.router_media_group_sent == 1


@pytest.mark.asyncio
async def test_three_genuinely_useful_images_all_allowed(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(3)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500),
        _fake_candidate(candidate_id="b", rank=2, quality_score=80, relevance_score=80, width=1920, height=1080),
        _fake_candidate(candidate_id="c", rank=3, quality_score=75, relevance_score=75, width=1600, height=900),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 3
    assert result.router_media_group_sent == 1
    assert result.notified == 1


# ---------------------------------------------------------------------------
# Media-quality corrective phase - Part 3: within-event near-duplicate detection, wired via
# already-persisted sha256/perceptual_hash exposed through EditorialImageCandidate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identical_sha256_duplicate_excluded_from_the_album(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    same_hash = "a" * 64
    candidates = [
        _fake_candidate(
            candidate_id="a", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500,
            sha256=same_hash,
        ),
        _fake_candidate(
            candidate_id="b", rank=2, quality_score=85, relevance_score=85, width=1920, height=1080,
            sha256=same_hash,
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()  # the exact-duplicate never becomes a second album image
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1


@pytest.mark.asyncio
async def test_near_duplicate_perceptual_hash_within_threshold_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    # hamming_distance("0000...0", "0000...f") == 4 (last hex digit 0 vs f = 0b0000 vs 0b1111,
    # every other digit identical) - exactly at the existing <=4 threshold.
    hash_a = "0" * 16
    hash_b = "0" * 15 + "f"
    candidates = [
        _fake_candidate(
            candidate_id="a", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500,
            perceptual_hash=hash_a,
        ),
        _fake_candidate(
            candidate_id="b", rank=2, quality_score=85, relevance_score=85, width=1920, height=1080,
            perceptual_hash=hash_b,
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1


@pytest.mark.asyncio
async def test_perceptually_distinct_images_both_remain(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    # Hamming distance between these two 16-hex-digit hashes is well above the <=4 threshold
    # (differ in every digit).
    hash_a = "0" * 16
    hash_b = "f" * 16
    candidates = [
        _fake_candidate(
            candidate_id="a", rank=1, quality_score=90, relevance_score=90, width=3000, height=1500,
            perceptual_hash=hash_a,
        ),
        _fake_candidate(
            candidate_id="b", rank=2, quality_score=85, relevance_score=85, width=1920, height=1080,
            perceptual_hash=hash_b,
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2
    assert result.router_media_group_sent == 1


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (Case E, docs/news_output_stability_forensic_report.md §6): the real
# Honor Robot Phone UPDATE delivered the same underlying photo twice - once served directly and
# once through WordPress/Jetpack's own Photon CDN proxy (i0.wp.com). Real measured Hamming
# distance between the two: 9 - above the existing <=4 threshold, so the pre-fix dedup logic could
# not catch it. This exercises the exact real URLs/hashes/dimensions from that draft.
# ---------------------------------------------------------------------------

_REAL_HONOR_HERO_URL = "https://9to5google.com/wp-content/uploads/sites/4/2026/08/honor-robot-phone-2.jpg?quality=82&strip=all"
_REAL_HONOR_PHOTON_URL = "https://i0.wp.com/9to5google.com/wp-content/uploads/sites/4/2026/08/honor-robot-phone-2.jpg?resize=1200%2C628&quality=82&strip=all&ssl=1"
_REAL_HONOR_HERO_PHASH = "a0bab2b23ababa30"
_REAL_HONOR_PHOTON_PHASH = "a0b8b0b07838b820"

# Real Guardian same-base-file pair with a genuinely DIFFERENT visible crop (not a resize) - the
# required "visually distinct same-product pair that must remain allowed" case, using the real
# measured hashes/URLs from this dataset (Hamming distance 36 between them).
_REAL_GUARDIAN_CROP_A_URL = "https://i.guim.co.uk/img/media/406704301905abb072d8bd2b3d9d87864722bf4a/0_21_3000_2399/master/3000.jpg?width=1200&quality=85&auto=format&fit=max&s=a"
_REAL_GUARDIAN_CROP_B_URL = "https://i.guim.co.uk/img/media/406704301905abb072d8bd2b3d9d87864722bf4a/0_21_3000_2399/master/3000.jpg?width=1200&height=630&quality=85&auto=format&fit=crop&s=b"
_REAL_GUARDIAN_CROP_A_PHASH = "628ecdce2b01c58f"
_REAL_GUARDIAN_CROP_B_PHASH = "f8d1842525ad3bed"


@pytest.mark.asyncio
async def test_honor_style_photon_cdn_duplicate_excluded_from_the_album(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact real regression: same underlying photo, one direct URL and one served through
    Jetpack's Photon CDN proxy, real Hamming distance 9 - must now be excluded."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    candidates = [
        _fake_candidate(
            candidate_id="hero", rank=1, quality_score=96, relevance_score=90, width=3000, height=1500,
            perceptual_hash=_REAL_HONOR_HERO_PHASH, final_url=_REAL_HONOR_HERO_URL,
        ),
        _fake_candidate(
            candidate_id="photon", rank=2, quality_score=88, relevance_score=85, width=1200, height=628,
            perceptual_hash=_REAL_HONOR_PHOTON_PHASH, final_url=_REAL_HONOR_PHOTON_URL,
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()  # the Photon duplicate never becomes a second album image
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1


@pytest.mark.asyncio
async def test_same_base_file_crop_variants_are_now_deduplicated_to_one_slot(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §A):
    deliberate, evidence-driven policy correction. This fixture pair (same normalized URL origin,
    real Hamming distance 36) was PREVIOUSLY treated as "genuinely different crops, both must
    remain" - but the real acceptance canary showed this exact URL pattern (same base file,
    different crop/resize query params) live-producing real published albums that show the same
    photograph 2-3 times (the $70M SF-estate and Apple/iCloud Private Relay albums). Per the
    corrected product invariant - "different transformations of the same source photograph must
    occupy only one album slot" - same-origin is now sufficient on its own, regardless of
    perceptual distance. See test_genuinely_different_images_at_different_paths_both_remain below
    for the still-intact "truly distinct photos must remain eligible" guarantee."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 1
    candidates = [
        _fake_candidate(
            candidate_id="crop-a", rank=1, quality_score=90, relevance_score=90, width=1200, height=960,
            perceptual_hash=_REAL_GUARDIAN_CROP_A_PHASH, final_url=_REAL_GUARDIAN_CROP_A_URL,
        ),
        _fake_candidate(
            candidate_id="crop-b", rank=2, quality_score=85, relevance_score=85, width=1200, height=630,
            perceptual_hash=_REAL_GUARDIAN_CROP_B_PHASH, final_url=_REAL_GUARDIAN_CROP_B_URL,
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_not_called()  # the same-source crop variant never becomes a second album image
    fake_bot.send_photo.assert_called_once()
    assert result.router_image_sent == 1


@pytest.mark.asyncio
async def test_genuinely_different_images_at_different_paths_both_remain(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Required control case: two candidates at genuinely DIFFERENT source file paths (not sharing
    a base filename) must remain eligible even when their perceptual hashes happen to be close -
    the origin-identity dedup signal only ever fires on a real shared source file, never on visual
    similarity alone. Proves the acceptance follow-up fix does not over-tighten past legitimate
    distinct images."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    candidates = [
        _fake_candidate(
            candidate_id="photo-a", rank=1, quality_score=90, relevance_score=90, width=1200, height=960,
            perceptual_hash=_REAL_GUARDIAN_CROP_A_PHASH, final_url="https://i.guim.co.uk/img/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/0_0_100_100/master/one.jpg?width=1200",
        ),
        _fake_candidate(
            candidate_id="photo-b", rank=2, quality_score=85, relevance_score=85, width=1200, height=630,
            perceptual_hash=_REAL_GUARDIAN_CROP_B_PHASH, final_url="https://i.guim.co.uk/img/media/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/0_0_100_100/master/two.jpg?width=1200",
        ),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    assert len(kwargs["media"]) == 2
    assert result.router_media_group_sent == 1


def test_normalize_image_origin_strips_jetpack_photon_cdn_proxy_prefix() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_HONOR_HERO_URL) == _normalize_image_origin(_REAL_HONOR_PHOTON_URL)


def test_normalize_image_origin_distinguishes_unrelated_hosts() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin("https://example.com/a.jpg") != _normalize_image_origin("https://example.com/b.jpg")
    assert _normalize_image_origin(None) is None
    assert _normalize_image_origin("") is None


def test_compute_within_event_duplicate_flags_honor_pair_directly() -> None:
    from worker.content_cycle import _compute_within_event_duplicate_flags

    hero = _fake_candidate(
        candidate_id="hero", rank=1, perceptual_hash=_REAL_HONOR_HERO_PHASH, final_url=_REAL_HONOR_HERO_URL,
    )
    photon = _fake_candidate(
        candidate_id="photon", rank=2, perceptual_hash=_REAL_HONOR_PHOTON_PHASH, final_url=_REAL_HONOR_PHOTON_URL,
    )
    flags = _compute_within_event_duplicate_flags([hero, photon])
    assert flags[hero.id] is False
    assert flags[photon.id] is True


def test_compute_within_event_duplicate_flags_guardian_crop_pair_directly() -> None:
    """NEWS Stability Acceptance follow-up: same normalized origin (same base file `3000.jpg`,
    different crop/resize query params) is now sufficient on its own for a duplicate flag,
    regardless of the real measured Hamming distance (36) between these two - see docs/
    post_acceptance_followup_checkpoint.md §A."""
    from worker.content_cycle import _compute_within_event_duplicate_flags

    crop_a = _fake_candidate(
        candidate_id="crop-a", rank=1, perceptual_hash=_REAL_GUARDIAN_CROP_A_PHASH, final_url=_REAL_GUARDIAN_CROP_A_URL,
    )
    crop_b = _fake_candidate(
        candidate_id="crop-b", rank=2, perceptual_hash=_REAL_GUARDIAN_CROP_B_PHASH, final_url=_REAL_GUARDIAN_CROP_B_URL,
    )
    flags = _compute_within_event_duplicate_flags([crop_a, crop_b])
    assert flags[crop_a.id] is False
    assert flags[crop_b.id] is True


def test_compute_within_event_duplicate_flags_real_sf_estate_album_directly() -> None:
    """The exact real acceptance-canary failure: the $70M SF-estate Guardian album presented the
    same underlying photograph 3 times (ranks 1-3 actually sent), differing only by crop/resize
    query params on the same base file `3702.jpg`. Real measured Hamming distances between the 3
    sent variants were 14-28 - all well above both the old global (<=4) and same-origin (<=10)
    thresholds, which is exactly why they previously all survived. Only the first (best-ranked)
    must now survive."""
    from worker.content_cycle import _compute_within_event_duplicate_flags

    base = "https://i.guim.co.uk/img/media/7d9d381f45fe902c8c8f6e6f526ebeb6b2c15afc/785_0_3702_2962/master/3702.jpg"
    rank1 = _fake_candidate(
        candidate_id="rank1", rank=1, perceptual_hash="9fa8a08b888c2fbd",
        final_url=f"{base}?width=1200&height=630&quality=85&auto=format&fit=crop&s=1af90ff2",
    )
    rank2 = _fake_candidate(
        candidate_id="rank2", rank=2, perceptual_hash="39a88c8c272b05cc",
        final_url=f"{base}?width=1200&height=1200&quality=85&auto=format&fit=crop&s=5b1da97b",
    )
    rank3 = _fake_candidate(
        candidate_id="rank3", rank=3, perceptual_hash="b9888c8c369f8b0c",
        final_url=f"{base}?width=1200&height=900&quality=85&auto=format&fit=crop&s=329cfb24",
    )
    flags = _compute_within_event_duplicate_flags([rank1, rank2, rank3])
    assert flags[rank1.id] is False
    assert flags[rank2.id] is True
    assert flags[rank3.id] is True


def test_compute_within_event_duplicate_flags_real_cnet_apple_album_directly() -> None:
    """The exact real acceptance-canary failure: the Apple/iCloud Private Relay CNET album
    presented the same underlying photograph 3 times via WordPress's own `?resize=WxH` query
    convention on the same base file `7d5d5d73-...jpg`. Real measured Hamming distances were
    12-22 - well above both old thresholds."""
    from worker.content_cycle import _compute_within_event_duplicate_flags

    base = "https://www.cnet.com/wp-content/uploads/sites/2/7d5d5d73-029b-4dcd-9b51-93acca1a424b.jpg"
    rank1 = _fake_candidate(candidate_id="rank1", rank=1, perceptual_hash="0307070f1737170f", final_url=base)
    rank2 = _fake_candidate(
        candidate_id="rank2", rank=2, perceptual_hash="000301072b6b694d", final_url=f"{base}?resize=1200%2C1200",
    )
    rank3 = _fake_candidate(
        candidate_id="rank3", rank=3, perceptual_hash="01070307b2b2330f", final_url=f"{base}?resize=1200%2C900",
    )
    flags = _compute_within_event_duplicate_flags([rank1, rank2, rank3])
    assert flags[rank1.id] is False
    assert flags[rank2.id] is True
    assert flags[rank3.id] is True


def test_normalize_image_origin_strips_wordpress_dimension_suffix() -> None:
    from worker.content_cycle import _normalize_image_origin

    full = "https://example.com/wp-content/uploads/2026/08/photo.jpg"
    resized = "https://example.com/wp-content/uploads/2026/08/photo-1024x768.jpg"
    assert _normalize_image_origin(full) == _normalize_image_origin(resized)


# ---------------------------------------------------------------------------------------------
# iXBT production forensic (event d5b8d887-3176-4876-8640-4572ca3bcbe2, exact selector replay
# against the real deployed code): _normalize_image_origin() previously only looked at the OUTER
# CDN host, never past it - media.ixbt.com's own resize proxy embeds the full, scheme-qualified
# original URL after a resize/crop path segment, so four real crop/resize transformations of the
# SAME source photo (MINISFORUM-NAS-N5-MAX-HERO_large.jpg) each normalized to a different string
# and all got dup=False. The live selector replay picked three of them for the same album. This
# is the generic "CDN wrapper embeds a full absolute source URL" fix - real production URLs below,
# reproduced verbatim from the replay output.
# ---------------------------------------------------------------------------------------------

_REAL_IXBT_HERO_1600 = "https://media.ixbt.com/1600x900/smart/jpeg/https://www.ixbt.com/img/n1/news/2026/7/1/MINISFORUM-NAS-N5-MAX-HERO_large.jpg"
_REAL_IXBT_HERO_1200x900 = "https://media.ixbt.com/1200x900/smart/https://www.ixbt.com/img/n1/news/2026/7/1/MINISFORUM-NAS-N5-MAX-HERO_large.jpg"
_REAL_IXBT_HERO_1200x1200 = "https://media.ixbt.com/1200x1200/smart/https://www.ixbt.com/img/n1/news/2026/7/1/MINISFORUM-NAS-N5-MAX-HERO_large.jpg"
_REAL_IXBT_HERO_FITIN = "https://media.ixbt.com/fit-in/1729x900/https://www.ixbt.com/img/n1/news/2026/7/1/MINISFORUM-NAS-N5-MAX-HERO_large.jpg"
_REAL_IXBT_OTHER_URL = "https://media.ixbt.video/fit-in/768x432/ixbt-data/1289117/f6a3582e-c0df-406c-9765-b27f6821b00a.png"


def test_normalize_image_origin_collapses_all_four_real_ixbt_hero_transforms() -> None:
    """The exact 4 real URLs from the production selector replay - all must normalize to the
    same origin, despite the outer media.ixbt.com wrapper differing in resize/crop path segment
    on every one."""
    from worker.content_cycle import _normalize_image_origin

    origins = {
        _normalize_image_origin(u)
        for u in (_REAL_IXBT_HERO_1600, _REAL_IXBT_HERO_1200x900, _REAL_IXBT_HERO_1200x1200, _REAL_IXBT_HERO_FITIN)
    }
    assert len(origins) == 1
    assert origins == {"www.ixbt.com/img/n1/news/2026/7/1/MINISFORUM-NAS-N5-MAX-HERO_large.jpg"}


def test_normalize_image_origin_ixbt_unrelated_candidate_keeps_its_own_origin() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_IXBT_OTHER_URL) != _normalize_image_origin(_REAL_IXBT_HERO_1600)


def test_normalize_image_origin_embedded_url_never_collapses_different_source_files() -> None:
    """Required control case: two genuinely different embedded source files (different basenames,
    same wrapper convention) must never collapse - the fix reads the embedded path verbatim, never
    guesses identity from a filename alone."""
    from worker.content_cycle import _normalize_image_origin

    a = "https://media.ixbt.com/1200x900/smart/https://www.ixbt.com/img/a.jpg"
    b = "https://media.ixbt.com/1200x900/smart/https://www.ixbt.com/img/b.jpg"
    assert _normalize_image_origin(a) != _normalize_image_origin(b)


def test_normalize_image_origin_wrapper_without_embedded_scheme_falls_back_unchanged() -> None:
    """No literal http(s):// anywhere in the path - must resolve exactly as it did before this
    fix (plain outer host+path, WordPress-suffix-stripped)."""
    from worker.content_cycle import _normalize_image_origin

    assert (
        _normalize_image_origin("https://media.ixbt.com/1200x900/smart/no-embedded-url-here.jpg")
        == "media.ixbt.com/1200x900/smart/no-embedded-url-here.jpg"
    )


def test_normalize_image_origin_jetpack_photon_regression_unaffected_by_embedded_url_addition() -> None:
    """Jetpack/Photon's own pattern embeds a bare host+path (no scheme) - _EMBEDDED_ABSOLUTE_URL_RE
    must never match it, so this falls through to the pre-existing, unmodified Jetpack-specific
    branch exactly as before."""
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_HONOR_HERO_URL) == _normalize_image_origin(_REAL_HONOR_PHOTON_URL)


def test_compute_within_event_duplicate_flags_real_ixbt_minisforum_hero_transforms() -> None:
    """Direct replay of the real production event's own candidate shape (4 hero crop/resize
    transforms + 1 genuinely different image), mirroring the SF-estate/CNET direct-unit-test style
    above. Perceptual hashes are illustrative (not captured by the original replay's own print
    statement) and deliberately chosen with LARGE mutual Hamming distance, to prove the
    origin-identity signal alone - not perceptual similarity - is what catches these."""
    from worker.content_cycle import _compute_within_event_duplicate_flags

    hero_1600 = _fake_candidate(
        candidate_id="hero-1600", rank=1, perceptual_hash="0000000000000000", final_url=_REAL_IXBT_HERO_1600,
    )
    hero_1200x900 = _fake_candidate(
        candidate_id="hero-1200x900", rank=2, perceptual_hash="ffffffffffffffff", final_url=_REAL_IXBT_HERO_1200x900,
    )
    hero_1200x1200 = _fake_candidate(
        candidate_id="hero-1200x1200", rank=3, perceptual_hash="0f0f0f0f0f0f0f0f", final_url=_REAL_IXBT_HERO_1200x1200,
    )
    other = _fake_candidate(
        candidate_id="other", rank=4, perceptual_hash="f0f0f0f0f0f0f0f0", final_url=_REAL_IXBT_OTHER_URL,
    )
    flags = _compute_within_event_duplicate_flags([hero_1600, hero_1200x900, hero_1200x1200, other])
    assert flags[hero_1600.id] is False
    assert flags[hero_1200x900.id] is True
    assert flags[hero_1200x1200.id] is True
    assert flags[other.id] is False


def test_select_top_ranked_image_candidates_ixbt_hero_transforms_never_fill_more_than_one_slot() -> None:
    """Deterministic replay unit test for the selector layer itself (not just the duplicate-flag
    computation): 3 real hero transforms + 1 real unrelated image -> selection must pick exactly
    one hero transform (the best-ranked) and the one genuinely different image, never 2-3 hero
    transforms filling the whole album."""
    from worker.content_cycle import _select_top_ranked_image_candidates

    hero_1600 = _fake_candidate(
        candidate_id="hero-1600", rank=1, quality_score=98, relevance_score=81, width=1600, height=900,
        perceptual_hash="0000000000000000", final_url=_REAL_IXBT_HERO_1600,
    )
    hero_1200x900 = _fake_candidate(
        candidate_id="hero-1200x900", rank=2, quality_score=96, relevance_score=81, width=1200, height=900,
        perceptual_hash="ffffffffffffffff", final_url=_REAL_IXBT_HERO_1200x900,
    )
    hero_1200x1200 = _fake_candidate(
        candidate_id="hero-1200x1200", rank=3, quality_score=91, relevance_score=80, width=1200, height=1200,
        perceptual_hash="0f0f0f0f0f0f0f0f", final_url=_REAL_IXBT_HERO_1200x1200,
    )
    other = _fake_candidate(
        candidate_id="other", rank=4, quality_score=70, relevance_score=44, width=768, height=432,
        perceptual_hash="f0f0f0f0f0f0f0f0", final_url=_REAL_IXBT_OTHER_URL,
    )

    selected = _select_top_ranked_image_candidates([hero_1600, hero_1200x900, hero_1200x1200, other], limit=3)

    selected_ids = [c.candidate_id for c in selected]
    print("SELECTED IDs:", selected_ids)
    print("SELECTED URLs:", [c.final_url for c in selected])
    assert selected_ids == ["hero-1600", "other"]
    assert sum(1 for cid in selected_ids if cid.startswith("hero-")) == 1


# ---------------------------------------------------------------------------------------------
# Approved narrow CDN source-origin normalization fix (2026-08-17 forensic + design proposal):
# two confirmed real production gaps, both caught by the live post-c39a09b canary. Real URLs
# reproduced verbatim below - see worker/content_cycle.py::_IXBT_STABLE_ASSET_MARKER/
# _MACRUMORS_STABLE_ASSET_MARKER for the full forensic trail.
# ---------------------------------------------------------------------------------------------

_REAL_IXBT_DATA_1289200_A = "https://media.ixbt.com/1200x1200/smart/ixbt-data/1289200/media-6otqdpxmgcu7zjyloyntpqqh.jpg"
_REAL_IXBT_DATA_1289200_B = "https://media.ixbt.com/1600x900/smart/jpeg/ixbt-data/1289200/media-6otqdpxmgcu7zjyloyntpqqh.jpg"
_REAL_IXBT_VIDEO_1289117 = "https://media.ixbt.video/fit-in/768x432/ixbt-data/1289117/f6a3582e-c0df-406c-9765-b27f6821b00a.png"

_REAL_MACRUMORS_SIRI_A = "https://images.macrumors.com/t/5VqGjtmjIjCfOM8Sv0v-nzPfg54=/1600x/article-new/2026/03/ios-27-siri-animation.jpg"
_REAL_MACRUMORS_SIRI_B = "https://images.macrumors.com/t/K3APdjcvztsHADZNjOYSvOm3kEI=/1600x1200/smart/article-new/2026/03/ios-27-siri-animation.jpg"
_REAL_MACRUMORS_IPHONE18 = "https://images.macrumors.com/t/0543dbjxfqM6PrA4sngiXK-aF-o=/2500x/article-new/2026/07/iPhone-18-Pro-and-Pro-Max-Feature.jpg"


def test_normalize_image_origin_collapses_two_real_ixbt_data_transforms() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_IXBT_DATA_1289200_A) == _normalize_image_origin(_REAL_IXBT_DATA_1289200_B)
    assert _normalize_image_origin(_REAL_IXBT_DATA_1289200_A) == "media.ixbt.com/ixbt-data/1289200/media-6otqdpxmgcu7zjyloyntpqqh.jpg"


def test_normalize_image_origin_ixbt_video_host_supported() -> None:
    """Proves the marker rule applies on the sibling confirmed host, not just media.ixbt.com."""
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_IXBT_VIDEO_1289117) == "media.ixbt.video/ixbt-data/1289117/f6a3582e-c0df-406c-9765-b27f6821b00a.png"


def test_normalize_image_origin_ixbt_data_marker_scoped_to_allowed_hosts_only() -> None:
    """The identical path shape on an unrelated host must NOT use the marker rule - falls through
    to plain host+path instead."""
    from worker.content_cycle import _normalize_image_origin

    unrelated = "https://example.com/1200x1200/smart/ixbt-data/1289200/media-6otqdpxmgcu7zjyloyntpqqh.jpg"
    assert _normalize_image_origin(unrelated) == "example.com/1200x1200/smart/ixbt-data/1289200/media-6otqdpxmgcu7zjyloyntpqqh.jpg"
    assert _normalize_image_origin(unrelated) != _normalize_image_origin(_REAL_IXBT_DATA_1289200_A)


def test_normalize_image_origin_ixbt_data_different_assets_remain_distinct() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_IXBT_DATA_1289200_A) != _normalize_image_origin(_REAL_IXBT_VIDEO_1289117)


def test_normalize_image_origin_collapses_two_real_macrumors_article_new_transforms() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_MACRUMORS_SIRI_A) == _normalize_image_origin(_REAL_MACRUMORS_SIRI_B)
    assert _normalize_image_origin(_REAL_MACRUMORS_SIRI_A) == "images.macrumors.com/article-new/2026/03/ios-27-siri-animation.jpg"


def test_normalize_image_origin_macrumors_marker_scoped_to_macrumors_only() -> None:
    from worker.content_cycle import _normalize_image_origin

    unrelated = "https://example.com/t/sig=/1600x/article-new/2026/03/ios-27-siri-animation.jpg"
    assert _normalize_image_origin(unrelated) != _normalize_image_origin(_REAL_MACRUMORS_SIRI_A)


def test_normalize_image_origin_macrumors_different_files_remain_distinct() -> None:
    from worker.content_cycle import _normalize_image_origin

    assert _normalize_image_origin(_REAL_MACRUMORS_SIRI_A) != _normalize_image_origin(_REAL_MACRUMORS_IPHONE18)


def test_compute_within_event_duplicate_flags_real_ixbt_data_pair_directly() -> None:
    """Direct duplicate-flag replay for the real iXBT pair - deliberately different dimensions,
    sha256, and pHash on both candidates, so only the normalized-origin signal can be what
    catches this (proves the fix, not an accidental hash coincidence)."""
    from worker.content_cycle import _compute_within_event_duplicate_flags

    first = _fake_candidate(
        candidate_id="ixbt-a", rank=1, width=1200, height=1200, sha256="a" * 64,
        perceptual_hash="0000000000000000", final_url=_REAL_IXBT_DATA_1289200_A,
    )
    second = _fake_candidate(
        candidate_id="ixbt-b", rank=2, width=1600, height=900, sha256="b" * 64,
        perceptual_hash="ffffffffffffffff", final_url=_REAL_IXBT_DATA_1289200_B,
    )
    flags = _compute_within_event_duplicate_flags([first, second])
    assert flags[first.id] is False
    assert flags[second.id] is True


def test_compute_within_event_duplicate_flags_real_macrumors_pair_directly() -> None:
    from worker.content_cycle import _compute_within_event_duplicate_flags

    first = _fake_candidate(
        candidate_id="mr-a", rank=1, width=1600, height=900, sha256="c" * 64,
        perceptual_hash="0f0f0f0f0f0f0f0f", final_url=_REAL_MACRUMORS_SIRI_A,
    )
    second = _fake_candidate(
        candidate_id="mr-b", rank=2, width=1600, height=1200, sha256="d" * 64,
        perceptual_hash="f0f0f0f0f0f0f0f0", final_url=_REAL_MACRUMORS_SIRI_B,
    )
    flags = _compute_within_event_duplicate_flags([first, second])
    assert flags[first.id] is False
    assert flags[second.id] is True


def test_select_top_ranked_image_candidates_ixbt_data_transforms_never_fill_more_than_one_slot() -> None:
    """Selector production-shape replay: 2 real ixbt-data transforms of the same asset + 1
    genuinely different valid image -> selection must pick exactly one ixbt-data transform and
    the other image, never both transforms."""
    from worker.content_cycle import _select_top_ranked_image_candidates

    transform_a = _fake_candidate(
        candidate_id="ixbt-a", rank=1, quality_score=95, relevance_score=80, width=1200, height=1200,
        perceptual_hash="0000000000000000", final_url=_REAL_IXBT_DATA_1289200_A,
    )
    transform_b = _fake_candidate(
        candidate_id="ixbt-b", rank=2, quality_score=90, relevance_score=78, width=1600, height=900,
        perceptual_hash="ffffffffffffffff", final_url=_REAL_IXBT_DATA_1289200_B,
    )
    other = _fake_candidate(
        candidate_id="other", rank=3, quality_score=70, relevance_score=44, width=768, height=432,
        perceptual_hash="f0f0f0f0f0f0f0f0", final_url=_REAL_IXBT_VIDEO_1289117,
    )

    selected = _select_top_ranked_image_candidates([transform_a, transform_b, other], limit=3)

    selected_ids = [c.candidate_id for c in selected]
    print("SELECTED IDs:", selected_ids)
    print("SELECTED URLs:", [c.final_url for c in selected])
    assert selected_ids == ["ixbt-a", "other"]
    assert sum(1 for cid in selected_ids if cid.startswith("ixbt-")) == 1


def test_select_top_ranked_image_candidates_macrumors_transforms_never_fill_more_than_one_slot() -> None:
    """Equivalent selector production-shape replay for MacRumors."""
    from worker.content_cycle import _select_top_ranked_image_candidates

    transform_a = _fake_candidate(
        candidate_id="mr-a", rank=1, quality_score=95, relevance_score=80, width=1600, height=900,
        perceptual_hash="0f0f0f0f0f0f0f0f", final_url=_REAL_MACRUMORS_SIRI_A,
    )
    transform_b = _fake_candidate(
        candidate_id="mr-b", rank=2, quality_score=90, relevance_score=78, width=1600, height=1200,
        perceptual_hash="f0f0f0f0f0f0f0f0", final_url=_REAL_MACRUMORS_SIRI_B,
    )
    other = _fake_candidate(
        candidate_id="other", rank=3, quality_score=70, relevance_score=60, width=2500, height=1400,
        perceptual_hash="00ff00ff00ff00ff", final_url=_REAL_MACRUMORS_IPHONE18,
    )

    selected = _select_top_ranked_image_candidates([transform_a, transform_b, other], limit=3)

    selected_ids = [c.candidate_id for c in selected]
    print("SELECTED IDs:", selected_ids)
    print("SELECTED URLs:", [c.final_url for c in selected])
    assert selected_ids == ["mr-a", "other"]
    assert sum(1 for cid in selected_ids if cid.startswith("mr-")) == 1


# ---------------------------------------------------------------------------------------------
# Production wiring (docs/video_delivery_wiring_checkpoint.md): worker/content_cycle.py now
# retrieves/converts a real video candidate and passes it into build_rich_media_plan() (Phase 19
# M10-M12, all reused verbatim). Gated behind rich_media_mode=="enforce" (default "off" is
# byte-identical to every image-only test above, all of which remain unmodified and passing).
# ---------------------------------------------------------------------------------------------

def _fake_video_candidate(**overrides: object) -> EligibleVideoCandidate:
    base: dict[str, object] = dict(
        id=uuid4(), event_id=uuid4(), content_draft_id=None,
        discovery_method="open_graph_video_secure", remote_url="https://cdn.example.com/clip.mp4",
        platform="direct_hosted", declared_width=1280, declared_height=720,
        declared_mime_type="video/mp4", declared_duration_seconds=30,
        validation_status="valid", detected_container="mp4", byte_size=5000, error_code=None,
    )
    base.update(overrides)
    return EligibleVideoCandidate(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_valid_video_candidate_reaches_the_media_group_when_rich_media_enforced(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real direct-hosted video candidate, retrieved and converted, reaches
    build_rich_media_plan() and is sent as the last item of the media group as an InputMediaVideo -
    end-to-end proof of the wiring, not just the converter in isolation."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "rich_media_mode", "enforce")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=[_fake_candidate()])),
        patch(
            "worker.content_cycle.get_video_candidates_for_event",
            new=AsyncMock(return_value=[_fake_video_candidate()]),
        ) as mock_get_video,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_get_video.assert_called_once()
    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    media = kwargs["media"]
    assert len(media) == 2
    assert isinstance(media[-1], InputMediaVideo)
    assert media[-1].media == "https://cdn.example.com/clip.mp4"
    assert result.notified == 1


@pytest.mark.asyncio
async def test_no_video_candidate_leaves_image_only_delivery_unchanged(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback (docs/video_delivery_wiring_checkpoint.md §"preserve fallback behavior"): even
    with rich_media_mode="enforce", no persisted video candidate for the event must leave the
    existing image-only media-group send completely unaffected - never a crash, never a blocked
    or altered image send."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    monkeypatch.setattr(settings, "rich_media_mode", "enforce")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
        patch("worker.content_cycle.get_video_candidates_for_event", new=AsyncMock(return_value=[])),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    _, kwargs = fake_bot.send_media_group.call_args
    media = kwargs["media"]
    assert len(media) == 2
    assert all(not isinstance(item, InputMediaVideo) for item in media)
    assert result.notified == 1
    assert result.router_media_group_sent == 1


@pytest.mark.asyncio
async def test_video_lookup_is_never_called_when_rich_media_mode_is_off(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default-config regression guard: rich_media_mode defaults to "off" - the video lookup must
    never even run, keeping this byte-identical to the pre-wiring image-only behavior every other
    test in this file already exercises."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    assert settings.rich_media_mode == "off"
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(2)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
        patch("worker.content_cycle.get_video_candidates_for_event", new=AsyncMock()) as mock_get_video,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_get_video.assert_not_called()
    fake_bot.send_media_group.assert_called_once()
    assert result.notified == 1


# ---------------------------------------------------------------------------
# Delivery-gap fix (2026-08-16 production forensic): a real router-mode photo send timed out
# (~60s) - services.telegram_routing.send_photo_to_editorial_destination() caught the
# TelegramAPIError and returned sent=False, but worker/content_cycle.py only counted
# notification_failed and moved on, dropping a fully generated, treatment-approved post
# entirely. It now attempts exactly one plain-text fallback via the existing
# send_to_editorial_destination() (same html/keyboard/destination/reply_to_message_id) whenever
# send_photo_to_editorial_destination()/send_media_group_to_editorial_destination() returns
# sent=False. Residual, disclosed, NOT fixed here: a Telegram timeout can occur after Telegram
# already accepted the photo/media-group but before this process saw the response, so this
# one-shot fallback can theoretically produce a real photo+text duplicate in that ambiguous
# case - see the matching comment in worker/content_cycle.py. No idempotency redesign, no
# retries, no sleeps are introduced.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_photo_succeeds_no_text_fallback_attempted(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 1: the unmodified success path - no fallback call, notified once,
    router_image_sent increments, the new router_text_fallback_sent counter stays 0."""
    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.return_value.message_id = 111

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    fake_bot.send_message.assert_not_called()
    assert result.notified == 1
    assert result.notification_failed == 0
    assert result.router_image_sent == 1
    assert result.router_text_fallback_sent == 0


@pytest.mark.asyncio
async def test_photo_timeout_triggers_exactly_one_text_fallback_attempt(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirements 2 and 3: send_photo raising TelegramAPIError (the real production timeout
    shape) triggers exactly one send_message fallback attempt, which succeeds - notified once,
    notification_failed stays 0, router_image_sent stays 0 (the shape actually delivered was
    text, not photo), and the delivered message_id is the fallback's own."""
    from aiogram.exceptions import TelegramAPIError

    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]
    fake_bot.send_message.return_value.message_id = 222

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    fake_bot.send_message.assert_called_once()
    assert result.notified == 1
    assert result.notification_failed == 0
    assert result.router_image_sent == 0
    assert result.router_text_fallback_sent == 1


@pytest.mark.asyncio
async def test_photo_timeout_and_text_fallback_both_fail_counts_one_notification_failure(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 4: when the fallback also fails, notification_failed increments exactly
    once - never retried, never double-counted."""
    from aiogram.exceptions import TelegramAPIError

    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]
    fake_bot.send_message.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_called_once()
    fake_bot.send_message.assert_called_once()  # exactly one fallback attempt, never retried
    assert result.notified == 0
    assert result.notification_failed == 1
    assert result.router_image_sent == 0
    assert result.router_text_fallback_sent == 0


@pytest.mark.asyncio
async def test_media_group_timeout_triggers_text_fallback_router_media_group_sent_stays_zero(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 5: the media-group analogue - send_media_group raising TelegramAPIError
    triggers the same one-shot text fallback, which succeeds; router_media_group_sent stays 0
    (a media group was never actually delivered), router_text_fallback_sent counts it instead."""
    from aiogram.exceptions import TelegramAPIError

    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]
    fake_bot.send_message.return_value.message_id = 333
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
        _fake_candidate(candidate_id="c", rank=3, quality_score=80, relevance_score=80),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    fake_bot.send_message.assert_called_once()
    fake_bot.send_photo.assert_not_called()
    assert result.notified == 1
    assert result.notification_failed == 0
    assert result.router_media_group_sent == 0
    assert result.router_text_fallback_sent == 1


@pytest.mark.asyncio
async def test_media_group_succeeds_no_text_fallback_attempted(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 6: the unmodified media-group success path - no fallback call."""
    _common_settings(monkeypatch)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "8.2")
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v82_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_media_group.return_value = _fake_media_messages(3)
    candidates = [
        _fake_candidate(candidate_id="a", rank=1, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", rank=2, quality_score=85, relevance_score=85),
        _fake_candidate(candidate_id="c", rank=3, quality_score=80, relevance_score=80),
    ]

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch("worker.content_cycle.get_editorial_image_candidates", new=AsyncMock(return_value=candidates)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_media_group.assert_called_once()
    fake_bot.send_message.assert_not_called()
    assert result.notified == 1
    assert result.router_media_group_sent == 1
    assert result.router_text_fallback_sent == 0


@pytest.mark.asyncio
async def test_dry_run_never_attempts_a_real_send_or_a_fallback(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 7: dry-run must stay exactly as side-effect-free as before this fix.
    send_photo_to_editorial_destination()/send_media_group_to_editorial_destination() both
    short-circuit to sent=False, reason="dry_run" without ever calling the real bot method
    (services/telegram_routing.py's own established contract) - the new fallback guard
    (`not effective_dry_run`) must never treat that dry-run sent=False as a real failure worth
    a second, equally-fake send attempt."""
    settings.editorial_delivery_mode = "router"
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    monkeypatch.setattr(settings, "copywriting_prompt_version", "6")
    monkeypatch.setattr(settings, "content_generation_dry_run", True)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    fake_bot.send_photo.assert_not_called()
    fake_bot.send_message.assert_not_called()
    fake_bot.send_media_group.assert_not_called()
    assert result.dry_run_rendered == 1
    assert result.notified == 0
    assert result.notification_failed == 0
    assert result.router_image_sent == 0
    assert result.router_text_fallback_sent == 0


@pytest.mark.asyncio
async def test_fallback_reuses_the_exact_same_keyboard_and_reply_to_message_id(
    factory: async_sessionmaker[AsyncSession], test_source: object, _isolated_freshness_window: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement 9: the fallback call is the exact same send_to_editorial_destination() call
    every other plain-text NEWS send already uses, given the exact same `keyboard`/
    `reply_to_message_id` local variables the failed photo attempt itself received - proven here
    by object-identity on the keyboard (built exactly once per draft, never rebuilt for the
    fallback) and value-equality on reply_to_message_id, compared directly against what the
    failed send_photo call itself was actually invoked with (AsyncMock records call args before
    a side_effect exception is raised, so this is the real value passed, not a re-derived one)."""
    from aiogram.exceptions import TelegramAPIError

    _common_settings(monkeypatch)
    await _seed_eligible_event(factory, test_source)
    _gateway, registry = _v6_capability_registry()
    fake_bot = AsyncMock()
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]
    fake_bot.send_message.return_value.message_id = 444

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(return_value=_standard_decision()),
        ),
        patch(
            "worker.content_cycle.get_editorial_image_candidates",
            new=AsyncMock(return_value=[_fake_candidate()]),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.router_text_fallback_sent == 1
    photo_kwargs = fake_bot.send_photo.call_args.kwargs
    text_kwargs = fake_bot.send_message.call_args.kwargs
    assert text_kwargs["reply_markup"] is photo_kwargs["reply_markup"]  # exact same keyboard object
    assert text_kwargs["reply_to_message_id"] == photo_kwargs["reply_to_message_id"]
    assert text_kwargs["message_thread_id"] == photo_kwargs["message_thread_id"]
