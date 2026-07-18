"""Static architecture-boundary validator (Phase 7 M0).

Mechanically checks a small, hand-curated subset of the forbidden-dependency
edges from docs/phase6_architecture_contract.md §1 and
docs/phase7_architecture_contract.md §1 by AST-scanning every module's
imports. This is deliberately NOT a general-purpose import-linter: the rule
table below is transcribed by hand from the two frozen contracts and MUST be
updated by hand (never auto-derived from the docs) whenever a new module is
added that a rule should apply to, or a future amendment changes a rule.

No third-party dependency is introduced - this is pure stdlib (ast, pathlib).

Usage:
    python scripts/validate_architecture.py [root]

Exit code 0 if no violation is found, 1 otherwise. Every violation is printed
as "path:line: message".
"""
from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Directories that are never scanned: virtual envs, caches, migrations
# (generated code), and the tests/docs trees themselves (rules apply to
# production source, not to test doubles or documentation).
EXCLUDED_DIR_NAMES = {
    ".venv", "venv", "__pycache__", ".git", ".mypy_cache", ".ruff_cache",
    "tests", "docs", "node_modules",
}

# Provider SDK module prefixes a provider adapter is allowed to import, and
# nothing else in the repo is (Phase 6 rule; Phase 7 P11 / §1 row 1).
PROVIDER_SDK_MODULE_PREFIXES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "ollama",
    "cohere",
    "mistralai",
)

# A file is a "provider adapter" file - the one place a provider SDK import
# is allowed - if its POSIX-style relative path matches this pattern.
_ADAPTER_PATH_SUFFIX_MARKER = ("integrations/llm_gateway/providers/", "_adapter.py")


def _is_provider_adapter_file(rel_posix: str) -> bool:
    prefix, suffix = _ADAPTER_PATH_SUFFIX_MARKER
    return rel_posix.startswith(prefix) and rel_posix.endswith(suffix)


@dataclass(frozen=True)
class Rule:
    """One forbidden-edge rule.

    `applies_to`: predicate over a POSIX-style path relative to the scan
    root; `forbidden_import_prefixes`: an import is a violation if its
    dotted module name starts with any of these prefixes; `description`:
    the contract section this rule encodes, shown in violation output.
    """

    name: str
    applies_to: Callable[[str], bool]
    forbidden_import_prefixes: tuple[str, ...]
    description: str


def _under(*prefixes: str) -> Callable[[str], bool]:
    def _predicate(rel_posix: str) -> bool:
        return any(rel_posix.startswith(p) for p in prefixes)
    return _predicate


def _under_excluding(prefix: str, *excluded_files: str) -> Callable[[str], bool]:
    def _predicate(rel_posix: str) -> bool:
        if not rel_posix.startswith(prefix):
            return False
        return rel_posix not in excluded_files
    return _predicate


def _is_gateway_composition_root(rel_posix: str) -> bool:
    # "The LLMGateway implementation boundary" (§1, §18) names the concrete composition-root
    # class (gateway.py) specifically - not every file under integrations/llm_gateway/, most
    # of which (FallbackPolicy, BudgetGuard's ledger reader, etc.) legitimately reference
    # shared exception types like capabilities.errors.BudgetExceededError per the contract's
    # own design (§5.4 step 2). Scoping this narrowly avoids a repeat of the same false-
    # positive class already fixed once for the capability-isolation rule (M0's log).
    return rel_posix == "integrations/llm_gateway/gateway.py"


# The hand-curated rule table. Each rule's `description` cites the exact
# section of the frozen contract it encodes.
RULES: tuple[Rule, ...] = (
    Rule(
        name="workflow-isolation",
        applies_to=_under("workflows/"),
        forbidden_import_prefixes=(
            "capabilities",
            "integrations.llm_gateway",
            "integrations.prompts",
            *PROVIDER_SDK_MODULE_PREFIXES,
        ),
        description="Phase 6 contract §14 rule 2 / P2: workflows/ must not import "
        "capabilities/, integrations.llm_gateway, integrations.prompts, or a provider SDK.",
    ),
    Rule(
        name="capability-isolation",
        # The four named infrastructure files (plus __init__.py) legitimately reference
        # BudgetGuard/LLMGateway/ToolRegistry/workflows types at the boundary (registry.py's
        # build_registry() signature, executor.py's DB session and workflows.errors mapping,
        # etc.) and are excluded from the rules below, which apply only to actual Capability
        # implementation files (Phase 8 contract §2).
        applies_to=_under_excluding(
            "capabilities/",
            "capabilities/registry.py",
            "capabilities/executor.py",
            "capabilities/errors.py",
            "capabilities/capability_mapping.py",
            "capabilities/__init__.py",
        ),
        forbidden_import_prefixes=(
            *PROVIDER_SDK_MODULE_PREFIXES,
            "database.session",
            "sqlalchemy",
            "services.budget_guard",
            "services.cost_tracker",
            "integrations.llm_gateway.cache",
            "integrations.llm_gateway.rate_limit",
            "integrations.llm_gateway.fallback",
            "integrations.llm_gateway.routing",
            "integrations.llm_gateway.providers",
            "workflows",
        ),
        description="Phase 6 contract §14 rule 1 / P3 / P8, extended by Phase 8 contract §2: a "
        "Capability implementation must not import a provider SDK, hold a database/ORM session "
        "(a plain model/enum reference from database.models is not itself a session and is not "
        "flagged - see capability_mapping.py), import BudgetGuard or CostTracker (Amendment C), "
        "import Phase 7's internal Gateway machinery (cache/rate_limit/fallback/routing/"
        "providers, invisible per P14), or import any workflows/ module.",
    ),
    Rule(
        name="prompt-repository-isolation",
        applies_to=_under("integrations/prompts/"),
        forbidden_import_prefixes=(
            *PROVIDER_SDK_MODULE_PREFIXES,
            "database.session",
            "sqlalchemy",
        ),
        description="Phase 6 contract §1: PromptRepository must not import a provider SDK "
        "or a database session.",
    ),
    Rule(
        name="provider-sdk-confinement",
        applies_to=lambda rel_posix: not _is_provider_adapter_file(rel_posix),
        forbidden_import_prefixes=PROVIDER_SDK_MODULE_PREFIXES,
        description="Phase 7 contract §1 row 1 / P11: no file outside "
        "integrations/llm_gateway/providers/<provider>_adapter.py may import a provider SDK.",
    ),
    Rule(
        name="gateway-boundary-no-upward-knowledge",
        applies_to=_is_gateway_composition_root,
        forbidden_import_prefixes=("capabilities.registry", "capabilities.executor", "workflows"),
        description="Phase 7 contract §1: the LLMGateway implementation boundary (the "
        "composition root, gateway.py) must not import capabilities/ or workflows/ business "
        "logic (no upward knowledge, Phase 6 P1 unchanged). capabilities.errors is exempted - "
        "see _is_gateway_composition_root's comment.",
    ),
    Rule(
        name="budget-guard-isolation",
        applies_to=_under("services/budget_guard.py"),
        forbidden_import_prefixes=(
            "integrations.llm_gateway.gateway",
            "integrations.llm_gateway.providers",
            *PROVIDER_SDK_MODULE_PREFIXES,
        ),
        description="Phase 7 contract §1: BudgetGuard must not import LLMGateway or "
        "ProviderAdapter (or a provider SDK directly).",
    ),
    Rule(
        name="cost-tracker-isolation",
        applies_to=_under("services/cost_tracker.py"),
        forbidden_import_prefixes=(
            "integrations.llm_gateway.gateway",
            "integrations.llm_gateway.providers",
            "services.budget_guard",
            *PROVIDER_SDK_MODULE_PREFIXES,
        ),
        description="Phase 7 contract §1: CostTracker must not import LLMGateway, "
        "ProviderAdapter, or BudgetGuard (one-directional; BudgetGuard reads CostTracker's "
        "ledger, never the reverse).",
    ),
    Rule(
        name="cost-estimator-isolation",
        applies_to=_under("services/cost_estimator.py"),
        forbidden_import_prefixes=("services.cost_tracker",),
        description="Phase 7 contract §1: CostEstimator must not import CostTracker "
        "(an estimator never reads actuals).",
    ),
    Rule(
        name="pricing-catalog-isolation",
        applies_to=_under("services/pricing_catalog.py"),
        forbidden_import_prefixes=(
            "services.cost_tracker",
            "services.budget_guard",
            "services.cost_estimator",
        ),
        description="Phase 7 contract §1 (mirrors §18's PricingCatalog row): PricingCatalog "
        "must not import CostTracker, BudgetGuard, or CostEstimator.",
    ),
    Rule(
        name="routing-policy-purity",
        applies_to=_under("integrations/llm_gateway/routing/policy.py"),
        forbidden_import_prefixes=(
            "services.budget_guard",
            "services.cost_tracker",
            "sqlalchemy",
            "redis",
            "httpx",
            "database",
        ),
        description="Phase 7 contract §1 / P17: RoutingPolicy performs no I/O and must not "
        "import BudgetGuard or CostTracker.",
    ),
    Rule(
        name="routing-engine-isolation",
        applies_to=_under("integrations/llm_gateway/routing/engine.py"),
        forbidden_import_prefixes=("services.budget_guard", "services.cost_tracker"),
        description="Phase 7 contract §1: RoutingEngine / RoutingPolicy must not import "
        "BudgetGuard or CostTracker.",
    ),
    Rule(
        name="fallback-policy-isolation",
        applies_to=_under("integrations/llm_gateway/fallback/policy.py"),
        # capabilities.errors is exempted: the contract itself specifies BudgetGuard.check()
        # raises capabilities.errors.BudgetExceededError, which FallbackPolicy MUST catch
        # (§5.4 step 2) - a shared exception-vocabulary import, not a dependency on Capability
        # business logic. capabilities.registry/executor/capability_mapping (the actual
        # Capability/CapabilityExecutor machinery) remain forbidden, matching services/
        # budget_guard.py's identical, already-established precedent (M12).
        forbidden_import_prefixes=(
            "capabilities.registry",
            "capabilities.executor",
            "capabilities.capability_mapping",
            "workflows",
            "services.cost_tracker",
        ),
        description="Phase 7 contract §1 (mirrors §18's FallbackPolicy row): FallbackPolicy "
        "must not import CostTracker (recording is post-hoc, performed by the Gateway after "
        "a successful dispatch, never by FallbackPolicy itself), Capability, or "
        "CapabilityExecutor. capabilities.errors is exempted - see comment above.",
    ),
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule_name: str
    imported: str
    description: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule_name}] imports '{self.imported}' - {self.description}"


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        yield path


def _imported_module_names(tree: ast.Module) -> list[tuple[str, int]]:
    """Return every (dotted module name, line number) this module imports."""
    names: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and node.level == 0:
                names.append((node.module, node.lineno))
    return names


def find_violations(root: Path, rules: Sequence[Rule] = RULES) -> list[Violation]:
    """Scan every .py file under `root` against `rules`, returning all violations found."""
    violations: list[Violation] = []
    for path in _iter_python_files(root):
        rel_posix = path.relative_to(root).as_posix()
        applicable_rules = [rule for rule in rules if rule.applies_to(rel_posix)]
        if not applicable_rules:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(
                Violation(path, exc.lineno or 0, "unparseable", "<syntax error>", str(exc))
            )
            continue
        imports = _imported_module_names(tree)
        for module_name, lineno in imports:
            for rule in applicable_rules:
                if any(
                    module_name == prefix or module_name.startswith(prefix + ".")
                    for prefix in rule.forbidden_import_prefixes
                ):
                    violations.append(
                        Violation(path, lineno, rule.name, module_name, rule.description)
                    )
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(argv[0]).resolve() if argv else Path(__file__).resolve().parent.parent
    violations = find_violations(root)
    if not violations:
        print(f"validate_architecture: clean - 0 forbidden-dependency violations under {root}")
        return 0
    print(f"validate_architecture: {len(violations)} forbidden-dependency violation(s) found:")
    for violation in violations:
        print(f"  {violation}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
