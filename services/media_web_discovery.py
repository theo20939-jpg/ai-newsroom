"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 sections 5/6/7/8: Tier 2-4 web-based media discovery
- the layer that does NOT exist anywhere in this codebase today (confirmed by direct code audit:
`services/image_intelligence.py` only ever fetches the NewsEvent's OWN article URL; there is no
search-engine/press-kit/stock-photo client anywhere in this repo).

Section 6's own instruction - "the search result thumbnail itself is not sufficient evidence" -
is why this module is two steps, not one: `WebDiscoveryClient.search()` only locates candidate
PAGES; `WebDiscoveryClient.resolve_page_image()` then resolves the actual origin page (publisher,
caption/alt, the real asset URL) before anything downstream ever treats a hit as a candidate.

`NullWebDiscoveryClient` is the production-safe default (section 25 of this phase's own spec: no
new external network capability is switched live by this phase) - it returns nothing, exactly like
`image_intelligence_mode="off"`/`media_vision_review_mode="off"` are true no-ops elsewhere in this
codebase. A real backend (this phase's own canary uses one backed by an operator's own web-search
tool calls, disclosed in the report) can be swapped in later behind the same Protocol without
touching anything downstream (scoring/selection never know which implementation ran)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import DiscoveryTier, MediaProvenance, MediaUsageClassification, ResolvedMediaCandidate
from services.media_query_generation import generate_search_queries

MAX_RESULTS_PER_QUERY = 5


class WebSearchHit(BaseModel):
    """One search-result-page reference - never itself an image asset (section 6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(max_length=300)
    result_url: str = Field(max_length=2000)
    title: str = Field(max_length=500)
    snippet: str | None = Field(default=None, max_length=1000)


class ResolvedPageImage(BaseModel):
    """The output of actually resolving a hit's origin page - section 6/7's real evidence, not a
    thumbnail guess."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin_url: str = Field(max_length=2000)
    asset_url: str = Field(max_length=2000)
    publisher_domain: str = Field(max_length=255)
    caption_or_alt: str | None = Field(default=None, max_length=500)
    page_title: str | None = Field(default=None, max_length=500)
    published_date_text: str | None = Field(default=None, max_length=100)


class WebDiscoveryClient(Protocol):
    async def search(self, query: str, *, max_results: int) -> list[WebSearchHit]: ...

    async def resolve_page_image(self, hit: WebSearchHit) -> ResolvedPageImage | None: ...


class NullWebDiscoveryClient:
    """The real, production-safe default - zero network calls, zero results, always. Mirrors
    `services/instagram_publish_adapter.py::ShadowInstagramPublishClient`'s own "identical
    Protocol, deterministic, inert" shape, except this is the OFF state, not a shadow-success
    simulation - there is nothing to simulate discovering."""

    async def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
        return []

    async def resolve_page_image(self, hit: WebSearchHit) -> ResolvedPageImage | None:
        return None


# Section 8: a conservative, disclosed, NON-exhaustive domain heuristic - never a legal
# determination. Extending either list is safe (additive, no behavior change for domains already
# classified); a domain absent from both defaults to EDITORIAL_REVIEW_REQUIRED, the safe default.
_STOCK_OR_NOT_USABLE_DOMAINS = frozenset({
    "gettyimages.com", "shutterstock.com", "alamy.com", "istockphoto.com", "depositphotos.com",
    "123rf.com", "dreamstime.com",
})

# A small, disclosed allowlist of publishers this codebase already treats as reputable editorial
# sources elsewhere (services/news_source.py-style reliability scoring exists for RSS ingestion;
# this is a separate, narrower list for the specific "is this a corroborating editorial outlet"
# question section 5's Tier 3 asks - deliberately not reused 1:1 from the ingestion source list,
# which scores RECENCY/RELIABILITY for a different purpose).
_KNOWN_EDITORIAL_DOMAINS = frozenset({
    "theverge.com", "engadget.com", "techcrunch.com", "macrumors.com", "9to5mac.com", "9to5google.com",
    "cnet.com", "arstechnica.com", "wired.com", "reuters.com", "apnews.com", "bloomberg.com",
    "nbcnews.com", "gsmarena.com", "phonearena.com", "androidauthority.com",
})


def _registrable_domain(url: str) -> str:
    """Same naive last-two-label heuristic services/image_relevance.py::_registrable_domain()
    already uses elsewhere in this codebase - kept consistent rather than inventing a second,
    divergent domain-parsing rule."""
    host = (urlsplit(url).hostname or "").lower()
    host = re.sub(r"^www\.", "", host)
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_discovery_tier(domain: str, *, official_domains: frozenset[str] = frozenset()) -> DiscoveryTier:
    if domain in official_domains:
        return DiscoveryTier.TIER2_OFFICIAL_PRIMARY
    if domain in _KNOWN_EDITORIAL_DOMAINS:
        return DiscoveryTier.TIER3_CORROBORATING_EDITORIAL
    return DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY


def classify_usage(domain: str, tier: DiscoveryTier) -> MediaUsageClassification:
    """Section 8 - explicitly not a copyright detector. A stock-photo domain is the one case this
    heuristic hard-disqualifies; everything else maps from its own discovery tier."""
    if domain in _STOCK_OR_NOT_USABLE_DOMAINS:
        return MediaUsageClassification.NOT_USABLE
    if tier is DiscoveryTier.TIER2_OFFICIAL_PRIMARY:
        return MediaUsageClassification.OFFICIAL_PRESS_ASSET
    return MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED


async def discover_web_candidates(
    intent: MediaIntent, client: WebDiscoveryClient, *,
    max_query_variants: int = 5, max_results_per_query: int = MAX_RESULTS_PER_QUERY,
    official_domains: frozenset[str] = frozenset(),
) -> list[ResolvedMediaCandidate]:
    """Section 5 Tiers 2-4 in one pass (tier is assigned per-result from its own resolved domain,
    not per-query) + section 7's provenance requirement enforced structurally - a candidate is
    only ever constructed from a real `ResolvedPageImage`, never from a bare `WebSearchHit`."""
    queries = generate_search_queries(intent, max_variants=max_query_variants)
    candidates: list[ResolvedMediaCandidate] = []
    seen_asset_urls: set[str] = set()

    for query in queries:
        hits = await client.search(query, max_results=max_results_per_query)
        for hit in hits:
            resolved = await client.resolve_page_image(hit)
            if resolved is None:
                continue
            if resolved.asset_url in seen_asset_urls:
                continue
            seen_asset_urls.add(resolved.asset_url)

            domain = resolved.publisher_domain or _registrable_domain(resolved.origin_url)
            tier = classify_discovery_tier(domain, official_domains=official_domains)
            usage = classify_usage(domain, tier)

            candidates.append(
                ResolvedMediaCandidate(
                    candidate_id=f"web:{len(candidates)}:{domain}",
                    provenance=MediaProvenance(
                        origin_url=resolved.origin_url, asset_url=resolved.asset_url,
                        publisher_domain=domain, discovery_query=query,
                        discovered_at=datetime.now(timezone.utc), discovery_tier=tier,
                        caption_or_alt=resolved.caption_or_alt,
                    ),
                    usage_classification=usage,
                )
            )
    return candidates
