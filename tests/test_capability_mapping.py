"""Tests for capabilities.capability_mapping - the single centralized
"step name -> AICapability" table (Amendment A, §15)."""
import pytest

from database.models.ai_execution import AICapability
from capabilities.capability_mapping import resolve_ai_capability
from capabilities.errors import CapabilityConfigurationError


@pytest.mark.parametrize(
    "name,expected",
    [
        ("research", AICapability.RESEARCH),
        ("intelligence", AICapability.INTELLIGENCE),
        ("trend", AICapability.TREND),
        ("scoring", AICapability.SCORING),
        ("copywriting", AICapability.COPYWRITING),
        ("creative", AICapability.CREATIVE),
        ("quality", AICapability.QUALITY),
    ],
)
def test_direct_capability_names_map_to_their_own_enum_value(name: str, expected: AICapability) -> None:
    assert resolve_ai_capability(name) == expected


def test_engagement_is_a_temporary_alias_to_intelligence() -> None:
    """Amendment A: this is a persistence alias only, not a redefinition of
    Engagement as Intelligence - see capabilities/capability_mapping.py."""
    assert resolve_ai_capability("engagement") == AICapability.INTELLIGENCE


def test_unmapped_capability_name_raises_configuration_error() -> None:
    with pytest.raises(CapabilityConfigurationError):
        resolve_ai_capability("no_such_capability")
