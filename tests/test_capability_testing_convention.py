"""Phase 8 M6: formalizes contract §15's testing-philosophy rules into the shared convention
every Capability's tests follow, retroactively applied to M3's ScoringCapability tests
(tests/test_scoring_capability.py, tests/test_scoring_capability_retry.py - both now use
FakeLLMGateway + FakePromptRepository, never the real FilePromptRepository, per §15.3).

The convention, going forward for M7+:
- Unit tests (§15.1-§15.4): tests.fakes.fake_gateway.FakeLLMGateway +
  tests.fakes.fake_prompt_repository.FakePromptRepository. Deterministic, no real network
  call, no real published prompt store.
- Integration/end-to-end tests (§15.6): tests.fakes.fake_provider_adapter.FakeProviderAdapter
  underneath a real, fully-assembled RoutingGateway (tests/test_capability_boot_wiring_e2e.py) -
  a distinct tier, never a replacement for the unit tests above.
- Each registered Capability has at least one golden-path regression test (§15.7):
  ScoringCapability's is test_scoring_capability.py::test_execute_full_shape_end_to_end.
"""
import ast
from pathlib import Path

import pytest

from integrations.prompts.protocol import RenderedPrompt
from tests.fakes.fake_prompt_repository import FakePromptRepository

_TESTS_ROOT = Path(__file__).resolve().parent

# Modules a Capability-level unit test file must never import (§15.1/§15.5: no real network
# call, no real provider). Mirrors PROVIDER_SDK_MODULE_PREFIXES in scripts/validate_architecture.py.
_FORBIDDEN_UNIT_TEST_IMPORTS = (
    "openai",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "ollama",
    "cohere",
    "mistralai",
    "integrations.llm_gateway.providers.openai_adapter",
)

# Capability-level unit test files this convention governs - deliberately a short, explicit,
# hand-maintained list (mirrors scripts/validate_architecture.py's own "hand-curated, never
# auto-derived" discipline) rather than a glob, so a future test file is swept in only by a
# deliberate one-line addition here, not silently.
_CAPABILITY_UNIT_TEST_FILES = (
    "test_scoring_capability.py",
    "test_scoring_capability_retry.py",
    "test_quality_capability.py",  # M7 - swept in at M8's §15 cross-cutting review pass
)


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.add(node.module)
    return names


def test_capability_unit_test_files_never_import_a_real_provider() -> None:
    """§15.1/§15.5, checked mechanically rather than merely asserted in prose: no Capability
    unit test file imports a real provider SDK or the real OpenAI adapter module."""
    for filename in _CAPABILITY_UNIT_TEST_FILES:
        path = _TESTS_ROOT / filename
        assert path.exists(), f"{filename} is listed in the convention but does not exist"
        imports = _imported_module_names(path)
        for forbidden in _FORBIDDEN_UNIT_TEST_IMPORTS:
            matching = {name for name in imports if name == forbidden or name.startswith(forbidden + ".")}
            assert not matching, f"{filename} imports forbidden module(s): {matching}"


def test_fake_prompt_repository_satisfies_the_protocol_deterministically() -> None:
    """§15.3/§15.4: a fake PromptRepository, deterministic - identical input produces
    identical output on every call."""
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(name="example", version="1", system="s", rules=["r"], output_schema={"type": "object"})
    )

    first = repository.resolve("example", "1")
    second = repository.resolve("example", "1")

    assert first == second
    assert first is second  # loaded into an immutable in-memory mapping, same object every call


def test_fake_prompt_repository_raises_for_unknown_name() -> None:
    repository = FakePromptRepository()

    with pytest.raises(KeyError):
        repository.resolve("no_such_prompt")


def test_fake_prompt_repository_version_none_resolves_to_most_recently_registered() -> None:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(name="example", version="1", system="v1", rules=[], output_schema={})
    )
    repository.register(
        RenderedPrompt(name="example", version="2", system="v2", rules=[], output_schema={})
    )

    latest = repository.resolve("example")

    assert latest.version == "2"
    assert repository.resolve("example", "1").version == "1"
