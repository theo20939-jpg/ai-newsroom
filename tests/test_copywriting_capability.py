"""Tests for capabilities.copywriting_capability.CopywritingCapability (Phase 10 M1).

Unit-tier: `FakeLLMGateway` + `FakePromptRepository` only, mirroring
`tests/test_research_capability.py`/`tests/test_intelligence_capability.py`'s exact convention.
`step_results["research"]` is seeded from `tests/fakes/research_output.py`'s
`CANONICAL_RESEARCH_OUTPUT`, reused (not hand-duplicated), matching Phase 9's own established
practice. No canonical Intelligence-output fixture exists yet, so `step_results["intelligence"]`
is a small, local, schema-accurate dict instead of a new shared fixture file - M1 authorizes no
new file beyond `capabilities/copywriting_capability.py`/`prompts/copywriting/v1.yaml`.
"""
import ast
import inspect
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from capabilities.copywriting_capability import CAPABILITY_NAME, CopywritingCapability
from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityError,
    PermanentCapabilityError,
    ValidationCapabilityError,
)
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import (
    AllProvidersFailedError,
    NoRoutableCandidateError,
    ProviderModerationBlockedError,
)
from integrations.llm_gateway.protocol import GenerateResponse, UnsupportedGatewayCapabilityError
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    CapabilityUsage,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT

_COPYWRITING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "hashtags": {"type": "array"},
    },
    "required": ["title", "body", "hashtags"],
}

_VALID_OUTPUT = {
    "title": "Example draft title",
    "body": "Example draft body text.",
    "hashtags": ["#example", "#news"],
}

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.75,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with high priority",
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="1",
            system="You are a fake copywriting assistant for tests.",
            rules=["Do not fabricate facts."],
            output_schema=_COPYWRITING_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(
    *,
    title: str = "Example headline",
    category: str = "technology",
    step_results: dict[str, dict[str, object]] | None = None,
) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title=title,
                summary=None,
                content="Example body text.",
                url=None,
                category=category,
                published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="content_generation",
                workflow_version=1,
                completed_steps=list(step_results.keys()) if step_results else [],
                step_results=step_results or {},
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(),
            event_id=uuid4(),
            capability_name=CAPABILITY_NAME,
            priority=TaskPriority.B,
            attempt=1,
            iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def _valid_response(structured_output: dict[str, object] | None = None) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output if structured_output is not None else _VALID_OUTPUT,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=20, output_tokens=8),
    )


@pytest.mark.asyncio
async def test_execute_full_shape_end_to_end_reflects_upstream_output_in_prompt() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT, "intelligence": _INTELLIGENCE_OUTPUT})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"
    assert result.calls[0].gateway_method == "generate"
    assert result.calls[0].model_used == "fake-model-v1"
    assert result.started_at <= result.finished_at

    # Proves the step_results handoff actually flowed into the built prompt - not merely that
    # the step ran (mirrors test_intelligence_capability.py's pattern for Research->Intelligence,
    # applied here to Research/Intelligence->Copywriting).
    assert len(gateway.received_requests) == 1
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in request_text
    assert str(CANONICAL_RESEARCH_OUTPUT["confidence"]) in request_text
    assert str(_INTELLIGENCE_OUTPUT["angle"]) in request_text
    assert str(_INTELLIGENCE_OUTPUT["recommendation"]) in request_text


@pytest.mark.asyncio
async def test_missing_step_results_does_not_raise() -> None:
    """Contract §5 (mirroring Intelligence's own §9.1 precedent): Copywriting MUST NOT raise
    merely because Research's/Intelligence's output is absent - proves the "does not hard-require
    it be populated" design decision is actually implemented."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository())
    context = _context(step_results={})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "did not run" in request_text.lower()


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error_not_silent_success() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"title": "only a title"},  # missing required "body"/"hashtags"
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = CopywritingCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context(step_results={"research": CANONICAL_RESEARCH_OUTPUT}))


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    """§4.2/§4.3/§4.4: no BudgetGuard, no CostTracker in the constructor signature."""
    params = list(inspect.signature(CopywritingCapability.__init__).parameters)

    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository())

    first = await capability.execute(_context(title="Story A", step_results={"research": CANONICAL_RESEARCH_OUTPUT}))
    second = await capability.execute(_context(title="Story B", step_results={"research": CANONICAL_RESEARCH_OUTPUT}))

    assert first.calls[0].call_id != second.calls[0].call_id
    assert len(first.calls) == 1
    assert len(second.calls) == 1  # not accumulated across calls - no shared mutable state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_error", "expected_capability_error"),
    [
        (NoRoutableCandidateError("no candidates"), CapabilityConfigurationError),
        (UnsupportedGatewayCapabilityError("unsupported"), CapabilityConfigurationError),
        (ProviderModerationBlockedError("blocked"), PermanentCapabilityError),
        (AllProvidersFailedError("exhausted", reason="all_candidates_failed"), PermanentCapabilityError),
    ],
)
async def test_gateway_errors_are_translated_never_escape_raw(
    gateway_error: Exception, expected_capability_error: type[CapabilityError]
) -> None:
    gateway = FakeLLMGateway(generate_error=gateway_error)
    capability = CopywritingCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    with pytest.raises(expected_capability_error):
        await capability.execute(context)

    with pytest.raises(expected_capability_error) as exc_info:
        await capability.execute(context)
    assert not isinstance(exc_info.value, type(gateway_error))


@pytest.mark.asyncio
async def test_failed_capability_call_is_preserved_via_logging_before_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    capability = CopywritingCapability(gateway, _prompt_repository())

    with caplog.at_level(logging.INFO):
        with pytest.raises(CapabilityConfigurationError):
            await capability.execute(_context(step_results={"research": CANONICAL_RESEARCH_OUTPUT}))

    failure_records = [r for r in caplog.records if r.message == "capability_call_failed"]
    assert len(failure_records) == 1
    assert getattr(failure_records[0], "status") == "FAILED"  # noqa: B009 - dynamic `extra=` field
    assert getattr(failure_records[0], "gateway_method") == "generate"  # noqa: B009


def test_non_coupling_never_imports_research_or_intelligence_capability() -> None:
    """Contract §5's binding rule, checked directly and mechanically (an AST-based import check,
    mirroring `tests/test_intelligence_capability.py::test_non_coupling_never_imports_research_
    capability`'s own approach): CopywritingCapability MUST NOT hold a direct reference to
    ResearchCapability or IntelligenceCapability, import either, or call either. Only actual
    import statements are checked - this file's own docstring legitimately *names* both
    Capabilities in prose, which is not a coupling violation."""
    source = Path("capabilities/copywriting_capability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any("research_capability" in module for module in imported_modules)
    assert not any("intelligence_capability" in module for module in imported_modules)
