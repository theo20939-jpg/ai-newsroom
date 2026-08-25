"""FINAL_POST_AUTHORING WorkflowDefinition (Phase I.1: Approved EVENT_RECAP -> Final Post
Authoring Core).

One step: "final_post_authoring", capability="final_post_authoring" - a genuinely new Capability
(see capabilities/final_post_authoring_capability.py's own docstring), never CopywritingCapability/
EventRecapCapability, mirroring TELEGRAPH_ARTICLE's own "article_generation" precedent exactly.

Its own workflow type, anchored to the SAME `event_id` as its source EVENT_RECAP task - see
schemas/workflow.py::WorkflowType.FINAL_POST_AUTHORING's own docstring for the full reasoning and
for how services.workflow_service.create_task()'s own existing one-task-per-(event_id,
workflow_type) guard doubles as this workflow's exactly-once mechanism per anchor.

Phase I.1 only: registered (workflows/registry.py) but nothing in this codebase creates a
FINAL_POST_AUTHORING task automatically - dormant, exactly like EVENT_RECAP/TELEGRAPH_ARTICLE were
when first registered. Only services/final_post_processor.py::generate_final_post_for_review(),
itself only ever invoked manually via scripts/final_post_authoring_worker.py, creates one.

Timeout/retry values mirror EVENT_RECAP's own identical shape (one structured-output authoring
call) - not fit to any real timing data yet.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.FINAL_POST_AUTHORING,
    version=1,
    steps=[
        WorkflowStepDefinition(
            name="final_post_authoring", capability="final_post_authoring", max_attempts=3, timeout_seconds=120,
        ),
    ],
    max_iterations=1,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=240,
    required_input=["event_id"],
    expected_output=["title", "body"],
)
