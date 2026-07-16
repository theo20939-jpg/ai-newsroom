"""Contract/shape test for integrations.prompts.protocol - no filesystem, no network."""
from integrations.prompts.protocol import PromptRepository, RenderedPrompt


class FakePromptRepository:
    """Minimal in-memory PromptRepository, proving the Protocol is implementable."""

    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        return RenderedPrompt(
            name=name, version=version or "1", system="You are a fake.", rules=["be deterministic"],
            output_schema={"type": "object", "properties": {}},
        )


def _repo() -> PromptRepository:
    return FakePromptRepository()


def test_resolve_returns_a_rendered_prompt() -> None:
    prompt = _repo().resolve("research")
    assert prompt.name == "research"
    assert prompt.version == "1"


def test_resolve_with_explicit_version() -> None:
    prompt = _repo().resolve("research", version="2")
    assert prompt.version == "2"
