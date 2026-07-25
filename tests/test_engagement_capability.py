"""Tests for capabilities.engagement_capability.EngagementCapability (Phase 13 M1).

Unit-tier: `FakeLLMGateway` + `FakePromptRepository` only, mirroring
`tests/test_intelligence_capability.py`'s convention exactly. `step_results["research"]`/
`step_results["intelligence"]` are seeded from canonical fixtures - never hand-duplicated
where an existing shared fixture (`tests/fakes/research_output.py`) already exists.
"""
import inspect
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from capabilities.engagement_capability import CAPABILITY_NAME, EngagementCapability
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

_INTELLIGENCE_OUTPUT = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}

_ENGAGEMENT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "engagement_potential_score": {"type": "number"},
        "audience_fit": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["engagement_potential_score", "audience_fit", "reasoning"],
    "additionalProperties": False,
}

_VALID_OUTPUT = {
    "engagement_potential_score": 0.65,
    "audience_fit": "AI/tech enthusiasts",
    "reasoning": "Novel technical development with broad relevance.",
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="1",
            system="You are a fake engagement assistant for tests.",
            rules=["Never claim access to real engagement metrics."],
            output_schema=_ENGAGEMENT_OUTPUT_SCHEMA,
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
                workflow_name="news_analysis",
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
async def test_execute_full_shape_end_to_end_reflects_research_and_intelligence_in_prompt() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = EngagementCapability(gateway, _prompt_repository())
    context = _context(
        step_results={"research": CANONICAL_RESEARCH_OUTPUT, "intelligence": _INTELLIGENCE_OUTPUT}
    )

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"

    # Proves the step_results handoff actually flowed into the built prompt for BOTH prior
    # steps, not merely that the call succeeded (mirrors test_intelligence_capability.py's
    # own pattern for inspecting sent requests).
    assert len(gateway.received_requests) == 1
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in request_text
    assert _INTELLIGENCE_OUTPUT["angle"] in request_text
    assert _INTELLIGENCE_OUTPUT["recommendation"] in request_text


@pytest.mark.asyncio
async def test_missing_step_results_research_and_intelligence_does_not_raise() -> None:
    """Engagement MUST NOT raise merely because Research's/Intelligence's output is absent -
    graceful degradation, mirroring IntelligenceCapability's own established design for a
    missing upstream step."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = EngagementCapability(gateway, _prompt_repository())
    context = _context(step_results={})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "did not run" in request_text.lower()


@pytest.mark.asyncio
async def test_missing_intelligence_only_still_succeeds_with_research_present() -> None:
    """Partial degradation: Research ran, Intelligence did not - still no raise, and the
    request text distinguishes the two (Research populated, Intelligence explicitly absent)."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = EngagementCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in request_text
    assert "did not run" in request_text.lower()


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error_not_silent_success() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"engagement_potential_score": 0.5},  # missing required keys
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = EngagementCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(
            _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT, "intelligence": _INTELLIGENCE_OUTPUT})
        )


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    """No BudgetGuard, no CostTracker in the constructor signature (Amendment C)."""
    params = list(inspect.signature(EngagementCapability.__init__).parameters)

    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = EngagementCapability(gateway, _prompt_repository())

    first = await capability.execute(
        _context(title="Story A", step_results={"research": CANONICAL_RESEARCH_OUTPUT})
    )
    second = await capability.execute(
        _context(title="Story B", step_results={"research": CANONICAL_RESEARCH_OUTPUT})
    )

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
    capability = EngagementCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT, "intelligence": _INTELLIGENCE_OUTPUT})

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
    capability = EngagementCapability(gateway, _prompt_repository())

    with caplog.at_level(logging.INFO):
        with pytest.raises(CapabilityConfigurationError):
            await capability.execute(
                _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT, "intelligence": _INTELLIGENCE_OUTPUT})
            )

    failure_records = [r for r in caplog.records if r.message == "capability_call_failed"]
    assert len(failure_records) == 1
    assert getattr(failure_records[0], "status") == "FAILED"  # noqa: B009 - dynamic `extra=` field
    assert getattr(failure_records[0], "gateway_method") == "generate"  # noqa: B009


def test_engagement_capability_does_not_yet_read_real_engagement_metrics() -> None:
    """Phase 15 M3 is data-preservation only - NewsEvent.views_count/forwards_count/
    replies_count/reactions_count (now persisted) must not be read anywhere in this capability's
    prompt-building path, so engagement_potential_score's behavior is provably unchanged by M3.
    Wiring real metrics into this prompt is explicitly deferred to a future milestone."""
    source = Path("capabilities/engagement_capability.py").read_text(encoding="utf-8")
    for field_name in ("views_count", "forwards_count", "replies_count", "reactions_count"):
        assert field_name not in source


def test_non_coupling_never_imports_research_or_intelligence_capability() -> None:
    """Mirrors intelligence_capability.py's own analogous non-coupling proof
    (test_non_coupling_never_imports_research_capability): EngagementCapability MUST NOT hold
    a direct reference to ResearchCapability/IntelligenceCapability, import them, or call
    them - it consumes their output exclusively via step_results. AST-based, mechanical."""
    import ast

    source = Path("capabilities/engagement_capability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any("research_capability" in module for module in imported_modules)
    assert not any("intelligence_capability" in module for module in imported_modules)


def test_prompt_schema_is_strict_mode_compliant() -> None:
    """Prompt/schema invariant (§19 of the Plan): additionalProperties: false + all-3-fields-
    required - a synthetic invalid schema fails the check, the real prompts/engagement/v1.yaml
    passes it (non-tautological)."""
    from integrations.prompts.file_repository import FilePromptRepository

    def _strict_schema_violations(schema: dict[str, object]) -> list[str]:
        violations: list[str] = []
        if schema.get("additionalProperties") is not False:
            violations.append("missing additionalProperties: false")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        for key in properties:
            if key not in required:
                violations.append(f"{key} not in required")
        return violations

    invalid_schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": [],
    }
    assert _strict_schema_violations(invalid_schema) != []

    repository = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
    rendered = repository.resolve(CAPABILITY_NAME, "1")
    assert _strict_schema_violations(rendered.output_schema) == []
    assert rendered.output_schema.get("required") == [
        "engagement_potential_score",
        "audience_fit",
        "reasoning",
    ]
