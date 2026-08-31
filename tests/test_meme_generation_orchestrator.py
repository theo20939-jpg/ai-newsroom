"""MEME PRODUCTION PIPELINE (overnight phase): services.meme_generation_orchestrator -
trigger_meme_generation(). Real Postgres (db_session fixture), FakeLLMGateway (zero network/cost),
MockImageAdapter (zero network/cost, injected explicitly), LocalImageStorage(tmp_path), and a real
aiogram Bot bound to a fake in-memory session (no real Telegram API call ever) - mirrors this
codebase's own established DB-integration test shape (tests/test_telegraph_article_processor.py's
own `_DualGateway`/real-workflow-run pattern), generalized to MEME_GENERATION's own 4-step
workflow (research -> intelligence -> meme_concept -> meme_copywriting).
"""
from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendPhoto, TelegramMethod
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.intelligence_capability import INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability
from capabilities.meme_concept_capability import MEME_CONCEPT_CAPABILITY_DEFINITION, MemeConceptCapability
from capabilities.meme_copywriting_capability import (
    MEME_COPYWRITING_CAPABILITY_DEFINITION,
    MemeCopywritingCapability,
)
from capabilities.registry import CapabilityRegistry
from capabilities.research_capability import RESEARCH_CAPABILITY_DEFINITION, ResearchCapability
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import CapabilityUsage
from services.meme_generation_orchestrator import (
    _find_in_progress_meme_task,
    _normalize_alt_text,
    _resolve_default_image_gateway,
    trigger_meme_generation,
)
from tests.fakes.fake_gateway import FakeLLMGateway

_RESEARCH_OUTPUT = {"facts": ["Company X shipped product Y."], "confidence": 0.8, "gaps": []}
_INTELLIGENCE_OUTPUT = {
    # significance is `type: number` per prompts/intelligence/v1.yaml and v2.yaml's own
    # response_schema (both versions, confirmed by direct inspection) - a pre-existing fixture bug
    # (this literal was a string, "notable") found while verifying this phase's own new tests;
    # fixed here since it blocks every DB-backed test in this file from ever completing a real
    # workflow run, not just the ones this phase adds.
    "significance": 0.8, "angle": "irony", "audience_relevance": "high", "recommendation": "cover",
}
_CONCEPT_OUTPUT = {
    "premise": "Company X shipped product Y.", "setup": "Everyone expected a delay.",
    "punchline": "It shipped on time, somehow.", "humor_mechanism": "subverted expectation",
    "visual_scene": "A calendar with a shocked face emoji.", "characters_objects": ["calendar"],
    "text_overlay_intent": "Express disbelief.", "source_fact_links": ["Company X shipped product Y."],
    "forbidden_interpretations": [], "meme_format": "drake_comparison",
}
_COPY_OUTPUT = {
    "top_text": "NOBODY EXPECTED IT ON TIME", "bottom_text": "IT SHIPPED ON TIME",
    "punchline_short": "Shipped. On time. Somehow.", "telegram_caption": "When it actually ships on time.",
    "editor_explanation": "Plays on the surprise.", "alt_text": "A calendar with a shocked emoji.",
}


def _response(structured_output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=100),
    )


def _full_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    from integrations.prompts.file_repository import FilePromptRepository
    from pathlib import Path

    prompt_repository = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
    registry = CapabilityRegistry()
    registry.register(RESEARCH_CAPABILITY_DEFINITION, ResearchCapability(gateway, prompt_repository))
    registry.register(INTELLIGENCE_CAPABILITY_DEFINITION, IntelligenceCapability(gateway, prompt_repository))
    registry.register(MEME_CONCEPT_CAPABILITY_DEFINITION, MemeConceptCapability(gateway, prompt_repository))
    registry.register(MEME_COPYWRITING_CAPABILITY_DEFINITION, MemeCopywritingCapability(gateway, prompt_repository))
    registry.seal()
    return registry


def _gateway(*, concept_output: dict | None = None, copy_output: dict | None = None) -> FakeLLMGateway:
    return FakeLLMGateway(generate_responses=[
        _response(_RESEARCH_OUTPUT), _response(_INTELLIGENCE_OUTPUT),
        _response(concept_output or _CONCEPT_OUTPUT), _response(copy_output or _COPY_OUTPUT),
    ])


class _FakeBotSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        self.sent.append(method)
        from datetime import datetime, timezone as tz
        from aiogram.types import Chat, Message as AiogramMessage
        chat_id = getattr(method, "chat_id", 0)
        return AiogramMessage(message_id=1, date=datetime.now(tz.utc), chat=Chat(id=chat_id, type="supergroup"))

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def _bot() -> tuple[Bot, _FakeBotSession]:
    session = _FakeBotSession()
    return Bot(token="123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session), session


async def _make_event(db_session: AsyncSession, *, title: str = "Company X ships product Y on schedule, shocking everyone") -> NewsEvent:
    source = NewsSource(name=f"Orchestrator test source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title=title, content="Company X shipped product Y on schedule.",
        category=EventCategory.AI, hash=f"orch-{uuid.uuid4()}", published_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    await db_session.flush()
    return event


@pytest.fixture(autouse=True)
def _reset_meme_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -1004297182444)
    monkeypatch.setattr(settings, "meme_topic_id", 88)
    monkeypatch.setattr(settings, "meme_image_generation_mode", "dry_run")
    monkeypatch.setattr(settings, "meme_telegram_preview_mode", "enforce")
    monkeypatch.setattr(settings, "meme_safety_gate_mode", "off")
    monkeypatch.setattr(settings, "meme_opportunity_mode", "off")


@pytest.mark.asyncio
async def test_manual_trigger_bypasses_opportunity_gate_and_delivers(db_session: AsyncSession, tmp_path) -> None:
    event = await _make_event(db_session)
    gateway = _gateway()
    bot, session = _bot()
    storage = LocalImageStorage(tmp_path)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=storage, bot=bot,
    )

    assert outcome.status == "delivered"
    assert outcome.candidate_id is not None
    # services/meme_preview_notifier.py sends the generated image via bot.send_photo() (SendPhoto),
    # falling back to bot.send_message() only when no photo is available - a successful delivery
    # with a real generated+watermarked image always takes the SendPhoto path (pre-existing fixture
    # bug found here: this assertion previously filtered SendMessage, which this success path never
    # sends, silently masking itself behind an earlier, unrelated fixture bug - see _INTELLIGENCE_
    # OUTPUT's own comment above).
    sends = [m for m in session.sent if isinstance(m, SendPhoto)]
    assert len(sends) == 1
    assert sends[0].chat_id == -1004297182444
    assert sends[0].message_thread_id == 88


@pytest.mark.asyncio
async def test_automatic_trigger_enforce_mode_rejects_low_signal_story(db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meme_opportunity_mode", "enforce")
    # A dry, unremarkable HARDWARE story with no irony/relatability/visual markers scores low.
    event = await _make_event(db_session, title="Quarterly firmware update released")
    event.category = EventCategory.HARDWARE
    event.content = "A routine firmware update was released."
    await db_session.flush()
    gateway = _gateway()
    bot, session = _bot()
    storage = LocalImageStorage(tmp_path)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="automatic",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=storage, bot=bot,
    )

    assert outcome.status == "not_meme_worthy"
    assert outcome.task_id is None
    assert gateway.received_requests == []  # zero LLM calls - the gate short-circuits before any task
    assert session.sent == []


@pytest.mark.asyncio
async def test_zero_worthy_candidate_is_a_valid_non_error_outcome(db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors the prior test's own assertion under a different name - the required matrix's own
    explicit "zero-worthy-candidate outcome valid" case: not_meme_worthy is a normal, successful
    return value, never an exception."""
    monkeypatch.setattr(settings, "meme_opportunity_mode", "enforce")
    event = await _make_event(db_session, title="Minor spec sheet update")
    event.category = EventCategory.HARDWARE
    event.content = "A minor spec sheet correction."
    await db_session.flush()
    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="automatic",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert outcome.status == "not_meme_worthy"  # a valid PASS, not a raised exception


@pytest.mark.asyncio
async def test_debounce_blocks_rapid_duplicate_while_in_progress(db_session: AsyncSession, tmp_path) -> None:
    """Simulates 'in progress' by creating a real MEME_GENERATION task in CREATED status directly
    (without running it) - a genuine, unfinished task for this event."""
    from schemas.workflow import WorkflowExecutionState, WorkflowType
    from workflows.registry import registry as default_registry

    event = await _make_event(db_session)
    definition = default_registry.resolve(WorkflowType.MEME_GENERATION)
    state = WorkflowExecutionState(
        workflow_name=definition.name, workflow_version=definition.version,
        current_step=definition.steps[0].name, completed_steps=[], iteration_count=0,
        step_results=[], failure=None,
    )
    in_progress_task = EditorialTask(
        event_id=event.id, priority=TaskPriority.C, workflow=state.model_dump(mode="json"),
        status=TaskStatus.RUNNING, retry_count=0,
    )
    db_session.add(in_progress_task)
    await db_session.commit()

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert outcome.status == "already_in_progress"
    assert outcome.task_id == in_progress_task.id


@pytest.mark.asyncio
async def test_repeated_manual_trigger_after_completion_creates_new_variant(db_session: AsyncSession, tmp_path) -> None:
    event = await _make_event(db_session)
    storage = LocalImageStorage(tmp_path)

    first = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=storage, bot=_bot()[0],
    )
    assert first.status == "delivered"

    second = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=storage, bot=_bot()[0],
    )
    assert second.status == "delivered"
    assert second.task_id != first.task_id
    assert second.candidate_id != first.candidate_id  # a genuinely NEW variant, not a reused one

    rows = (await db_session.execute(select(MemeCandidate).where(MemeCandidate.news_event_id == event.id))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_safety_enforce_blocks_and_persists_candidate_without_image(db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meme_safety_gate_mode", "enforce")
    event = await _make_event(db_session)
    unsafe_concept = {**_CONCEPT_OUTPUT, "premise": "A tragedy occurred and someone died."}
    gateway = _gateway(concept_output=unsafe_concept)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )

    assert outcome.status == "safety_blocked"
    assert outcome.candidate_id is not None
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.SAFETY_BLOCKED
    assert candidate.image_status is None  # image generation never attempted


@pytest.mark.asyncio
async def test_image_generation_off_mode_never_delivers(db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meme_image_generation_mode", "off")
    event = await _make_event(db_session)
    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert outcome.status == "image_generation_failed"  # OFF status is not GENERATED -> treated as failure to deliver


@pytest.mark.asyncio
async def test_watermark_applied_on_every_successful_delivery(db_session: AsyncSession, tmp_path) -> None:
    """Proves the compositor is actually invoked on the real success path - the final persisted
    render_storage_key must point at WATERMARKED bytes, never the raw rendered-only bytes."""
    event = await _make_event(db_session)
    storage = LocalImageStorage(tmp_path)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=storage, bot=_bot()[0],
    )
    assert outcome.status == "delivered"
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.render_storage_key is not None

    from PIL import Image
    import io

    final_bytes = storage.read(candidate.render_storage_key)
    final_image = Image.open(io.BytesIO(final_bytes)).convert("RGB")
    # The real, precise pixel-level proof that the compositor actually changes pixels lives in
    # tests/test_meme_watermark.py; this is an end-to-end smoke check that the full pipeline
    # reaches watermarking and persists a real, decodable final image (never crashes, never skips
    # the step) - exact pixel equality isn't asserted here since MockImageAdapter's own generated
    # background is itself non-deterministic-looking gradient/noise content.
    assert final_image.size[0] > 0 and final_image.size[1] > 0
    assert candidate.render_storage_key != candidate.image_storage_key  # a genuinely different, later asset


# ---------------------------------------------------------------------------
# MEME-PROD-2: _resolve_default_image_gateway() provider selection - OpenAI (gpt-image-2), not
# Gemini. No real network call anywhere below - constructing an OpenAIImageAdapter only stores its
# fields (integrations/llm_gateway/providers/openai_image_adapter.py::__init__ constructs a real
# `AsyncOpenAI()` client object, which itself makes no network call at construction time); these
# tests prove SEAM SELECTION, never call generate_image() on a real adapter.
# ---------------------------------------------------------------------------


def test_resolve_default_gateway_is_mock_in_off_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meme_image_generation_mode", "off")
    gateway = _resolve_default_image_gateway()
    assert isinstance(gateway, MockImageAdapter)


def test_resolve_default_gateway_is_mock_in_dry_run_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meme_image_generation_mode", "dry_run")
    gateway = _resolve_default_image_gateway()
    assert isinstance(gateway, MockImageAdapter)


def test_resolve_default_gateway_is_openai_in_enforce_mode_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from integrations.llm_gateway.providers.openai_image_adapter import OpenAIImageAdapter

    monkeypatch.setattr(settings, "meme_image_generation_mode", "enforce")
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-only-fake-key-never-real"))

    gateway = _resolve_default_image_gateway()

    assert isinstance(gateway, OpenAIImageAdapter)
    assert gateway.CAPABILITIES.supports_text_to_image is True  # meme generation is pure TEXT_TO_IMAGE
    assert gateway._quality == "medium"  # noqa: SLF001 - §5's own required default production profile
    assert gateway._text_to_image_size == "1024x1024"  # noqa: SLF001


def test_resolve_default_gateway_is_none_in_enforce_mode_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The explicit fail-closed proof required by Section 4: enforce mode with no configured
    credential must return None, never silently fall back to MockImageAdapter."""
    monkeypatch.setattr(settings, "meme_image_generation_mode", "enforce")
    monkeypatch.setattr(settings, "openai_api_key", None)

    gateway = _resolve_default_image_gateway()

    assert gateway is None


def test_resolve_default_gateway_ignores_gemini_key_in_enforce_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """MEME-PROD-2 §7/§14: Gemini must no longer be selected for MEME enforce generation, even
    when a valid gemini_api_key IS configured (e.g. for editorial_recomposition.py's own,
    unaffected use) - only openai_api_key governs this seam now."""
    from pydantic import SecretStr

    from integrations.llm_gateway.providers.openai_image_adapter import OpenAIImageAdapter

    monkeypatch.setattr(settings, "meme_image_generation_mode", "enforce")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("a-real-looking-gemini-key"))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("a-real-looking-openai-key"))

    gateway = _resolve_default_image_gateway()

    assert isinstance(gateway, OpenAIImageAdapter)


def test_resolve_default_gateway_fails_closed_even_when_only_gemini_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: a configured gemini_api_key must never be used as a fallback credential for
    the MEME image seam - only openai_api_key counts."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "meme_image_generation_mode", "enforce")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("a-real-looking-gemini-key"))
    monkeypatch.setattr(settings, "openai_api_key", None)

    gateway = _resolve_default_image_gateway()

    assert gateway is None


def test_editorial_recomposition_still_imports_gemini_adapter_unaffected() -> None:
    """§7/§15: this phase only removes Gemini from the MEME image-generation seam - unrelated
    Gemini functionality (live NEWS photo recomposition) must remain completely untouched.
    Structural, source-level proof rather than exercising that whole separate module."""
    import inspect

    import services.editorial_recomposition as recomposition_module

    source = inspect.getsource(recomposition_module)
    assert "GeminiImageAdapter" in source
    assert "GEMINI_3_1_FLASH_IMAGE" in source


# ---------------------------------------------------------------------------
# REAL IMAGE PROVIDER FINALIZATION: trigger_meme_generation() end-to-end, WITHOUT an injected
# image_gateway - proving the production default-resolution path itself, not just test injection.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_gateway_is_mock_when_not_injected_in_dry_run_mode(db_session: AsyncSession, tmp_path) -> None:
    """dry_run (the _reset_meme_modes fixture's own default) never calls a paid provider even when
    no image_gateway is explicitly injected - the production default resolves to MockImageAdapter,
    recorded on the persisted candidate as provider="mock"."""
    event = await _make_event(db_session)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
        # image_gateway intentionally omitted - exercising the real default-resolution seam.
    )

    assert outcome.status == "delivered"
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.image_provider == "mock"


@pytest.mark.asyncio
async def test_enforce_mode_without_provider_fails_closed_never_falls_back_to_mock(
    db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 4's explicit required test: enforce mode with no openai_api_key configured must
    fail closed BEFORE any task/candidate is created - never silently deliver a Mock-generated
    placeholder as if it were a real image."""
    monkeypatch.setattr(settings, "meme_image_generation_mode", "enforce")
    monkeypatch.setattr(settings, "openai_api_key", None)
    event = await _make_event(db_session)
    gateway = _gateway()

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(gateway),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
        # image_gateway intentionally omitted - the whole point of this test.
    )

    assert outcome.status == "provider_not_configured"
    assert outcome.task_id is None
    assert outcome.candidate_id is None
    assert gateway.received_requests == []  # zero LLM calls - fails closed before any workflow work
    rows = (await db_session.execute(select(MemeCandidate).where(MemeCandidate.news_event_id == event.id))).scalars().all()
    assert rows == []  # zero candidates persisted - never a placeholder passed off as real


# ---------------------------------------------------------------------------
# MEME-PROD-1: automatic-worthy ACCEPT path (the reject path above was already covered; the
# accept-and-actually-generate path was not), story/news identity preservation, and a structural
# no-outward-publish proof.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_automatic_trigger_enforce_mode_accepts_high_signal_story_and_delivers(
    db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely high-signal story (gold-labeled MEME_READY in tests/test_phase18_m1_meme_
    opportunity.py's own gold set, empirically confirmed to score >= the READY threshold under the
    real, unmocked classifier) must actually proceed through the full pipeline under enforce mode -
    the automatic path is not just capable of REJECTING, it must also actually ACCEPT and deliver."""
    monkeypatch.setattr(settings, "meme_opportunity_mode", "enforce")
    event = await _make_event(
        db_session, title="CEO of Nvidia insists AI is not destroying jobs",
    )
    event.content = "The Nvidia chief executive publicly insists artificial intelligence is not destroying jobs."
    await db_session.flush()
    gateway = _gateway()
    bot, session = _bot()

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="automatic",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=bot,
    )

    assert outcome.status == "delivered"
    assert outcome.task_id is not None
    assert outcome.candidate_id is not None
    assert len(gateway.received_requests) == 4  # research, intelligence, meme_concept, meme_copywriting
    sends = [m for m in session.sent if isinstance(m, SendPhoto)]
    assert len(sends) == 1


@pytest.mark.asyncio
async def test_source_news_identity_preserved_through_the_full_pipeline(db_session: AsyncSession, tmp_path) -> None:
    """The delivered candidate/card is bound to the EXACT NewsEvent the pipeline started from -
    never a different or re-derived event - throughout concept generation, candidate persistence,
    and delivery."""
    event = await _make_event(db_session, title="A specific, uniquely identifiable news headline")
    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert outcome.status == "delivered"
    assert outcome.news_event_id == event.id

    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.news_event_id == event.id  # bound to the exact event, never a different one

    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    assert task.event_id == event.id  # the workflow task itself is anchored to the same event


# ---------------------------------------------------------------------------
# MEME-PROD-1: structural - no outward/public publishing path anywhere in the meme delivery chain.
# Mirrors tests/test_telegraph_article_processor.py's own established
# test_no_telegram_or_telegraph_publishing_reference_in_processor_source() pattern.
# ---------------------------------------------------------------------------

_ORCHESTRATOR_SOURCE = Path("services/meme_generation_orchestrator.py").read_text(encoding="utf-8")
_PREVIEW_NOTIFIER_SOURCE = Path("services/meme_preview_notifier.py").read_text(encoding="utf-8")


def test_orchestrator_never_references_an_external_publishing_api() -> None:
    for forbidden in ("telegra.ph", "createPage", "createAccount", "requests.post", "httpx.post", "urlopen"):
        assert forbidden not in _ORCHESTRATOR_SOURCE, f"unexpected reference: {forbidden}"
        assert forbidden not in _PREVIEW_NOTIFIER_SOURCE, f"unexpected reference: {forbidden}"


def test_preview_notifier_only_ever_routes_to_the_meme_editorial_destination() -> None:
    """`EditorialDestination.MEME` is the only destination this module's own send call may ever
    resolve - proven by scanning for every OTHER destination member name in the source text (a
    real reference to e.g. `EditorialDestination.NEWS` here would mean a second, un-audited send
    path exists)."""
    for other_destination in ("EditorialDestination.NEWS", "EditorialDestination.TELEGRAPH", "EditorialDestination.INSTAGRAM", "EditorialDestination.REELS"):
        assert other_destination not in _PREVIEW_NOTIFIER_SOURCE, f"unexpected reference: {other_destination}"
    assert "EditorialDestination.MEME" in _PREVIEW_NOTIFIER_SOURCE


# ---------------------------------------------------------------------------
# MEME-PROD-1B: production canary - MemeCopy.alt_text > 200 chars crashed the manual callback with
# an uncaught pydantic ValidationError. _normalize_alt_text() unit tests first (pure, no DB), then
# end-to-end orchestrator tests proving generation continues (never crashes) after normalization,
# other validation failures still fail closed without crashing, and a failed task never blocks a
# retry through _find_in_progress_meme_task().
# ---------------------------------------------------------------------------


def test_normalize_alt_text_leaves_text_at_or_under_limit_unchanged() -> None:
    exactly_200 = "x" * 200
    assert _normalize_alt_text(exactly_200) == exactly_200
    short = "A short description."
    assert _normalize_alt_text(short) == short


def test_normalize_alt_text_shortens_oversized_text_to_the_limit() -> None:
    oversized = "word " * 60  # 300 chars
    result = _normalize_alt_text(oversized)
    assert len(result) <= 200
    assert len(result) > 0


def test_normalize_alt_text_never_ends_on_broken_whitespace_or_dangling_punctuation() -> None:
    oversized = ("A photo of a robot, standing, waiting, thinking, wondering, calculating, " * 4)[:250]
    result = _normalize_alt_text(oversized)
    assert result == result.rstrip()  # no trailing whitespace
    assert result[-1] not in ",;:–—-("  # never ends on dangling connective punctuation


def test_normalize_alt_text_handles_cyrillic_correctly() -> None:
    cyrillic = "Скриншот с забавным текстом про ИИ, который заменяет работу программистов совсем скоро, по мнению аналитиков рынка труда " * 2
    assert len(cyrillic) > 200
    result = _normalize_alt_text(cyrillic)
    assert len(result) <= 200
    assert len(result) > 0
    assert result == result.rstrip()


def test_normalize_alt_text_handles_emoji_and_zwj_sequences_without_breaking() -> None:
    emoji_text = ("A robot 🤖 typing on a keyboard 💻 while a human watches nervously 😰 in a busy office " * 3) + "👨‍👩‍👧"
    assert len(emoji_text) > 200
    result = _normalize_alt_text(emoji_text)
    assert len(result) <= 200
    assert len(result) > 0
    # never ends on a lone zero-width-joiner or variation selector (a half-rendered glyph)
    assert result[-1] != "‍"
    assert not unicodedata.combining(result[-1])


@pytest.mark.asyncio
async def test_oversized_alt_text_is_normalized_and_generation_still_delivers(
    db_session: AsyncSession, tmp_path,
) -> None:
    """The exact production defect: MemeCopy.alt_text > 200 chars must never crash
    trigger_meme_generation() - it is normalized in place and the pipeline completes normally,
    reaching image generation and delivery."""
    event = await _make_event(db_session)
    oversized_copy = {**_COPY_OUTPUT, "alt_text": "A very detailed description of the meme image. " * 6}
    assert len(oversized_copy["alt_text"]) > 200
    gateway = _gateway(copy_output=oversized_copy)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )

    assert outcome.status == "delivered"
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.copy_data is not None
    assert len(candidate.copy_data["alt_text"]) <= 200
    assert candidate.image_status == "generated"  # image generation was actually reached


@pytest.mark.asyncio
async def test_valid_alt_text_at_exactly_200_is_never_touched(db_session: AsyncSession, tmp_path) -> None:
    event = await _make_event(db_session)
    exact_copy = {**_COPY_OUTPUT, "alt_text": "x" * 200}
    gateway = _gateway(copy_output=exact_copy)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )

    assert outcome.status == "delivered"
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.copy_data is not None
    assert candidate.copy_data["alt_text"] == "x" * 200  # byte-for-byte unchanged


@pytest.mark.asyncio
async def test_normal_valid_copy_completely_unaffected_by_the_normalization_seam(
    db_session: AsyncSession, tmp_path,
) -> None:
    event = await _make_event(db_session)
    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert outcome.status == "delivered"
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.copy_data is not None
    assert candidate.copy_data["alt_text"] == _COPY_OUTPUT["alt_text"]
    assert candidate.copy_data["top_text"] == _COPY_OUTPUT["top_text"]  # untouched


@pytest.mark.asyncio
async def test_other_invalid_required_field_still_fails_closed_without_crashing(
    db_session: AsyncSession, tmp_path,
) -> None:
    """A malformed field OTHER than alt_text (e.g. an empty required top_text) is never
    auto-repaired (brief's own "do not alter... unless required") - it must still fail closed via
    a controlled MemeGenerationOutcome, never an uncaught ValidationError."""
    event = await _make_event(db_session)
    broken_copy = {**_COPY_OUTPUT, "top_text": ""}  # violates MemeCopy's own min_length=1
    gateway = _gateway(copy_output=broken_copy)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(gateway), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )

    assert outcome.status == "copy_validation_failed"
    assert outcome.error is not None
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.copy_data is None  # attach_copy() was never reached


@pytest.mark.asyncio
async def test_copy_validation_failure_never_blocks_a_subsequent_manual_retry(
    db_session: AsyncSession, tmp_path,
) -> None:
    """Critical debounce-safety proof (§6): WorkflowRunner.run() already commits the EditorialTask
    as COMPLETED before trigger_meme_generation() ever reaches MemeCopy.model_validate() (workflows/
    runner.py's own unconditional `task.status = TaskStatus.COMPLETED; await session.commit()` on
    every exit path) - a copy-validation failure can therefore never leave a non-terminal task.
    _find_in_progress_meme_task() must report None immediately afterward, and a second manual
    click must be free to create a genuinely new task/candidate, exactly like any other completed-
    but-undelivered attempt."""
    event = await _make_event(db_session)
    broken_copy = {**_COPY_OUTPUT, "top_text": ""}

    first = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway(copy_output=broken_copy)), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert first.status == "copy_validation_failed"
    assert first.task_id is not None

    failed_task = await db_session.get(EditorialTask, first.task_id)
    assert failed_task is not None
    assert failed_task.status == TaskStatus.COMPLETED  # terminal, never left RUNNING/CREATED/WAITING

    in_progress = await _find_in_progress_meme_task(db_session, event.id)
    assert in_progress is None  # never blocks the next click

    second = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=MockImageAdapter(),
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )
    assert second.status == "delivered"
    assert second.task_id != first.task_id  # a genuinely new attempt, not blocked/reused


# ---------------------------------------------------------------------------
# MEME-PROD-2: full pipeline integration with a REAL OpenAIImageAdapter instance (not Mock) - the
# underlying AsyncOpenAI client is injected/mocked (test_v2_1_openai_image_adapter.py's own
# established "AsyncMock-injected client + real SDK Pydantic response types" convention), so this
# proves the real adapter's own request/response translation integrates correctly with the rest of
# the pipeline (storage -> render_meme() -> apply_nnj_watermark() -> delivery), never just that
# Mock happens to work. No real network call anywhere in this section.
# ---------------------------------------------------------------------------


def _openai_gateway_with_valid_png():
    from tests.test_v2_1_openai_image_adapter import _FakeRawResponse, _images_response, _mock_client

    from integrations.llm_gateway.providers.openai_image_adapter import OpenAIImageAdapter

    # A real, valid, decodable 8x8 PNG (not the test-only opaque bytes test_v2_1's own fixtures
    # use) - generate_meme_image()'s own Image.open()/.verify() must succeed on it for the
    # pipeline to actually proceed past image generation into storage/render/watermark.
    import base64
    import io as _io

    from PIL import Image as _Image

    buf = _io.BytesIO()
    _Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    valid_png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    client = _mock_client(_FakeRawResponse(_images_response(b64_json=valid_png_b64)), method="generate")
    return OpenAIImageAdapter(api_key="fake-key-never-real", client=client)


@pytest.mark.asyncio
async def test_real_openai_adapter_success_reaches_deterministic_render_and_watermark(
    db_session: AsyncSession, tmp_path,
) -> None:
    """§9/§12/§14 combined proof: a successful REAL OpenAIImageAdapter generation still flows
    through the completely unchanged storage/render_meme()/apply_nnj_watermark()/delivery chain -
    the OpenAI adapter never adds branding itself, never renders meme typography itself."""
    event = await _make_event(db_session)
    image_gateway = _openai_gateway_with_valid_png()

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=image_gateway,
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )

    assert outcome.status == "delivered"
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.image_provider == "openai"  # the real adapter's own provider label
    assert candidate.image_status == "generated"
    assert candidate.render_storage_key is not None  # render_meme() ran
    assert candidate.render_storage_key != candidate.image_storage_key  # watermark() produced a distinct, later asset


@pytest.mark.asyncio
async def test_real_openai_adapter_failure_becomes_controlled_outcome_never_crashes(
    db_session: AsyncSession, tmp_path,
) -> None:
    """§11: a real OpenAIImageAdapter failure (e.g. the provider itself returning empty image
    data) must still resolve to the controlled `image_generation_failed` outcome - never an
    uncaught exception reaching the manual callback."""
    from tests.test_v2_1_openai_image_adapter import _FakeRawResponse, _images_response, _mock_client

    from integrations.llm_gateway.providers.openai_image_adapter import OpenAIImageAdapter

    client = _mock_client(_FakeRawResponse(_images_response(b64_json=None)), method="generate")
    image_gateway = OpenAIImageAdapter(api_key="fake-key-never-real", client=client)
    event = await _make_event(db_session)

    outcome = await trigger_meme_generation(
        db_session, news_event_id=event.id, trigger_source="manual",
        capability_registry=_full_registry(_gateway()), image_gateway=image_gateway,
        storage=LocalImageStorage(tmp_path), bot=_bot()[0],
    )

    assert outcome.status == "image_generation_failed"  # controlled, never a raised exception
    candidate = await db_session.get(MemeCandidate, outcome.candidate_id)
    assert candidate is not None
    assert candidate.render_storage_key is None  # never reached rendering
