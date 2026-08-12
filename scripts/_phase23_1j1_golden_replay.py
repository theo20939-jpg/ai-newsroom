"""Phase 23.1J.1 - golden real-data replay of Copywriting V8.1 (docs/phase23_1j1_v81_review.md).
Calls the real V8.1 CopywritingCapability directly against 5 real, already-triaged NewsEvent rows,
using their already-persisted NEWS_ANALYSIS research/intelligence output as input - mirrors
scripts/_phase23_1j_golden_replay.py's own established pattern (itself mirroring scripts/
phase19_overnight_abc_harness.py's "manual CapabilityContext construction, direct capability.
execute() call" technique), used here because each of these 5 events already has a real
CONTENT_GENERATION EditorialTask from an earlier phase, and services/workflow_service.py::
create_task() unconditionally refuses a second task for the same (event, workflow_type) pair
regardless of status.

NO Telegram sends, NO ContentDraft persistence, NO workflow/task creation at all - this script
calls CopywritingCapability.execute() in complete isolation, reads the structured_output directly,
and records cost against each event's EXISTING real NEWS_ANALYSIS task_id (a disclosed, deliberate
choice for this bounded, one-off evaluation script - not a production cost-attribution pattern).

settings.copywriting_prompt_version is set to "8.1" in-process only, for the duration of this
script's own process - never touches the real .env, never becomes the permanent default.
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select

from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from database.models.editorial_task import TaskPriority
from services.cost_recording import record_ai_execution
from services.pricing_catalog import ModelRegistryPricingCatalog
from integrations.llm_gateway.models.catalog import build_model_registry

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_COPYWRITING_NAME = "copywriting"

_TARGET_EVENTS = {
    "armenia_firebird_nvidia": "36891f69-a5f0-47f8-a336-ddb917f9bdd1",
    "google_pay_ai": "16cc52d8-85f7-42b5-85a3-12c24db9f284",
    "ghost_particles": "3e6058d3-104b-4394-a238-af6701791419",
    "ai_virus_bacteria": "ef465ca2-957a-4d51-bdb0-7e1284330fbb",
    "stack_overflow": "8df7ac00-ec49-4ffc-8f66-88d326b78a60",
}


async def main() -> None:
    setup_logging()
    settings.copywriting_prompt_version = "8.1"
    print(f"copywriting_prompt_version = {settings.copywriting_prompt_version}")

    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    _def, copywriting_capability = ai_layer.capability_registry.resolve(_COPYWRITING_NAME)

    async with async_session_factory() as session:
        baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()

    results: dict[str, object] = {}
    async with async_session_factory() as session:
        for label, event_id in _TARGET_EVENTS.items():
            print(f"=== {label} ({event_id}) ===")
            event = await session.get(NewsEvent, event_id)
            assert event is not None, f"event {event_id} not found"

            na_task = (
                await session.execute(
                    select(EditorialTask).where(
                        EditorialTask.event_id == event_id,
                        EditorialTask.workflow["workflow_name"].as_string() == "NEWS_ANALYSIS",
                    )
                )
            ).scalars().first()
            assert na_task is not None, f"no NEWS_ANALYSIS task for event {event_id}"
            step_results = {
                s["step_name"]: s["result"]
                for s in (na_task.workflow or {}).get("step_results", [])
                if s.get("status") == "SUCCESS" and s.get("result") is not None
            }

            snapshot = NewsEventSnapshot(
                id=event.id, title=event.title, summary=event.summary, content=event.content,
                url=event.url, category=event.category.value, published_at=event.published_at,
            )
            business = BusinessContext(
                news_event=snapshot,
                workflow_state=WorkflowExecutionStateSnapshot(
                    workflow_name="content_generation", workflow_version=1,
                    completed_steps=list(step_results.keys()), step_results=step_results,
                ),
                language="ru",
            )
            runtime = RuntimeContext(
                task_id=na_task.id, event_id=event.id, capability_name=_COPYWRITING_NAME,
                priority=TaskPriority.B, attempt=1, iteration_count=0,
            )
            context = CapabilityContext(business=business, runtime=runtime, execution=ExecutionContext())

            result = await copywriting_capability.execute(context)
            print(f"status={result.status}")

            async with session.begin_nested():
                for call in result.calls:
                    await record_ai_execution(
                        session, task_id=na_task.id, event_id=event.id, workflow_name="content_generation_v81_replay",
                        capability_name=_COPYWRITING_NAME, call=call, pricing_catalog=pricing_catalog,
                    )
            await session.commit()

            results[label] = {
                "event_id": event_id, "news_title": event.title, "status": result.status,
                "copywriting_output": result.structured_output,
            }

    async with async_session_factory() as session:
        final_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
    cost_delta = final_cost - baseline_cost
    print(f"=== COST: baseline={baseline_cost} final={final_cost} delta={cost_delta} ===")

    with open("scripts/_phase23_1j1_golden_replay_results.json", "w", encoding="utf-8") as f:
        json.dump({"cost_delta_usd": str(cost_delta), "results": results}, f, indent=2, ensure_ascii=False, default=str)
    print("=== WROTE scripts/_phase23_1j1_golden_replay_results.json ===")


if __name__ == "__main__":
    asyncio.run(main())
