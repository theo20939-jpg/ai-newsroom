"""Typed exception hierarchy for the Workflow Engine (Phase 5).

No bare `except Exception` without logged context is used anywhere in
workflows/ or services/workflow_service.py - every failure mode raised by
this layer has a dedicated type here.

TaskNotFoundError sits outside both WorkflowServiceError and
WorkflowRunnerError because it is raised by both
services.workflow_service.get_task() and workflows.runner.WorkflowRunner.run()
- it is not specific to either module.
"""


class WorkflowConfigError(Exception):
    """Base class for errors in workflow definition/registration, not execution."""


class UnknownWorkflowTypeError(WorkflowConfigError):
    """Raised when WorkflowRegistry.resolve() is asked for an unregistered WorkflowType."""


class DuplicateWorkflowRegistrationError(WorkflowConfigError):
    """Raised when two WorkflowDefinitions share the same (name, version)."""


class TaskNotFoundError(Exception):
    """Raised when an EditorialTask id does not exist - shared by get_task() and run()."""


class WorkflowServiceError(Exception):
    """Base class for errors raised by services.workflow_service."""


class NewsEventNotFoundError(WorkflowServiceError):
    """Raised when create_task() is given an event_id with no matching NewsEvent."""


class DuplicateActiveTaskError(WorkflowServiceError):
    """Raised when an active (CREATED/RUNNING) task already exists for (event_id, workflow_type)."""


class WorkflowRunnerError(Exception):
    """Base class for errors raised by workflows.runner.WorkflowRunner."""


class TaskAlreadyRunningError(WorkflowRunnerError):
    """Raised when run() is called on a task whose status is already RUNNING."""


class TaskAlreadyCompletedError(WorkflowRunnerError):
    """Raised when run() is called on a task whose status is already COMPLETED or FAILED."""


class MaxIterationsExceededError(WorkflowRunnerError):
    """Raised when a task would need another full pass beyond WorkflowDefinition.max_iterations."""


class StepTimeoutError(WorkflowRunnerError):
    """Raised when a single step exceeds WorkflowStepDefinition.timeout_seconds."""


class StepExecutionError(WorkflowRunnerError):
    """A retryable step failure - eligible for retry up to the step's max_attempts."""


class PermanentStepFailureError(WorkflowRunnerError):
    """A non-retryable step failure - fails the task immediately, no retry attempted."""
