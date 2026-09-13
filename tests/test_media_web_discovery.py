"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 sections 5/6/7/8: services.media_web_discovery."""
from __future__ import annotations

import pytest

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from schemas.media_subject_match import DiscoveryTier, MediaUsageClassification
from services.media_web_discovery import (
    NullWebDiscoveryClient,
    ResolvedPageImage,
    WebSearchHit,
    classify_discovery_tier,
    classify_usage,
    discover_web_candidates,
)


def _intent() -> MediaIntent:
    return MediaIntent(
        subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", model_name="iPhone Duo",
        company="Apple", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
    )


class _FakeClient:
    """Deterministic fake - never issues a real network call. `hits_by_query` is keyed by the
    REAL query strings `generate_search_queries()` will actually produce for a given intent, so
    tests that need a specific query -> hit mapping must use those real strings (never an
    arbitrary placeholder the pipeline would never actually generate)."""

    def __init__(self, hits_by_query: dict[str, list[WebSearchHit]], resolved_by_url: dict[str, ResolvedPageImage]) -> None:
        self._hits_by_query = hits_by_query
        self._resolved_by_url = resolved_by_url
        self.search_calls: list[str] = []

    async def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
        self.search_calls.append(query)
        return self._hits_by_query.get(query, [])[:max_results]

    async def resolve_page_image(self, hit: WebSearchHit) -> ResolvedPageImage | None:
        return self._resolved_by_url.get(hit.result_url)


class _AllQueriesReturnSameSequenceClient:
    """A different fake, for tests that only care about cross-query dedup, not about which exact
    query string triggered which hit - returns `hits[0]` on its first call, `hits[1]` on its
    second, regardless of the query text (never hard-codes a query string that a future change to
    generate_search_queries() could silently break)."""

    def __init__(self, hits: list[WebSearchHit], resolved_by_url: dict[str, ResolvedPageImage]) -> None:
        self._hits = hits
        self._resolved_by_url = resolved_by_url
        self._call_count = 0

    async def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
        if self._call_count >= len(self._hits):
            return []
        hit = self._hits[self._call_count]
        self._call_count += 1
        return [hit][:max_results]

    async def resolve_page_image(self, hit: WebSearchHit) -> ResolvedPageImage | None:
        return self._resolved_by_url.get(hit.result_url)


@pytest.mark.asyncio
async def test_null_client_discovers_nothing_zero_network() -> None:
    candidates = await discover_web_candidates(_intent(), NullWebDiscoveryClient())
    assert candidates == []


def test_classify_discovery_tier_official_domain() -> None:
    assert classify_discovery_tier("apple.com", official_domains=frozenset({"apple.com"})) is DiscoveryTier.TIER2_OFFICIAL_PRIMARY


def test_classify_discovery_tier_known_editorial_domain() -> None:
    assert classify_discovery_tier("macrumors.com") is DiscoveryTier.TIER3_CORROBORATING_EDITORIAL


def test_classify_discovery_tier_unknown_domain_is_generic_web() -> None:
    assert classify_discovery_tier("some-random-blog.example") is DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY


def test_classify_usage_stock_photo_domain_is_not_usable() -> None:
    assert classify_usage("gettyimages.com", DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY) is MediaUsageClassification.NOT_USABLE


def test_classify_usage_official_domain_is_official_press_asset() -> None:
    assert classify_usage("apple.com", DiscoveryTier.TIER2_OFFICIAL_PRIMARY) is MediaUsageClassification.OFFICIAL_PRESS_ASSET


def test_classify_usage_unknown_domain_defaults_to_review_required_never_not_usable() -> None:
    assert classify_usage("some-random-blog.example", DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY) is MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_discover_web_candidates_resolves_real_provenance_never_a_bare_thumbnail() -> None:
    intent = _intent()
    hit = WebSearchHit(query="Apple iPhone Duo", result_url="https://www.macrumors.com/article", title="Apple Announces iPhone Duo")
    resolved = ResolvedPageImage(
        origin_url="https://www.macrumors.com/article", asset_url="https://images.macrumors.com/iphone-duo.jpg",
        publisher_domain="macrumors.com", caption_or_alt="iphone duo",
    )
    client = _FakeClient(hits_by_query={"Apple iPhone Duo": [hit]}, resolved_by_url={"https://www.macrumors.com/article": resolved})

    candidates = await discover_web_candidates(intent, client)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.provenance.asset_url == resolved.asset_url
    assert candidate.provenance.discovery_tier is DiscoveryTier.TIER3_CORROBORATING_EDITORIAL
    assert candidate.provenance.discovery_query == "Apple iPhone Duo"
    assert candidate.usage_classification is MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_discover_web_candidates_deduplicates_the_same_asset_url_across_queries() -> None:
    intent = _intent()
    hit1 = WebSearchHit(query="q1", result_url="https://a.example/page1", title="t1")
    hit2 = WebSearchHit(query="q2", result_url="https://a.example/page2", title="t2")
    same_asset = ResolvedPageImage(
        origin_url="https://a.example/pageX", asset_url="https://a.example/same.jpg", publisher_domain="a.example",
    )
    client = _AllQueriesReturnSameSequenceClient(
        hits=[hit1, hit2],
        resolved_by_url={"https://a.example/page1": same_asset, "https://a.example/page2": same_asset},
    )

    candidates = await discover_web_candidates(intent, client, max_query_variants=5)
    asset_urls = {c.provenance.asset_url for c in candidates}
    assert len(asset_urls) == 1
    assert len(candidates) == 1  # the second, same-asset hit never becomes a second candidate


@pytest.mark.asyncio
async def test_unresolved_hit_is_skipped_never_becomes_a_candidate() -> None:
    intent = _intent()
    hit = WebSearchHit(query="q", result_url="https://dead.example/page", title="t")
    client = _FakeClient(hits_by_query={"q": [hit]}, resolved_by_url={})

    candidates = await discover_web_candidates(intent, client)
    assert candidates == []
