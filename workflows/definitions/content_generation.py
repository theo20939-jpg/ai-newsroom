"""CONTENT_GENERATION WorkflowDefinition.

Phase 10 M2: research -> intelligence -> copywriting -> quality, for an
already-analyzed NewsEvent/task (docs/
phase10_production_content_pipeline_architecture_contract.md §3). `research`/
`intelligence` are reused unmodified from Phase 9; `copywriting` is the one
new Phase 10 Capability; `quality` is amended (§5.1) to review `copywriting`'s
output. `timeout_seconds=120` reuses the same value `NEWS_ANALYSIS` already
declares for its own 4-step chain - not a newly proven number (§3).
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
        WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
        WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
        WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
        WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
    ],
    max_iterations=3,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=120,
    required_input=["event_id"],
    expected_output=["research_summary", "intelligence_report", "draft_content", "quality_report"],
)
