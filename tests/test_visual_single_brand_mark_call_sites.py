"""VISUAL-SINGLE-BRAND-MARK-1 §8: static call-site guard for `apply_master_news_branding()`, the
one production compositing entry point for the locked MASTER NEWS canonical branding contract.

Why AST-based, not a runtime test: this is a structural fact about the source code (which modules
import a specific name), not a behavior that depends on data - mirrors tests/
test_presentation_director_mode_contract.py's own identical "parse real source with ast, assert on
the parse tree" rationale exactly. Fails immediately if a future change adds a new import of
`apply_master_news_branding` from an unapproved delivery/notifier module - the real, live incident
class this phase's own product requirement addresses ("each delivery path independently deciding to
apply NNJ branding" - see services/media_finalizer.py's own module docstring for the ORIGINAL such
incident this repo already fixed once).

Deliberately scoped to `bot/`, `services/`, `worker/` only - `scripts/` holds manual, never-
automatically-invoked acceptance/diagnostic harnesses (confirmed by their own module docstrings),
not a live delivery path, and is intentionally exempt so this test never fails on a harmless new
manual proof script."""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ("bot", "services", "worker")

# The only modules allowed to import `apply_master_news_branding` - the deterministic renderer
# itself, its one shared finalizer choke point, the real production router, and the Final Post
# Review preview/RECAP-fallback notifier (services/final_post_review_notifier.py's own module
# docstring: the storage_key/RECAP-Tier-3 branch has no other path to canonical branding). Adding a
# new name here must be a deliberate, reviewed decision - never an accidental side effect of
# wiring a new notifier.
_ALLOWED_IMPORTERS = frozenset({
    "services/nnj_master_news_overlay.py",  # defines it
    "services/media_finalizer.py",
    "services/final_post_review_notifier.py",
    "worker/content_cycle.py",
})


def _imports_apply_master_news_branding(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "services.nnj_master_news_overlay":
            if any(alias.name == "apply_master_news_branding" for alias in node.names):
                return True
        if isinstance(node, ast.Import):
            if any(alias.name == "services.nnj_master_news_overlay" for alias in node.names):
                # A bare `import services.nnj_master_news_overlay` could still reference the
                # function via attribute access - conservatively treat any such import as a hit,
                # since this codebase's own established convention (seen throughout this test
                # suite) is always `from module import name`, never bare module import, for this
                # kind of internal service import.
                return True
    return False


def test_apply_master_news_branding_has_no_unapproved_call_sites() -> None:
    offenders: list[str] = []
    for scan_dir in _SCAN_DIRS:
        for path in (_REPO_ROOT / scan_dir).rglob("*.py"):
            relative = path.relative_to(_REPO_ROOT).as_posix()
            if relative in _ALLOWED_IMPORTERS:
                continue
            if _imports_apply_master_news_branding(path):
                offenders.append(relative)
    assert not offenders, (
        f"apply_master_news_branding() imported from unapproved module(s): {offenders} - "
        "either route this delivery path through services/media_finalizer.py::finalize_photo_input() "
        "instead, or add it to _ALLOWED_IMPORTERS above as a deliberate, reviewed decision."
    )


def test_allowed_importers_are_still_real_files() -> None:
    """Guards the allowlist itself against silent drift (a renamed/deleted module leaving a stale,
    meaningless entry behind) - mirrors this repo's own established "prove the guard still tests
    something real" convention (e.g. tests/test_presentation_director_mode_contract.py's own
    `test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`)."""
    for relative in _ALLOWED_IMPORTERS:
        assert (_REPO_ROOT / relative).is_file(), f"{relative} no longer exists - update _ALLOWED_IMPORTERS"
