"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 6: YouTube Trend Radar source adapter.

Uses the official YouTube Data API v3 (search.list scoped by a TrendDiscoveryScope's own
`all_terms`, then videos.list for the real statistics YouTube's own API returns) - never scrapes,
never estimates a metric the API doesn't return. Shadow-only this phase: `settings.
trend_collection_enabled` stays False by default and nothing in worker/content_cycle.py calls
this adapter yet - wiring it into a live collection cycle is explicit future work, gated on
Founder-approved thresholds observed against real data (see services/trend_evidence_ranking.py).

A missing/unset `settings.youtube_api_key` is not an error condition to work around - callers are
expected to catch `TrendSourceNotConfigured` and skip this source, exactly like a Gateway
fail-soft path elsewhere in this phase (never a reason to return fabricated candidates)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from core.config import settings
from services.trend_fingerprint import TrendSignalCandidate, TrendSourceNotConfigured
from services.trend_source_scope import TrendDiscoveryScope

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
MAX_RESULTS_PER_TERM = 10
MAX_TERMS_PER_CYCLE = 8
_STATISTIC_KEYS = ("viewCount", "likeCount", "commentCount")


class YouTubeTrendSourceAdapter:
    """Fetches recent, real YouTube video engagement signals for a TrendDiscoveryScope's terms."""

    async def fetch_candidates(self, scope: TrendDiscoveryScope) -> list[TrendSignalCandidate]:
        if not settings.youtube_api_key:
            raise TrendSourceNotConfigured("settings.youtube_api_key is not set")
        api_key = settings.youtube_api_key.get_secret_value()

        candidates: list[TrendSignalCandidate] = []
        seen_video_ids: set[str] = set()
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            for term in scope.all_terms[:MAX_TERMS_PER_CYCLE]:
                video_ids = await self._search_video_ids(client, api_key, term)
                new_ids = [vid for vid in video_ids if vid not in seen_video_ids]
                if not new_ids:
                    continue
                seen_video_ids.update(new_ids)
                candidates.extend(await self._fetch_video_details(client, api_key, new_ids))
        return candidates

    async def _search_video_ids(self, client: httpx.AsyncClient, api_key: str, term: str) -> list[str]:
        params: dict[str, str | int] = {
            "part": "id", "q": term, "type": "video", "order": "viewCount",
            "maxResults": MAX_RESULTS_PER_TERM, "key": api_key,
        }
        try:
            response = await client.get(SEARCH_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("YouTube search failed for term %r: %s", term, exc)
            return []
        payload = response.json()
        return [
            item["id"]["videoId"] for item in payload.get("items", [])
            if isinstance(item.get("id"), dict) and item["id"].get("videoId")
        ]

    async def _fetch_video_details(
        self, client: httpx.AsyncClient, api_key: str, video_ids: list[str],
    ) -> list[TrendSignalCandidate]:
        params = {"part": "snippet,statistics", "id": ",".join(video_ids), "key": api_key}
        try:
            response = await client.get(VIDEOS_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("YouTube videos.list failed for %d ids: %s", len(video_ids), exc)
            return []

        results: list[TrendSignalCandidate] = []
        for item in response.json().get("items", []):
            video_id = item.get("id")
            snippet = item.get("snippet") or {}
            statistics = item.get("statistics") or {}
            if not video_id or not snippet.get("title"):
                continue
            engagement_snapshot = {
                key: int(statistics[key]) for key in _STATISTIC_KEYS
                if key in statistics and str(statistics[key]).isdigit()
            }
            results.append(TrendSignalCandidate(
                source="youtube", source_item_id=video_id,
                raw_topic_text=f"{snippet.get('title', '')} {snippet.get('description', '')}".strip(),
                engagement_snapshot=engagement_snapshot,
                observed_at=datetime.now(timezone.utc),
                canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            ))
        return results
