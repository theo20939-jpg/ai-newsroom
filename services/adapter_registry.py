"""Adapter Registry: resolves a NewsSource row to its SourceAdapter.

Built fresh once per Collector run from a snapshot of SourceDefinition
objects (see services.collector.run_collection_cycle) - never cached at
module level. A module-level cache (e.g. functools.lru_cache, the pattern
core.config.get_settings() uses) would make resolution implicitly depend on
whichever SourceDefinitions happened to be loaded first in the process, and
would make tests that build a registry from synthetic fixtures liable to see
another test's cached real-pack data. Building an explicit AdapterRegistry
object per cycle avoids both problems and makes "built once, not once per
source" visible at the call site instead of hidden behind a cache.

NewsSource never persists the pack's `adapter` field (see services.source_pack_importer),
so resolution has to reconstruct "was there an explicit adapter" from the
source's url - matched against the same SourceDefinition list the Universal
Source Registry already loaded, not inferred from the url's domain/shape.

resolve() also hands back whichever SourceDefinition matched, alongside the
adapter - some adapters (GitHubSourceAdapter) need pack-only config that
never reaches NewsSource (see schemas.source_definition.SourceDefinition.metadata).
Handing it back here means the Collector can pass it through SourceFetchContext
without any adapter re-parsing the pack itself.
"""
import logging
from dataclasses import dataclass

from database.models.news_source import NewsSource
from integrations.sources.base import SourceAdapter
from schemas.source_definition import SourceDefinition
from services.adapter_keys import ADAPTER_KEY_TO_ADAPTER, TYPE_FALLBACK_KEYS, resolve_adapter_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AdapterResolution:
    """What AdapterRegistry.resolve() returns: the concrete adapter, plus
    whichever SourceDefinition matched this NewsSource's url (None if none did,
    e.g. a manually imported Telegram channel with no pack entry at all)."""

    adapter: SourceAdapter
    definition: SourceDefinition | None


@dataclass(frozen=True, slots=True)
class SourceLookupKey:
    """Identity key for matching a NewsSource back to its SourceDefinition.

    Wraps just the normalized url today. Kept as its own type rather than a
    bare str so this lookup can grow to consider aliases, canonical urls, or
    provider ids later without changing AdapterRegistry's public signature.
    """

    normalized_url: str

    @classmethod
    def from_url(cls, url: str) -> "SourceLookupKey":
        # Same normalization formula as services.source_registry._normalize_url -
        # duplicated rather than imported (that one is private to its module),
        # but simple enough that keeping the two in sync isn't a real risk.
        return cls(url.strip().rstrip("/"))


class AdapterRegistry:
    """Resolves NewsSource rows to adapters, using a pre-built url -> adapter-key index."""

    def __init__(
        self,
        url_index: dict[SourceLookupKey, str],
        definition_index: dict[SourceLookupKey, SourceDefinition],
    ) -> None:
        self._url_index = url_index
        self._definition_index = definition_index

    def resolve(self, source: NewsSource) -> AdapterResolution | None:
        """Resolve the AdapterResolution for one NewsSource row, or None if unsupported."""
        key = SourceLookupKey.from_url(source.url) if source.url else None
        explicit_key = self._url_index.get(key) if key else None
        fallback_key = TYPE_FALLBACK_KEYS.get(source.type)
        adapter_key = resolve_adapter_key(explicit_key, fallback_key)

        if adapter_key is None:
            logger.info("No adapter resolvable for source %s (type=%s)", source.name, source.type)
            return None

        adapter = ADAPTER_KEY_TO_ADAPTER.get(adapter_key)
        if adapter is None:
            logger.info(
                "Source %s resolved to adapter key %r, which has no implementation yet (pending)",
                source.name,
                adapter_key,
            )
            return None

        return AdapterResolution(adapter=adapter, definition=self._definition_index.get(key) if key else None)


def build_registry(definitions: list[SourceDefinition]) -> AdapterRegistry:
    """Build a fresh AdapterRegistry from a SourceDefinition snapshot.

    url_index only covers definitions with an explicit `adapter` - sources
    relying on type-based fallback (bare rss/atom, or sources absent from the
    pack entirely, such as manually imported Telegram channels) are
    intentionally not in it; AdapterRegistry.resolve() reaches them through
    TYPE_FALLBACK_KEYS instead. definition_index covers every definition
    regardless of `adapter`, since it exists purely to hand config back to
    whichever adapter gets resolved, not to influence resolution itself.
    """
    url_index: dict[SourceLookupKey, str] = {}
    definition_index: dict[SourceLookupKey, SourceDefinition] = {}

    for definition in definitions:
        key = SourceLookupKey.from_url(definition.url)
        definition_index[key] = definition

        if not definition.adapter:
            continue

        if key in url_index:
            # services.source_registry.load_source_pack already rejects duplicate
            # urls across the whole pack, so this should be unreachable in
            # practice - kept as a defensive, deterministic fallback rather
            # than trusting that invariant silently.
            logger.warning("Duplicate normalized url building Adapter Registry, keeping first: %s", definition.url)
            continue

        url_index[key] = definition.adapter

    return AdapterRegistry(url_index, definition_index)
