"""INSTAGRAM-GROWTH-3, item 17: cost accounting for Instagram's own Gateway usage. Reuses the SAME
cost formula every real Capability's AIExecution row uses (services/cost_tracker.py::
compute_call_cost against a real ModelRegistry-backed PricingCatalog) - never an independently
invented price table. See database/models/instagram_ai_call_record.py's own docstring for why this
writes its own small table rather than a real AIExecution row (that model's task_id is a NOT-NULL
FK to editorial_tasks.id, which no Instagram feature has)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_ai_call_record import InstagramAICallRecord
from integrations.llm_gateway.models.catalog import build_model_registry
from schemas.capability import CapabilityCall
from services.cost_tracker import compute_call_cost
from services.pricing_catalog import ModelRegistryPricingCatalog

_PRICING_CATALOG = ModelRegistryPricingCatalog(build_model_registry())


async def record_ai_call(
    session: AsyncSession, *, capability_name: str, call: CapabilityCall,
) -> InstagramAICallRecord:
    """Never fabricates a cost - if `call.model_used` isn't in the pricing catalog (or is None,
    e.g. a failed call), `cost_usd` stays NULL rather than guessing 0."""
    cost: float | None = None
    if call.status == "SUCCESS" and call.model_used is not None:
        try:
            cost = float(compute_call_cost(call, _PRICING_CATALOG))
        except Exception:
            cost = None

    record = InstagramAICallRecord(
        capability_name=capability_name, model_used=call.model_used, provider=call.provider,
        prompt_name=call.prompt_name, prompt_version=call.prompt_version, status=call.status,
        input_tokens=call.usage.input_tokens, output_tokens=call.usage.output_tokens, cost_usd=cost,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def total_recorded_cost(session: AsyncSession, *, capability_name: str | None = None) -> float:
    """Sums only rows with a real (non-NULL) `cost_usd` - never treats an unpriced call as free."""
    stmt = select(InstagramAICallRecord)
    if capability_name is not None:
        stmt = stmt.where(InstagramAICallRecord.capability_name == capability_name)
    rows = (await session.execute(stmt)).scalars().all()
    return sum(float(r.cost_usd) for r in rows if r.cost_usd is not None)
