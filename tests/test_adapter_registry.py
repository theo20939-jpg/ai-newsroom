"""Tests for services.adapter_registry - SourceLookupKey and AdapterRegistry.resolve()."""
from database.models.news_source import NewsSource, SourceType
from integrations.sources.arxiv_source import ArxivSourceAdapter
from integrations.sources.github_source import GitHubSourceAdapter
from integrations.sources.rss_source import RSSSourceAdapter
from integrations.sources.telegram_source import TelegramSourceAdapter
from schemas.source_definition import SourceDefinition
from services.adapter_registry import SourceLookupKey, build_registry

BASE = {
    "name": "Example",
    "category": "media",
    "language": "en",
    "region": "global",
    "priority": 80,
    "reliability": 0.9,
    "fetch_interval": "15m",
    "enabled": True,
    "tags": ["ai"],
}


def _definition(**overrides: object) -> SourceDefinition:
    return SourceDefinition.model_validate(
        {**BASE, "id": "example", "type": "rss", "url": "https://example.com/feed.xml", **overrides}
    )


def _news_source(source_type: SourceType, url: str | None) -> NewsSource:
    return NewsSource(name="Example", type=source_type, url=url)


def test_source_lookup_key_normalizes_trailing_slash_and_whitespace() -> None:
    assert SourceLookupKey.from_url("https://example.com/a/") == SourceLookupKey.from_url(" https://example.com/a ")


def test_source_in_pack_with_explicit_adapter_resolves_to_that_adapter() -> None:
    definitions = [
        _definition(id="openai_github", adapter="github_api", url="https://api.github.com/orgs/openai/repos"),
    ]
    registry = build_registry(definitions)

    source = _news_source(SourceType.NEWS_API, "https://api.github.com/orgs/openai/repos")
    resolution = registry.resolve(source)

    assert resolution is not None
    assert isinstance(resolution.adapter, GitHubSourceAdapter)


def test_resolution_carries_the_matching_source_definition() -> None:
    definition = _definition(id="openai_github", adapter="github_api", url="https://api.github.com/orgs/openai/repos")
    registry = build_registry([definition])

    source = _news_source(SourceType.NEWS_API, "https://api.github.com/orgs/openai/repos")
    resolution = registry.resolve(source)

    assert resolution is not None
    assert resolution.definition is definition


def test_resolution_definition_is_none_when_source_absent_from_pack() -> None:
    registry = build_registry([])
    source = _news_source(SourceType.TELEGRAM, "@some_channel")
    resolution = registry.resolve(source)

    assert resolution is not None
    assert resolution.definition is None


def test_source_in_pack_without_adapter_falls_back_by_type() -> None:
    definitions = [_definition(id="some_feed", url="https://example.com/feed.xml")]  # no `adapter`
    registry = build_registry(definitions)

    source = _news_source(SourceType.RSS, "https://example.com/feed.xml")
    resolution = registry.resolve(source)

    assert resolution is not None
    assert isinstance(resolution.adapter, RSSSourceAdapter)
    assert resolution.definition is definitions[0]


def test_source_absent_from_pack_falls_back_by_type() -> None:
    """A manually imported Telegram channel (resources/sources.json) was never in the
    YAML pack at all - its url matches nothing in the index, so it falls back on
    NewsSource.type, exactly like the previous case."""
    registry = build_registry([])  # empty pack

    source = _news_source(SourceType.TELEGRAM, "@some_channel")
    resolution = registry.resolve(source)

    assert resolution is not None
    assert isinstance(resolution.adapter, TelegramSourceAdapter)


def test_explicit_adapter_not_registered_stays_pending_not_generic_rss() -> None:
    definitions = [
        _definition(
            id="reddit_openai",
            category="reddit",
            adapter="reddit_rss",
            url="https://www.reddit.com/r/OpenAI/new/.rss",
        ),
    ]
    registry = build_registry(definitions)

    source = _news_source(SourceType.NEWS_API, "https://www.reddit.com/r/OpenAI/new/.rss")
    assert registry.resolve(source) is None


def test_arxiv_resolves_distinctly_from_github_and_hacker_news() -> None:
    definitions = [
        _definition(id="openai_github", adapter="github_api", url="https://api.github.com/orgs/openai/repos"),
        _definition(id="hn", adapter="hacker_news", url="https://hacker-news.firebaseio.com/v0/topstories.json"),
        _definition(
            id="arxiv_cs_ai",
            adapter="arxiv",
            url="https://export.arxiv.org/api/query?search_query=cat:cs.AI",
        ),
    ]
    registry = build_registry(definitions)

    arxiv_source = _news_source(SourceType.NEWS_API, "https://export.arxiv.org/api/query?search_query=cat:cs.AI")
    resolution = registry.resolve(arxiv_source)

    assert resolution is not None
    assert isinstance(resolution.adapter, ArxivSourceAdapter)


def test_source_with_no_url_falls_back_by_type_only() -> None:
    registry = build_registry([])
    source = _news_source(SourceType.RSS, None)
    resolution = registry.resolve(source)

    assert resolution is not None
    assert isinstance(resolution.adapter, RSSSourceAdapter)


def test_duplicate_normalized_url_keeps_first_deterministically() -> None:
    definitions = [
        _definition(id="first", adapter="github_api", url="https://api.github.com/orgs/openai/repos"),
        _definition(id="second", adapter="hacker_news", url="https://api.github.com/orgs/openai/repos/"),
    ]
    registry = build_registry(definitions)

    source = _news_source(SourceType.NEWS_API, "https://api.github.com/orgs/openai/repos")
    resolution = registry.resolve(source)

    assert resolution is not None
    assert isinstance(resolution.adapter, GitHubSourceAdapter)
