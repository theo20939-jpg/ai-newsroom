"""Phase 20 M1: offline (fake-gateway, real-DB) proof that the three overnight-harness bugs found
by the real Phase 19 A/B/C run are actually fixed:

A. Every real capability call now writes a real AIExecution row (previously $0.00 recorded
   regardless of real spend).
B. Variant B and Variant C share one Research/Intelligence/Editorial Plan computation (previously
   each recomputed all three, wasting real calls).
C. Variant B/C now run Quality (with fact_safety applied, matching Variant A's real parity).

Uses FakeLLMGateway (no real provider, no real cost) against the real DB (committed rows,
explicitly cleaned up in a finally block - record_ai_execution() commits for real, so this cannot
rely on SAVEPOINT rollback like tests/conftest.py::db_session does for lighter-weight tests).
"""
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from capabilities.registry import build_registry
from core.config import settings
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from scripts.phase19_overnight_abc_harness import build_shared_bc_context, run_copywriting_stage
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT

_REAL_MODEL = "gpt-5.6-luna"  # must be a real, catalog-known model so compute_call_cost succeeds

_INTELLIGENCE_OUTPUT = {
    "significance": 0.7, "angle": "Market impact", "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_PLAN_OUTPUT = {
    "central_fact": "Example fact.", "what_changed": None, "what_is_new": "Example fact.",
    "why_it_matters": "It matters.", "essential_facts": ["fact one"], "secondary_facts_omittable": [],
    "necessary_background": None, "already_published_summary": None, "must_not_repeat": None,
    "story_classification": "new_story", "headline_emphasis": "Example fact.", "opening_emphasis": "",
    "what_remains_unknown": None, "verified_quote_text": None, "media_role_needed": "none",
    "editorial_risks": [],
}
_COPY_OUTPUT = {
    "title": "Example title", "opening": "Example opening.", "context": "Example context.",
    "why_it_matters": "Example why.", "what_changed": "Example change.", "what_happens_next": None,
    "conclusion": "Example conclusion.", "what_remains_unknown": None, "quote": None,
}
_QUALITY_OUTPUT = {"passed": True, "issues": []}


def _response(structured_output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used=_REAL_MODEL, usage=CapabilityUsage(input_tokens=50, output_tokens=20),
    )


@pytest.mark.asyncio
async def test_m1_shared_context_costs_are_recorded_and_not_duplicated() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    gateway = FakeLLMGateway(generate_responses=[
        _response(CANONICAL_RESEARCH_OUTPUT),  # research (shared)
        _response(_INTELLIGENCE_OUTPUT),        # intelligence (shared)
        _response(_PLAN_OUTPUT),                # editorial_planning (shared)
        _response(_COPY_OUTPUT),                # copywriting - Variant B
        _response(_QUALITY_OUTPUT),             # quality - Variant B
        _response(_COPY_OUTPUT),                # copywriting - Variant C
        _response(_QUALITY_OUTPUT),             # quality - Variant C
    ])
    registry = build_registry(gateway, FilePromptRepository(Path("prompts")), AllowingBudgetGuard(), ToolRegistry())
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    source_id = None
    event_id = None
    try:
        async with factory() as session:
            source = NewsSource(name=f"phase20-m1-test-{uuid4()}", type=SourceType.RSS, active=True)
            session.add(source)
            await session.flush()
            source_id = source.id

            event = NewsEvent(
                source_id=source.id, title="Phase 20 M1 harness fix test event",
                category=EventCategory.TECH, hash=f"phase20-m1-test-{uuid4()}",
            )
            session.add(event)
            await session.commit()
            event_id = event.id

        async with factory() as session:
            baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
            news_event = await session.get(NewsEvent, event_id)
            assert news_event is not None

            shared = await build_shared_bc_context(
                news_event, capability_registry=registry, session=session, pricing_catalog=pricing_catalog,
            )
            variant_b = await run_copywriting_stage(
                news_event, shared, label="B", capability_registry=registry, session=session,
                pricing_catalog=pricing_catalog, include_prior_coverage=False,
            )
            variant_c = await run_copywriting_stage(
                news_event, shared, label="C", capability_registry=registry, session=session,
                pricing_catalog=pricing_catalog, include_prior_coverage=True,
            )

        # --- B: exactly 7 real calls total (not 10) - proves Research/Intelligence/Plan were
        # shared, not recomputed, between B and C (M1 fix B). ---
        assert len(gateway.received_requests) == 7, (
            f"expected exactly 7 capability calls (research, intelligence, plan shared once; "
            f"copywriting+quality once per variant), got {len(gateway.received_requests)} - "
            f"B/C are recomputing shared steps"
        )

        # --- A: real AIExecution rows were written for every one of those 7 calls. ---
        async with factory() as session:
            new_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
            row_count = (await session.execute(
                select(func.count()).select_from(AIExecution).where(AIExecution.event_id == event_id)
            )).scalar_one()
        assert row_count == 7, f"expected 7 AIExecution rows recorded for this event, got {row_count}"
        assert new_cost > baseline_cost, "cost tracking still not recording real spend"

        # --- C: Quality now runs for both B/C (previously skipped entirely). ---
        assert variant_b.quality_output is not None
        assert variant_c.quality_output is not None
        # Phase 20 M1 discovered a real schema-mismatch bug here: services/fact_safety.py::
        # apply_fact_safety() used to read copywriting_output["body"] only (V4's schema shape) -
        # V6's schema (opening/context/why_it_matters/... instead of one "body" field, prompts/
        # copywriting/v6.yaml) has no "body" key at all, so the function structurally no-opped for
        # V6 output regardless of fact_safety_mode. Phase 21 (services/fact_safety.py::
        # _extract_draft_text()) fixed this - Fact Safety now runs normally for V6 too, so the
        # harness's real, correct-parity call (matching Variant A's own path) now produces a real
        # result instead of a silent None.
        assert variant_b.fact_safety_status == "pass"
        assert variant_c.fact_safety_status == "pass"

        # --- Variants B and C used the SAME shared plan/evidence, differing only in prior coverage. ---
        assert variant_b.editorial_plan == variant_c.editorial_plan
        assert variant_b.editorial_plan_context_text == variant_c.editorial_plan_context_text
    finally:
        async with factory() as session:
            if event_id is not None:
                await session.execute(delete(AIExecution).where(AIExecution.event_id == event_id))
                await session.execute(delete(EditorialTask).where(EditorialTask.event_id == event_id))
                await session.execute(delete(NewsEvent).where(NewsEvent.id == event_id))
            if source_id is not None:
                await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
            await session.commit()
        await engine.dispose()
