"""INSTAGRAM-GROWTH-3, item 17: AI cost accounting tests."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.capability import CapabilityCall, CapabilityUsage
from services.instagram_ai_cost import record_ai_call, total_recorded_cost


def _call(*, status: str = "SUCCESS", model_used: str | None = "gpt-5.6-sol", input_tokens: int = 100, output_tokens: int = 50) -> CapabilityCall:
    now = datetime.now(timezone.utc)
    return CapabilityCall(
        call_id=uuid4(), sequence=0, gateway_method="generate", status=status, model_used=model_used,
        provider="openai", prompt_name="instagram_semantic_match", prompt_version="1",
        usage=CapabilityUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        started_at=now, finished_at=now, duration_seconds=0.5,
    )


@pytest.mark.asyncio
async def test_successful_call_records_real_cost(db_session: AsyncSession) -> None:
    record = await record_ai_call(db_session, capability_name="instagram_semantic_match", call=_call())
    assert record.cost_usd is not None
    assert record.cost_usd > 0
    assert record.input_tokens == 100
    assert record.output_tokens == 50


@pytest.mark.asyncio
async def test_failed_call_never_fabricates_a_cost(db_session: AsyncSession) -> None:
    record = await record_ai_call(
        db_session, capability_name="instagram_semantic_match",
        call=_call(status="FAILED", model_used=None, input_tokens=0, output_tokens=0),
    )
    assert record.cost_usd is None


@pytest.mark.asyncio
async def test_unknown_model_never_fabricates_a_cost(db_session: AsyncSession) -> None:
    record = await record_ai_call(
        db_session, capability_name="instagram_semantic_match", call=_call(model_used="totally-unknown-model"),
    )
    assert record.cost_usd is None


@pytest.mark.asyncio
async def test_total_recorded_cost_sums_only_priced_calls(db_session: AsyncSession) -> None:
    await record_ai_call(db_session, capability_name="instagram_semantic_match", call=_call())
    await record_ai_call(db_session, capability_name="instagram_semantic_match", call=_call(status="FAILED", model_used=None))
    total = await total_recorded_cost(db_session, capability_name="instagram_semantic_match")
    assert total > 0
