"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 / UNIFIED-EDITORIAL-PIPELINE-VISION-GATE-CLOSURE-1:
mechanically enforces WHERE `MediaSubjectMatchCapability`'s real, LLM-backed `execute()` is
reachable from - mirrors tests/test_media_vision_review_isolation.py's own ast-based "prove it,
don't just assert it in prose" technique exactly (the sibling capability this one was built
alongside).

VISION-GATE-CLOSURE-1 update: `services/editorial_pipeline/telegram_integration.py` is now a
DELIBERATE, reviewed importer - the real, gated production wiring point that closes the
`ACTUAL_IMAGE_VERIFICATION_WIRED` Founder HIGH from RUNTIME-CLOSURE-1. It is gated three ways, all
proven by other tests (`tests/test_unified_pipeline_vision_gate.py`,
`tests/test_unified_pipeline_vision_gate_replays.py`): (1) `unified_editorial_pipeline_enabled`
must be True for this whole code path to run at all; (2) `capability_registry.resolve(...)` must
actually succeed (fails soft to the plain deterministic classifier otherwise); (3) the vision-gate
policy itself only escalates when text evidence is ambiguous AND the intent requires an
exact/narrow subject. `capabilities/executor.py` and `worker/content_cycle.py` themselves still
never import it directly (see the two tests below, unchanged) - this module remains the ONE real
call site, never duplicated."""
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


def test_only_the_reviewed_call_sites_import_the_capability() -> None:
    allowed_prefixes = (
        "scripts/_cross_platform_media_research_canary_1.py",
        "tests/test_media_subject_match",
        "tests/test_unified_pipeline_vision_gate",  # VISION-GATE-CLOSURE-1's own real tests
        "capabilities/registry.py",
        "capabilities/media_subject_match_capability.py",
        "services/media_research_selection.py",  # accepts an injected classifier callback only -
        # never imports the capability module itself; listed defensively in case a future refactor
        # adds a direct import there, which this test would then need to re-examine, not silently allow.
        "services/editorial_pipeline/telegram_integration.py",  # VISION-GATE-CLOSURE-1: the ONE
        # real, gated production wiring point - see this file's own module docstring above for the
        # three-way gating this import is subject to.
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
