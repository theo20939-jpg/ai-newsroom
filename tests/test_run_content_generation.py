"""Tests for scripts.run_content_generation.run_content_generation_for_event (Phase 10 M4,
docs/phase10_production_content_pipeline_architecture_contract.md §9/§12 "CLI tests").

Every test uses `tests.test_triage_orchestrator_claims.independent_session_factory()`/
`real_committed_event()` (Phase 9 M2's own precedent, already reused by Phase 9.5 M2 and Phase 10
M3), never the `db_session` fixture: `run_content_generation_for_event()` opens its own session
via an injected `session_factory` callable, which the `db_session` fixture (an already-open
session instance, not a sessionmaker) cannot supply.

Only `run_content_generation_for_event()` is tested - never the thin `main()`/CLI wrapper,
mirroring this repository's own established convention (no existing script's `main()` is
unit-tested anywhere in this codebase; `scripts/run_triage.py`'s own `main()` has no test either).
No live external LLM API call is made anywhere in this file - `capability_registry` is always
injected with a `FakeLLMGateway`-backed registry, or `assemble_ai_integration_layer` itself is
monkeypatched to a non-network stub.
"""
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import scripts.run_content_generation as run_content_generation_module
from capabilities.registry import build_registry
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityUsage
from scripts.run_content_generation import run_content_generation_for_event
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from tests.test_triage_orchestrator_claims import independent_session_factory, real_committed_event
from workflows.errors import NewsEventNotFoundError

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title",
    "body": "Example draft body text.",
    "hashtags": ["#example", "#news"],
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


def _fake_registry_for_success():
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_COPYWRITING_OUTPUT),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    return build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]


def _fake_registry_for_failure():
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    return build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


async def _cleanup_content_draft(factory: async_sessionmaker[AsyncSession], task_id: UUID) -> None:
    """ContentDraft.task_id has no ON DELETE CASCADE - must be removed before
    real_committed_event()'s own teardown deletes the EditorialTask."""
    async with factory() as session:
        rows = (await session.execute(select(ContentDraft).where(ContentDraft.task_id == task_id))).scalars().all()
        for row in rows:
            await session.delete(row)
        if rows:
            await session.commit()


# ---------------------------------------------------------------------------
# 1/2. Injected-registry execution never touches the real production bootstrap.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_injected_registry_execution_never_calls_the_real_bootstrap(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("assemble_ai_integration_layer() MUST NOT be called when a capability_registry is injected")

    monkeypatch.setattr(run_content_generation_module, "assemble_ai_integration_layer", _fail_if_called)

    async with real_committed_event(factory) as event_id:
        outcome = await run_content_generation_for_event(
            event_id, capability_registry=_fake_registry_for_success(), session_factory=factory
        )
        try:
            assert outcome.workflow_status == "COMPLETED"
            assert outcome.content_draft is not None
        finally:
            await _cleanup_content_draft(factory, outcome.task_id)


# ---------------------------------------------------------------------------
# 3. Default production path uses the existing production integration bootstrap.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_path_uses_the_production_bootstrap(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0

    class _FakeAiLayer:
        def __init__(self) -> None:
            self.capability_registry = _fake_registry_for_success()

    def _stub_assemble(*args: object, **kwargs: object) -> _FakeAiLayer:
        nonlocal call_count
        call_count += 1
        return _FakeAiLayer()

    monkeypatch.setattr(run_content_generation_module, "assemble_ai_integration_layer", _stub_assemble)

    async with real_committed_event(factory) as event_id:
        outcome = await run_content_generation_for_event(event_id, session_factory=factory)  # no capability_registry
        try:
            assert call_count == 1
            assert outcome.workflow_status == "COMPLETED"
        finally:
            await _cleanup_content_draft(factory, outcome.task_id)


# ---------------------------------------------------------------------------
# 4/5/6/Step 10. End-to-end proof: real WorkflowRunner/CapabilityExecutor/CapabilityRegistry
# interface/CONTENT_GENERATION definition/ContentDraftService, fake AI/provider behavior only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_generation_end_to_end_persists_exactly_one_content_draft(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        outcome = await run_content_generation_for_event(
            event_id, capability_registry=_fake_registry_for_success(), session_factory=factory
        )
        try:
            assert outcome.workflow_status == "COMPLETED"
            assert outcome.content_draft is not None
            draft = outcome.content_draft
            assert draft.task_id == outcome.task_id
            assert draft.title == _COPYWRITING_OUTPUT["title"]
            assert draft.body == _COPYWRITING_OUTPUT["body"]
            assert draft.hashtags == _COPYWRITING_OUTPUT["hashtags"]
            assert draft.version == 1
            assert draft.status == "draft"

            async with factory() as session:
                task = await session.get(EditorialTask, outcome.task_id)
                assert task is not None
                assert task.event_id == event_id

                rows = (
                    await session.execute(select(ContentDraft).where(ContentDraft.task_id == outcome.task_id))
                ).scalars().all()
                assert len(rows) == 1
                assert rows[0].id == draft.id
        finally:
            await _cleanup_content_draft(factory, outcome.task_id)


# ---------------------------------------------------------------------------
# 7. Failed workflow persists zero ContentDraft rows.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_workflow_does_not_persist_a_content_draft(factory: async_sessionmaker[AsyncSession]) -> None:
    async with real_committed_event(factory) as event_id:
        outcome = await run_content_generation_for_event(
            event_id, capability_registry=_fake_registry_for_failure(), session_factory=factory
        )
        try:
            assert outcome.workflow_status == "FAILED"
            assert outcome.content_draft is None

            async with factory() as session:
                rows = (
                    await session.execute(select(ContentDraft).where(ContentDraft.task_id == outcome.task_id))
                ).scalars().all()
                assert rows == []
        finally:
            await _cleanup_content_draft(factory, outcome.task_id)


# ---------------------------------------------------------------------------
# 8. A ContentDraftService persistence failure (which a "COMPLETED but missing/invalid
# copywriting result" would be one real-world cause of, per services/content_draft_service.py's
# own _copywriting_output() guard, already proven directly in tests/test_content_draft_service.py)
# surfaces as a distinct, logged non-success outcome - never a script crash, never a silently
# created draft. Reachable at this orchestration layer via any ContentDraftService failure, since
# the real four-step chain can never itself produce a COMPLETED result missing "copywriting"
# (it is a required step) - this test exercises the general persistence-failure branch, not a
# claim that the real chain can produce a missing-copywriting COMPLETED result.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistence_failure_surfaces_as_distinct_outcome_not_a_crash(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated ContentDraftService failure")

    monkeypatch.setattr(run_content_generation_module.ContentDraftService, "create_from_result", _raise)

    async with real_committed_event(factory) as event_id:
        outcome = await run_content_generation_for_event(
            event_id, capability_registry=_fake_registry_for_success(), session_factory=factory
        )
        try:
            assert outcome.workflow_status == "COMPLETED"  # the workflow itself did complete
            assert outcome.content_draft is None  # but no draft was persisted

            async with factory() as session:
                rows = (
                    await session.execute(select(ContentDraft).where(ContentDraft.task_id == outcome.task_id))
                ).scalars().all()
                assert rows == []
        finally:
            await _cleanup_content_draft(factory, outcome.task_id)


# ---------------------------------------------------------------------------
# 9. NewsEvent not found.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_news_event_not_found_raises(factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(NewsEventNotFoundError):
        await run_content_generation_for_event(
            uuid4(), capability_registry=_fake_registry_for_success(), session_factory=factory
        )
