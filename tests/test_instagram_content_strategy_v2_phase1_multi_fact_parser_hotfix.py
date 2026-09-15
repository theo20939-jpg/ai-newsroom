"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1 HOTFIX: live production diagnosis proved
`prompts/business_context_parser/v2.yaml` (and v1 before it) violated OpenAI's strict
`response_format="json_schema"` contract - every key in an object's `properties` must also
appear in that object's `required` array, with "optional" expressed via a nullable type union,
never via omission from `required`. Every real provider call was rejected with a 400
`invalid_json_schema` error before any output was ever generated. `v3.yaml` fixes the schema
shape (verified against the real production OpenAI endpoint via one authorized bounded
diagnostic call, not merely unit-tested against a fake). `PARSER_PROMPT_VERSION` is now "3".

This file proves, with the EXACT real Founder message that triggered the live failure, that the
already-existing multi-product/multi-fact extraction architecture (no new parser, no new schema
concept - the same `products_mentioned` array the schema always had) produces two independent,
safe, unconfirmed proposals - using the real extraction shape a live v3 diagnostic call actually
returned, not an invented one."""
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
from services.business_context_command_parser import (
    PARSER_PROMPT_NAME,
    PARSER_PROMPT_VERSION,
    build_change_set,
)
from services.product_context_service import create_product, get_product_by_slug
from tests.fakes.fake_gateway import FakeLLMGateway

_CHAT_ID = -1004297182444
_FOUNDER = 5507703201
_LIVE_FOUNDER_MESSAGE = (
    "Релиз Ninja Ai в телеграмм запланирован до конца сентября. "
    "До конца ноября мы запускаем вэб магазин ninja store"
)

# The exact shape a real, authorized, bounded v3-schema diagnostic call against the live
# production OpenAI endpoint returned for this exact message (captured during live root-cause
# verification, not invented) - reused here so the FakeLLMGateway-driven test proves the SAME
# real-world extraction shape is handled correctly end-to-end, never a shape convenient for the
# test to pass.
_LIVE_EXTRACTION_OUTPUT = {
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

    prompt_repository = FakePromptRepository()
    prompt_repository.register(RenderedPrompt(
        name=PARSER_PROMPT_NAME, version=PARSER_PROMPT_VERSION, system="parse", rules=[],
        output_schema={"type": "object", "properties": {}, "required": []},
    ))
    monkeypatch.setattr(module, "_ai_layer", MagicMock(gateway=gateway))
    monkeypatch.setattr(module, "_prompt_repository", prompt_repository)
    return gateway


def _message(*, text: str, message_id: int = 900, user_id: int = _FOUNDER) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.chat.id = _CHAT_ID
    message.message_thread_id = None
    message.message_id = message_id
    message.from_user.id = user_id
    message.reply_to_message = None
    sent = MagicMock()
    sent.message_id = message_id + 1
    message.answer = AsyncMock(return_value=sent)
    return message


@pytest.mark.asyncio
async def test_live_founder_message_produces_two_safe_unconfirmed_proposals(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [_LIVE_EXTRACTION_OUTPUT])

    await create_product(db_session, slug="ninja-ai", name="NINJA AI")
    await create_product(db_session, slug="ninja-store", name="NINJA Store")

    message = _message(text=_LIVE_FOUNDER_MESSAGE)
    await module.handle_plain_text(message)

    # Exactly one proposal was created (one atomic change_set covering both products) - never
    # auto-confirmed.
    stmt = select(BusinessContextProposal).where(
        BusinessContextProposal.status == BusinessContextProposalStatus.PENDING
    )
    pending = list((await db_session.execute(stmt)).scalars().all())
    assert len(pending) == 1
    proposal = pending[0]
    assert proposal.raw_instruction == _LIVE_FOUNDER_MESSAGE  # raw wording preserved verbatim

    change_set = proposal.proposed_change_set
    version_ops = [op for op in change_set if op["entity_type"] == "product_context_version"]
    assert {op["product_slug"] for op in version_ops} == {"ninja-ai", "ninja-store"}

    ai_op = next(op for op in version_ops if op["product_slug"] == "ninja-ai")
    store_op = next(op for op in version_ops if op["product_slug"] == "ninja-store")
    assert ai_op["structured_context"]["planned_features_add"] == ["Релиз в Telegram"]
    assert store_op["structured_context"]["planned_features_add"] == ["Запуск веб-магазина"]
    # Never a "confirmed" (live-now) feature state - both are PLANNED, matching the message's own
    # future-tense "запланирован"/"запускаем ... до конца ноября" wording.
    assert "current_features_add" not in ai_op["structured_context"]
    assert "current_features_add" not in store_op["structured_context"]

    # Canonical Product Truth is NOT mutated before confirmation.
    ai_product = await get_product_by_slug(db_session, "ninja-ai")
    store_product = await get_product_by_slug(db_session, "ninja-store")
    assert ai_product is not None and ai_product.planned_features in (None, [])
    assert store_product is not None and store_product.planned_features in (None, [])


@pytest.mark.asyncio
async def test_live_founder_message_no_invented_precise_dates(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither product_context_version op contains a fabricated ISO date - "до конца сентября"/
    "до конца ноября" have no lossless representation anywhere in the current schema/change-set
    contract other than free text, so a correct extraction never invents one."""
    _enable_settings(monkeypatch)
    _wire_session(monkeypatch, db_session)
    _wire_gateway(monkeypatch, [_LIVE_EXTRACTION_OUTPUT])

    await create_product(db_session, slug="ninja-ai", name="NINJA AI")
    await create_product(db_session, slug="ninja-store", name="NINJA Store")

    await module.handle_plain_text(_message(text=_LIVE_FOUNDER_MESSAGE))

    stmt = select(BusinessContextProposal).where(
        BusinessContextProposal.status == BusinessContextProposalStatus.PENDING
    )
    proposal = (await db_session.execute(stmt)).scalars().one()
    import json
    serialized = json.dumps(proposal.proposed_change_set)
    for fabricated in ("2026-09-30", "2026-09-01", "2026-11-30", "2026-11-01"):
        assert fabricated not in serialized


def test_build_change_set_handles_null_milestone_fields_with_correct_defaults() -> None:
    """The v3 schema now ALWAYS includes visibility/publicity_allowed/asset_preparation_allowed/
    priority (nullable, never omitted) - proves build_change_set() applies its documented default
    when the LLM explicitly returns null for one of them, not only when the key was absent (a real
    bug the v3 rollout would otherwise have silently (re)introduced - `dict.get(key, default)`
    only applies `default` on a MISSING key, never on a present key holding None)."""
    from services.business_context_command_parser import BusinessContextExtraction

    extraction = BusinessContextExtraction(
        milestones=[{
            "product_slug": "ninja-ai", "title": "Launch", "milestone_at": None,
            "visibility": None, "publicity_allowed": None, "asset_preparation_allowed": None,
        }],
        directives=[{"instruction": "Do the thing", "valid_until": None, "priority": None, "scope": None, "products": None}],
    )
    change_set = build_change_set(extraction, raw_text="x")
    milestone_op = next(op for op in change_set if op["entity_type"] == "campaign_milestone")
    assert milestone_op["visibility"] == "internal_only"
    assert milestone_op["publicity_allowed"] is False
    assert milestone_op["asset_preparation_allowed"] is False

    directive_op = next(op for op in change_set if op["entity_type"] == "strategic_directive")
    assert directive_op["priority"] == 100


def test_build_change_set_preserves_a_real_zero_priority_directive() -> None:
    """The `is not None` default-application fix must never clobber a real, meaningful priority=0
    (the highest-priority value) - a naive `value or default` fallback would have."""
    from services.business_context_command_parser import BusinessContextExtraction

    extraction = BusinessContextExtraction(
        directives=[{"instruction": "Urgent", "valid_until": None, "priority": 0, "scope": None, "products": None}],
    )
    change_set = build_change_set(extraction, raw_text="x")
    directive_op = next(op for op in change_set if op["entity_type"] == "strategic_directive")
    assert directive_op["priority"] == 0
