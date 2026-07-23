"""FakeSourceAdapter / FakeAdapterRegistry: deterministic, network-free collector test doubles.

Used only by tests (Phase 12 Contract §7/§22) - never imported by production code. Neither class
imports services.adapter_registry's AdapterRegistry class or services.adapter_keys'
ADAPTER_KEY_TO_ADAPTER map; FakeAdapterRegistry implements services.collector.SourceAdapterResolver
purely structurally, so injecting it via run_collection_cycle(adapter_resolver_factory=...) never
reaches any real, network-calling adapter.
"""
from database.models.news_source import NewsSource
from integrations.sources.base import SourceAdapter, SourceFetchContext
from schemas.raw_news_item import RawNewsItem
from schemas.source_definition import SourceDefinition
from services.adapter_registry import AdapterResolution


class FakeSourceAdapter(SourceAdapter):
    """Returns canned RawNewsItems, or raises a configured error - zero network I/O."""

    def __init__(
        self, items: list[RawNewsItem] | None = None, error: Exception | None = None
    ) -> None:
        self._items = items or []
        self._error = error
        self.received_calls: list[tuple[NewsSource, SourceFetchContext]] = []

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        self.received_calls.append((source, context))
        if self._error is not None:
            raise self._error
        return self._items


class FakeAdapterRegistry:
    """A test-owned resolver: resolves to the fake adapter only for the explicitly listed
    source id(s) - anything else (in particular, any real, pre-existing NewsSource row in the
    shared database, see Phase 12 Plan §12.0) resolves to None, exactly as the real
    AdapterRegistry.resolve() would for a source it does not recognize. This selectivity is not
    optional: _load_active_sources() queries ALL active NewsSource rows in the shared database
    (there is no separate test database), so a resolver that matched unconditionally would cause
    the collector to process every real active source too, not just the test's own.

    Never constructs services.adapter_registry.AdapterRegistry and never looks up
    services.adapter_keys.ADAPTER_KEY_TO_ADAPTER - the whole point of this fake.
    """

    def __init__(
        self,
        adapter: SourceAdapter,
        resolvable_source_ids: set,
        definition: SourceDefinition | None = None,
    ) -> None:
        self._adapter = adapter
        self._resolvable_source_ids = resolvable_source_ids
        self._definition = definition

    def resolve(self, source: NewsSource) -> AdapterResolution | None:
        if source.id not in self._resolvable_source_ids:
            return None
        return AdapterResolution(adapter=self._adapter, definition=self._definition)
