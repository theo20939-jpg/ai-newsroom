"""MEME_GENERATION WorkflowDefinition (Phase 18).

Not yet registered in `workflows/registry.py::WorkflowRegistry` (docs/
phase18_m0_meme_discovery_report.md §4.3) - mirrors `WorkflowType.DAILY_DIGEST`'s own
declared-but-unregistered precedent. Registration is deferred until enough steps exist for a
coherent end-to-end run; this module is extended step-by-step as each milestone lands
(M2: research -> intelligence -> meme_concept only, so far).

`research`/`intelligence` reuse the exact same Capabilities CONTENT_GENERATION already uses
(`capabilities/executor.py::_try_reuse` now also recognizes MEME_GENERATION as eligible to reuse
a source NEWS_ANALYSIS task's own persisted results - docs/phase18_m2_meme_concept_report.md) -
never a meme-specific reimplementation of research/intelligence.
"""
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)

DEFINITION = WorkflowDefinition(
    name=WorkflowType.MEME_GENERATION,
    version=1,
    steps=[
        WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
        WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
        WorkflowStepDefinition(name="meme_concept", capability="meme_concept", timeout_seconds=30),
    ],
    max_iterations=3,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=120,
    required_input=["event_id"],
    expected_output=["research_summary", "intelligence_report", "meme_concept"],
)
