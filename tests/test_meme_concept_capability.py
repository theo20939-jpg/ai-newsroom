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
        "visual_punchline": {"type": "string"},
        "characters_objects": {"type": "array"},
        "panel_count": {"type": "integer"},
        "panel_beats": {"type": "array"},
        "visual_style": {"type": "string"},
        "text_overlay_intent": {"type": "string"},
        "source_fact_links": {"type": "array"},
        "forbidden_interpretations": {"type": "array"},
        "meme_format": {"type": "string"},
    },
    "required": [
        "premise", "setup", "punchline", "humor_mechanism", "visual_scene", "visual_punchline",
        "characters_objects", "panel_count", "panel_beats", "visual_style", "text_overlay_intent",
        "source_fact_links", "forbidden_interpretations", "meme_format",
    ],
}

_VALID_OUTPUT = {
    "premise": "An AI company insists AI won't take jobs.",
    "setup": "The CEO of an AI company reassures workers.",
    "punchline": "Meanwhile the CEO's own job is the one thing AI actually can't replace.",
    "humor_mechanism": "self_referential_irony",
    "visual_scene": "A CEO on a stage pointing at a slide titled 'Jobs are safe'.",
    "visual_punchline": "The CEO's own chair is visibly being carried out by a robot behind him.",
    "characters_objects": ["CEO", "presentation slide"],
    "panel_count": 1,
    "panel_beats": [],
    "visual_style": "reaction photo",
    "text_overlay_intent": "Contrast the reassurance with public skepticism.",
    "source_fact_links": ["The CEO publicly stated AI is not destroying jobs."],
    "forbidden_interpretations": ["Not a claim that the CEO is lying."],
    "meme_format": "classic_top_bottom",
}


def _prompt_repository(*, rules: list[str] | None = None) -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            # MEME-PROD-4: matches capabilities/meme_concept_capability.py's own PROMPT_VERSION
            # ("4" as of this phase) - a unit-tier fake, never the real prompts/meme_concept/
            # v4.yaml file (test_real_v4_prompt_file_loads_and_matches_the_meme_concept_schema
            # below is what exercises that real file).
            name=CAPABILITY_NAME,
            version="4",
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


# ---------------------------------------------------------------------------
# MEME-PROD-4: meme-shape correction retry (mirrors scoring_capability.py's own §10 shape).
# ---------------------------------------------------------------------------

_RESTATED_OUTPUT = {
    **_VALID_OUTPUT,
    # Deliberately near-identical to visual_scene - services/meme_shape_gate.py must flag this.
    "visual_punchline": "A CEO on a stage pointing at a slide titled 'Jobs are safe' during the speech.",
}

_GOOD_RETRY_OUTPUT = {
    **_VALID_OUTPUT,
    "visual_punchline": "A robot quietly wheels the CEO's own desk out the door behind him mid-speech.",
}


@pytest.mark.asyncio
async def test_shape_risk_triggers_exactly_one_correction_retry_then_accepts_result() -> None:
    gateway = FakeLLMGateway(
        generate_responses=[_valid_response(_RESTATED_OUTPUT), _valid_response(_GOOD_RETRY_OUTPUT)],
    )
    capability = MemeConceptCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert result.structured_output == _GOOD_RETRY_OUTPUT
    assert len(result.calls) == 2
    assert result.calls[0].sequence == 0
    assert result.calls[1].sequence == 1
    assert result.metadata is not None
    assert result.metadata["retry_reason"] == "meme_shape_risk"
    assert result.metadata["shape_risk_reason"] == "visual_punchline_restates_visual_scene"
    assert len(gateway.received_requests) == 2
    # §10.2-style "no re-routing": the retry pins preferred_model to the first attempt's model.
    assert gateway.received_requests[1].preferred_model == "fake-model-v1"
    # The correction message is APPENDED, never replacing the original message list.
    assert len(gateway.received_requests[1].messages) == len(gateway.received_requests[0].messages) + 1


@pytest.mark.asyncio
async def test_shape_risk_still_present_on_retry_is_accepted_unconditionally() -> None:
    """Shape is a soft quality signal, not a hard contract - a second consecutive risk verdict is
    accepted, never a third attempt, never a raise (unlike a real schema violation)."""
    gateway = FakeLLMGateway(
        generate_responses=[_valid_response(_RESTATED_OUTPUT), _valid_response(_RESTATED_OUTPUT)],
    )
    capability = MemeConceptCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert result.structured_output == _RESTATED_OUTPUT
    assert len(result.calls) == 2
    assert len(gateway.received_requests) == 2  # never a third attempt


@pytest.mark.asyncio
async def test_schema_violation_on_shape_correction_retry_still_raises() -> None:
    """Structural validity stays hard even on the retry - only the SHAPE verdict is accepted
    unconditionally on a second pass, never a broken schema."""
    broken_retry_output = {k: v for k, v in _GOOD_RETRY_OUTPUT.items() if k != "visual_scene"}
    gateway = FakeLLMGateway(
        generate_responses=[_valid_response(_RESTATED_OUTPUT), _valid_response(broken_retry_output)],
    )
    capability = MemeConceptCapability(gateway, _prompt_repository())
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(context)


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


# MEME-PROD-4: the exact required-field set every one of v1/v2/v3 declared - frozen, hardcoded
# here rather than derived from the live `MemeConcept.model_fields`, because that schema has now
# genuinely evolved (MEME-PROD-4 added new REQUIRED fields for v4's own Meme Director shape).
# v1/v2/v3 are immutable prompt files - they were correct for the schema shape that existed when
# each was written, and asserting them against today's ever-evolving live schema would make every
# future schema change spuriously "break" a frozen historical file it was never meant to track.
_V1_V2_V3_REQUIRED_FIELDS = {
    "premise", "setup", "punchline", "humor_mechanism", "visual_scene", "characters_objects",
    "text_overlay_intent", "source_fact_links", "forbidden_interpretations", "meme_format",
}


def test_real_v1_prompt_file_loads_and_matches_the_meme_concept_schema() -> None:
    """Proves the *real*, published `prompts/meme_concept/v1.yaml` (not merely a test fixture)
    resolves and its output_schema's required keys match the field set MemeConcept had when v1
    was written (see _V1_V2_V3_REQUIRED_FIELDS's own comment for why this is frozen, not live)."""
    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "1")
    assert set(prompt.output_schema["required"]) == _V1_V2_V3_REQUIRED_FIELDS


def test_real_v2_prompt_file_loads_and_matches_the_meme_concept_schema() -> None:
    """v1 stays frozen and separately tested above."""
    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "2")
    assert set(prompt.output_schema["required"]) == _V1_V2_V3_REQUIRED_FIELDS
    # The whole point of v2: meme_format must NOT be enum-restricted anymore.
    assert "enum" not in prompt.output_schema["properties"]["meme_format"]


def test_real_v3_prompt_file_loads_and_matches_the_meme_concept_schema() -> None:
    """v1/v2 stay frozen and separately tested above."""
    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "3")
    assert set(prompt.output_schema["required"]) == _V1_V2_V3_REQUIRED_FIELDS
    assert "enum" not in prompt.output_schema["properties"]["meme_format"]


def test_real_v4_prompt_file_loads_and_matches_the_meme_concept_schema() -> None:
    """MEME-PROD-4: the currently-active prompt version (capabilities/meme_concept_capability.py::
    PROMPT_VERSION == "4") - v1/v2/v3 stay frozen and separately tested above. This one DOES check
    against the live schema, since v4 is the version required to stay in lockstep with it."""
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.meme_concept import MemeConcept

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    prompt = repository.resolve(CAPABILITY_NAME, "4")
    schema_required = set(prompt.output_schema["required"])
    concept_fields = set(MemeConcept.model_fields) - {"schema_version"}
    assert schema_required == concept_fields
    assert "enum" not in prompt.output_schema["properties"]["meme_format"]
    assert prompt.output_schema["properties"]["panel_count"]["enum"] == [1, 2, 4]
    # The whole point of v4: visual_punchline must be a distinct visual joke, not a restatement of
    # visual_scene/the premise - the requirement plus its concrete bad/good example pair.
    rules_text = " ".join(prompt.rules).lower()
    assert "visual_punchline" in rules_text
    assert "toll booth" in rules_text and "kidney" in rules_text  # the concrete bad/good example pair
