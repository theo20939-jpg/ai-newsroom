"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S13/S35) - bounded web discovery, proven with a
fake client (no real external network dependency - S35's own explicit requirement). Verifies the
actual call counts/limits `discover_web_candidates()` already enforces (services/media_web_
discovery.py), never merely asserted in a comment."""
from __future__ import annotations


import pytest

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from services.media_web_discovery import ResolvedPageImage, WebSearchHit, discover_web_candidates

pytestmark = pytest.mark.asyncio

_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="Zorblex Nyquora-8", model_name="Nyquora-8",
    product_name="Zorblex", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
)


class _CountingClient:
    """Never touches the network - returns a bounded, deterministic, distinct hit per call so
    every dedup/count assertion below is unambiguous."""

    def __init__(self) -> None:
        self.search_calls: list[tuple[str, int]] = []
        self.resolve_calls = 0

    async def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
        self.search_calls.append((query, max_results))
        # Return MORE hits than max_results asks for - the client itself must be bounded by the
        # caller reading no more than `max_results`, never trusting a misbehaving client.
        return [
            WebSearchHit(query=query, result_url=f"https://x.example/{query}/{i}", title=f"hit {i}")
            for i in range(max_results + 5)
        ]

    async def resolve_page_image(self, hit: WebSearchHit) -> ResolvedPageImage | None:
        self.resolve_calls += 1
        return ResolvedPageImage(
            origin_url=hit.result_url, asset_url=hit.result_url + ".jpg", publisher_domain="x.example",
            caption_or_alt="Zorblex Nyquora-8 product photo",
        )


async def test_query_count_is_bounded_by_max_query_variants() -> None:
    client = _CountingClient()
    await discover_web_candidates(_INTENT, client, max_query_variants=3, max_results_per_query=2)
    assert len(client.search_calls) <= 3


async def test_results_per_query_are_bounded_even_when_the_client_returns_more() -> None:
    client = _CountingClient()
    candidates = await discover_web_candidates(_INTENT, client, max_query_variants=1, max_results_per_query=2)
    # The client's fake search() always returns max_results+5 raw hits, but resolve_page_image()
    # (and therefore the final candidate count) must never exceed max_results per query.
    assert client.resolve_calls <= 2
    assert len(candidates) <= 2


async def test_identical_asset_url_is_never_resolved_or_counted_twice() -> None:
    class _DuplicateHitClient(_CountingClient):
        async def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
            self.search_calls.append((query, max_results))
            return [WebSearchHit(query=query, result_url="https://x.example/same", title="same hit")] * 3

        async def resolve_page_image(self, hit: WebSearchHit) -> ResolvedPageImage | None:
            self.resolve_calls += 1
            return ResolvedPageImage(origin_url=hit.result_url, asset_url="https://x.example/same.jpg", publisher_domain="x.example")

    client = _DuplicateHitClient()
    candidates = await discover_web_candidates(_INTENT, client, max_query_variants=1, max_results_per_query=3)
    assert len(candidates) == 1  # deduplicated by asset_url - never the same asset counted 3 times
