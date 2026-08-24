"""Tests for workflows.registry.WorkflowRegistry. Pure unit tests, no database."""
import pytest

from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from workflows.errors import (
    DuplicateWorkflowRegistrationError,
    RegistryAlreadySealedError,
    UnknownWorkflowTypeError,
)
from workflows.registry import WorkflowRegistry
from workflows.registry import registry as default_registry


def _definition(name: WorkflowType = WorkflowType.NEWS_ANALYSIS, version: int = 1) -> WorkflowDefinition:
    return WorkflowDefinition(
        name=name,
        version=version,
        steps=[WorkflowStepDefinition(name="step_one", capability="research", timeout_seconds=10)],
        retry_policy=WorkflowRetryPolicy(max_attempts=1, retryable_error_types=["StepExecutionError"]),
        timeout_seconds=60,
        required_input=["event_id"],
        expected_output=["result"],
    )


def test_register_and_resolve() -> None:
    registry = WorkflowRegistry()
    definition = _definition()
    registry.register(definition)

    assert registry.resolve(WorkflowType.NEWS_ANALYSIS) is definition


def test_duplicate_registration_raises() -> None:
    registry = WorkflowRegistry()
    registry.register(_definition())

    with pytest.raises(DuplicateWorkflowRegistrationError):
        registry.register(_definition())


def test_unknown_type_raises() -> None:
    registry = WorkflowRegistry()

    with pytest.raises(UnknownWorkflowTypeError):
        registry.resolve(WorkflowType.NEWS_ANALYSIS)


def test_returned_definition_is_immutable() -> None:
    registry = WorkflowRegistry()
    registry.register(_definition())

    resolved = registry.resolve(WorkflowType.NEWS_ANALYSIS)
    with pytest.raises(Exception):  # pydantic raises on mutating a frozen model
        resolved.version = 2  # type: ignore[misc]


def test_daily_digest_is_not_registered_in_the_real_registry() -> None:
    """Phase 5 approval: DAILY_DIGEST must never be registered."""
    with pytest.raises(UnknownWorkflowTypeError):
        default_registry.resolve(WorkflowType.DAILY_DIGEST)


def test_news_analysis_and_content_generation_are_registered_in_the_real_registry() -> None:
    assert default_registry.resolve(WorkflowType.NEWS_ANALYSIS).name == WorkflowType.NEWS_ANALYSIS
    assert default_registry.resolve(WorkflowType.CONTENT_GENERATION).name == WorkflowType.CONTENT_GENERATION


def test_event_recap_is_registered_dormant_in_the_real_registry() -> None:
    """NINJA PULSE RECAP Phase R2 integration, Phase A: registered (like TELEGRAPH_RESEARCH/
    TELEGRAPH_ARTICLE), one step, capability="event_recap" - dormant, since nothing in this
    codebase creates an EVENT_RECAP task yet."""
    definition = default_registry.resolve(WorkflowType.EVENT_RECAP)
    assert definition.name == WorkflowType.EVENT_RECAP
    assert [step.capability for step in definition.steps] == ["event_recap"]


def test_registration_during_build_succeeds() -> None:
    registry = WorkflowRegistry()
    registry.register(_definition())  # not sealed yet - must succeed
    registry.seal()

    assert registry.resolve(WorkflowType.NEWS_ANALYSIS).name == WorkflowType.NEWS_ANALYSIS


def test_registration_after_sealing_raises() -> None:
    registry = WorkflowRegistry()
    registry.register(_definition())
    registry.seal()

    with pytest.raises(RegistryAlreadySealedError):
        registry.register(_definition(name=WorkflowType.CONTENT_GENERATION))


def test_resolution_after_sealing_still_works() -> None:
    registry = WorkflowRegistry()
    definition = _definition()
    registry.register(definition)
    registry.seal()

    assert registry.resolve(WorkflowType.NEWS_ANALYSIS) is definition


def test_the_real_registry_is_sealed() -> None:
    """workflows.registry.registry is built and sealed at import time."""
    with pytest.raises(RegistryAlreadySealedError):
        default_registry.register(_definition(name=WorkflowType.CONTENT_GENERATION))
