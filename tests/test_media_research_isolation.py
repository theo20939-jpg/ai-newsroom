"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 25: proves none of this phase's new modules
are wired into any live/automatic worker path yet - mirrors tests/test_media_subject_match_
isolation.py's own ast-based technique, extended to the whole new module surface (not just the
Capability)."""
from __future__ import annotations

import ast
from pathlib import Path

_NEW_MODULES = (
    "media_intent", "media_subject_match", "media_query_generation", "media_web_discovery",
    "media_download_cache", "media_candidate_scoring", "media_research_selection",
    "media_subject_match_capability",
)


def _imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_worker_content_cycle_never_imports_any_new_media_research_module() -> None:
    imports = _imports_in(Path("worker/content_cycle.py"))
    hits = [m for m in imports for new in _NEW_MODULES if new in m]
    assert hits == []


def test_capabilities_executor_never_imports_any_new_media_research_module() -> None:
    imports = _imports_in(Path("capabilities/executor.py"))
    hits = [m for m in imports for new in _NEW_MODULES if new in m]
    assert hits == []
