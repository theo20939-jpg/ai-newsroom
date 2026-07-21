"""Phase 10 M2: CopywritingCapability registration / registry resolution.

Proves `build_registry()` resolves `CopywritingCapability` by its Contract-frozen name
("copywriting"), coexisting correctly alongside the four pre-existing Capabilities, with zero
change to `capabilities/capability_mapping.py`, `integrations/llm_gateway/boot.py`,
`ProviderRegistry`, or `ModelRegistry` - mirrors `tests/test_phase9_capability_registration.py`'s
own decision to add a small, new, phase-scoped file rather than grow an earlier phase's file
further (docs/phase10_production_content_pipeline_architecture_contract.md §12 "Registry
resolution tests").
"""
from pathlib import Path

import pytest

from capabilities.copywriting_capability import CAPABILITY_NAME as COPYWRITING_CAPABILITY_NAME
from capabilities.copywriting_capability import CopywritingCapability
from capabilities.errors import UnknownCapabilityError
from capabilities.intelligence_capability import CAPABILITY_NAME as INTELLIGENCE_CAPABILITY_NAME
from capabilities.quality_capability import CAPABILITY_NAME as QUALITY_CAPABILITY_NAME
from capabilities.registry import build_registry
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from tests.fakes.fake_infra import AllowingBudgetGuard

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def test_build_registry_resolves_copywriting_directly() -> None:
    """`CapabilityRegistry.resolve("copywriting")` succeeds, without going through a full
    workflow run - the direct-`resolve()` technique already used for the four pre-existing
    registrations (corrects MINOR-2 of the Final Re-Audit's own re-audit: previously only
    implied transitively through the full-chain workflow test)."""
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type] # never called - construction/resolution only
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    definition, capability = registry.resolve(COPYWRITING_CAPABILITY_NAME)

    assert definition.name == COPYWRITING_CAPABILITY_NAME
    assert isinstance(capability, CopywritingCapability)


def test_build_registry_resolves_all_five_capabilities() -> None:
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type]
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    for name in (
        SCORING_CAPABILITY_NAME,
        QUALITY_CAPABILITY_NAME,
        RESEARCH_CAPABILITY_NAME,
        INTELLIGENCE_CAPABILITY_NAME,
        COPYWRITING_CAPABILITY_NAME,
    ):
        definition, capability = registry.resolve(name)
        assert definition.name == name


def test_unregistered_capability_still_raises_unknown_capability_error() -> None:
    """Proves the two-line registry addition (capabilities/registry.py) is purely additive and
    does not alter resolve()'s existing behavior for any other, still-unregistered name -
    "engagement" is the same real, already-unregistered name Contract §3 itself cites."""
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type]
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("engagement")

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("no_such_capability")
