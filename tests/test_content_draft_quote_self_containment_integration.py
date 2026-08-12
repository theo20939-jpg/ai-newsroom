"""NEWS Output Stability Fix (Case D, docs/news_output_stability_forensic_report.md §5):
integration tests proving ContentDraftService.create_from_result() now also enforces
check_quote_is_self_contained() at the exact same fail-closed point verify_quote() already
enforces at - a fragment quote (verbatim, correctly attributed, but not self-contained, mirroring
the real BBC/Discord "thoughtfully reviewing" case) must be dropped, never persisted, and the
draft itself must still be created normally without it.

Real Postgres (db_session, rolled back). Deliberately a separate file from tests/test_content_
draft_quote_integration.py - that file's own `pytestmark = pytest.mark.skip(...)` is stale (the
migration it names, f12a9b9732cc, is confirmed applied in this environment via a direct DB
inspection during this fix's implementation - `content_draft_quotes` table exists), but fixing
that pre-existing, unrelated stale skip is out of this corrective phase's own narrow scope; this
file avoids inheriting it so these new tests actually run.
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

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7, "angle": "Market impact", "audience_relevance": "General",
    "recommendation": "Publish",
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}

# Real source sentence shape (mirrors the actual BBC/Discord event.content) - contains both a
# genuinely self-contained quote and, separately, the exact real fragment.
_SOURCE_CONTENT = (
    'Discord told the BBC it was "thoughtfully reviewing" the order by the data protection '
    'agency, and added: "we take this seriously."'
)


def _copywriting_output(quote: dict[str, object] | None) -> dict[str, object]:
    return {
        "title": "Discord responds to regulator order",
        "body": "Discord addressed the regulator's order in a statement to the BBC.",
        "what_happened": "Discord responded to a data protection agency order.",
        "why_it_matters": "This affects how the platform is regulated in the region this year.",
        "what_remains_unknown": None,
        "quote": quote,
    }


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


async def _make_event_with_content(session: AsyncSession, content: str) -> NewsEvent:
    source = NewsSource(name=f"Quote Self-Containment Test Source {uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=f"Quote self-containment test event {uuid4()}", content=content,
        category=EventCategory.AI, hash=f"quote-self-containment-test-{uuid4()}",
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
async def test_self_contained_verbatim_quote_is_persisted(db_session: AsyncSession) -> None:
    event = await _make_event_with_content(db_session, _SOURCE_CONTENT)
    quote: dict[str, object] = {"text": "we take this seriously", "translated_text": None, "speaker": "Discord"}
    draft = await _run_and_persist(db_session, event, _copywriting_output(quote))

    quote_row = await db_session.get(ContentDraftQuote, draft.id)
    assert quote_row is not None
    assert quote_row.speaker == "Discord"


@pytest.mark.asyncio
async def test_real_fragment_quote_is_dropped_and_draft_still_renders_normally(db_session: AsyncSession) -> None:
    """The exact real regression: a verbatim, correctly-attributed, but contextless fragment
    ("thoughtfully reviewing") must be dropped - and the draft itself must still be created
    normally, with no quote, exactly like the existing fabricated-quote-drop behavior."""
    event = await _make_event_with_content(db_session, _SOURCE_CONTENT)
    quote: dict[str, object] = {"text": "thoughtfully reviewing", "translated_text": "вдумчиво рассматривает", "speaker": "Discord"}
    draft = await _run_and_persist(db_session, event, _copywriting_output(quote))

    quote_row = await db_session.get(ContentDraftQuote, draft.id)
    assert quote_row is None  # dropped - never persisted

    # NEWS still renders normally without the quote - the draft itself is completely unaffected.
    assert draft.title
    assert draft.body
    assert draft.status == "draft"


@pytest.mark.asyncio
async def test_self_contained_quote_with_missing_speaker_follows_existing_policy(db_session: AsyncSession) -> None:
    """Missing speaker is NOT one of check_quote_is_self_contained()'s own conditions (that
    dimension is check_quote_has_attribution()'s - a separate, non-blocking QualityGateReport
    signal, unchanged by this fix) - a self-contained, verbatim quote with an empty speaker must
    still be persisted exactly as the existing policy already allows (ContentDraftQuote.speaker
    stored as ""), never newly blocked by this corrective phase."""
    event = await _make_event_with_content(db_session, _SOURCE_CONTENT)
    quote: dict[str, object] = {"text": "we take this seriously", "translated_text": None, "speaker": None}
    draft = await _run_and_persist(db_session, event, _copywriting_output(quote))

    quote_row = await db_session.get(ContentDraftQuote, draft.id)
    assert quote_row is not None  # still persisted - self-containment alone does not require a speaker
    assert quote_row.speaker == ""
