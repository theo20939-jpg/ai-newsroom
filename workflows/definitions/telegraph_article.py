"""TELEGRAPH_ARTICLE WorkflowDefinition (TELEGRAPH Checkpoint 5).

One step: "generate_article", capability="article_generation" - a genuinely new Capability (see
capabilities/article_generation_capability.py's own docstring), never CopywritingCapability.

Its own workflow type, not an extension of TELEGRAPH_RESEARCH - see schemas/workflow.py::
WorkflowType.TELEGRAPH_ARTICLE's own docstring for the full reasoning (a COMPLETED task can never
gain new steps in this engine) and for how services.workflow_service.create_task()'s own existing
one-task-per-(event_id, workflow_type) guard doubles as this workflow's exactly-once mechanism.

Longer timeouts than TELEGRAPH_RESEARCH - a full long-form article is a larger structured output
than deep-research evidence. Reasoned starting point, not fit to any real timing data yet.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.TELEGRAPH_ARTICLE,
    version=1,
    steps=[
        WorkflowStepDefinition(
            name="generate_article", capability="article_generation", max_attempts=3, timeout_seconds=120,
        ),
    ],
    max_iterations=1,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=240,
    required_input=["telegraph_topic_proposal_id"],
    expected_output=[
        "headline", "lead", "context", "timeline", "confirmed_facts", "analysis", "implications",
        "background", "risks", "conclusion", "sources",
    ],
)
