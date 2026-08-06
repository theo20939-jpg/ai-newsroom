"""Tests for capabilities.capability_mapping - the single centralized
"step name -> AICapability" table (Amendment A, §15; resolved by Phase 18.10 M9)."""
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
        ("engagement", AICapability.ENGAGEMENT),
    ],
)
def test_direct_capability_names_map_to_their_own_enum_value(name: str, expected: AICapability) -> None:
    assert resolve_ai_capability(name) == expected


def test_engagement_maps_to_its_own_enum_value() -> None:
    """Phase 18.10 M9: the former Amendment A persistence alias (engagement -> INTELLIGENCE) is
    resolved - engagement now has its own AICapability value, matching the Redis cost ledger's
    (services/cost_tracker.py) own always-correct raw-string bucketing."""
    assert resolve_ai_capability("engagement") == AICapability.ENGAGEMENT


def test_unmapped_capability_name_raises_configuration_error() -> None:
    with pytest.raises(CapabilityConfigurationError):
        resolve_ai_capability("no_such_capability")
