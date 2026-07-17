"""Tests for scripts.validate_architecture. Pure unit tests against synthetic
module trees under tmp_path - never against files that might be mid-edit in
the real repo (that's what running the script directly against the repo root
is for, as a separate runtime-validation step)."""
from pathlib import Path

from scripts.validate_architecture import Rule, find_violations


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    _write(tmp_path, "workflows/runner.py", "import asyncio\nfrom typing import Any\n")
    _write(tmp_path, "capabilities/registry.py", "from typing import Protocol\n")

    assert find_violations(tmp_path) == []


def test_workflow_importing_capabilities_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "workflows/runner.py", "from capabilities.registry import CapabilityRegistry\n")

    violations = find_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].rule_name == "workflow-isolation"
    assert violations[0].imported == "capabilities.registry"


def test_workflow_importing_llm_gateway_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "workflows/runner.py", "import integrations.llm_gateway.gateway\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "workflow-isolation" for v in violations)


def test_provider_sdk_outside_adapter_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "import openai\n")

    violations = find_violations(tmp_path)

    rule_names = {v.rule_name for v in violations}
    assert "provider-sdk-confinement" in rule_names
    assert "capability-isolation" in rule_names


def test_provider_sdk_inside_named_adapter_file_is_allowed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "integrations/llm_gateway/providers/openai_adapter.py",
        "import openai\n",
    )

    assert find_violations(tmp_path) == []


def test_capability_executor_is_exempt_from_database_rule(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/executor.py", "from sqlalchemy.ext.asyncio import AsyncSession\n")

    assert find_violations(tmp_path) == []


def test_other_capability_file_importing_database_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "import sqlalchemy\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "capability-isolation" and v.imported == "sqlalchemy" for v in violations)


def test_gateway_boundary_importing_capabilities_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "integrations/llm_gateway/gateway.py", "from capabilities.registry import registry\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "gateway-boundary-no-upward-knowledge" for v in violations)


def test_budget_guard_importing_gateway_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/budget_guard.py", "from integrations.llm_gateway.gateway import RoutingGateway\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "budget-guard-isolation" for v in violations)


def test_cost_estimator_importing_cost_tracker_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/cost_estimator.py", "from services.cost_tracker import RedisCostTracker\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "cost-estimator-isolation" for v in violations)


def test_routing_policy_importing_redis_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "integrations/llm_gateway/routing/policy.py", "import redis\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "routing-policy-purity" for v in violations)


def test_fallback_policy_importing_capabilities_errors_is_allowed(tmp_path: Path) -> None:
    """capabilities.errors is a shared exception-vocabulary module, not Capability business
    logic - FallbackPolicy MUST be able to catch BudgetExceededError from it (§5.4 step 2)."""
    _write(
        tmp_path,
        "integrations/llm_gateway/fallback/policy.py",
        "from capabilities.errors import BudgetExceededError\n",
    )

    assert find_violations(tmp_path) == []


def test_fallback_policy_importing_capabilities_registry_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "integrations/llm_gateway/fallback/policy.py",
        "from capabilities.registry import CapabilityRegistry\n",
    )

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "fallback-policy-isolation" for v in violations)


def test_non_python_and_excluded_dirs_are_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_something.py", "import openai\n")
    _write(tmp_path, "docs/example.py", "import openai\n")

    assert find_violations(tmp_path) == []


def test_syntax_error_is_reported_not_raised(tmp_path: Path) -> None:
    _write(tmp_path, "workflows/broken.py", "def broken(:\n")

    violations = find_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].rule_name == "unparseable"


def test_custom_rule_set_can_be_passed_explicitly(tmp_path: Path) -> None:
    _write(tmp_path, "any_module.py", "import banned_thing\n")

    custom_rule = Rule(
        name="custom",
        applies_to=lambda rel_posix: rel_posix == "any_module.py",
        forbidden_import_prefixes=("banned_thing",),
        description="test-only custom rule",
    )

    violations = find_violations(tmp_path, rules=(custom_rule,))

    assert len(violations) == 1
    assert violations[0].rule_name == "custom"
