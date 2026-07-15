"""Tests for workflows.registry.WorkflowRegistry. Pure unit tests, no database."""
import pytest

from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from workflows.errors import DuplicateWorkflowRegistrationError, UnknownWorkflowTypeError
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
