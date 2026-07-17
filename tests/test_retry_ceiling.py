"""Tests for integrations.llm_gateway.boot.validate_retry_ceiling
(docs/phase7_architecture_contract.md §6 rule 4). Pure unit tests, no I/O - pure arithmetic."""
import pytest

from integrations.llm_gateway.boot import validate_retry_ceiling
from integrations.llm_gateway.errors import RetryCeilingExceededError


def test_product_under_the_default_ceiling_does_not_raise() -> None:
    # 3 x 3 x (1 + 1) = 18 <= 30
    validate_retry_ceiling(workflow_retry_max_attempts=3, max_fallback_attempts=3, max_same_candidate_retries=1)


def test_product_exactly_at_the_default_ceiling_does_not_raise() -> None:
    # 3 x 5 x (1 + 1) = 30 <= 30 (not > 30)
    validate_retry_ceiling(workflow_retry_max_attempts=3, max_fallback_attempts=5, max_same_candidate_retries=1)


def test_product_over_the_default_ceiling_raises() -> None:
    # 5 x 5 x (1 + 2) = 75 > 30
    with pytest.raises(RetryCeilingExceededError):
        validate_retry_ceiling(workflow_retry_max_attempts=5, max_fallback_attempts=5, max_same_candidate_retries=2)


def test_custom_ceiling_is_honored() -> None:
    # 2 x 2 x (1 + 1) = 8 > 5 (a custom, lower ceiling)
    with pytest.raises(RetryCeilingExceededError):
        validate_retry_ceiling(
            workflow_retry_max_attempts=2, max_fallback_attempts=2, max_same_candidate_retries=1, ceiling=5
        )


def test_error_message_includes_capability_name_when_given() -> None:
    with pytest.raises(RetryCeilingExceededError, match="research"):
        validate_retry_ceiling(
            workflow_retry_max_attempts=10,
            max_fallback_attempts=10,
            max_same_candidate_retries=5,
            capability_name="research",
        )


def test_error_message_names_the_computed_product_and_ceiling() -> None:
    with pytest.raises(RetryCeilingExceededError, match=r"75.*30"):
        validate_retry_ceiling(workflow_retry_max_attempts=5, max_fallback_attempts=5, max_same_candidate_retries=2)
