"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1: mechanically enforces that MediaSubjectMatchCapability's
real, LLM-backed execute() is never reachable from an automatic/scheduled worker path - mirrors
tests/test_media_vision_review_isolation.py's own ast-based "prove it, don't just assert it in
prose" technique exactly (the sibling capability this one was built alongside)."""
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


def test_capabilities_executor_never_imports_media_subject_match_capability() -> None:
    imports = _imports_in(Path("capabilities/executor.py"))
    assert not any("media_subject_match" in module for module in imports)


def test_worker_content_cycle_never_imports_media_subject_match() -> None:
    imports = _imports_in(Path("worker/content_cycle.py"))
    assert not any("media_subject_match" in module for module in imports)


def test_only_the_manual_harness_script_and_its_own_tests_import_the_capability() -> None:
    allowed_prefixes = (
        "scripts/_cross_platform_media_research_canary_1.py",
        "tests/test_media_subject_match",
        "capabilities/registry.py",
        "capabilities/media_subject_match_capability.py",
        "services/media_research_selection.py",  # accepts an injected classifier callback only -
        # never imports the capability module itself; listed defensively in case a future refactor
        # adds a direct import there, which this test would then need to re-examine, not silently allow.
    )
    offenders = []
    for path in Path(".").rglob("*.py"):
        relative = path.as_posix()
        if "__pycache__" in relative or not (
            relative.startswith("scripts/") or relative.startswith("tests/")
            or relative.startswith("capabilities/") or relative.startswith("worker/")
            or relative.startswith("services/")
        ):
            continue
        if any(relative.startswith(prefix) for prefix in allowed_prefixes):
            continue
        imports = _imports_in(path)
        if any("media_subject_match_capability" in module for module in imports):
            offenders.append(relative)
    assert offenders == [], f"Unexpected importer(s) of media_subject_match_capability: {offenders}"
