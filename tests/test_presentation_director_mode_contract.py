"""NINJA PULSE Visual System v1 pre-commit correction - structural proof of the
`presentation_director_mode` off/shadow/enforce contract inside `worker/content_cycle.py`.

Why AST-based, not a full DB round-trip: `run_content_cycle()` is a large, deeply-integrated
function (real Postgres, real capability registry, real image/quote/treatment resolution) that
`tests/test_content_worker_cycle.py` already exercises end-to-end for its own unrelated
invariants. Building a second full round-trip harness here, just to prove "these four variables
are never reassigned outside one specific `if` block," would duplicate a large amount of fragile
fixture machinery for a claim that is actually a pure structural fact about the source code, not a
runtime behavior that depends on data. Parsing the real, current source with `ast` and checking
line ranges makes this test fail immediately if a future change ever moves one of these
assignments out of the enforce-only gate - the same guarantee a round-trip test would give, at a
fraction of the cost and with zero flakiness.

Complements (does not replace): `tests/test_presentation_director.py` (proves `decide_presentation()`
itself is a pure function - no I/O, so it cannot possibly leak into delivery on its own) and
`tests/test_telegram_editorial_routing.py::test_photo_send_omits_show_caption_above_media_kwarg_by_default`
(proves the one real leak this correction pass found and fixed - the outgoing Telegram request
shape - at the lowest level).
"""
import ast
from pathlib import Path

_SOURCE_PATH = Path("worker/content_cycle.py")

_MUTATING_TARGETS = {"keyboard", "photo_input", "media_group_items", "show_caption_above_media"}


def _parse_run_content_cycle() -> ast.AsyncFunctionDef:
    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_content_cycle":
            return node
    raise AssertionError("run_content_cycle() not found in worker/content_cycle.py")


def _find_if(func: ast.AsyncFunctionDef, needle: str) -> ast.If:
    for node in ast.walk(func):
        if isinstance(node, ast.If) and needle in ast.unparse(node.test):
            return node
    raise AssertionError(f"no `if` statement with {needle!r} in its test found")


def _assignment_targets(node: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            for target in n.targets:
                if isinstance(target, ast.Name):
                    found.append((target.id, n.lineno))
    return found


def test_enforce_gate_is_nested_inside_the_off_shadow_gate() -> None:
    func = _parse_run_content_cycle()
    outer_if = _find_if(func, "presentation_director_mode != 'off'")
    enforce_if = _find_if(func, "presentation_director_mode == 'enforce'")
    assert enforce_if.lineno >= outer_if.lineno
    assert enforce_if.end_lineno is not None and outer_if.end_lineno is not None
    assert enforce_if.end_lineno <= outer_if.end_lineno


def test_off_and_shadow_modes_never_mutate_keyboard_photo_or_caption_position() -> None:
    """The real proof: every assignment to `keyboard`/`photo_input`/`media_group_items`/
    `show_caption_above_media` that occurs anywhere inside the `!= "off"` gate must fall strictly
    within the `== "enforce"` sub-gate's own line range - i.e. "shadow" (which reaches the outer
    gate but never the inner one) can never reach any of these assignments."""
    func = _parse_run_content_cycle()
    outer_if = _find_if(func, "presentation_director_mode != 'off'")
    enforce_if = _find_if(func, "presentation_director_mode == 'enforce'")
    assert enforce_if.end_lineno is not None

    for name, lineno in _assignment_targets(outer_if):
        if name in _MUTATING_TARGETS:
            assert enforce_if.lineno <= lineno <= enforce_if.end_lineno, (
                f"assignment to {name!r} at worker/content_cycle.py:{lineno} escapes the "
                "enforce-only gate - this would leak into 'shadow' mode's visible output"
            )


def test_enforce_gate_actually_assigns_every_mutating_target_at_least_once() -> None:
    """Guards the test above against vacuous success (e.g. a future refactor that renames these
    variables and silently stops testing anything real) - the enforce-only block must genuinely
    contain at least one assignment to each tracked variable today."""
    func = _parse_run_content_cycle()
    enforce_if = _find_if(func, "presentation_director_mode == 'enforce'")
    assigned_names = {name for name, _lineno in _assignment_targets(enforce_if)}
    missing = _MUTATING_TARGETS - assigned_names
    assert not missing, f"expected the enforce-only gate to assign {missing}, found none - test may be stale"


def test_presentation_decision_is_computed_and_logged_outside_the_enforce_gate() -> None:
    """"shadow" must still compute and log the decision (spec's own explicit requirement) - the
    `decide_presentation()` call and its `logger.info("presentation_decision", ...)` companion
    must sit in the outer `!= "off"` gate but OUTSIDE (before) the inner `== "enforce"` gate."""
    func = _parse_run_content_cycle()
    outer_if = _find_if(func, "presentation_director_mode != 'off'")
    enforce_if = _find_if(func, "presentation_director_mode == 'enforce'")

    decide_call_line = None
    log_call_line = None
    for node in ast.walk(outer_if):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "decide_presentation":
            decide_call_line = node.lineno
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "info" and node.args
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == "presentation_decision"
        ):
            log_call_line = node.lineno

    assert decide_call_line is not None, "decide_presentation() call not found inside the off/shadow/enforce gate"
    assert log_call_line is not None, "logger.info('presentation_decision', ...) call not found"
    assert decide_call_line < enforce_if.lineno
    assert log_call_line < enforce_if.lineno
