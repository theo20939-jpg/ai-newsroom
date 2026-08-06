"""Phase 19 M2: enforces build_evidence_package()'s own binding contract (services/
evidence_package.py's docstring, point 3) - a source-text-scan regression guard, mirroring
tests/test_meme_pipeline_not_live.py's established convention for this codebase.

Two invariants:
1. Only the two documented, already-guarded production call sites ever call
   build_evidence_package() - a new caller must be added to _ALLOWED_CALLER_FILES deliberately,
   never silently.
2. Each allowed call site actually wraps its call in a SAVEPOINT (session.begin_nested()) -
   catches the specific regression this milestone's own review found and fixed (an earlier
   version of this code called build_evidence_package() unguarded).
"""
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_ALLOWED_CALLER_FILES = {
    "capabilities/executor.py",
    "services/content_draft_service.py",
}


def _all_python_files() -> list[Path]:
    excluded_dirs = {".git", "__pycache__", "tests", "venv", ".venv", "node_modules"}
    files = []
    for path in _REPO_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(_REPO_ROOT).parts
        if any(part in excluded_dirs for part in relative_parts):
            continue
        files.append(path)
    return files


def _find_callers() -> dict[str, str]:
    """Maps relative-path -> file text, for every non-test .py file that references
    build_evidence_package(), excluding the definition itself."""
    callers: dict[str, str] = {}
    for path in _all_python_files():
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative == "services/evidence_package.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "build_evidence_package(" in text:
            callers[relative] = text
    return callers


def test_only_documented_call_sites_call_build_evidence_package() -> None:
    callers = _find_callers()
    assert set(callers.keys()) == _ALLOWED_CALLER_FILES, (
        "build_evidence_package() has a new or removed caller not reflected in this test's "
        "_ALLOWED_CALLER_FILES (and services/evidence_package.py's own docstring, point 3) - "
        f"found: {sorted(callers.keys())}"
    )


def test_every_call_site_is_savepoint_guarded() -> None:
    """A crude but effective source-text proximity check: within a small window before the
    build_evidence_package( call, the same function body must contain begin_nested() - proving
    the SAVEPOINT guard is actually present, not merely a docstring promise."""
    callers = _find_callers()
    for relative, text in callers.items():
        call_index = text.index("build_evidence_package(")
        window = text[max(0, call_index - 400) : call_index]
        assert "begin_nested()" in window, (
            f"{relative} calls build_evidence_package() without a nearby session.begin_nested() "
            "SAVEPOINT guard - this violates the binding contract in "
            "services/evidence_package.py's own docstring (point 2)."
        )
        assert "except Exception" in text[call_index : call_index + 600], (
            f"{relative} calls build_evidence_package() without a broad except Exception guard "
            "shortly after the call - a schema-mismatch failure would crash this call site."
        )
