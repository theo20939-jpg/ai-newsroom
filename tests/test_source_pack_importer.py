"""Tests for services.source_pack_importer's SourceDefinition -> SourceImportItem mapping."""
import pytest
from pydantic import SecretStr

from core.config import settings
from database.models.news_source import SourceType
from schemas.source_definition import SourceDefinition
from services.source_pack_importer import SourcePackImportReport, _to_import_item

BASE = {
    "name": "Example",
    "category": "media",
    "url": "https://example.com/feed.xml",
    "language": "en",
    "region": "global",
    "priority": 80,
    "reliability": 0.9,
    "fetch_interval": "15m",
    "enabled": True,
    "tags": ["ai"],
}


def _definition(**overrides: object) -> SourceDefinition:
    return SourceDefinition.model_validate({**BASE, "id": "example", "type": "rss", **overrides})


def test_bare_rss_is_importable() -> None:
    report = SourcePackImportReport()
    item = _to_import_item(_definition(), report)

    assert item is not None
    assert item.type is SourceType.RSS
    assert item.url == "https://example.com/feed.xml"
    assert report.pending_adapter == 0


def test_bare_atom_is_importable() -> None:
    report = SourcePackImportReport()
    item = _to_import_item(_definition(type="atom"), report)

    assert item is not None
    assert item.type is SourceType.RSS


def test_named_adapter_override_is_pending() -> None:
    """A source with an explicit adapter (e.g. reddit_rss) has no adapter yet, even though
    its underlying `type` is rss."""
    report = SourcePackImportReport()
    item = _to_import_item(_definition(adapter="reddit_rss"), report)

    assert item is None
    assert report.pending_adapter == 1


@pytest.mark.parametrize("type_", ["web_page", "api", "arxiv_api", "github_org", "youtube_api", "requires_adapter"])
def test_unimplemented_types_are_pending(type_: str) -> None:
    """These types have no *explicit adapter* set here - matching a source that would
    fall back to its bare `type`, which none of these implement. In the real pack every
    github_org/api/arxiv_api entry always carries an explicit `adapter` too (see the
    Phase 4.2 tests below) - this test only covers the type-fallback path."""
    report = SourcePackImportReport()
    item = _to_import_item(_definition(type=type_), report)

    assert item is None
    assert report.pending_adapter == 1


@pytest.mark.parametrize(
    ("type_", "adapter"),
    [
        ("github_org", "github_api"),
        ("api", "hacker_news"),
        ("arxiv_api", "arxiv"),
    ],
)
def test_phase_4_2_adapters_are_importable(type_: str, adapter: str) -> None:
    report = SourcePackImportReport()
    item = _to_import_item(_definition(type=type_, adapter=adapter), report)

    assert item is not None
    assert item.type is SourceType.NEWS_API
    assert report.pending_adapter == 0


def test_disabled_source_is_skipped() -> None:
    report = SourcePackImportReport()
    item = _to_import_item(_definition(enabled=False), report)

    assert item is None
    assert report.disabled == 1
    assert report.pending_adapter == 0


def test_missing_auth_excludes_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_TEST_TOKEN", raising=False)
    report = SourcePackImportReport()
    item = _to_import_item(_definition(auth="SOME_TEST_TOKEN"), report)

    assert item is None
    assert report.auth_excluded == 1


def test_present_auth_allows_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_TEST_TOKEN", "value")
    report = SourcePackImportReport()
    item = _to_import_item(_definition(auth="SOME_TEST_TOKEN"), report)

    assert item is not None
    assert report.auth_excluded == 0


def test_pending_adapter_takes_priority_over_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source needing both an unimplemented adapter and a missing auth var is
    reported as pending_adapter, not auth_excluded."""
    monkeypatch.delenv("SOME_TEST_TOKEN", raising=False)
    report = SourcePackImportReport()
    item = _to_import_item(_definition(type="github_org", auth="SOME_TEST_TOKEN"), report)

    assert item is None
    assert report.pending_adapter == 1
    assert report.auth_excluded == 0


def test_telegram_client_bundle_is_pending_not_imported() -> None:
    """The pack's own telegram_channels entry (adapter=telegram_client) must never become
    a NewsSource - real Telegram channels only ever come from resources/sources.json."""
    report = SourcePackImportReport()
    item = _to_import_item(
        _definition(type="requires_adapter", adapter="telegram_client", url="https://telegram.org/"),
        report,
    )

    assert item is None
    assert report.pending_adapter == 1


def test_github_token_from_settings_satisfies_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """GITHUB_TOKEN is a known Settings field - must be recognized via settings even when
    absent from raw os.environ (the bug this fix addresses)."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(settings, "github_token", SecretStr("configured-only-in-settings"))

    report = SourcePackImportReport()
    item = _to_import_item(_definition(type="github_org", adapter="github_api", auth="GITHUB_TOKEN"), report)

    assert item is not None
    assert report.auth_excluded == 0
