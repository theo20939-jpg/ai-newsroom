"""Pydantic mirror of config/newsroom_sources_v1/source.schema.json.

Kept in lockstep with that JSON Schema by hand - same required fields, same
type enum, same numeric ranges, same regex patterns - so a bad source entry
fails with a normal pydantic ValidationError instead of pulling in a separate
jsonschema validator. This matches how every other import path in this
project validates untrusted input (see schemas/source_import.py).
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal[
    "rss",
    "atom",
    "api",
    "arxiv_api",
    "youtube_api",
    "github_org",
    "web_page",
    "requires_adapter",
]


class SourceDefinition(BaseModel):
    """One validated entry from the newsroom_sources_v1 config package.

    Holds every field the package defines - including priority, tags,
    fetch_interval, adapter and auth - even though only a subset of them
    currently maps onto the NewsSource database model. Nothing from the YAML
    is dropped here; narrowing down to what NewsSource supports happens
    downstream, in services.source_pack_importer.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    category: str
    type: SourceKind
    url: str
    language: str
    region: str
    priority: int = Field(ge=0, le=100)
    reliability: float = Field(ge=0.0, le=1.0)
    fetch_interval: str = Field(pattern=r"^[0-9]+[mhd]$")
    enabled: bool
    tags: list[str]
    adapter: str | None = None
    auth: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
