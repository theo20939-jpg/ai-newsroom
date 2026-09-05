"""Phase 19 M13: mechanically enforces that MediaVisionReviewCapability's real, LLM-backed
execute() is never reachable from an automatic/scheduled worker path - mirrors tests/
test_source_intelligence_isolation.py's own ast-based "prove it, don't just assert it in prose"
technique.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_capabilities_executor_never_imports_media_vision_review_capability() -> None:
    """capabilities/executor.py is the only place a live WorkflowRunner step could reach a
    Capability's real execute() automatically - it must never import this one at all, since no
    shadow hook for it exists (media_vision_review_mode's own "shadow" value is currently a no-op
    - see core/config.py's own comment)."""
    imports = _imports_in(Path("capabilities/executor.py"))
    assert not any("media_vision_review" in module for module in imports)


def test_worker_content_cycle_never_imports_media_vision_review() -> None:
    imports = _imports_in(Path("worker/content_cycle.py"))
    assert not any("media_vision_review" in module for module in imports)


def test_media_vision_review_diagnostics_script_never_imports_the_capability() -> None:
    """MEDIA-PROD-1: scripts/media_vision_review_diagnostics.py is a read-only report over already-
    persisted rows - it must never import the capability module itself (that would mean it could
    trigger a real LLM call, not just read), keeping the "manual harness only" fence intact."""
    imports = _imports_in(Path("scripts/media_vision_review_diagnostics.py"))
    assert not any("media_vision_review_capability" in module for module in imports)


def test_only_the_manual_harness_script_and_its_own_tests_import_the_capability() -> None:
    """A repo-wide sweep: every .py file that imports capabilities.media_vision_review_capability
    (module path, not the registry.py registration line - registering a Capability is required
    architecture, not a live-call path) must be either the manual harness script, this test
    module's own siblings, or capabilities/registry.py itself."""
    allowed_prefixes = ("scripts/phase19_m13_vision_review_manual.py", "tests/test_media_vision_review", "capabilities/registry.py", "capabilities/media_vision_review_capability.py", "tests/test_openai_strict_schema_compliance.py")
    offenders = []
    for path in Path(".").rglob("*.py"):
        relative = path.as_posix()
        if "__pycache__" in relative or not (relative.startswith("scripts/") or relative.startswith("tests/") or relative.startswith("capabilities/") or relative.startswith("worker/") or relative.startswith("services/")):
            continue
        if any(relative.startswith(prefix) for prefix in allowed_prefixes):
            continue
        imports = _imports_in(path)
        if any("media_vision_review_capability" in module for module in imports):
            offenders.append(relative)
    assert offenders == [], f"Unexpected importer(s) of media_vision_review_capability: {offenders}"
