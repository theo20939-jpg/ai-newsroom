"""Phase 23.1M final polish - golden real-data replay of Copywriting V8.4 (docs/
phase23_1m_final_russian_polish_report.md, Part 17). Same manual CapabilityContext construction
technique as scripts/_phase23_1m_golden_replay.py. Targets the 8 events the phase brief explicitly
requires: the 3 known-problem cases from Phase 23.1K's own live canary (Flock/anti-recognition
patterns, Google Play/Venmo, Intel $15B), Armenia/Firebird, Stack Overflow, and the 3 genuine
delivered posts from this phase's own V8.4 live canary (Long March 7A, Anthropic IPO,
Visa/Mastercard warning) - real, already-persisted events, no synthetic stories.

NO Telegram sends, NO ContentDraft persistence, NO workflow/task creation - calls
CopywritingCapability.execute() in isolation, cost recorded against each event's existing
NEWS_ANALYSIS task_id, workflow_name="content_generation_v84_replay".

settings.copywriting_prompt_version = "8.4" in-process only.
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select

from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from services.cost_recording import record_ai_execution
from services.pricing_catalog import ModelRegistryPricingCatalog

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_COPYWRITING_NAME = "copywriting"

_TARGET_EVENTS = {
    "flock_patterns_23_1k": "2770f7ec-a35f-40b8-86a0-9be6b98a6971",
    "intel_15b_23_1k": "38bc8bf0-c3e3-4dad-9c67-0984150b965f",
    "google_pay_venmo_23_1k": "9121041a-4aa7-422e-a447-d1a9552c9dde",
    "armenia_firebird": "36891f69-a5f0-47f8-a336-ddb917f9bdd1",
    "stack_overflow": "8df7ac00-ec49-4ffc-8f66-88d326b78a60",
    "long_march_7a": "63bb3959-a1e9-4acd-8b33-455155530c24",
    "anthropic_ipo": "73f3fe6c-e82d-414a-b504-2cc0c30d15f5",
    "visa_mastercard_warning": "09ce3c5a-376f-4305-928f-528882b4e02e",
}


async def main() -> None:
    setup_logging()
    settings.copywriting_prompt_version = "8.4"
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
                        session, task_id=na_task.id, event_id=event.id, workflow_name="content_generation_v84_replay",
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

    with open("scripts/_phase23_1m_final_golden_replay_results.json", "w", encoding="utf-8") as f:
        json.dump({"cost_delta_usd": str(cost_delta), "results": results}, f, indent=2, ensure_ascii=False, default=str)
    print("=== WROTE scripts/_phase23_1m_final_golden_replay_results.json ===")


if __name__ == "__main__":
    asyncio.run(main())
