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


_LANGUAGE_RULE = (
    'Always write the title, body, and hashtags entirely in the language given by "Target '
    'output language" in the CONTEXT block below.'
)


def _prompt_repository(*, rules: list[str] | None = None) -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="3",
            system="You are a fake copywriting assistant for tests.",
            rules=rules if rules is not None else ["Do not fabricate facts.", _LANGUAGE_RULE],
            output_schema=_COPYWRITING_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(
    *,
    title: str = "Example headline",
    category: str = "technology",
    language: str = "ru",
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
            language=language,
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


# --- Russian output remediation (docs/content_generation_language_final_implementation_plan.md) --


def test_prompt_version_resolves_to_3() -> None:
    from capabilities.copywriting_capability import PROMPT_VERSION

    assert PROMPT_VERSION == "3"


@pytest.mark.asyncio
async def test_target_output_language_label_and_value_appear_in_request() -> None:
    """Regression D (partial): a configured language value propagates all the way into the
    actual constructed request - the label is now unambiguous ("Target output language:"),
    not the old, ambiguous "Language:" that read like a source-event attribute."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository())
    context = _context(language="ru", step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    await capability.execute(context)

    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "Target output language: ru" in request_text
    assert "Language: ru" not in request_text  # the old, ambiguous label must be gone


@pytest.mark.asyncio
async def test_english_context_still_targets_configured_language_english_case() -> None:
    """Regression A: an English-language `context.business.news_event` (source content in
    English) combined with a non-English target `language` value must still surface the target
    value in the request - proves the target-language signal is independent of source content,
    matching the required "source may be any language, output targets the configured language"
    behavior. (Whether the model actually complies is a live-API concern, out of this offline
    unit test's reach - proven separately, see the plan's live-API check.)"""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository())
    context = _context(
        title="An English-language headline about markets",
        language="ru",
        step_results={"research": CANONICAL_RESEARCH_OUTPUT},
    )

    await capability.execute(context)

    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "An English-language headline about markets" in request_text  # source, unchanged
    assert "Target output language: ru" in request_text  # target, independent of source


@pytest.mark.asyncio
async def test_russian_source_context_still_targets_configured_language() -> None:
    """Regression B: a Russian-language source event with a Russian target language still
    correctly surfaces the target value - proves the mechanism doesn't depend on source
    language matching the target."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository())
    context = _context(
        title="Заголовок на русском языке о рынках",
        language="ru",
        step_results={"research": CANONICAL_RESEARCH_OUTPUT},
    )

    await capability.execute(context)

    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "Заголовок на русском языке о рынках" in request_text
    assert "Target output language: ru" in request_text


@pytest.mark.asyncio
async def test_governed_language_rule_flows_into_system_text() -> None:
    """Regression C: the actual Copywriting prompt/request contract contains an explicit
    governed instruction requiring output in the target language - proves the RULE (not just the
    dynamic value) reaches the real request the Gateway receives, via the ordinary, unmodified
    `prompt.rules` -> `system_text` plumbing every capability already uses."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = CopywritingCapability(gateway, _prompt_repository(rules=["Do not fabricate facts.", _LANGUAGE_RULE]))
    context = _context(step_results={"research": CANONICAL_RESEARCH_OUTPUT})

    await capability.execute(context)

    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert _LANGUAGE_RULE in request_text


def test_real_v3_prompt_file_contains_the_governed_language_rule() -> None:
    """Proves the *real*, published `prompts/copywriting/v3.yaml` (not merely a test fixture)
    actually contains the governed language rule, and that `prompts/copywriting/v2.yaml` remains
    byte-for-byte unmodified (Phase 6 §8 prompt-immutability)."""
    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    v3 = repository.resolve(CAPABILITY_NAME, "3")
    assert any("target output language" in rule.lower() for rule in v3.rules)

    v2 = repository.resolve(CAPABILITY_NAME, "2")
    assert v2.rules == [
        "Base the draft only on the given title/category and the supplied Research/Intelligence output"
        " - never invent facts not present in either.",
        "Keep the title concise and the body suitable for a short social post.",
        "Hashtags must be relevant to the event's category and content, no more than a handful.",
    ]
    assert not any("target output language" in rule.lower() for rule in v2.rules)
