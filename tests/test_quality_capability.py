"""Tests for capabilities.quality_capability.QualityCapability (Phase 8 M7).

Mirrors tests/test_scoring_capability.py's shape exactly, using the M6 testing convention
(FakeLLMGateway + FakePromptRepository) - proves contract §14's zero-change extension
guarantee for real: this file is the only new test file M7 adds, and it never imports or
modifies anything from capabilities/scoring_capability.py.
"""
import inspect
from uuid import uuid4

import pytest

from capabilities.errors import UnknownCapabilityError, ValidationCapabilityError
from capabilities.quality_capability import CAPABILITY_NAME, QualityCapability
from capabilities.registry import build_registry
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from capabilities.scoring_capability import ScoringCapability
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
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
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.fake_prompt_repository import FakePromptRepository

_QUALITY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}, "issues": {"type": "array"}},
    "required": ["passed", "issues"],
}


def _prompt_repository() -> FakePromptRepository:
    """Registers version "2" - Phase 10 M2 bumped `QualityCapability.PROMPT_VERSION` to "2"
    (docs/phase10_production_content_pipeline_architecture_contract.md §5.1), so this fake must
    resolve that version too, mirroring what `FilePromptRepository` now does against the real
    `prompts/quality/v2.yaml` on disk. A direct, mechanical consequence of the frozen Contract,
    not a weakened assertion - every assertion below is otherwise unchanged."""
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="3",
            system="You are a fake quality-check assistant for tests.",
            rules=["Do not invent issues."],
            output_schema=_QUALITY_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(*, step_results: dict[str, dict[str, object]] | None = None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title="Example headline",
                summary="A short summary.",
                content=None,
                url=None,
                category="technology",
                published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="daily_digest",
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


@pytest.mark.asyncio
async def test_execute_full_shape_end_to_end() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": True, "issues": []},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == {"passed": True, "issues": []}
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error_not_silent_success() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": True},  # missing required "issues"
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    params = list(inspect.signature(QualityCapability.__init__).parameters)

    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": False, "issues": ["missing summary"]},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    first = await capability.execute(_context())
    second = await capability.execute(_context())

    assert first.calls[0].call_id != second.calls[0].call_id
    assert len(first.calls) == 1
    assert len(second.calls) == 1


# ---------------------------------------------------------------------------
# §14 zero-change extension guarantee, proven for real: both capabilities coexist correctly in
# the same sealed CapabilityRegistry, neither shadowing nor interfering with the other.
# ---------------------------------------------------------------------------


def test_scoring_and_quality_coexist_in_the_same_sealed_registry() -> None:
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type] # never called - construction/resolution only
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    scoring_definition, scoring_capability = registry.resolve(SCORING_CAPABILITY_NAME)
    quality_definition, quality_capability = registry.resolve(CAPABILITY_NAME)

    assert scoring_definition.name == SCORING_CAPABILITY_NAME
    assert isinstance(scoring_capability, ScoringCapability)
    assert quality_definition.name == CAPABILITY_NAME
    assert isinstance(quality_capability, QualityCapability)
    assert scoring_capability is not quality_capability

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("no_such_capability")


# ---------------------------------------------------------------------------
# Phase 10 M2 amendment (Contract §5.1): QualityCapability now reads
# step_results["copywriting"]. Mandatory per the Contract Audit / §12 "QualityCapability
# adaptation tests" - this amendment touches existing, previously-tested behavior.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_built_request_includes_copywriting_draft_when_present() -> None:
    """Proves the step_results handoff actually flowed into the built prompt - the same
    "prove data flowed" discipline test_intelligence_capability.py already applies to
    Research->Intelligence, applied here to Copywriting->Quality."""
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": True, "issues": []},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())
    copywriting_output: dict[str, object] = {
        "title": "Example draft title",
        "body": "Example draft body text.",
        "hashtags": ["#example", "#news"],
    }

    result = await capability.execute(_context(step_results={"copywriting": copywriting_output}))

    assert result.status == "SUCCESS"
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "Example draft title" in request_text
    assert "Example draft body text." in request_text
    assert "#example" in request_text


@pytest.mark.asyncio
async def test_built_request_still_includes_news_event_fields_when_copywriting_absent() -> None:
    """§5.1's explicit "no existing NewsEvent-reading behavior is removed" guarantee,
    regression-tested directly - quality can still flag a poor underlying event even with no
    draft present, exactly as it did before this amendment."""
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": True, "issues": []},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    result = await capability.execute(_context(step_results={}))

    assert result.status == "SUCCESS"
    request_text = "\n".join(
        part.text for message in gateway.received_requests[0].messages for part in message.content if part.text
    )
    assert "Example headline" in request_text  # news_event.title
    assert "technology" in request_text  # news_event.category
    assert "A short summary." in request_text  # news_event.summary
    assert "did not run" in request_text.lower()  # Copywriting's absence is stated, not hidden


def test_prompt_version_resolves_to_3() -> None:
    from capabilities.quality_capability import PROMPT_VERSION

    assert PROMPT_VERSION == "3"


def test_v1_prompt_remains_on_disk_and_still_independently_resolvable() -> None:
    """Proves v1 was not deleted or mutated, only superseded as the default - v2 is what
    QualityCapability now resolves, but resolve("quality", "1") still works against the real
    FilePromptRepository (Phase 6 §8's prompt-immutability rule)."""
    from pathlib import Path

    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    v1 = repository.resolve(CAPABILITY_NAME, "1")
    v2 = repository.resolve(CAPABILITY_NAME, "2")

    assert v1.version == "1"
    assert v2.version == "2"
    assert v1.system != v2.system  # genuinely different prompt content, not a duplicate


def test_expected_output_keys_and_v2_schema_identical_to_v1() -> None:
    """Proves the amendment changed only the input side, not the output contract (§5.1)."""
    from pathlib import Path

    from capabilities.quality_capability import QUALITY_CAPABILITY_DEFINITION
    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    repository = FilePromptRepository(prompts_root)

    v1 = repository.resolve(CAPABILITY_NAME, "1")
    v2 = repository.resolve(CAPABILITY_NAME, "2")

    assert QUALITY_CAPABILITY_DEFINITION.expected_output_keys == ["passed", "issues"]
    assert v1.output_schema == v2.output_schema
    assert v2.output_schema["required"] == QUALITY_CAPABILITY_DEFINITION.expected_output_keys


def test_non_coupling_never_imports_copywriting_capability() -> None:
    """§5.1's binding rule, checked directly and mechanically (an AST-based import check,
    mirroring tests/test_intelligence_capability.py::test_non_coupling_never_imports_research_
    capability's own approach): QualityCapability MUST NOT hold a direct reference to
    CopywritingCapability, import it, or call it."""
    import ast
    from pathlib import Path

    source = Path("capabilities/quality_capability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any("copywriting_capability" in module for module in imported_modules)
