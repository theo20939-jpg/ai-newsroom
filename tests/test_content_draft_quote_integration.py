"""Phase 18.10 M5: integration tests proving ContentDraftService.create_from_result() verifies
and persists a quote end-to-end, and that a fabricated/unverifiable quote is dropped, never
persisted. Real Postgres (db_session, rolled back). Requires the Phase 18.10 M5 migration
(content_draft_quotes table) to be applied - skipped until then, same convention as
tests/test_story_memory_integration.py.
"""
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_quote import ContentDraftQuote
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.content_draft_service import ContentDraftService
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT

pytestmark = pytest.mark.skip(
    reason=(
        "Requires Alembic migration f12a9b9732cc (content_draft_quotes table) to be applied "
        "first - Phase 18.10 M5 ships this migration unapplied by explicit instruction "
        "(design-only). Remove this skip once applied."
    )
)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7, "angle": "Market impact", "audience_relevance": "General",
    "recommendation": "Publish",
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}

_SOURCE_CONTENT = 'The CEO said, "We will double our engineering team next year," at the event.'


def _copywriting_output_with_quote() -> dict[str, object]:
    return {
        "title": "Company doubles engineering headcount",
        "body": "The company announced plans to grow its engineering team significantly.",
        "what_happened": "The CEO announced a major hiring plan.",
        "why_it_matters": "This signals aggressive investment in product development this year.",
        "what_remains_unknown": None,
        "quote": {"text": "We will double our engineering team next year", "translated_text": None, "speaker": "CEO"},
    }


def _copywriting_output_with_fabricated_quote() -> dict[str, object]:
    output = _copywriting_output_with_quote()
    output["quote"] = {"text": "We will triple our engineering team by tomorrow", "translated_text": None, "speaker": "CEO"}
    return output


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


async def _make_event_with_content(session: AsyncSession, content: str) -> NewsEvent:
    source = NewsSource(name=f"Quote Test Source {uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=f"Quote test event {uuid4()}", content=content,
        category=EventCategory.AI, hash=f"quote-test-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _run_and_persist(session: AsyncSession, event: NewsEvent, copywriting_output: dict[str, object]):
    from capabilities.executor import CapabilityExecutor
    from capabilities.registry import build_registry
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from workflows.registry import registry as real_workflow_registry
    from workflows.runner import WorkflowRunner

    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(copywriting_output),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    capability_registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(session, command)
    executor = CapabilityExecutor(session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(session, task.id)
    assert result.status == "COMPLETED"
    return await ContentDraftService(session).create_from_result(task.id, result, event_id=event.id)


@pytest.mark.asyncio
async def test_verified_quote_is_persisted(db_session: AsyncSession) -> None:
    event = await _make_event_with_content(db_session, _SOURCE_CONTENT)
    draft = await _run_and_persist(db_session, event, _copywriting_output_with_quote())

    quote_row = await db_session.get(ContentDraftQuote, draft.id)
    assert quote_row is not None
    assert quote_row.speaker == "CEO"


@pytest.mark.asyncio
async def test_fabricated_quote_is_dropped_never_persisted(db_session: AsyncSession) -> None:
    event = await _make_event_with_content(db_session, _SOURCE_CONTENT)
    draft = await _run_and_persist(db_session, event, _copywriting_output_with_fabricated_quote())

    quote_row = await db_session.get(ContentDraftQuote, draft.id)
    assert quote_row is None  # fabricated - never verified, never persisted
