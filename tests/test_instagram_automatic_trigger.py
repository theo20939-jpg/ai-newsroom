"""INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1 §16: the required test matrix for the automatic
newsroom-to-Instagram-Telegram trigger. `FakeLLMGateway`/`FakePromptRepository` mirror
`tests/test_instagram_creative_director.py`'s own established convention exactly - zero real
LLM/network calls. `Bot` is a plain `unittest.mock.AsyncMock`, mirroring `tests/test_telegram_
editorial_routing.py`'s own convention - zero real Telegram API contact."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.instagram_editorial_delivery import InstagramEditorialDelivery
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.editorial_treatment import BRIEF, MAJOR, SKIP, STANDARD, EditorialTreatmentDecision
from services.instagram_automatic_trigger import evaluate_and_submit_instagram_candidate
from services.instagram_creative_director import SINGLE_PROMPT_NAME
from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService, compute_package_identity
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_SINGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "creative_angle": {"type": "string"}, "visual_concept": {"type": "string"},
        "on_image_copy": {"type": "string"}, "caption_direction": {"type": "string"},
        "cta": {"type": ["string", "null"]}, "asset_requirements": {"type": "array"},
        "evidence_used": {"type": "array"},
    },
    "required": ["creative_angle", "visual_concept", "on_image_copy", "caption_direction", "asset_requirements", "evidence_used"],
}


@pytest.fixture(autouse=True)
def _topic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -1002345678901)
    monkeypatch.setattr(settings, "instagram_topic_id", 40)


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=SINGLE_PROMPT_NAME, version="2", system="you are the creative director", rules=["never invent facts"],
        output_schema=_SINGLE_SCHEMA,
    ))
    return repository


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=200, output_tokens=150),
    ))


_GOOD_OUTPUT = {
    "creative_angle": "a real breakthrough", "visual_concept": "bold headline over dark gradient",
    "on_image_copy": "Big Tech Story Breaks", "caption_direction": "explain what happened and why it matters",
    "cta": "Follow for more", "asset_requirements": [], "evidence_used": ["Company X announced Y on 2026-09-14"],
}

_MAJOR = EditorialTreatmentDecision(treatment=MAJOR, human_review_required=False, reason="high significance")
_STANDARD = EditorialTreatmentDecision(treatment=STANDARD, human_review_required=False, reason="medium significance")
_BRIEF = EditorialTreatmentDecision(treatment=BRIEF, human_review_required=True, reason="low significance")
_SKIP = EditorialTreatmentDecision(treatment=SKIP, human_review_required=False, reason="too weak")


async def _submit(session: AsyncSession, *, event_id: str, treatment: EditorialTreatmentDecision, output: dict = _GOOD_OUTPUT):
    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 601
    bot.send_message.return_value.message_id = 602
    outcome = await evaluate_and_submit_instagram_candidate(
        session, bot, event_id=event_id, event_title="A real breaking story", treatment=treatment,
        research_facts=["Company X announced Y on 2026-09-14"], gateway=_gateway(output),
        prompt_repository=_prompt_repository(),
    )
    return outcome, bot


# ---------------------------------------------------------------------------
# A/B - selection: MAJOR triggers, STANDARD/BRIEF/SKIP never force a package
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_major_treatment_triggers_a_real_evaluation_and_delivery(db_session: AsyncSession) -> None:
    outcome, bot = await _submit(db_session, event_id="evt-major-1", treatment=_MAJOR)
    assert outcome.accepted is True
    assert outcome.gate_decision == "ready_for_editor"
    assert outcome.delivery_sent is True
    bot.send_photo.assert_called_once()


@pytest.mark.parametrize("treatment", [_STANDARD, _BRIEF, _SKIP])
@pytest.mark.asyncio
async def test_b_non_major_treatment_never_forces_a_package(db_session: AsyncSession, treatment: EditorialTreatmentDecision) -> None:
    outcome, bot = await _submit(db_session, event_id=f"evt-{treatment.treatment.lower()}", treatment=treatment)
    assert outcome.accepted is False
    assert outcome.reason == f"treatment={treatment.treatment}"
    bot.send_photo.assert_not_called()
    bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# C/E - idempotent submission (no duplicate work, no resend)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_same_story_on_next_cycle_does_not_duplicate_work(db_session: AsyncSession) -> None:
    first, bot1 = await _submit(db_session, event_id="evt-dup-1", treatment=_MAJOR)
    assert first.delivery_sent is True

    second, bot2 = await _submit(db_session, event_id="evt-dup-1", treatment=_MAJOR)
    assert second.reason == "already_submitted"
    bot2.send_photo.assert_not_called()  # no second Creative Director call, no second Telegram send
    bot2.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_e_existing_persisted_package_does_not_resend(db_session: AsyncSession) -> None:
    """Same as C, phrased against the persisted row directly (§16.E)."""
    outcome, _ = await _submit(db_session, event_id="evt-persisted-1", treatment=_MAJOR)
    identity = compute_package_identity(source_key="evt-persisted-1", content_format="single")
    delivery = await InstagramEditorialDeliveryService().find_current(db_session, package_identity=identity)
    assert delivery is not None
    before_updated_at = delivery.updated_at

    again, bot = await _submit(db_session, event_id="evt-persisted-1", treatment=_MAJOR)
    assert again.reason == "already_submitted"
    reloaded = await db_session.get(InstagramEditorialDelivery, delivery.id)
    assert reloaded.updated_at == before_updated_at
    bot.send_photo.assert_not_called()


# ---------------------------------------------------------------------------
# F/G/H - topic correctness + QA gate authority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_ready_package_delivers_to_the_configured_instagram_topic(db_session: AsyncSession) -> None:
    outcome, bot = await _submit(db_session, event_id="evt-topic-1", treatment=_MAJOR)
    assert outcome.delivery_sent is True
    assert bot.send_photo.call_args.args[0] == -1002345678901
    assert bot.send_photo.call_args.kwargs["message_thread_id"] == 40


@pytest.mark.asyncio
async def test_g_hold_package_never_presented_as_ready(db_session: AsyncSession) -> None:
    """A restricted claim not present in allowed_evidence makes the Creative Director's own
    fact-safety check fail closed - exercised here via evidence_used citing something never
    supplied, forcing a Creative-Director-level rejection (a defense-in-depth path this module
    must survive without crashing, distinct from a real HOLD/BLOCK from the Art/Editorial gate)."""
    bad_output = dict(_GOOD_OUTPUT, evidence_used=["a fact that was never in allowed_evidence"])
    outcome, bot = await _submit(db_session, event_id="evt-hold-1", treatment=_MAJOR, output=bad_output)
    assert outcome.reason.startswith("creative_director_failed")
    bot.send_photo.assert_not_called()


# ---------------------------------------------------------------------------
# J/K - independence from Instagram credentials/media hosting
# ---------------------------------------------------------------------------


def test_j_and_k_module_never_imports_credentials_or_media_hosting() -> None:
    import ast
    import inspect

    import services.instagram_automatic_trigger as trigger_module

    tree = ast.parse(inspect.getsource(trigger_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "services.instagram_account_reader" not in imported
    assert "services.instagram_media_hosting" not in imported


# ---------------------------------------------------------------------------
# M - zero Instagram write calls (structural, mirrors the delivery module's own test)
# ---------------------------------------------------------------------------


def test_m_no_instagram_publish_import_anywhere_in_the_trigger_module() -> None:
    import ast
    import inspect

    import services.instagram_automatic_trigger as trigger_module

    tree = ast.parse(inspect.getsource(trigger_module))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "services.instagram_publish_adapter" not in imported


# ---------------------------------------------------------------------------
# T - publication flags stay false throughout
# ---------------------------------------------------------------------------


def test_t_publication_flags_remain_false() -> None:
    assert settings.instagram_publication_enabled is False
    assert settings.instagram_autonomous_publication_enabled is False
