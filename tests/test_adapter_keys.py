"""Tests for services.adapter_keys - the shared adapter-key roster and resolution rule."""
from services.adapter_keys import (
    ADAPTER_KEY_TO_ADAPTER,
    ADAPTER_KEY_TO_SOURCE_TYPE,
    resolve_adapter_key,
)


def test_explicit_key_wins_over_fallback() -> None:
    assert resolve_adapter_key("github_api", "web_page") == "github_api"


def test_fallback_used_when_no_explicit_key() -> None:
    assert resolve_adapter_key(None, "rss") == "rss"


def test_explicit_but_unimplemented_key_does_not_fall_back() -> None:
    """The whole point of the rule: an explicit-but-unimplemented key (e.g. reddit_rss)
    must be returned as-is, never silently replaced by the type fallback."""
    assert resolve_adapter_key("reddit_rss", "rss") == "reddit_rss"


def test_no_explicit_and_no_fallback_resolves_to_none() -> None:
    assert resolve_adapter_key(None, None) is None


def test_import_time_roster_is_subset_of_collect_time_roster() -> None:
    """Every importable key must be fetchable - but not every fetchable key needs to be
    importable from the pack (telegram_client is the one exception, see below)."""
    assert set(ADAPTER_KEY_TO_SOURCE_TYPE) <= set(ADAPTER_KEY_TO_ADAPTER)


def test_telegram_client_is_fetchable_but_not_importable_from_pack() -> None:
    """telegram_client must stay resolvable at collect time (type fallback for rows
    already imported from resources/sources.json) but never importable from the pack's
    own telegram_channels bundle entry."""
    assert "telegram_client" in ADAPTER_KEY_TO_ADAPTER
    assert "telegram_client" not in ADAPTER_KEY_TO_SOURCE_TYPE


def test_phase_4_2_keys_are_registered() -> None:
    for key in ("telegram_client", "rss", "atom", "github_api", "hacker_news", "arxiv"):
        assert key in ADAPTER_KEY_TO_ADAPTER


def test_reddit_rss_is_not_registered_yet() -> None:
    assert "reddit_rss" not in ADAPTER_KEY_TO_ADAPTER
