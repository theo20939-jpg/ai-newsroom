"""Tests for scripts.validate_architecture. Pure unit tests against synthetic
module trees under tmp_path - never against files that might be mid-edit in
the real repo (that's what running the script directly against the repo root
is for, as a separate runtime-validation step)."""
from pathlib import Path

from scripts.validate_architecture import RULES, Rule, find_violations


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


def _capability_isolation_rule() -> Rule:
    return next(rule for rule in RULES if rule.name == "capability-isolation")


def test_capability_isolation_exclusion_list_is_exactly_the_named_infra_files() -> None:
    """Phase 8 contract §2 / M0: the exclusion set is exactly these five files - a future
    accidental narrowing or widening of the exemption must be caught here, not discovered later."""
    rule = _capability_isolation_rule()
    exempt_files = {
        "capabilities/registry.py",
        "capabilities/executor.py",
        "capabilities/errors.py",
        "capabilities/capability_mapping.py",
        "capabilities/__init__.py",
    }

    for path in exempt_files:
        assert rule.applies_to(path) is False, f"{path} should be exempt"

    assert rule.applies_to("capabilities/some_capability.py") is True
    assert rule.applies_to("capabilities/another_capability.py") is True


def test_capability_importing_budget_guard_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from services.budget_guard import BudgetGuard\n")

    violations = find_violations(tmp_path)

    assert any(
        v.rule_name == "capability-isolation" and v.imported == "services.budget_guard"
        for v in violations
    )


def test_capability_importing_cost_tracker_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from services.cost_tracker import RedisCostTracker\n")

    violations = find_violations(tmp_path)

    assert any(
        v.rule_name == "capability-isolation" and v.imported == "services.cost_tracker"
        for v in violations
    )


def test_capability_importing_gateway_cache_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from integrations.llm_gateway.cache import store\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "capability-isolation" for v in violations)


def test_capability_importing_gateway_rate_limit_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from integrations.llm_gateway.rate_limit import limiter\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "capability-isolation" for v in violations)


def test_capability_importing_gateway_fallback_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from integrations.llm_gateway.fallback import policy\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "capability-isolation" for v in violations)


def test_capability_importing_gateway_routing_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from integrations.llm_gateway.routing import engine\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "capability-isolation" for v in violations)


def test_capability_importing_gateway_providers_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "capabilities/some_capability.py",
        "import integrations.llm_gateway.providers.base\n",
    )

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "capability-isolation" for v in violations)


def test_capability_importing_workflows_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/some_capability.py", "from workflows.errors import TaskNotFoundError\n")

    violations = find_violations(tmp_path)

    assert any(
        v.rule_name == "capability-isolation" and v.imported == "workflows.errors"
        for v in violations
    )


def test_registry_is_exempt_from_new_capability_rules(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/registry.py", "from services.budget_guard import BudgetGuard\n")

    assert find_violations(tmp_path) == []


def test_errors_module_is_exempt_from_new_capability_rules(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/errors.py", "from workflows.errors import TaskNotFoundError\n")

    assert find_violations(tmp_path) == []


def test_capability_mapping_is_exempt_from_new_capability_rules(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/capability_mapping.py", "from services.cost_tracker import RedisCostTracker\n")

    assert find_violations(tmp_path) == []


def test_init_is_exempt_from_new_capability_rules(tmp_path: Path) -> None:
    _write(tmp_path, "capabilities/__init__.py", "from integrations.llm_gateway.fallback import policy\n")

    assert find_violations(tmp_path) == []


def test_clean_phase9_tree_has_no_violations(tmp_path: Path) -> None:
    _write(tmp_path, "services/freshness.py", "from datetime import datetime\n")
    _write(
        tmp_path,
        "services/triage.py",
        "from services.freshness import compute_freshness\n"
        "from database.models.editorial_task import TaskPriority\n",
    )
    _write(
        tmp_path,
        "services/triage_orchestrator.py",
        "from services.workflow_service import create_task\n"
        "from schemas.workflow import WorkflowType\n"
        "import sqlalchemy\n",
    )

    assert find_violations(tmp_path) == []


def test_freshness_importing_sqlalchemy_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/freshness.py", "import sqlalchemy\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "freshness-purity" and v.imported == "sqlalchemy" for v in violations)


def test_freshness_importing_another_services_module_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/freshness.py", "from services.collector import run_collection_cycle\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "freshness-purity" for v in violations)


def test_freshness_importing_llm_gateway_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/freshness.py", "import integrations.llm_gateway.gateway\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "freshness-purity" for v in violations)


def test_triage_importing_llm_gateway_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/triage.py", "import integrations.llm_gateway.gateway\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "triage-purity" for v in violations)


def test_triage_importing_capability_registry_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/triage.py", "from capabilities.registry import CapabilityRegistry\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "triage-purity" for v in violations)


def test_triage_importing_workflows_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/triage.py", "from workflows.runner import WorkflowRunner\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "triage-purity" for v in violations)


def test_triage_importing_freshness_and_task_priority_is_allowed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "services/triage.py",
        "from services.freshness import compute_freshness\n"
        "from database.models.editorial_task import TaskPriority\n",
    )

    assert find_violations(tmp_path) == []


def test_triage_orchestrator_importing_llm_gateway_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/triage_orchestrator.py", "import integrations.llm_gateway.gateway\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "triage-orchestrator-isolation" for v in violations)


def test_triage_orchestrator_importing_capabilities_registry_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/triage_orchestrator.py", "from capabilities.registry import CapabilityRegistry\n")

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "triage-orchestrator-isolation" for v in violations)


def test_triage_orchestrator_importing_research_capability_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "services/triage_orchestrator.py",
        "from capabilities.research_capability import ResearchCapability\n",
    )

    violations = find_violations(tmp_path)

    assert any(v.rule_name == "triage-orchestrator-isolation" for v in violations)


def test_triage_orchestrator_importing_provider_sdk_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "services/triage_orchestrator.py", "import openai\n")

    violations = find_violations(tmp_path)

    rule_names = {v.rule_name for v in violations}
    assert "triage-orchestrator-isolation" in rule_names
    assert "provider-sdk-confinement" in rule_names


def test_triage_orchestrator_importing_workflow_service_and_workflow_type_is_allowed(tmp_path: Path) -> None:
    """The Contract explicitly requires both imports (§7.2 step 3) - this is the one case most
    likely to be gotten wrong by copy-pasting an existing isolation rule too literally."""
    _write(
        tmp_path,
        "services/triage_orchestrator.py",
        "from services.workflow_service import create_task\n"
        "from schemas.workflow import WorkflowType\n"
        "import sqlalchemy\n"
        "from sqlalchemy import update\n"
        "from database.models.news_event import NewsEvent, EventStatus\n",
    )

    assert find_violations(tmp_path) == []


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
