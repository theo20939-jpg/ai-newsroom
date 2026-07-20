"""Tests for capabilities.registry.CapabilityRegistry. Pure unit tests, no database."""
import pytest

from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from capabilities.errors import (
    CapabilityRegistryAlreadySealedError,
    DuplicateCapabilityRegistrationError,
    UnknownCapabilityError,
)
from capabilities.registry import CapabilityRegistry, build_registry
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from tests.fakes.fake_capability import AlwaysSucceedsCapability
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard


class _FakePromptRepository:
    """Minimal in-memory PromptRepository, proving build_registry()'s new signature (§19 rule
    2) is satisfiable - mirrors tests/test_prompt_repository_protocol.py's own fake."""

    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        return RenderedPrompt(
            name=name, version=version or "1", system="You are a fake.", rules=[], output_schema={}
        )


def _build_registry() -> CapabilityRegistry:
    tool_registry = ToolRegistry()
    tool_registry.seal()
    prompt_repository: PromptRepository = _FakePromptRepository()
    return build_registry(FakeLLMGateway(), prompt_repository, AllowingBudgetGuard(), tool_registry)


def _definition(name: str = "research", version: int = 1) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name, version=version, config=CapabilityConfig(timeout_seconds=10),
        required_context=["news_event"], expected_output_keys=["summary"],
    )


def test_register_and_resolve() -> None:
    registry = CapabilityRegistry()
    definition = _definition()
    capability = AlwaysSucceedsCapability()
    registry.register(definition, capability)

    resolved_definition, resolved_capability = registry.resolve("research")
    assert resolved_definition is definition
    assert resolved_capability is capability


def test_duplicate_registration_raises() -> None:
    registry = CapabilityRegistry()
    registry.register(_definition(), AlwaysSucceedsCapability())

    with pytest.raises(DuplicateCapabilityRegistrationError):
        registry.register(_definition(), AlwaysSucceedsCapability())


def test_unknown_name_raises() -> None:
    registry = CapabilityRegistry()

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("research")


def test_registration_after_sealing_raises() -> None:
    registry = CapabilityRegistry()
    registry.register(_definition(), AlwaysSucceedsCapability())
    registry.seal()

    with pytest.raises(CapabilityRegistryAlreadySealedError):
        registry.register(_definition(name="intelligence"), AlwaysSucceedsCapability())


def test_resolution_after_sealing_still_works() -> None:
    registry = CapabilityRegistry()
    definition = _definition()
    capability = AlwaysSucceedsCapability()
    registry.register(definition, capability)
    registry.seal()

    resolved_definition, resolved_capability = registry.resolve("research")
    assert resolved_definition is definition
    assert resolved_capability is capability


def test_build_registry_ships_sealed_and_rejects_an_unregistered_name() -> None:
    """build_registry() requires the four injected dependencies §19 rule 2 specifies (M19).
    By Phase 9, it ships registered with "scoring"/"quality" (Phase 8) and
    "research"/"intelligence" (Phase 9 M6) - no longer empty (that was only ever true through
    Phase 7) - but remains sealed, and still rejects a genuinely-unregistered name."""
    real_registry = _build_registry()

    with pytest.raises(UnknownCapabilityError):
        real_registry.resolve("definitely_unregistered_capability")

    with pytest.raises(CapabilityRegistryAlreadySealedError):
        real_registry.register(_definition(), AlwaysSucceedsCapability())
