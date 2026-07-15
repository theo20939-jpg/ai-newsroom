"""Workflow Engine (Phase 5): deterministic task-lifecycle infrastructure.

Registers typed WorkflowDefinitions (workflows.registry.WorkflowRegistry),
runs them against EditorialTask rows (workflows.runner.WorkflowRunner) via a
placeholder, non-AI StepExecutor. Contains no AI logic and no Capability
implementation - see docs/phase5_workflow_engine_planning.md.
"""
