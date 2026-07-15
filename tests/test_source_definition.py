"""Tests for schemas.source_definition.SourceDefinition."""
import pytest
from pydantic import ValidationError

from schemas.source_definition import SourceDefinition

VALID_ENTRY = {
    "id": "example_feed",
    "name": "Example Feed",
    "category": "media",
    "type": "rss",
    "url": "https://example.com/feed.xml",
    "language": "en",
    "region": "global",
    "priority": 80,
    "reliability": 0.9,
    "fetch_interval": "15m",
    "enabled": True,
    "tags": ["ai"],
}


def test_valid_entry_parses() -> None:
    definition = SourceDefinition.model_validate(VALID_ENTRY)
    assert definition.id == "example_feed"
    assert definition.adapter is None
    assert definition.auth is None


def test_optional_fields_roundtrip() -> None:
    entry = {**VALID_ENTRY, "adapter": "reddit_rss", "auth": "GITHUB_TOKEN", "notes": "note"}
    definition = SourceDefinition.model_validate(entry)
    assert definition.adapter == "reddit_rss"
    assert definition.auth == "GITHUB_TOKEN"
    assert definition.notes == "note"


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "Has-Uppercase"},
        {"priority": 101},
        {"priority": -1},
        {"reliability": 1.5},
        {"fetch_interval": "15"},
        {"type": "not_a_real_type"},
    ],
)
def test_invalid_entries_are_rejected(overrides: dict) -> None:
    entry = {**VALID_ENTRY, **overrides}
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(entry)


def test_unknown_field_is_rejected() -> None:
    entry = {**VALID_ENTRY, "unexpected_field": "value"}
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(entry)
