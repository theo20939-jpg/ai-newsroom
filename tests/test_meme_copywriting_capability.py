"""Tests for capabilities.meme_copywriting_capability.MemeCopywritingCapability (Phase 18 M4).

Unit-tier: `FakeLLMGateway` + `FakePromptRepository` only, mirroring
`tests/test_meme_concept_capability.py`'s exact convention.
"""
import ast
import inspect
from pathlib import Path
from uuid import uuid4

import pytest

from capabilities.errors import ValidationCapabilityError
from capabilities.meme_copywriting_capability import CAPABILITY_NAME, MemeCopywritingCapability
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import GenerateResponse
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

_MEME_COPY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "top_text": {"type": "string"},
        "bottom_text": {"type": ["string", "null"]},
        "panel_texts": {"type": ["array", "null"]},
        "punchline_short": {"type": "string"},
        "telegram_caption": {"type": "string"},
        "editor_explanation": {"type": ["string", "null"]},
        "alt_text": {"type": "string"},
    },
    "required": [
        "top_text", "bottom_text", "panel_texts", "punchline_short", "telegram_caption",
        "editor_explanation", "alt_text",
    ],
}

_VALID_OUTPUT = {
    "top_text": "AI WON'T TAKE YOUR JOB",
    "bottom_text": "SAYS GUY WHOSE JOB IS AI",
    "panel_texts": None,
    "punchline_short": "The one job AI can't replace: reassuring you about AI.",
    "telegram_caption": "From today's Nvidia keynote - CEO addresses job-loss fears.",
    "editor_explanation": "Plays on the irony of an AI CEO reassuring workers about AI.",
    "alt_text": "A CEO on stage pointing at a slide reading 'Jobs are safe'.",
}

_CONCEPT_OUTPUT = {
    "premise": "An AI company insists AI won't take jobs.",
    "setup": "The CEO reassures workers during a keynote.",
    "punchline": "Meanwhile the CEO's own job is the one AI can't replace.",
    "humor_mechanism": "self_referential_irony",
    "visual_scene": "A CEO on stage pointing at a slide reading 'Jobs are safe'.",
    "visual_punchline": "A robot quietly wheels the CEO's own desk out the door mid-speech.",
    "characters_objects": ["CEO", "presentation slide"],
    "panel_count": 1,
    "panel_beats": [],
    "visual_style": "reaction photo",
    "text_overlay_intent": "Contrast reassurance with public skepticism.",
    "source_fact_links": ["The CEO publicly stated AI is not destroying jobs."],
    "forbidden_interpretations": [],
    "meme_format": "classic_top_bottom",
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="2",
            system="You are a fake meme copywriter for tests.",
            rules=["Never put a URL in on-image text."],
            output_schema=_MEME_COPY_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(step_results: dict[str, dict[str, object]] | None = None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Nvidia CEO insists AI is not destroying jobs", summary=None,
                content="Example body text.", url=None, category="AI", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="meme_generation", workflow_version=1,
                completed_steps=list(step_results.keys()) if step_results else [],
                step_results=step_results or {},
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.B, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def _valid_response(structured_output: dict[str, object] | None = None) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output if structured_output is not None else _VALID_OUTPUT,
        finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=20, output_tokens=8),
    )


@pytest.mark.asyncio
async def test_execute_reflects_concept_output_in_prompt() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MemeCopywritingCapability(gateway, _prompt_repository())
    context = _context(step_results={"meme_concept": _CONCEPT_OUTPUT})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert _CONCEPT_OUTPUT["punchline"] in request_text
    assert _CONCEPT_OUTPUT["visual_scene"] in request_text


@pytest.mark.asyncio
async def test_missing_concept_step_results_does_not_raise() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MemeCopywritingCapability(gateway, _prompt_repository())

    result = await capability.execute(_context(step_results={}))

    assert result.status == "SUCCESS"
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "did not run" in request_text.lower()


@pytest.mark.asyncio
async def test_editorial_brief_summary_included_when_present() -> None:
    """Brief's own 'reuse Phase 17 editorial intelligence as input, don't duplicate' requirement -
    proves the optional summary actually reaches the built prompt when available."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MemeCopywritingCapability(gateway, _prompt_repository())
    intelligence_output = {
        "editorial_brief": {"why_it_matters": "Signals growing public anxiety about AI job loss."}
    }
    context = _context(step_results={"meme_concept": _CONCEPT_OUTPUT, "intelligence": intelligence_output})

    await capability.execute(context)

    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "Signals growing public anxiety about AI job loss." in request_text


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output={"top_text": "only top text"},
            finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = MemeCopywritingCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context(step_results={"meme_concept": _CONCEPT_OUTPUT}))


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    params = list(inspect.signature(MemeCopywritingCapability.__init__).parameters)
    assert params == ["self", "gateway", "prompt_repository"]


def test_non_coupling_never_imports_meme_concept_capability() -> None:
    source = Path("capabilities/meme_copywriting_capability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any("meme_concept_capability" in module for module in imported_modules)


def test_real_v1_prompt_file_loads_and_matches_the_meme_copy_schema() -> None:
    """v1 predates MEME-PROD-4's panel_texts field - frozen, hardcoded expected set here rather
    than the live MemeCopy.model_fields, mirroring test_meme_concept_capability.py's own identical
    "frozen historical prompt vs. ever-evolving live schema" precedent."""
    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "1")
    assert set(prompt.output_schema["required"]) == {
        "top_text", "bottom_text", "punchline_short", "telegram_caption",
        "editor_explanation", "alt_text",
    }


def test_real_v2_prompt_file_loads_and_matches_the_meme_copy_schema() -> None:
    """MEME-PROD-4: the currently-active prompt version (capabilities/meme_copywriting_
    capability.py::PROMPT_VERSION == "2") - v1 stays frozen and separately tested above."""
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.meme_copy import MemeCopy

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "2")
    schema_required = set(prompt.output_schema["required"])
    copy_fields = set(MemeCopy.model_fields) - {"schema_version"}
    assert schema_required == copy_fields
    assert prompt.output_schema["properties"]["panel_texts"]["minItems"] == 4
