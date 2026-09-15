"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1 CORRECTION (Founder pre-deploy review): a bare "да"/
"нет" answering a Director information-need QUESTION is a substantive contextual answer, never a
confirmation act and never rejected merely for being short - distinct from a bare "да"/"подтверждаю"
confirming an already-parsed Product Truth PROPOSAL. `bot.handlers.business_context.handle_plain_text`
now checks `resolved.origin == DIRECTOR_INITIATED_ORIGIN` BEFORE the bare-confirmation-phrase branch,
so ANY text (including a bare "да") reaching a resolved Director question is parsed as an answer
WITH that question's own text/missing_fact for grounding, never rejected with "ответьте по существу".

Same harness as tests/test_instagram_content_strategy_v2_phase1_fixtures.py (real Postgres
db_session, FakeLLMGateway with canned extraction, MagicMock aiogram Message) - duplicated locally
per that file's own established one-harness-per-phase-file convention."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bot.handlers.business_context as module
from core.config import settings
from database.models.business_context_proposal import BusinessContextProposal, BusinessContextProposalStatus
from integrations.llm_gateway.protocol import GenerateResponse
from schemas.capability import CapabilityUsage
from services.business_context_proposal_service import confirm_proposal, create_director_information_need
from services.product_context_service import create_product, get_product_by_slug
from tests.fakes.fake_gateway import FakeLLMGateway

_CHAT_ID = -1004297182444
_FOUNDER = 5507703201


class _DbSessionCm:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _enable_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _CHAT_ID)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    monkeypatch.setattr(settings, "business_context_role_map", {_FOUNDER: "founder"})


def _wire_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(module, "async_session_factory", lambda: _DbSessionCm(db_session))


def _wire_gateway(monkeypatch: pytest.MonkeyPatch, outputs: list[dict]) -> FakeLLMGateway:
    responses = [
        GenerateResponse(
            text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=50, output_tokens=30),
        )
        for output in outputs
    ]
    gateway = FakeLLMGateway(generate_responses=responses)
    from tests.fakes.fake_prompt_repository import FakePromptRepository
    from integrations.prompts.protocol import RenderedPrompt
    from services.business_context_command_parser import PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION

    prompt_repository = FakePromptRepository()
    prompt_repository.register(RenderedPrompt(
        name=PARSER_PROMPT_NAME, version=PARSER_PROMPT_VERSION, system="parse", rules=[],
        output_schema={"type": "object", "properties": {}, "required": []},
    ))
    monkeypatch.setattr(module, "_ai_layer", MagicMock(gateway=gateway))
    monkeypatch.setattr(module, "_prompt_repository", prompt_repository)
    return gateway


def _empty_output(**overrides) -> dict:
    base = {
        "products_mentioned": [], "campaign_updates": [], "milestones": [], "directives": [],
        "claims": [], "clarification_needed": [],
    }
    base.update(overrides)
    return base


def _message(
    *, text: str, message_id: int = 900, reply_to_message_id: int | None = None, user_id: int = _FOUNDER,
) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.chat.id = _CHAT_ID
    message.message_thread_id = None
    message.message_id = message_id
    message.from_user.id = user_id
    if reply_to_message_id is not None:
        message.reply_to_message = MagicMock()
        message.reply_to_message.message_id = reply_to_message_id
    else:
        message.reply_to_message = None

    sent = MagicMock()
    sent.message_id = message_id + 1
    message.answer = AsyncMock(return_value=sent)
    return message


async def _only_pending(db_session: AsyncSession) -> BusinessContextProposal:
    stmt = select(BusinessContextProposal).where(BusinessContextProposal.status == BusinessContextProposalStatus.PENDING)
    rows = list((await db_session.execute(stmt)).scalars().all())
    assert len(rows) == 1, f"expected exactly one pending proposal, found {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# 1: bare "да" answering a Director QUESTION is accepted as a substantive answer, not rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_da_answers_a_director_question_produces_a_proposal_not_a_rejection(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    await create_product(db_session, slug="ai", name="NINJA AI")
    question = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.availability",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT",
        question_text="Production Mode уже доступен всем пользователям?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    question.telegram_message_id = 700
    await db_session.commit()

    gateway = _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.availability", "feature_name": "Production Mode",
                "fact_state": "confirmed",
            }],
        }]),
    ])

    message = _message(text="да", message_id=950, reply_to_message_id=700)
    await module.handle_plain_text(message)

    # The parser WAS called (never rejected with "ответьте по существу") - and received the
    # question's own text/missing_fact for grounding, not the bare "да" in isolation.
    assert len(gateway.received_requests) == 1
    request = gateway.received_requests[0]
    combined_prompt_text = " ".join(
        part.text for message_ in request.messages for part in message_.content if part.text
    )
    assert "Production Mode уже доступен всем пользователям?" in combined_prompt_text
    assert "production_mode.availability" in combined_prompt_text

    # The question is now closed, and exactly one NEW proposal exists - never silently applied.
    reloaded_question = await db_session.get(BusinessContextProposal, question.id)
    assert reloaded_question is not None
    assert reloaded_question.status == BusinessContextProposalStatus.CANCELLED

    answer_proposal = await _only_pending(db_session)
    assert answer_proposal.raw_instruction == "да"
    assert answer_proposal.origin_context == question.origin_context

    # Canonical Product Truth is NOT changed yet - only the explicit confirmation gate writes it.
    product = await get_product_by_slug(db_session, "ai")
    assert product is not None
    assert product.current_features in (None, [])


# ---------------------------------------------------------------------------
# 2: bare "нет" answering the same shape of question follows the same safe proposal flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_net_answers_a_director_question_same_safe_proposal_flow(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    await create_product(db_session, slug="ai", name="NINJA AI")
    question = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.availability",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT",
        question_text="Production Mode уже доступен всем пользователям?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    question.telegram_message_id = 700
    await db_session.commit()

    gateway = _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.availability", "feature_name": "Production Mode",
                "fact_state": "planned",
            }],
        }]),
    ])

    message = _message(text="нет", message_id=950, reply_to_message_id=700)
    await module.handle_plain_text(message)

    assert len(gateway.received_requests) == 1  # parsed, never rejected

    reloaded_question = await db_session.get(BusinessContextProposal, question.id)
    assert reloaded_question is not None
    assert reloaded_question.status == BusinessContextProposalStatus.CANCELLED

    answer_proposal = await _only_pending(db_session)
    assert answer_proposal.raw_instruction == "нет"

    product = await get_product_by_slug(db_session, "ai")
    assert product is not None
    assert product.planned_features in (None, [])  # not yet confirmed


# ---------------------------------------------------------------------------
# 3: "ещё не решили" -> production_mode.billing proposed UNDECIDED, canonical fact key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eshche_ne_reshili_proposes_undecided_with_canonical_fact_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    await create_product(db_session, slug="ai", name="NINJA AI")
    question = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-2", opportunity_source_type="PRODUCT",
        question_text="Как будет считаться стоимость Production Mode?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    question.telegram_message_id = 701
    await db_session.commit()

    _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "Production Mode.Billing", "feature_name": "Production Mode billing",
                "fact_state": "undecided",
            }],
        }]),
    ])

    message = _message(text="ещё не решили", message_id=960, reply_to_message_id=701)
    await module.handle_plain_text(message)

    answer_proposal = await _only_pending(db_session)
    change_set = answer_proposal.proposed_change_set
    version_op = next(op for op in change_set if op["entity_type"] == "product_context_version")
    assert version_op["structured_context"]["undecided_facts_add"] == ["production_mode.billing"]

    confirmed = await confirm_proposal(db_session, answer_proposal.id, decided_by=_FOUNDER)
    assert confirmed is not None

    product = await get_product_by_slug(db_session, "ai")
    assert product is not None
    assert product.undecided_facts == ["production_mode.billing"]


# ---------------------------------------------------------------------------
# 4: two pending Director questions + bare "да" NOT sent as reply -> clarification, no guess
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_pending_questions_ambiguous_da_no_reply_asks_for_clarification(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    gateway = _wire_gateway(monkeypatch, [])  # no parse call should happen at all - still ambiguous

    await create_product(db_session, slug="ai", name="NINJA AI")
    q1 = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.availability",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT",
        question_text="Production Mode уже доступен всем?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    q2 = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-2", opportunity_source_type="PRODUCT",
        question_text="Как считается стоимость Production Mode?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )

    message = _message(text="да", message_id=970)
    await module.handle_plain_text(message)

    assert len(gateway.received_requests) == 0  # never guessed which question this answers
    message.answer.assert_awaited_once()
    reply_text = message.answer.await_args.args[0]
    assert "Production Mode уже доступен всем?" in reply_text
    assert "Как считается стоимость Production Mode?" in reply_text

    reloaded_q1 = await db_session.get(BusinessContextProposal, q1.id)
    reloaded_q2 = await db_session.get(BusinessContextProposal, q2.id)
    assert reloaded_q1.status == BusinessContextProposalStatus.PENDING
    assert reloaded_q2.status == BusinessContextProposalStatus.PENDING


# ---------------------------------------------------------------------------
# 5: two pending Director questions + "да" as a Telegram reply to ONE exact question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_to_one_of_two_pending_questions_correlates_only_that_one(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    await create_product(db_session, slug="ai", name="NINJA AI")
    q1 = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.availability",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT",
        question_text="Production Mode уже доступен всем?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    q1.telegram_message_id = 710
    q2 = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-2", opportunity_source_type="PRODUCT",
        question_text="Как считается стоимость Production Mode?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    q2.telegram_message_id = 711
    await db_session.commit()

    gateway = _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.availability", "feature_name": "Production Mode",
                "fact_state": "confirmed",
            }],
        }]),
    ])

    message = _message(text="да", message_id=980, reply_to_message_id=710)
    await module.handle_plain_text(message)

    assert len(gateway.received_requests) == 1
    request = gateway.received_requests[0]
    combined_prompt_text = " ".join(
        part.text for message_ in request.messages for part in message_.content if part.text
    )
    assert "Production Mode уже доступен всем?" in combined_prompt_text
    assert "Как считается стоимость Production Mode?" not in combined_prompt_text

    reloaded_q1 = await db_session.get(BusinessContextProposal, q1.id)
    reloaded_q2 = await db_session.get(BusinessContextProposal, q2.id)
    assert reloaded_q1.status == BusinessContextProposalStatus.CANCELLED  # answered, closed
    assert reloaded_q2.status == BusinessContextProposalStatus.PENDING  # untouched

    # Exactly one new answer proposal exists, correlated to q1's own origin_context only.
    stmt = select(BusinessContextProposal).where(BusinessContextProposal.status == BusinessContextProposalStatus.PENDING)
    pending = list((await db_session.execute(stmt)).scalars().all())
    assert len(pending) == 2  # q2 (still open) + the new answer proposal for q1
    answer_proposal = next(p for p in pending if p.id != q2.id)
    assert answer_proposal.origin_context == q1.origin_context


# ---------------------------------------------------------------------------
# 6: only the LATER explicit "подтверждаю" (confirming the PROPOSAL, not the question) writes
# canonical Product Truth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_after_answer_proposal_writes_canonical_product_truth(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    await create_product(db_session, slug="ai", name="NINJA AI")
    question = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.availability",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT",
        question_text="Production Mode уже доступен всем пользователям?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    question.telegram_message_id = 700
    await db_session.commit()

    _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.availability", "feature_name": "Production Mode",
                "fact_state": "confirmed",
            }],
        }]),
    ])

    answer_message = _message(text="да", message_id=950, reply_to_message_id=700)
    await module.handle_plain_text(answer_message)

    # Not yet confirmed - canonical Product Truth stays untouched.
    product = await get_product_by_slug(db_session, "ai")
    assert product is not None
    assert product.current_features in (None, [])

    answer_proposal = await _only_pending(db_session)
    proposal_message_id = answer_proposal.telegram_message_id
    assert proposal_message_id == 951  # answer_message.message_id + 1, the sent preview

    confirm_message = _message(text="подтверждаю", message_id=960, reply_to_message_id=proposal_message_id)
    await module.handle_plain_text(confirm_message)

    reloaded_proposal = await db_session.get(BusinessContextProposal, answer_proposal.id)
    assert reloaded_proposal is not None
    assert reloaded_proposal.status == BusinessContextProposalStatus.CONFIRMED

    await db_session.refresh(product)
    assert product.current_features == ["Production Mode"]
