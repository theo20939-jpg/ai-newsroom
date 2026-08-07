"""Phase 19 M3: proves editorial_planning_mode="shadow" actually persists a
ContentDraftEditorialPlan row for review, against a real, migrated database.

Migration b4d92a7f6e13 (adds 'content_draft_editorial_plans') ships unapplied to the real
ai_newsroom DB by explicit Phase 19 policy (docs/phase19_m6... and the migration's own
docstring), so this test cannot assume the table exists in whatever DB `settings.database_url`
happens to point at when the full suite runs. Rather than a static `pytest.mark.skip` (which
would silently stay skipped forever, even once the migration is legitimately applied), it checks
at runtime whether the table is present and skips only when it genuinely is not - passes for real
against a disposable DB that has had `alembic upgrade head` run against it (see
docs/phase19_m3_editorial_plan_comparison_packet.md / the Phase 19 M3 checkpoint notes for the
exact disposable-DB validation procedure), and degrades to a clean skip against the real,
intentionally-unmigrated DB.
"""
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import build_registry
from core.config import settings
from database.models.content_draft_editorial_plan import ContentDraftEditorialPlan
from database.models.editorial_task import TaskPriority
from database.models.news_event import NewsEvent
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from workflows.registry import registry as real_workflow_registry
from workflows.runner import WorkflowRunner

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7, "angle": "Market impact", "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title", "body": "Example draft body text.",
    "what_happened": "Example event happened.",
    "why_it_matters": "Example editorial interpretation of the impact.",
    "what_remains_unknown": None, "quote": None,
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


@pytest.mark.asyncio
async def test_shadow_mode_persists_a_deterministic_scaffold_row(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not await _table_exists(db_session, "content_draft_editorial_plans"):
        pytest.skip(
            "content_draft_editorial_plans table not present on this DB - migration "
            "b4d92a7f6e13 ships unapplied to the real DB by Phase 19 policy; run this test "
            "against a disposable DB that has had 'alembic upgrade head' applied."
        )

    monkeypatch.setattr(settings, "fact_safety_mode", "off")
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")
    monkeypatch.setattr(settings, "editorial_planning_mode", "shadow")

    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_COPYWRITING_OUTPUT),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    command = EditorialTaskCreate(
        event_id=real_news_event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B
    )
    task = await workflow_service.create_task(db_session, command)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"

    rows = (
        await db_session.execute(
            select(ContentDraftEditorialPlan).where(ContentDraftEditorialPlan.event_id == real_news_event.id)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].is_deterministic_scaffold is True
    assert rows[0].plan["central_fact"] == real_news_event.title
    assert rows[0].content_draft_id is None  # shadow never links to a ContentDraft
