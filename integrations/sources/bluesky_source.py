"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 6: Bluesky Trend Radar source adapter.

Uses the public AT Protocol API (app.bsky.feed.searchPosts), authenticating with an app
password via com.atproto.server.createSession exactly as Bluesky's own docs specify - never
scrapes, never estimates a metric the API doesn't return. Shadow-only this phase, same contract
as youtube_source.py: nothing in worker/content_cycle.py calls this adapter yet, and a missing/
unset `settings.bluesky_handle`/`bluesky_app_password` raises `TrendSourceNotConfigured` rather
than returning fabricated candidates."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from core.config import settings
from services.trend_fingerprint import TrendSignalCandidate, TrendSourceNotConfigured
from services.trend_source_scope import TrendDiscoveryScope

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
BASE_URL = "https://bsky.social/xrpc"
MAX_RESULTS_PER_TERM = 25
MAX_TERMS_PER_CYCLE = 8
_ENGAGEMENT_KEYS = ("likeCount", "repostCount", "replyCount")


class BlueskyTrendSourceAdapter:
    """Fetches recent, real Bluesky post engagement signals for a TrendDiscoveryScope's terms."""

    async def fetch_candidates(self, scope: TrendDiscoveryScope) -> list[TrendSignalCandidate]:
        if not settings.bluesky_handle or not settings.bluesky_app_password:
            raise TrendSourceNotConfigured("settings.bluesky_handle/bluesky_app_password are not set")

        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            access_jwt = await self._create_session(client)
            if access_jwt is None:
                return []
            headers = {"Authorization": f"Bearer {access_jwt}"}

            candidates: list[TrendSignalCandidate] = []
            seen_post_uris: set[str] = set()
            for term in scope.all_terms[:MAX_TERMS_PER_CYCLE]:
                for candidate in await self._search_posts(client, headers, term):
                    if candidate.source_item_id in seen_post_uris:
                        continue
                    seen_post_uris.add(candidate.source_item_id)
                    candidates.append(candidate)
        return candidates

    async def _create_session(self, client: httpx.AsyncClient) -> str | None:
        assert settings.bluesky_app_password is not None  # guarded by fetch_candidates
        try:
            response = await client.post(
                f"{BASE_URL}/com.atproto.server.createSession",
                json={
                    "identifier": settings.bluesky_handle,
                    "password": settings.bluesky_app_password.get_secret_value(),
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Bluesky session creation failed: %s", exc)
            return None
        return response.json().get("accessJwt")

    async def _search_posts(
        self, client: httpx.AsyncClient, headers: dict, term: str,
    ) -> list[TrendSignalCandidate]:
        params: dict[str, str | int] = {"q": term, "limit": MAX_RESULTS_PER_TERM, "sort": "top"}
        try:
            response = await client.get(f"{BASE_URL}/app.bsky.feed.searchPosts", params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Bluesky search failed for term %r: %s", term, exc)
            return []

        results: list[TrendSignalCandidate] = []
        for post in response.json().get("posts", []):
            uri = post.get("uri")
            record = post.get("record") or {}
            text = record.get("text")
            if not uri or not text:
                continue
            engagement_snapshot = {
                key: int(post[key]) for key in _ENGAGEMENT_KEYS
                if key in post and isinstance(post[key], int)
            }
            author_handle = (post.get("author") or {}).get("handle")
            post_rkey = uri.rsplit("/", 1)[-1]
            results.append(TrendSignalCandidate(
                source="bluesky", source_item_id=uri, raw_topic_text=text,
                engagement_snapshot=engagement_snapshot,
                observed_at=datetime.now(timezone.utc),
                canonical_url=f"https://bsky.app/profile/{author_handle}/post/{post_rkey}" if author_handle else None,
            ))
        return results
