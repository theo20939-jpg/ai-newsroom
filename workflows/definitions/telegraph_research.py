"""TELEGRAPH_RESEARCH WorkflowDefinition (TELEGRAPH Checkpoint 3).

One step only: "deep_research", reusing the existing, registered "research" Capability
(capabilities/research_capability.py) unmodified in its own registration/class - see that
module's own Checkpoint 3 addendum for how it distinguishes a normal NEWS/CONTENT_GENERATION
call from a TELEGRAPH deep-research call (presence of `context.business.
telegraph_research_bundle_text`, never a new capability class or CapabilityRegistry entry).

Deliberately its own workflow type, not TELEGRAPH_ARTICLE - see schemas/workflow.py::
WorkflowType.TELEGRAPH_RESEARCH's own docstring for why growing a single shared workflow across
future checkpoints (Visual Research, Copywriting, publishing) is not actually supported by this
engine (a COMPLETED task can never be resumed with newly-added steps).

`timeout_seconds`/step `timeout_seconds` are longer than NEWS_ANALYSIS's own 30s/120s - deep
research reads a materially larger bundle and is expected to produce a materially larger
structured output (see capabilities/executor.py's own TELEGRAPH-specific max_tokens override).
Reasoned starting points, not fit to any real timing data yet - matches this codebase's own
established "reasoned default, refine later" convention.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.TELEGRAPH_RESEARCH,
    version=1,
    steps=[
        WorkflowStepDefinition(
            name="deep_research", capability="research", max_attempts=3, timeout_seconds=90,
        ),
    ],
    max_iterations=1,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=180,
    required_input=["telegraph_topic_proposal_id"],
    expected_output=[
        "thesis", "confirmed_facts", "timeline", "source_evidence", "primary_sources",
        "context_background", "implications", "competing_views", "gaps", "risky_claims",
        "suggested_article_angles", "confidence",
    ],
)
