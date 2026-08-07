"""Phase 19 M8: mechanically enforces that Source Intelligence data can never reach Copywriting
or generate attribution language - mirrors tests/test_content_draft_service.py::
test_capabilities_never_import_content_draft()'s exact "prove it with ast.parse, don't just assert
it in prose" technique.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def test_no_capability_imports_source_intelligence() -> None:
    """No file under capabilities/ imports services.source_intelligence or
    services.source_intelligence_persistence or database.models.news_event_source_intelligence -
    Source Intelligence data can only ever reach a review-only persistence path via
    capabilities/executor.py's own _attach_source_intelligence() hook (which itself lives in
    executor.py, not in any individual Capability), never a Capability's own prompt-building
    code."""
    capabilities_dir = Path("capabilities")
    forbidden_substrings = ("source_intelligence",)
    for path in sorted(capabilities_dir.glob("*.py")):
        if path.name == "executor.py":
            continue  # the one sanctioned caller of the shadow-persistence indirection
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        assert not any(
            any(sub in module for sub in forbidden_substrings) for module in imported_modules
        ), f"{path} imports source_intelligence - Copywriting must never read Source Intelligence data."


def test_no_prompt_file_references_source_intelligence_labels() -> None:
    """No prompt YAML file mentions Source Intelligence's own label vocabulary - a structural
    guard against a future prompt edit accidentally wiring hedged labels into generated prose.
    Deliberately scoped to the label vocabulary alone (specific, low false-positive risk) rather
    than generic attribution phrasing like "confirmed by" - too fragile a substring match against
    arbitrary prose (an unrelated existing prompt file's own comment legitimately contains
    "confirmed by" in an unrelated sentence)."""
    prompts_dir = Path("prompts")
    forbidden_phrases = (
        "possible_original", "possible_confirmation", "possible_aggregation", "possible_analysis",
    )
    for path in sorted(prompts_dir.rglob("*.yaml")):
        content = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden_phrases:
            assert phrase not in content, f"{path} references '{phrase}' - Source Intelligence must never reach a prompt."


def test_source_intelligence_labels_are_all_hedged() -> None:
    """Every exported label constant is either UNKNOWN or starts with POSSIBLE_ - enforced by
    inspecting the module's own public constants, not by re-deriving the list here."""
    source = Path("services/source_intelligence.py").read_text(encoding="utf-8")
    constant_names = re.findall(r'^([A-Z_]+)\s*=\s*"([A-Z_]+)"', source, re.MULTILINE)
    assert constant_names, "expected at least one label constant to be found"
    for _name, value in constant_names:
        assert value == "UNKNOWN" or value.startswith("POSSIBLE_"), (
            f"label value '{value}' is not hedged - Source Intelligence must never assert a "
            "definitive attribution claim."
        )
