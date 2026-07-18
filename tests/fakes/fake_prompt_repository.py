"""FakePromptRepository: deterministic, in-memory PromptRepository fixture for unit tests
(Phase 8 contract §15.3) - never a real, published prompt store. Register RenderedPrompt
content explicitly; resolve() is a pure, deterministic lookup, mirroring the same determinism
the real FilePromptRepository guarantees in production (§7.6).

Formalizes what tests/test_scoring_capability.py and tests/test_scoring_capability_retry.py
did ad hoc (M3/M5, both used the real FilePromptRepository against real prompts/ content) into
the shared convention every future Capability's tests should use instead (§15.1-§15.4).
"""
from integrations.prompts.protocol import RenderedPrompt


class FakePromptRepository:
    """Implements PromptRepository (integrations.prompts.protocol). The most recently
    register()-ed version for a given name becomes that name's "latest" (version=None)
    resolution - test-controlled, deterministic, no ambiguity."""

    def __init__(self) -> None:
        self._prompts: dict[tuple[str, str], RenderedPrompt] = {}
        self._latest_version: dict[str, str] = {}

    def register(self, prompt: RenderedPrompt) -> None:
        self._prompts[(prompt.name, prompt.version)] = prompt
        self._latest_version[prompt.name] = prompt.version

    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        resolved_version = version if version is not None else self._latest_version.get(name)
        if resolved_version is None:
            raise KeyError(f"FakePromptRepository: no prompt registered for name '{name}'.")

        rendered = self._prompts.get((name, resolved_version))
        if rendered is None:
            raise KeyError(f"FakePromptRepository: no prompt '{name}' version '{resolved_version}'.")
        return rendered
