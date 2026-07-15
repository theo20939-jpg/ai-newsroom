"""Canonical adapter-key roster - the single source of truth for which
source adapters this codebase implements.

Both services.source_pack_importer (decides what may be persisted to
NewsSource) and services.adapter_registry (decides what the Collector can
fetch) derive their view from IMPLEMENTED_ADAPTERS below instead of each
maintaining their own list. This is also where the one shared resolution
rule lives: an explicit adapter key always wins over a type-derived
fallback, and a fallback is only ever consulted when there is no explicit
key at all - never as a second attempt after an explicit-but-unimplemented
key.
"""
from dataclasses import dataclass

from database.models.news_source import SourceType
from integrations.sources.arxiv_source import ArxivSourceAdapter
from integrations.sources.base import SourceAdapter
from integrations.sources.github_source import GitHubSourceAdapter
from integrations.sources.hacker_news_source import HackerNewsSourceAdapter
from integrations.sources.rss_source import RSSSourceAdapter
from integrations.sources.telegram_source import TelegramSourceAdapter


@dataclass(frozen=True)
class AdapterRegistration:
    """One implemented adapter: its key, the SourceType it persists as, and its instance.

    importable_from_pack=False marks an adapter that is only ever reached
    through NewsSource.type fallback for rows that already exist - never
    through a pack SourceDefinition's explicit `adapter` field. telegram_client
    is the only case today: the pack's own "telegram_channels" entry
    (social.yaml) names this key, but it's a single bundle standing in for
    many channels, not one fetchable url - real Telegram channels only ever
    arrive via resources/sources.json, outside the pack entirely. Importing
    that bundle entry as a literal NewsSource(url="https://telegram.org/")
    would hand TelegramSourceAdapter a meaningless "channel" to fetch.
    """

    key: str
    source_type: SourceType
    adapter: SourceAdapter
    importable_from_pack: bool = True


IMPLEMENTED_ADAPTERS: list[AdapterRegistration] = [
    AdapterRegistration(
        "telegram_client", SourceType.TELEGRAM, TelegramSourceAdapter(), importable_from_pack=False
    ),
    AdapterRegistration("rss", SourceType.RSS, RSSSourceAdapter()),
    AdapterRegistration("atom", SourceType.RSS, RSSSourceAdapter()),
    AdapterRegistration("github_api", SourceType.NEWS_API, GitHubSourceAdapter()),
    AdapterRegistration("hacker_news", SourceType.NEWS_API, HackerNewsSourceAdapter()),
    AdapterRegistration("arxiv", SourceType.NEWS_API, ArxivSourceAdapter()),
]

# Import-time view (services.source_pack_importer): only adapters a pack
# SourceDefinition may actually be persisted as.
ADAPTER_KEY_TO_SOURCE_TYPE: dict[str, SourceType] = {
    reg.key: reg.source_type for reg in IMPLEMENTED_ADAPTERS if reg.importable_from_pack
}

# Collect-time view (services.adapter_registry): every adapter the Collector
# can dispatch to, including ones only reachable via type fallback.
ADAPTER_KEY_TO_ADAPTER: dict[str, SourceAdapter] = {
    reg.key: reg.adapter for reg in IMPLEMENTED_ADAPTERS
}

# Consulted only when a source has no explicit `adapter` at all (neither in
# its SourceDefinition, nor - for sources outside the pack entirely, such as
# manually imported Telegram channels - any SourceDefinition to begin with).
# NEWS_API/WEB/SOCIAL have no entry: there is no sensible "default" API
# adapter, so a NEWS_API-typed source with no resolvable explicit key stays
# pending rather than guessing.
TYPE_FALLBACK_KEYS: dict[SourceType, str] = {
    SourceType.TELEGRAM: "telegram_client",
    SourceType.RSS: "rss",
}


def resolve_adapter_key(explicit_key: str | None, type_fallback_key: str | None) -> str | None:
    """Decide the effective adapter key: explicit always wins, fallback only fills a gap.

    An explicit key that turns out not to be implemented is still returned
    as-is - callers must not retry with type_fallback_key in that case, or a
    source like adapter=reddit_rss would silently degrade to the generic RSS
    adapter. Checking whether the returned key is actually implemented is
    each caller's own job (against ADAPTER_KEY_TO_SOURCE_TYPE or
    ADAPTER_KEY_TO_ADAPTER, depending on which one it needs).
    """
    return explicit_key if explicit_key else type_fallback_key
