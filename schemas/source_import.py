"""Validated contract for the JSON source import file."""
from pydantic import BaseModel, Field

from database.models.news_source import SourceType


class SourceImportItem(BaseModel):
    """A single source entry from an import file."""

    name: str
    type: SourceType
    url: str
    category: str | None = None
    reliability_score: float | None = Field(default=None, ge=0.0, le=1.0)
    active: bool = True


class SourceImportFile(BaseModel):
    """The top-level shape of a source import JSON file."""

    sources: list[SourceImportItem]
