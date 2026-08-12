"""Phase 20 M10: mechanically enforces that Story Memory V2 (services/story_delta_engine.py,
services/story_confidence.py, services/story_suppression.py) stays out of every LLM-call-adjacent
live path (`capabilities/executor.py`, `worker/content_cycle.py`,
`capabilities/copywriting_capability.py`) and never depends on its own unmigrated shadow columns
(`database/models/story_link.py` still does not declare them - `NewsEventStoryLink` stays a plain,
already-migrated table). Mirrors tests/test_media_vision_review_isolation.py's own ast-based
"prove it, don't just assert it in prose" technique.

Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md) narrowed, not removed, the
isolation this file enforces: `services/triage_orchestrator.py` (LOGGING-only diagnostics, never
persisted, never gating `create_task()`) and `services/story_duplicate_guard.py` (re-derives V2
classifications on the fly at delivery time from already-persisted V1 state - never reads the
unmigrated shadow columns either) are now real, intentional, narrowly-scoped importers - the two
tests below were updated accordingly, not deleted, when that decision was made. Every other
constraint in this file (no LLM-call-adjacent module, no shadow-column dependency) is unchanged and
still independently enforced.
"""
from __future__ import annotations

import ast
from pathlib import Path

_V2_MODULES = ("story_delta_engine", "story_suppression", "story_confidence")
_V2_IDENTIFIERS = ("delta_classification", "confidence_band", "would_suppress")


def _imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_capabilities_executor_never_imports_v2_modules() -> None:
    """capabilities/executor.py is the only place a live WorkflowRunner step could reach these
    modules' outputs automatically - it must never import any of the three."""
    imports = _imports_in(Path("capabilities/executor.py"))
    for module_name in _V2_MODULES:
        assert not any(module_name in module for module in imports), module_name


def test_worker_content_cycle_never_imports_v2_modules() -> None:
    imports = _imports_in(Path("worker/content_cycle.py"))
    for module_name in _V2_MODULES:
        assert not any(module_name in module for module in imports), module_name


def test_copywriting_capability_never_imports_v2_modules() -> None:
    """The V6 seam (BusinessContext.prior_coverage_context) is populated only by the offline
    harness/tests this phase (services/story_context_serializer.py::serialize_delta_engine_context)
    - capabilities/copywriting_capability.py itself must stay unaware these modules exist."""
    imports = _imports_in(Path("capabilities/copywriting_capability.py"))
    for module_name in _V2_MODULES:
        assert not any(module_name in module for module in imports), module_name


def test_triage_orchestrator_imports_v2_modules_for_logging_diagnostics_only() -> None:
    """Phase 23.1P: services/triage_orchestrator.py now DOES import all three V2 modules -
    intentionally, to log delta_classification/confidence_band/would_suppress diagnostics for
    every confident Story Memory match (Part A4's "every candidate must produce observable
    diagnostics" requirement). This is the opposite assertion from the pre-23.1P version of this
    test, which asserted zero V2 imports at all - superseded, not merely loosened, by that
    phase's own explicit decision to wire V2 in for real. What still holds, checked below: this
    stays LOGGING-only, never a `create_task()` gate, and never depends on the unmigrated V2
    shadow columns (test_migration_3c22be05f4e5_is_not_the_alembic_current_head_applied_marker,
    unchanged)."""
    imports = _imports_in(Path("services/triage_orchestrator.py"))
    for module_name in _V2_MODULES:
        assert any(module_name in module for module in imports), (
            f"expected services/triage_orchestrator.py to import {module_name} (Phase 23.1P diagnostics)"
        )
    source = Path("services/triage_orchestrator.py").read_text(encoding="utf-8")
    assert "logger.info(\n        \"phase23_1p_story_memory_v2_diagnostics\"" in source or \
        "phase23_1p_story_memory_v2_diagnostics" in source, (
        "V2 outputs must be logged for observability, not silently computed"
    )


def test_no_live_source_file_references_the_new_column_identifiers_by_name() -> None:
    """A stronger check than import-scanning alone: even a hypothetical direct-string reference
    to one of the three new (unmigrated) column names anywhere in a live worker/capability/service
    module - independent of how it got there - would be a live-wiring red flag worth catching."""
    live_prefixes = ("worker/", "capabilities/")
    offenders: list[str] = []
    for path in Path(".").rglob("*.py"):
        relative = path.as_posix()
        if "__pycache__" in relative or not relative.startswith(live_prefixes):
            continue
        source = path.read_text(encoding="utf-8")
        if any(identifier in source for identifier in _V2_IDENTIFIERS):
            offenders.append(relative)
    assert offenders == [], f"Unexpected live reference to Story Memory V2 shadow columns: {offenders}"


def test_only_expected_files_import_the_v2_modules() -> None:
    """Repo-wide sweep: every .py file importing story_delta_engine / story_suppression /
    story_confidence must be one of the V2 modules themselves, the shared story_context_serializer
    seam (M9), a test file, the M11 replay script, or - as of Phase 23.1P (docs/
    phase23_1p_story_memory_quotes_gate_report.md) - `services/triage_orchestrator.py` (logging
    diagnostics only) / `services/story_duplicate_guard.py` (delivery-time re-derivation, see that
    module's own docstring for why this is still zero dependency on the unmigrated shadow
    columns). Still never a worker, capability, or any other scripts/ automation entry point -
    `capabilities/executor.py`, `worker/content_cycle.py`, and `capabilities/
    copywriting_capability.py` remain unlisted here deliberately (see the three `test_*_never_
    imports_v2_modules` tests above, all still enforced, all still passing)."""
    allowed_prefixes = (
        "services/story_delta_engine.py", "services/story_suppression.py", "services/story_confidence.py",
        "services/story_context_serializer.py", "services/triage_orchestrator.py",
        "services/story_duplicate_guard.py", "tests/", "scripts/phase20_story_memory_replay.py",
    )
    offenders: list[str] = []
    for path in Path(".").rglob("*.py"):
        relative = path.as_posix()
        if "__pycache__" in relative:
            continue
        if any(relative.startswith(prefix) for prefix in allowed_prefixes):
            continue
        imports = _imports_in(path)
        for module_name in _V2_MODULES:
            if any(module_name in module for module in imports):
                offenders.append(f"{relative} imports {module_name}")
    assert offenders == [], f"Unexpected importer(s) of Story Memory V2 modules: {offenders}"


def test_migration_3c22be05f4e5_is_not_the_alembic_current_head_applied_marker() -> None:
    """Sanity check on the shadow-neutrality claim itself: the ORM model (database/models/
    story_link.py) must NOT yet declare the three new columns - see that file's own Phase 20 M10
    docstring for why (SQLAlchemy includes every mapped column in every INSERT regardless of
    whether it was explicitly set, so declaring them before the migration is applied would break
    every real NewsEventStoryLink insert - verified empirically during M10)."""
    source = Path("database/models/story_link.py").read_text(encoding="utf-8")
    for identifier in _V2_IDENTIFIERS:
        assert f"{identifier}: Mapped" not in source, identifier
