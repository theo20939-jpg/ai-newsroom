"""CONTENT_GENERATION WorkflowDefinition.

Maps to steps 9-10 of the docs/13_1 §11 pipeline (Copywriting -> Quality) for
an already-analyzed NewsEvent/task. Step capabilities are placeholder
identifiers only - see workflows.runner.StepExecutor for the Phase 5
executor and docs/phase5_workflow_engine_planning.md for the full rationale.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.CONTENT_GENERATION,
    version=1,
    steps=[
        WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
        WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
    ],
    max_iterations=3,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=60,
    required_input=["event_id"],
    expected_output=["draft_content", "quality_report"],
)
