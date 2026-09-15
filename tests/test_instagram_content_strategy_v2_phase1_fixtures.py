"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1 GATE - the required conversational fixtures (A-F) from
the Founder's own overnight-run authorization, exercised end-to-end through
bot.handlers.business_context.handle_plain_text: real Postgres (db_session), a FakeLLMGateway
pre-loaded with the exact canned extraction each message should produce (no real LLM/network
call), and a MagicMock aiogram Message (mirrors tests/test_director_refresh_callback.py's own
`db_session_cm`/AI-layer-monkeypatch conventions exactly - the established pattern for testing a
handler that owns `async with async_session_factory() as session:` internally).

A. "В NINJA AI добавляем Production Mode." -> proposed + confirmed -> Production Mode PLANNED.
B. "Пока в разработке, экономику ещё не решили." -> proposed + confirmed -> production_mode.billing
   UNDECIDED, nothing invented (no billing model value fabricated).
C. A pre-existing Director question is answered in natural language -> correlated to the correct
   pending question (origin_context carried through), safely proposed (never silently applied),
   then confirmed.
D. Two pending proposals + ambiguous bare "да" -> no random confirmation, a clarification request.
E. Reply-to one of two pending proposals with "да" -> only that one confirmed.
F. ProductContextVersion provenance (raw_instruction, confirmed_by, supersedes chain) is correct.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bot.handlers.business_context as module
from core.config import settings
from database.models.business_context_proposal import BusinessContextProposal, BusinessContextProposalStatus
from database.models.product import Product
from database.models.product_context_version import ProductContextVersion
from integrations.llm_gateway.protocol import GenerateResponse
from schemas.capability import CapabilityUsage
from services.business_context_proposal_service import create_director_information_need
from services.product_context_service import get_product_by_slug
from tests.fakes.fake_gateway import FakeLLMGateway

_CHAT_ID = -1004297182444
_FOUNDER = 5507703201


class _DbSessionCm:
    """Mirrors tests/test_director_refresh_callback.py::db_session_cm exactly - hands back the
    SAME test db_session every time `async_session_factory()` is called inside the handler, so
    every write in one test stays on one real transaction/session, rolled back at teardown."""

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
# A + B + F: two plain-text statements -> PLANNED feature + UNDECIDED fact, real provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixtures_a_b_f_planned_feature_and_undecided_fact_with_real_provenance(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.status", "feature_name": "Production Mode",
                "fact_state": "planned",
            }],
        }]),
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.billing", "feature_name": "Production Mode billing",
                "fact_state": "undecided",
            }],
        }]),
    ])

    # --- A ---
    raw_a = "В NINJA AI добавляем Production Mode."
    await module.handle_plain_text(_message(text=raw_a, message_id=901))
    proposal_a = await _only_pending(db_session)
    from services.business_context_proposal_service import confirm_proposal
    confirmed_a = await confirm_proposal(db_session, proposal_a.id, decided_by=_FOUNDER)
    assert confirmed_a is not None and confirmed_a.status == BusinessContextProposalStatus.CONFIRMED

    product = await get_product_by_slug(db_session, "ai")
    assert product is not None
    assert product.planned_features == ["Production Mode"]
    assert product.current_features in (None, [])
    assert product.undecided_facts in (None, [])  # B has not happened yet - nothing invented early

    # --- B ---
    raw_b = "Пока в разработке, экономику ещё не решили."
    await module.handle_plain_text(_message(text=raw_b, message_id=911))
    proposal_b = await _only_pending(db_session)
    confirmed_b = await confirm_proposal(db_session, proposal_b.id, decided_by=_FOUNDER)
    assert confirmed_b is not None

    await db_session.refresh(product)
    assert product.planned_features == ["Production Mode"]  # unchanged, not clobbered
    assert product.undecided_facts == ["production_mode.billing"]
    assert product.current_features in (None, [])  # B never promotes anything to CONFIRMED

    # --- F: ProductContextVersion provenance ---
    versions = list((await db_session.execute(
        select(ProductContextVersion).where(ProductContextVersion.product_id == product.id)
        .order_by(ProductContextVersion.version)
    )).scalars().all())
    assert len(versions) == 2
    assert versions[0].raw_instruction == raw_a
    assert versions[1].raw_instruction == raw_b
    assert versions[0].confirmed_by == _FOUNDER
    assert versions[1].confirmed_by == _FOUNDER
    assert versions[1].supersedes_id == versions[0].id


# ---------------------------------------------------------------------------
# C: a Director-initiated question is answered in natural language -> correlated, proposed, confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_c_director_question_answer_is_correlated_and_confirmed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    from services.product_context_service import create_product

    await create_product(db_session, slug="ai", name="NINJA AI")
    question = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-42", opportunity_source_type="PRODUCT",
        question_text="Какая модель оплаты будет у Production Mode?",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    question.telegram_message_id = 700
    await db_session.commit()

    _wire_gateway(monkeypatch, [
        _empty_output(products_mentioned=[{
            "slug": "ai", "name": "NINJA AI",
            "feature_updates": [{
                "fact_key": "production_mode.billing", "feature_name": "Production Mode billing",
                "fact_state": "undecided",
            }],
        }]),
    ])

    # Founder answers naturally - it's the ONLY pending item, so no reply-to is even required.
    answer_text = "Пока в разработке, экономику ещё не решили."
    await module.handle_plain_text(_message(text=answer_text, message_id=920, reply_to_message_id=700))

    # The question itself is now closed (no longer open/PENDING)...
    reloaded_question = await db_session.get(BusinessContextProposal, question.id)
    assert reloaded_question is not None
    assert reloaded_question.status == BusinessContextProposalStatus.CANCELLED

    # ...and exactly one NEW proposal exists, carrying the SAME origin_context through.
    answer_proposal = await _only_pending(db_session)
    assert answer_proposal.origin_context == question.origin_context
    assert answer_proposal.raw_instruction == answer_text

    from services.business_context_proposal_service import confirm_proposal
    confirmed = await confirm_proposal(db_session, answer_proposal.id, decided_by=_FOUNDER)
    assert confirmed is not None

    product = await get_product_by_slug(db_session, "ai")
    assert product is not None
    assert product.undecided_facts == ["production_mode.billing"]


# ---------------------------------------------------------------------------
# D: two pending proposals + ambiguous bare "да" -> no random confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_d_two_pending_questions_ambiguous_da_asks_for_clarification(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [])  # no parse call should happen at all for a bare "да"

    from services.product_context_service import create_product

    await create_product(db_session, slug="ai", name="NINJA AI")
    q1 = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.billing",
        opportunity_id="opp-1", opportunity_source_type="PRODUCT", question_text="Q1",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    q2 = await create_director_information_need(
        db_session, product_slug="ai", missing_fact="production_mode.launch_date",
        opportunity_id="opp-2", opportunity_source_type="PRODUCT", question_text="Q2",
        telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )

    message = _message(text="да", message_id=930)
    await module.handle_plain_text(message)

    message.answer.assert_awaited_once()
    reply_text = message.answer.await_args.args[0]
    assert "Q1" in reply_text and "Q2" in reply_text

    reloaded_q1 = await db_session.get(BusinessContextProposal, q1.id)
    reloaded_q2 = await db_session.get(BusinessContextProposal, q2.id)
    assert reloaded_q1.status == BusinessContextProposalStatus.PENDING
    assert reloaded_q2.status == BusinessContextProposalStatus.PENDING


# ---------------------------------------------------------------------------
# E: reply directly to one of two pending proposals with "да" -> only that one confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_e_reply_to_one_of_two_pending_confirms_only_that_one(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [])

    from services.business_context_proposal_service import create_proposal
    from database.models.business_context_proposal import BusinessContextCommandType

    p1 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="first product",
        proposed_change_set=[{"entity_type": "product", "slug": "prodone", "name": "Prod One", "status": None}],
        created_by=_FOUNDER, telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    p1.telegram_message_id = 800
    p2 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="second product",
        proposed_change_set=[{"entity_type": "product", "slug": "prodtwo", "name": "Prod Two", "status": None}],
        created_by=_FOUNDER, telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    p2.telegram_message_id = 801
    await db_session.commit()

    await module.handle_plain_text(_message(text="да", message_id=940, reply_to_message_id=800))

    reloaded_p1 = await db_session.get(BusinessContextProposal, p1.id)
    reloaded_p2 = await db_session.get(BusinessContextProposal, p2.id)
    assert reloaded_p1.status == BusinessContextProposalStatus.CONFIRMED
    assert reloaded_p2.status == BusinessContextProposalStatus.PENDING

    count = (await db_session.execute(select(Product).where(Product.slug == "prodone"))).scalars().all()
    assert len(count) == 1
    count_two = (await db_session.execute(select(Product).where(Product.slug == "prodtwo"))).scalars().all()
    assert len(count_two) == 0
