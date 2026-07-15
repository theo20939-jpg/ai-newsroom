"""NEWS_ANALYSIS WorkflowDefinition.

Maps to steps 4-7 of the docs/13_1 §11 pipeline (Research -> Intelligence ->
Engagement Analysis -> Scoring) for a single NewsEvent. Step capabilities are
placeholder identifiers only - see workflows.runner.StepExecutor for the
Phase 5 executor and docs/phase5_workflow_engine_planning.md for the full
rationale.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.NEWS_ANALYSIS,
    version=1,
    steps=[
        WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
        WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
        WorkflowStepDefinition(name="engagement_analysis", capability="engagement", timeout_seconds=30),
        WorkflowStepDefinition(name="scoring", capability="scoring", timeout_seconds=30),
    ],
    max_iterations=3,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=120,
    required_input=["event_id"],
    expected_output=["research_summary", "intelligence_report", "engagement_analysis", "score"],
)
