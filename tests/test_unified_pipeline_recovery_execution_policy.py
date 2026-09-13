"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S24) - the recovery execution policy must be
real, explicit, and honestly disclosed - never implied ambiguously."""
from services.editorial_pipeline.recovery_execution_policy import (
    RECOVERY_HAS_AUTOMATIC_CONSUMER,
    RECOVERY_HAS_EXECUTION_POLICY,
    recovery_execution_policy_summary,
)


def test_policy_is_explicitly_defined() -> None:
    assert RECOVERY_HAS_EXECUTION_POLICY is True


def test_no_automatic_consumer_is_falsely_implied() -> None:
    """Option B was chosen deliberately this phase (see module docstring for the concrete,
    disclosed reason) - this must never silently flip to True without a real, tested consumer."""
    assert RECOVERY_HAS_AUTOMATIC_CONSUMER is False


def test_summary_is_a_real_structured_disclosure_not_a_placeholder() -> None:
    summary = recovery_execution_policy_summary()
    assert summary["recovery_has_execution_policy"] is True
    assert summary["automatic_consumer_exists"] is False
    assert summary["option"] == "B"
    assert len(str(summary["reason"])) > 20
