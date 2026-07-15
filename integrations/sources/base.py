"""Adapter contract shared by all news source integrations."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from database.models.news_source import NewsSource
from schemas.raw_news_item import RawNewsItem
from schemas.source_definition import SourceDefinition


@dataclass(frozen=True, slots=True)
class SourceFetchContext:
    """Provider-independent context passed alongside a NewsSource to fetch().

    definition is the SourceDefinition the Collector's Adapter Registry
    matched to this NewsSource's url, already loaded once per collection
    cycle - never None for it to be re-parsed here. It is None when no
    SourceDefinition matches (e.g. Telegram channels imported outside the
    pack via resources/sources.json). Most adapters ignore this entirely;
    it exists so an adapter that needs pack-only config (fields that never
    reach the NewsSource database row, such as GitHubSourceAdapter's
    curated repository list) can read it without querying anything itself.
    """

    definition: SourceDefinition | None


class SourceAdapter(ABC):
    """Fetches raw items from one external source.

    Each source type (Telegram, RSS, News API, ...) implements this
    interface independently. Adding a new source type never requires
    changing existing adapters or the collector orchestration.
    """

    @abstractmethod
    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch raw items produced by the given source."""
        raise NotImplementedError
