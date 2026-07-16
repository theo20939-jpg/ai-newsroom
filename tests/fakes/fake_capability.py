"""Deterministic fake Capability implementations - no LLMGateway, no network.

Used to drive capabilities.executor.CapabilityExecutor as a StepExecutor and
to exercise the full CapabilityError -> workflows.errors mapping table.
"""
from datetime import datetime, timezone
from uuid import uuid4

from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityTimeoutError,
    PermanentCapabilityError,
    RetryableCapabilityError,
    ValidationCapabilityError,
)
from schemas.capability import CapabilityCall, CapabilityContext, CapabilityResult, CapabilityUsage


class AlwaysSucceedsCapability:
    """Deterministic success with zero AI calls - proves `calls: []` is valid."""

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"ok": True, "capability": context.runtime.capability_name},
            confidence=90,
            calls=[],
            started_at=now,
            finished_at=now,
            duration_seconds=0.0,
        )


class AlwaysSucceedsWithOneCallCapability:
    """Deterministic success with exactly one CapabilityCall - used to exercise
    AIExecutionMapper against a realistic result, without ever persisting it."""

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(timezone.utc)
        call = CapabilityCall(
            call_id=uuid4(),
            sequence=0,
            gateway_method="generate",
            status="SUCCESS",
            model_used="fake-model-v1",
            provider="fake-provider",
            prompt_name="fake-prompt",
            prompt_version="1",
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
            started_at=now,
            finished_at=now,
            duration_seconds=0.01,
        )
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"ok": True},
            confidence=95,
            calls=[call],
            started_at=now,
            finished_at=now,
            duration_seconds=0.01,
        )


class AlwaysFailsRetryablyCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        raise RetryableCapabilityError("transient failure")


class AlwaysFailsPermanentlyCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        raise PermanentCapabilityError("cannot be retried")


class AlwaysFailsValidationCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        raise ValidationCapabilityError("output failed schema validation")


class AlwaysFailsConfigurationCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        raise CapabilityConfigurationError("bad config")


class AlwaysTimesOutCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        raise CapabilityTimeoutError("capability-internal timeout")


class FailsThenSucceedsCapability:
    """Fails retryably N times, then succeeds - mirrors tests/test_workflow_runner.py's pattern."""

    def __init__(self, failures_before_success: int) -> None:
        self._remaining_failures = failures_before_success

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RetryableCapabilityError(f"transient failure ({self._remaining_failures} left)")
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output={"ok": True},
            calls=[],
            started_at=now,
            finished_at=now,
            duration_seconds=0.0,
        )
