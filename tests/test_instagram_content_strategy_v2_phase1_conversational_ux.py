"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1 UX CORRECTION: the Founder-facing Director conversation
must read like an informed employee, never a database admin panel - internal object/field names
(product, product_context_version, structured_context, slug, campaign_milestone, visibility,
publicity_allowed, ...) must never appear in the default (plain-text/Director) preview or
confirmation text. Slash commands keep the existing technical view unchanged (a separate,
unaffected code path - `render_proposal_preview()` itself is untouched, still used there and as
the debug view).

Also covers the semantic fix the same live canary exposed: a plain launch-date statement must
never auto-fabricate a LaunchCampaign/campaign_milestone - `services/business_context_command_
parser.py::build_change_set()` only ever produces those entity types when the extraction itself
contains real campaign_updates/milestones entries, so this is tested by construction (an
extraction with empty campaign_updates/milestones - the v4 prompt's own now-tightened default -
produces a change_set with zero campaign/campaign_milestone ops), not by re-testing prompt
wording, which the real live diagnostic call already validated end-to-end in the hotfix commit."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bot.handlers.business_context as module
from bot.business_context_conversational_presenter import (
    render_conversational_confirmation,
    render_conversational_proposal_preview,
)
from bot.business_context_formatting import render_proposal_preview
from core.config import settings
from database.models.business_context_proposal import BusinessContextProposal, BusinessContextProposalStatus
from integrations.llm_gateway.protocol import GenerateResponse
from schemas.capability import CapabilityUsage
from services.business_context_command_parser import BusinessContextExtraction, build_change_set
from services.business_context_proposal_service import confirm_proposal, create_proposal
from services.product_context_service import create_product, get_product_by_slug
from tests.fakes.fake_gateway import FakeLLMGateway

_CHAT_ID = -1004297182444
_FOUNDER = 5507703201

_JARGON_WORDS = (
    "product_context_version", "structured_context", "campaign_milestone",
    "publicity_allowed", "asset_preparation_allowed", "entity_type", "slug:",
)

_LIVE_FOUNDER_MESSAGE = (
    "Релиз Ninja Ai в телеграмм запланирован до конца сентября. "
    "До конца ноября мы запускаем вэб магазин ninja store"
)

# The v4 prompt's own now-tightened default: a plain launch-date statement produces
# feature_updates only - campaign_updates/milestones stay empty (verified live against the real
# production OpenAI endpoint in the hotfix commit; this fixture matches that real shape).
_LIVE_EXTRACTION_OUTPUT_V4 = {
    "products_mentioned": [
        {
            "slug": "ninja-ai", "name": "NINJA AI", "status": "live",
            "current_stage": None, "description": None,
            "feature_updates": [{
                "fact_key": "telegram_release.launch", "feature_name": "Релиз в Telegram",
                "fact_state": "planned", "note": "Запланирован до конца сентября.",
            }],
        },
        {
            "slug": "ninja-store", "name": "NINJA Store", "status": "pre_launch",
            "current_stage": None, "description": None,
            "feature_updates": [{
                "fact_key": "web_store.launch", "feature_name": "Запуск веб-магазина",
                "fact_state": "planned", "note": "До конца ноября.",
            }],
        },
    ],
    "campaign_updates": [], "milestones": [], "directives": [], "claims": [],
    "clarification_needed": [],
}


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


def _assert_no_jargon(text: str) -> None:
    lowered = text.lower()
    for word in _JARGON_WORDS:
        assert word not in lowered, f"found jargon {word!r} in Founder-facing text: {text!r}"


# ---------------------------------------------------------------------------
# 1: exact live Founder message -> natural preview, no jargon, no fabricated campaign/milestone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_message_produces_natural_preview_no_jargon_no_fabricated_campaign(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [_LIVE_EXTRACTION_OUTPUT_V4])

    await create_product(db_session, slug="ninja-ai", name="NINJA AI")
    await create_product(db_session, slug="ninja-store", name="NINJA Store")

    message = _message(text=_LIVE_FOUNDER_MESSAGE)
    await module.handle_plain_text(message)

    message.answer.assert_awaited_once()
    preview_text = message.answer.await_args.args[0]
    _assert_no_jargon(preview_text)
    assert "NINJA AI" in preview_text
    assert "NINJA Store" in preview_text
    assert "сентября" in preview_text
    assert "ноября" in preview_text
    assert "Всё верно?" in preview_text
    assert "кампани" not in preview_text.lower()  # no campaign mentioned - never discussed

    stmt = select(BusinessContextProposal).where(BusinessContextProposalStatus.PENDING == BusinessContextProposal.status)
    proposal = (await db_session.execute(stmt)).scalars().one()
    assert proposal.origin == "conversational"

    # NO_FABRICATED_CAMPAIGNS: build_change_set never invents a campaign/milestone op when the
    # extraction's own campaign_updates/milestones are empty.
    entity_types = {op["entity_type"] for op in proposal.proposed_change_set}
    assert "campaign" not in entity_types
    assert "campaign_milestone" not in entity_types

    # No canonical mutation before confirmation.
    ai_product = await get_product_by_slug(db_session, "ninja-ai")
    assert ai_product is not None and ai_product.planned_features in (None, [])


# ---------------------------------------------------------------------------
# 2: single simple fact -> conversational, no schema dump
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_fact_message_produces_conversational_preview(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [{
        "products_mentioned": [{
            "slug": "ninja-ai", "name": "NINJA AI", "status": None, "current_stage": None, "description": None,
            "feature_updates": [{
                "fact_key": "production_mode.status", "feature_name": "Production Mode",
                "fact_state": "planned", "note": None,
            }],
        }],
        "campaign_updates": [], "milestones": [], "directives": [], "claims": [], "clarification_needed": [],
    }])
    await create_product(db_session, slug="ninja-ai", name="NINJA AI")

    message = _message(text="Production Mode пока в разработке.")
    await module.handle_plain_text(message)

    preview_text = message.answer.await_args.args[0]
    _assert_no_jargon(preview_text)
    assert "Production Mode" in preview_text


# ---------------------------------------------------------------------------
# 3: UNDECIDED phrasing
# ---------------------------------------------------------------------------


def test_undecided_fact_renders_as_not_yet_decided() -> None:
    proposal = MagicMock(spec=BusinessContextProposal)
    proposal.proposed_change_set = [
        {"entity_type": "product", "slug": "ninja-ai", "name": "NINJA AI", "status": None},
        {
            "entity_type": "product_context_version", "product_slug": "ninja-ai",
            "raw_instruction": "Экономику пока не решили.",
            "structured_context": {
                "undecided_facts_add": ["production_mode.billing"],
                "undecided_display_names": {"production_mode.billing": "Экономика Production Mode"},
            },
        },
    ]
    text = render_conversational_proposal_preview(proposal)
    _assert_no_jargon(text)
    assert "не решили" in text.lower() or "не определ" in text.lower()
    assert "Экономика Production Mode" in text


# ---------------------------------------------------------------------------
# 4: correction changes only one of two facts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correction_updates_only_the_mentioned_fact(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)

    await create_product(db_session, slug="ninja-ai", name="NINJA AI")
    await create_product(db_session, slug="ninja-store", name="NINJA Store")

    original = await create_proposal(
        db_session, command_type=module.BusinessContextCommandType.CONTEXT,
        raw_instruction=_LIVE_FOUNDER_MESSAGE,
        proposed_change_set=build_change_set(
            BusinessContextExtraction(products_mentioned=_LIVE_EXTRACTION_OUTPUT_V4["products_mentioned"]),
            raw_text=_LIVE_FOUNDER_MESSAGE,
        ),
        created_by=_FOUNDER, telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    original.origin = "conversational"
    original.telegram_message_id = 700
    await db_session.commit()

    _wire_gateway(monkeypatch, [{
        "products_mentioned": [
            {
                "slug": "ninja-ai", "name": "NINJA AI", "status": None, "current_stage": None, "description": None,
                "feature_updates": [{
                    "fact_key": "telegram_release.launch", "feature_name": "Релиз в Telegram",
                    "fact_state": "planned", "note": "До конца сентября.",
                }],
            },
            {
                "slug": "ninja-store", "name": "NINJA Store", "status": None, "current_stage": None, "description": None,
                "feature_updates": [{
                    "fact_key": "web_store.launch", "feature_name": "Запуск веб-магазина",
                    "fact_state": "planned", "note": "Ориентировочно в середине ноября.",
                }],
            },
        ],
        "campaign_updates": [], "milestones": [], "directives": [], "claims": [], "clarification_needed": [],
    }])

    correction_message = _message(
        text="Store не до конца ноября, а ориентировочно в середине ноября.",
        message_id=950, reply_to_message_id=700,
    )
    await module.handle_plain_text(correction_message)

    reloaded_original = await db_session.get(BusinessContextProposal, original.id)
    assert reloaded_original is not None
    assert reloaded_original.status == BusinessContextProposalStatus.CANCELLED

    stmt = select(BusinessContextProposal).where(BusinessContextProposal.status == BusinessContextProposalStatus.PENDING)
    new_proposal = (await db_session.execute(stmt)).scalars().one()
    preview_text = correction_message.answer.await_args.args[0]
    assert "середине ноября" in preview_text
    assert "NINJA AI" in preview_text  # still mentioned, unchanged
    _assert_no_jargon(preview_text)
    assert new_proposal.origin == "conversational"


# ---------------------------------------------------------------------------
# 5: debug view (render_proposal_preview) still exists and is still the technical dump
# ---------------------------------------------------------------------------


def test_technical_debug_preview_still_available_and_unchanged() -> None:
    proposal = MagicMock(spec=BusinessContextProposal)
    proposal.proposed_change_set = [
        {"entity_type": "product", "slug": "ninja-ai", "name": "NINJA AI", "status": None},
    ]
    text = render_proposal_preview(proposal)
    assert "product" in text  # the technical view IS the entity_type dump, by design


# ---------------------------------------------------------------------------
# 6: confirmation text is short, natural, no JSON dump
# ---------------------------------------------------------------------------


def test_conversational_confirmation_is_short_and_natural() -> None:
    proposal = MagicMock(spec=BusinessContextProposal)
    proposal.proposed_change_set = [
        {"entity_type": "product", "slug": "ninja-ai", "name": "NINJA AI", "status": None},
        {
            "entity_type": "product_context_version", "product_slug": "ninja-ai",
            "structured_context": {"planned_features_add": ["Релиз в Telegram"]},
        },
    ]
    text = render_conversational_confirmation(proposal)
    _assert_no_jargon(text)
    assert "Готово" in text
    assert "{" not in text and "}" not in text


# ---------------------------------------------------------------------------
# 7: slash commands remain unchanged (technical preview, origin stays None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slash_command_proposal_keeps_technical_preview(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    proposal = await create_proposal(
        db_session, command_type=module.BusinessContextCommandType.PRODUCT, raw_instruction="x",
        proposed_change_set=[{"entity_type": "product", "slug": "ninja-ai", "name": "NINJA AI", "status": None}],
        created_by=_FOUNDER, telegram_chat_id=_CHAT_ID, telegram_topic_id=None,
    )
    assert proposal.origin is None  # never tagged "conversational" by /product's own path
    assert module._preview_for(proposal) == render_proposal_preview(proposal)


# ---------------------------------------------------------------------------
# 8: confirmation safety unchanged - explicit confirm still required, still writes canonically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_gate_still_required_before_canonical_write(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [_LIVE_EXTRACTION_OUTPUT_V4])

    await create_product(db_session, slug="ninja-ai", name="NINJA AI")
    await create_product(db_session, slug="ninja-store", name="NINJA Store")

    await module.handle_plain_text(_message(text=_LIVE_FOUNDER_MESSAGE, message_id=960))

    stmt = select(BusinessContextProposal).where(BusinessContextProposal.status == BusinessContextProposalStatus.PENDING)
    proposal = (await db_session.execute(stmt)).scalars().one()

    ai_product = await get_product_by_slug(db_session, "ninja-ai")
    assert ai_product is not None and ai_product.planned_features in (None, [])

    confirmed = await confirm_proposal(db_session, proposal.id, decided_by=_FOUNDER)
    assert confirmed is not None and confirmed.status == BusinessContextProposalStatus.CONFIRMED

    await db_session.refresh(ai_product)
    assert ai_product.planned_features == ["Релиз в Telegram"]
