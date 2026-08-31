"""Tests for capabilities.meme_concept_capability.MemeConceptCapability (Phase 18 M2).

Unit-tier: `FakeLLMGateway` + `FakePromptRepository` only, mirroring
`tests/test_copywriting_capability.py`'s exact convention - no DB, no live provider call.
"""
import ast
import inspect
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityError,
    PermanentCapabilityError,
    ValidationCapabilityError,
)
from capabilities.meme_concept_capability import CAPABILITY_NAME, MemeConceptCapability
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

_MEME_CONCEPT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "premise": {"type": "string"},
        "setup": {"type": "string"},
        "punchline": {"type": "string"},
        "humor_mechanism": {"type": "string"},
        "visual_scene": {"type": "string"},
        "characters_objects": {"type": "array"},
        "text_overlay_intent": {"type": "string"},
        "source_fact_links": {"type": "array"},
        "forbidden_interpretations": {"type": "array"},
        "meme_format": {"type": "string"},
    },
    "required": [
        "premise", "setup", "punchline", "humor_mechanism", "visual_scene",
        "characters_objects", "text_overlay_intent", "source_fact_links",
        "forbidden_interpretations", "meme_format",
    ],
}

_VALID_OUTPUT = {
    "premise": "An AI company insists AI won't take jobs.",
    "setup": "The CEO of an AI company reassures workers.",
    "punchline": "Meanwhile the CEO's own job is the one thing AI actually can't replace.",
    "humor_mechanism": "self_referential_irony",
    "visual_scene": "A CEO on a stage pointing at a slide titled 'Jobs are safe'.",
    "characters_objects": ["CEO", "presentation slide"],
    "text_overlay_intent": "Contrast the reassurance with public skepticism.",
    "source_fact_links": ["The CEO publicly stated AI is not destroying jobs."],
    "forbidden_interpretations": ["Not a claim that the CEO is lying."],
    "meme_format": "classic_top_bottom",
}


def _prompt_repository(*, rules: list[str] | None = None) -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            # MEME PRODUCTION PIPELINE: matches capabilities/meme_concept_capability.py's own
            # PROMPT_VERSION ("2" as of that phase) - a unit-tier fake, never the real
            # prompts/meme_concept/v2.yaml file (test_real_v2_prompt_file_loads_and_matches_the_
            # meme_concept_schema below is what exercises that real file).
            name=CAPABILITY_NAME,
            version="2",
            system="You are a fake meme-concept assistant for tests.",
            rules=rules if rules is not None else ["Never invent facts not present in Research."],
            output_schema=_MEME_CONCEPT_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(
    *,
    title: str = "Nvidia CEO insists AI is not destroying jobs",
    category: str = "AI",
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
                workflow_name="meme_generation",
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
    capability = MemeConceptCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"
    assert result.calls[0].gateway_method == "generate"

    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in request_text


@pytest.mark.asyncio
async def test_missing_research_step_results_does_not_raise() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MemeConceptCapability(gateway, _prompt_repository())
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
            structured_output={"premise": "only a premise"},  # missing every other required key
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = MemeConceptCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context(step_results={"research": CANONICAL_RESEARCH_OUTPUT}))


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    params = list(inspect.signature(MemeConceptCapability.__init__).parameters)
    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MemeConceptCapability(gateway, _prompt_repository())

    first = await capability.execute(_context(title="Story A", step_results={"research": CANONICAL_RESEARCH_OUTPUT}))
    second = await capability.execute(_context(title="Story B", step_results={"research": CANONICAL_RESEARCH_OUTPUT}))

    assert first.calls[0].call_id != second.calls[0].call_id
    assert len(first.calls) == 1
    assert len(second.calls) == 1


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
    capability = MemeConceptCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    with pytest.raises(expected_capability_error):
        await capability.execute(context)


@pytest.mark.asyncio
async def test_failed_capability_call_is_preserved_via_logging_before_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    capability = MemeConceptCapability(gateway, _prompt_repository())

    with caplog.at_level(logging.INFO):
        with pytest.raises(CapabilityConfigurationError):
            await capability.execute(_context(step_results={"research": CANONICAL_RESEARCH_OUTPUT}))

    failure_records = [r for r in caplog.records if r.message == "capability_call_failed"]
    assert len(failure_records) == 1
    assert getattr(failure_records[0], "status") == "FAILED"  # noqa: B009


def test_non_coupling_never_imports_research_or_intelligence_capability() -> None:
    """Mirrors test_copywriting_capability.py's identical AST-based import check."""
    source = Path("capabilities/meme_concept_capability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any("research_capability" in module for module in imported_modules)
    assert not any("intelligence_capability" in module for module in imported_modules)


def test_real_v1_prompt_file_loads_and_matches_the_meme_concept_schema() -> None:
    """Proves the *real*, published `prompts/meme_concept/v1.yaml` (not merely a test fixture)
    resolves and its output_schema's required keys match MemeConcept's own fields."""
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.meme_concept import MemeConcept

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "1")
    schema_required = set(prompt.output_schema["required"])
    concept_fields = set(MemeConcept.model_fields) - {"schema_version"}
    assert schema_required == concept_fields


def test_real_v2_prompt_file_loads_and_matches_the_meme_concept_schema() -> None:
    """MEME PRODUCTION PIPELINE: the currently-active prompt version (capabilities/meme_concept_
    capability.py::PROMPT_VERSION == "2") - v1 stays frozen and separately tested above."""
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.meme_concept import MemeConcept

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "2")
    schema_required = set(prompt.output_schema["required"])
    concept_fields = set(MemeConcept.model_fields) - {"schema_version"}
    assert schema_required == concept_fields
    # The whole point of v2: meme_format must NOT be enum-restricted anymore.
    assert "enum" not in prompt.output_schema["properties"]["meme_format"]
