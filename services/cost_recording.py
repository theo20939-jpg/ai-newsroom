"""API cost optimization (docs/api_cost_optimization_report.md §8): writes one durable
`AIExecution` row per successful `CapabilityCall` - the "auditable per-capability cost
accounting" this task requires. Reuses `services.cost_tracker.compute_call_cost()` (the same
formula the Redis daily ledger uses) so both records always agree.

Deliberately separate from `services.cost_tracker.CostTracker` (which stays Redis-only, per its
own long-standing, unchanged contract) - this module owns the Postgres write, that module owns
the fast pre-flight-check-backing ledger. `capabilities/executor.py` calls both after a
successful capability call.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.capability_mapping import resolve_ai_capability
from database.models.ai_execution import AIExecution
from schemas.capability import CapabilityCall
from services.cost_tracker import compute_call_cost
from services.pricing_catalog import PricingCatalog


async def record_ai_execution(
    session: AsyncSession,
    *,
    task_id: UUID,
    event_id: UUID | None,
    workflow_name: str,
    capability_name: str,
    call: CapabilityCall,
    pricing_catalog: PricingCatalog,
) -> None:
    """Writes one `AIExecution` row for a SUCCESS-status `CapabilityCall`. A no-op for any other
    status (Phase 6's own `DefaultAIExecutionMapper` precedent: only successful-call
    compatibility is validated/recorded - a failed call's partial usage, if any, is not billed
    the same way and is out of this delivery's scope, matching that established boundary).
    Never raises - a cost-recording failure must never fail the workflow step it's recording."""
    if call.status != "SUCCESS":
        return
    try:
        ai_capability = resolve_ai_capability(capability_name)
        cost = compute_call_cost(call, pricing_catalog)
        session.add(
            AIExecution(
                task_id=task_id,
                event_id=event_id,
                workflow_name=workflow_name,
                capability=ai_capability,
                model=call.model_used or "unknown",
                prompt_version=call.prompt_version,
                retry_number=call.sequence,
                input_tokens=call.usage.input_tokens or 0,
                cached_input_tokens=call.usage.cached_input_tokens,
                output_tokens=call.usage.output_tokens or 0,
                reasoning_tokens=call.usage.reasoning_tokens,
                cost=cost,
                usage_source="provider_response",
            )
        )
    except Exception:  # noqa: BLE001 - cost-recording must never block or fail a real workflow step
        return
