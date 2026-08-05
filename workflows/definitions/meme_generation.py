"""MEME_GENERATION WorkflowDefinition (Phase 18).

Registered in `workflows/registry.py::WorkflowRegistry` as of M4 (docs/
phase18_m4_meme_copywriting_report.md) - research -> intelligence -> meme_concept ->
meme_copywriting is a coherent, independently-useful chain (a full text-only meme package: a
safety/originality-assessed concept plus its final copy, ready for a first pass of human review
even before an image exists). Registering the workflow only makes `WorkflowRunner.run()` able to
execute it if some caller explicitly creates a MEME_GENERATION `EditorialTask` - no such caller
exists yet (no script/worker creates one automatically), so this remains inert in production.
Image generation (M5), rendering (M6), and the quality gate (M7) each extend this same
`WorkflowStepDefinition` list when they land - `version` will bump only if an already-registered
step's own contract changes, per `docs/phase6_architecture_contract.md`'s versioning discipline;
purely appending new steps to the end does not require a version bump (mirrors how Phase 10 M2
introduced CONTENT_GENERATION at version 1 with its full step list already known).

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
        WorkflowStepDefinition(name="meme_copywriting", capability="meme_copywriting", timeout_seconds=30),
    ],
    max_iterations=3,
    retry_policy=WorkflowRetryPolicy(
        max_attempts=3,
        retry_delay_seconds=0,
        retryable_error_types=["StepExecutionError"],
    ),
    timeout_seconds=120,
    required_input=["event_id"],
    expected_output=["research_summary", "intelligence_report", "meme_concept", "meme_copy"],
)
