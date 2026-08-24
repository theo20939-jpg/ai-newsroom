"""EVENT_RECAP WorkflowDefinition (NINJA PULSE RECAP Phase R2 integration, Phase A).

One step: "synthesize_recap", capability="event_recap" - a genuinely new Capability (see
capabilities/event_recap_capability.py's own docstring), never CopywritingCapability, mirroring
TELEGRAPH_ARTICLE's own "article_generation" precedent exactly.

Its own workflow type, anchored to `story.first_event_id` (== services.event_recap.
EventRecapCandidate.anchor_event_id) - see schemas/workflow.py::WorkflowType.EVENT_RECAP's own
docstring for the full reasoning and for how services.workflow_service.create_task()'s own
existing one-task-per-(event_id, workflow_type) guard doubles as this workflow's exactly-once
mechanism.

Phase A only: this definition is registered (workflows/registry.py) but nothing in this codebase
creates an EVENT_RECAP task yet - dormant, exactly like TELEGRAPH_RESEARCH/TELEGRAPH_ARTICLE were
when first registered. No scheduler, no Telegram delivery, no new DB model - see
capabilities/event_recap_capability.py's own docstring for what Phase A's capability actually does.

Timeout/retry values are reasoned starting points mirroring TELEGRAPH_ARTICLE's own identical
shape (one structured-output synthesis call) - not fit to any real timing data yet.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.EVENT_RECAP,
    version=1,
    steps=[
        WorkflowStepDefinition(
            name="synthesize_recap", capability="event_recap", max_attempts=3, timeout_seconds=120,
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
    expected_output=["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
)
