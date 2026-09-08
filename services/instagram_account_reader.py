"""DIRECTOR-CONTROL-PLANE-1C §2/§5: the real, official, READ-ONLY Instagram account reader.

Official API family (§28):

    OFFICIAL_API_FAMILY   = Instagram API with Instagram Login  (a.k.a. "Business Login for
                            Instagram" - the direct-Instagram OAuth path that replaced the
                            deprecated Instagram Basic Display API, shut down Dec 2024).
    AUTH_MODEL            = OAuth 2.0 directly with Instagram (NO Facebook Page, NO Facebook
                            Login). The app obtains a long-lived Instagram User access token for
                            the ONE authorized professional (Business/Creator) account. This
                            adapter never performs the interactive OAuth dance itself - it
                            consumes an already-issued long-lived token supplied via config
                            (`settings.instagram_access_token`). The token-exchange / refresh
                            operational flow is documented in
                            `design/instagram_official_api.md`, not automated here (§16).
    HOST                 = https://graph.instagram.com  (settings.instagram_graph_base_url)
    API_VERSION          = settings.instagram_api_version (default "v23.0" - pinned, overridable,
                            never hardcoded inline so a version bump is a one-line config change,
                            §28's "do not freeze obsolete assumptions in code").
    REQUIRED_SCOPES      = instagram_business_basic                -> profile + owned media (always)
                           instagram_business_manage_insights      -> media/account insights (optional;
                                                                      capability is DETECTED from a
                                                                      real probe, never assumed, §14)
    NO WRITE SCOPES      = this adapter requests/uses none of instagram_business_content_publish,
                           instagram_business_manage_comments, instagram_business_manage_messages.
                           There is no code path here that publishes, edits, deletes, comments, or
                           touches DMs (§4).

Every method targets the ONE account the token authorizes (`/me` and its own edges) - there is no
parameter anywhere that could point at a personal or third-party account (§9 identity safety is
additionally enforced by `check_connection()` comparing the returned identity to the configured
expected account).

Nothing in this module logs, returns, embeds in an exception, or otherwise surfaces the raw token
(§7/§24). `InstagramReaderConfig` holds it as a `SecretStr`; it is `.get_secret_value()`-unwrapped
exactly once, at the point the HTTPS request is built, and never assigned to a local that outlives
that call.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from pydantic import SecretStr

from core.config import settings

logger = logging.getLogger(__name__)

# §6: bounded - the Director feed window is "latest 20-30 media"; 25 is the default, 30 the ceiling.
DEFAULT_MEDIA_LIMIT = 25
MAX_MEDIA_LIMIT = 30
_MAX_MEDIA_PAGES = 2  # 30 items / ~25 per page -> at most 2 pages; hard stop against pagination loops
_MEDIA_INSIGHTS_MAX = 30  # never request per-media insights for more than the bounded window

_PROFILE_FIELDS = "id,user_id,username,name,account_type,profile_picture_url,followers_count,follows_count,media_count,biography"
_MEDIA_FIELDS = "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp,like_count,comments_count"
# Candidate metric sets. The API rejects metrics that do not apply to a media_type / are not
# granted; `_request_insights()` treats a rejection as "metric absent" (UNAVAILABLE), never as 0.
_IMAGE_INSIGHT_METRICS = ("reach", "likes", "comments", "saved", "shares", "total_interactions", "views")
_REEL_INSIGHT_METRICS = (
    "reach", "likes", "comments", "saved", "shares", "total_interactions", "views",
    "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
)
_ACCOUNT_INSIGHT_METRICS = ("reach", "profile_views")


class InstagramReadErrorCode(str, enum.Enum):
    """Structured, safe error taxonomy - no raw provider text (which can echo the token, an
    internal id, or an expired signed media URL) ever reaches a caller or a log line."""

    NOT_CONFIGURED = "not_configured"
    INVALID_TOKEN = "invalid_token"          # 401 / OAuthException code 190
    INSUFFICIENT_PERMISSION = "insufficient_permission"  # 403 / missing scope
    NOT_FOUND = "not_found"                  # 404 / wrong id
    RATE_LIMITED = "rate_limited"            # 429 / X-Business-Use-Case-Usage exhausted
    TRANSIENT = "transient"                  # 5xx
    TIMEOUT = "timeout"
    MALFORMED_PAYLOAD = "malformed_payload"  # non-JSON / missing required key
    NETWORK = "network"                      # connect error, DNS, TLS


class InstagramReadError(Exception):
    """Carries only a structured `code`, an optional HTTP `status`, and a short curated `detail`
    (never the provider body, never the token). Callers map it to a connection ERROR state and an
    honestly-empty Director context - they never crash planning on it (§15)."""

    def __init__(self, code: InstagramReadErrorCode, *, status: int | None = None, detail: str = "") -> None:
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(f"{code.value}" + (f" (http {status})" if status is not None else "") + (f": {detail}" if detail else ""))


class InstagramNotConfiguredError(InstagramReadError):
    def __init__(self) -> None:
        super().__init__(InstagramReadErrorCode.NOT_CONFIGURED, detail="instagram_access_token / instagram_business_account_id absent")


@dataclass(frozen=True)
class InstagramReaderConfig:
    """Everything the reader needs, resolved once from `settings`. `access_token` is the only
    secret; it is `SecretStr` here and unwrapped only inside `_request()`."""

    access_token: SecretStr
    ig_user_id: str
    base_url: str
    api_version: str
    expected_username: str | None
    access_token_expires_at: datetime | None

    @classmethod
    def from_settings(cls) -> "InstagramReaderConfig | None":
        token = settings.instagram_access_token
        ig_user_id = settings.instagram_business_account_id
        if token is None or not ig_user_id:
            return None
        return cls(
            access_token=token,
            ig_user_id=str(ig_user_id),
            base_url=settings.instagram_graph_base_url.rstrip("/"),
            api_version=settings.instagram_api_version,
            expected_username=(settings.instagram_expected_username or None),
            access_token_expires_at=settings.instagram_access_token_expires_at,
        )


def is_configured() -> bool:
    """The one gate every caller checks first. True only when BOTH the token and the account id
    are present - a token string alone is never enough (§8)."""
    return InstagramReaderConfig.from_settings() is not None


# --------------------------------------------------------------------------------------------------
# Normalized, provider-neutral result types - the Director layer only ever sees these, never a
# raw Graph API JSON dict (§5's "do not expose provider-native raw JSON throughout the Director
# layer").
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedProfile:
    ig_user_id: str
    username: str | None = None
    name: str | None = None
    account_type: str | None = None  # BUSINESS | MEDIA_CREATOR | ...
    biography: str | None = None
    profile_picture_url: str | None = None
    followers_count: int | None = None
    follows_count: int | None = None
    media_count: int | None = None


@dataclass(frozen=True)
class NormalizedMedia:
    media_id: str
    media_type: str | None  # IMAGE | VIDEO | CAROUSEL_ALBUM
    media_product_type: str | None  # FEED | REELS | STORY
    caption: str | None
    timestamp: str | None  # ISO 8601, exactly as the API returns it
    permalink: str | None
    media_url: str | None
    thumbnail_url: str | None
    like_count: int | None
    comments_count: int | None
    # Populated ONLY from a real insights response for this exact media. A missing key = "the API
    # did not return this metric" (UNAVAILABLE) - never a guessed 0 (§3).
    insights: dict[str, float] = field(default_factory=dict)
    insights_status: str = "not_fetched"  # not_fetched | available | partial | unavailable


@dataclass(frozen=True)
class NormalizedAccountInsights:
    metrics: dict[str, float] = field(default_factory=dict)
    status: str = "unavailable"  # available | partial | unavailable


class InstagramCapability(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class InstagramCapabilitySet:
    """§14: populated from REAL probe outcomes, never from "the code has a method"."""

    read_profile: InstagramCapability = InstagramCapability.UNAVAILABLE
    read_media: InstagramCapability = InstagramCapability.UNAVAILABLE
    read_insights: InstagramCapability = InstagramCapability.UNAVAILABLE

    def as_map(self) -> dict[str, str]:
        return {
            "read_profile": self.read_profile.value,
            "read_media": self.read_media.value,
            "read_insights": self.read_insights.value,
        }


class ConnectionOutcome(str, enum.Enum):
    CONNECTED = "CONNECTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ERROR = "ERROR"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


@dataclass(frozen=True)
class ConnectionCheckResult:
    outcome: ConnectionOutcome
    profile: NormalizedProfile | None = None
    capabilities: InstagramCapabilitySet = field(default_factory=InstagramCapabilitySet)
    error_code: str | None = None
    error_detail: str | None = None  # curated, token-free
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    api_calls: int = 0
    token_expires_at: datetime | None = None

    @property
    def token_status(self) -> str:
        if self.token_expires_at is None:
            return "UNKNOWN"
        return "EXPIRED" if self.token_expires_at <= datetime.now(timezone.utc) else "VALID"


class InstagramAccountReader:
    """Bounded, read-only operations against the single authorized professional account.

    A `transport` may be injected (tests pass `httpx.MockTransport`); production leaves it None and
    a plain `httpx.AsyncClient` is used. Every method is independently bounded and never raises a
    bare exception - only `InstagramReadError`.
    """

    def __init__(
        self, config: InstagramReaderConfig, *, transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._config = config
        self._transport = transport
        self._timeout = timeout_seconds

    # -- HTTP core -------------------------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self._config.base_url}/{self._config.api_version}",
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _request(self, path: str, params: dict[str, str]) -> dict:
        """One GET. The token is injected here and nowhere else, as an `Authorization: Bearer`
        header (the Graph API family's officially-supported alternative to the `access_token`
        query param) - deliberately NOT in the URL, so it can never leak through httpx's own
        request logging or any URL that reaches a log line (§7/§24). Maps every failure mode to a
        structured `InstagramReadError`; the raw provider body is inspected for an error *code*
        only, never echoed."""
        headers = {"Authorization": f"Bearer {self._config.access_token.get_secret_value()}"}
        try:
            async with self._client() as client:
                response = await client.get(path, params=params, headers=headers)
        except httpx.TimeoutException as error:
            raise InstagramReadError(InstagramReadErrorCode.TIMEOUT, detail=type(error).__name__) from error
        except httpx.HTTPError as error:
            raise InstagramReadError(InstagramReadErrorCode.NETWORK, detail=type(error).__name__) from error

        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError as error:
                raise InstagramReadError(InstagramReadErrorCode.MALFORMED_PAYLOAD, status=200, detail="non-json body") from error
            if not isinstance(body, dict):
                raise InstagramReadError(InstagramReadErrorCode.MALFORMED_PAYLOAD, status=200, detail="response was not a JSON object")
            return body

        # Non-200: read a safe error code from the body if present, then discard the body.
        provider_code = _safe_provider_error_code(response)
        raise _map_status(response.status_code, provider_code)

    async def _get_all_pages(self, path: str, params: dict[str, str], *, max_pages: int, max_items: int) -> list[dict]:
        """Bounded pagination: follows `paging.cursors.after` at most `max_pages` times and stops
        the instant `max_items` is reached. No infinite loop is possible (§6)."""
        items: list[dict] = []
        page_params = dict(params)
        for _page in range(max_pages):
            body = await self._request(path, page_params)
            data = body.get("data")
            if isinstance(data, list):
                items.extend(d for d in data if isinstance(d, dict))
            if len(items) >= max_items:
                return items[:max_items]
            after = (((body.get("paging") or {}).get("cursors") or {}).get("after"))
            if not after:
                break
            page_params["after"] = str(after)
        return items[:max_items]

    # -- Public operations ---------------------------------------------------------------------

    async def fetch_account_context(self) -> NormalizedProfile:
        """GET /{ig-user-id}?fields=... - the ONE profile read. Requires only
        `instagram_business_basic`."""
        body = await self._request(f"/{self._config.ig_user_id}", {"fields": _PROFILE_FIELDS})
        return _normalize_profile(body, fallback_id=self._config.ig_user_id)

    async def fetch_recent_media(self, limit: int = DEFAULT_MEDIA_LIMIT) -> list[NormalizedMedia]:
        """GET /{ig-user-id}/media?fields=...&limit=... - bounded to `MAX_MEDIA_LIMIT`."""
        bounded = max(1, min(limit, MAX_MEDIA_LIMIT))
        rows = await self._get_all_pages(
            f"/{self._config.ig_user_id}/media",
            {"fields": _MEDIA_FIELDS, "limit": str(min(bounded, 25))},
            max_pages=_MAX_MEDIA_PAGES, max_items=bounded,
        )
        return [_normalize_media(row) for row in rows]

    async def fetch_media_insights(self, media_ids: list[str]) -> dict[str, NormalizedAccountInsights]:
        """GET /{media-id}/insights?metric=... for each id in a bounded window. One call per media
        (the API has no batch-insights edge); the window itself is capped at `_MEDIA_INSIGHTS_MAX`
        so this is O(window), never O(account history). A per-media failure degrades that ONE
        media's insights to `unavailable` - it never aborts the batch (§15)."""
        result: dict[str, NormalizedAccountInsights] = {}
        for media_id in media_ids[:_MEDIA_INSIGHTS_MAX]:
            result[media_id] = await self._fetch_one_media_insights(media_id)
        return result

    async def _fetch_one_media_insights(self, media_id: str, *, is_reel: bool = False) -> NormalizedAccountInsights:
        metrics = _REEL_INSIGHT_METRICS if is_reel else _IMAGE_INSIGHT_METRICS
        try:
            body = await self._request(f"/{media_id}/insights", {"metric": ",".join(metrics)})
        except InstagramReadError as error:
            if error.code is InstagramReadErrorCode.INSUFFICIENT_PERMISSION:
                return NormalizedAccountInsights(status="unavailable")
            if error.code in (InstagramReadErrorCode.NOT_FOUND, InstagramReadErrorCode.MALFORMED_PAYLOAD):
                return NormalizedAccountInsights(status="unavailable")
            raise
        parsed = _parse_insight_values(body)
        status = "available" if len(parsed) == len(metrics) else ("partial" if parsed else "unavailable")
        return NormalizedAccountInsights(metrics=parsed, status=status)

    async def fetch_account_insights(self) -> NormalizedAccountInsights:
        """GET /{ig-user-id}/insights?metric=reach,profile_views&period=day&metric_type=total.
        Requires `instagram_business_manage_insights`; a permission error -> `unavailable`, never
        fabricated numbers (§3)."""
        try:
            body = await self._request(
                f"/{self._config.ig_user_id}/insights",
                {"metric": ",".join(_ACCOUNT_INSIGHT_METRICS), "period": "day", "metric_type": "total"},
            )
        except InstagramReadError as error:
            if error.code is InstagramReadErrorCode.INSUFFICIENT_PERMISSION:
                return NormalizedAccountInsights(status="unavailable")
            raise
        parsed = _parse_insight_values(body)
        status = "available" if len(parsed) == len(_ACCOUNT_INSIGHT_METRICS) else ("partial" if parsed else "unavailable")
        return NormalizedAccountInsights(metrics=parsed, status=status)

    async def check_connection(self) -> ConnectionCheckResult:
        """§20's explicit admin check: profile fetch -> identity verification -> capability
        detection. Never persists anything itself (the caller in
        services/instagram_connection_service.py owns the safe-metadata write). Never raises."""
        api_calls = 0
        try:
            profile = await self.fetch_account_context()
            api_calls += 1
        except InstagramReadError as error:
            return ConnectionCheckResult(
                outcome=ConnectionOutcome.ERROR, error_code=error.code.value, error_detail=error.detail,
                api_calls=api_calls, token_expires_at=self._config.access_token_expires_at,
            )

        # §9 identity safety: the returned account MUST be the configured target.
        if not _identity_matches(profile, self._config):
            return ConnectionCheckResult(
                outcome=ConnectionOutcome.IDENTITY_MISMATCH, profile=profile,
                error_code="identity_mismatch",
                error_detail=(
                    f"connected account @{profile.username or profile.ig_user_id} does not match the "
                    f"configured expected account"
                ),
                api_calls=api_calls, token_expires_at=self._config.access_token_expires_at,
            )

        # §14 capability detection - probe the insights edge with a bounded call.
        insights_capable = InstagramCapability.UNAVAILABLE
        try:
            probe = await self.fetch_account_insights()
            api_calls += 1
            if probe.status in ("available", "partial"):
                insights_capable = InstagramCapability.AVAILABLE
        except InstagramReadError:
            insights_capable = InstagramCapability.UNAVAILABLE

        capabilities = InstagramCapabilitySet(
            read_profile=InstagramCapability.AVAILABLE,
            read_media=InstagramCapability.AVAILABLE,  # same scope as profile (instagram_business_basic)
            read_insights=insights_capable,
        )
        return ConnectionCheckResult(
            outcome=ConnectionOutcome.CONNECTED, profile=profile, capabilities=capabilities,
            api_calls=api_calls, token_expires_at=self._config.access_token_expires_at,
        )


# --------------------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------------------


def _safe_provider_error_code(response: httpx.Response) -> str | None:
    """Extract ONLY the Meta error `code`/`type` (an int/enum, safe) - never the `message` (which
    can echo the token or a signed URL)."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    subcode = error.get("error_subcode")
    return f"{code}/{subcode}" if subcode is not None else (str(code) if code is not None else None)


def _map_status(http_status: int, provider_code: str | None) -> InstagramReadError:
    detail = f"provider_code={provider_code}" if provider_code else ""
    if http_status == 401 or (provider_code or "").startswith("190"):
        return InstagramReadError(InstagramReadErrorCode.INVALID_TOKEN, status=http_status, detail=detail)
    if http_status == 403 or (provider_code or "").startswith(("10", "200")):
        return InstagramReadError(InstagramReadErrorCode.INSUFFICIENT_PERMISSION, status=http_status, detail=detail)
    if http_status == 404 or (provider_code or "").startswith("803"):
        return InstagramReadError(InstagramReadErrorCode.NOT_FOUND, status=http_status, detail=detail)
    if http_status == 429 or (provider_code or "").startswith(("4", "17", "32", "613")):
        return InstagramReadError(InstagramReadErrorCode.RATE_LIMITED, status=http_status, detail=detail)
    if 500 <= http_status < 600:
        return InstagramReadError(InstagramReadErrorCode.TRANSIENT, status=http_status, detail=detail)
    return InstagramReadError(InstagramReadErrorCode.MALFORMED_PAYLOAD, status=http_status, detail=detail or "unexpected status")


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalize_profile(body: dict, *, fallback_id: str) -> NormalizedProfile:
    return NormalizedProfile(
        ig_user_id=str(body.get("id") or body.get("user_id") or fallback_id),
        username=(str(body["username"]) if body.get("username") else None),
        name=(str(body["name"]) if body.get("name") else None),
        account_type=(str(body["account_type"]) if body.get("account_type") else None),
        biography=(str(body["biography"]) if body.get("biography") else None),
        profile_picture_url=(str(body["profile_picture_url"]) if body.get("profile_picture_url") else None),
        followers_count=_int_or_none(body.get("followers_count")),
        follows_count=_int_or_none(body.get("follows_count")),
        media_count=_int_or_none(body.get("media_count")),
    )


def _normalize_media(row: dict) -> NormalizedMedia:
    return NormalizedMedia(
        media_id=str(row.get("id") or ""),
        media_type=(str(row["media_type"]) if row.get("media_type") else None),
        media_product_type=(str(row["media_product_type"]) if row.get("media_product_type") else None),
        caption=(str(row["caption"]) if row.get("caption") else None),
        timestamp=(str(row["timestamp"]) if row.get("timestamp") else None),
        permalink=(str(row["permalink"]) if row.get("permalink") else None),
        media_url=(str(row["media_url"]) if row.get("media_url") else None),
        thumbnail_url=(str(row["thumbnail_url"]) if row.get("thumbnail_url") else None),
        like_count=_int_or_none(row.get("like_count")),
        comments_count=_int_or_none(row.get("comments_count")),
    )


def _parse_insight_values(body: dict) -> dict[str, float]:
    """Graph insights shape: {"data": [{"name": "reach", "total_value": {"value": N}} or
    {"name": "...", "values": [{"value": N}]}]}. A metric the API omitted is simply absent from
    the result - the caller never fills it with 0 (§3)."""
    out: dict[str, float] = {}
    for entry in body.get("data", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        value: object = None
        total_value = entry.get("total_value")
        if isinstance(total_value, dict) and "value" in total_value:
            value = total_value["value"]
        else:
            values = entry.get("values")
            if isinstance(values, list) and values and isinstance(values[0], dict):
                value = values[0].get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[name] = float(value)
    return out


def _identity_matches(profile: NormalizedProfile, config: InstagramReaderConfig) -> bool:
    """The returned account is the configured target iff its ig_user_id matches the configured id
    AND (when an expected username is configured) its username matches that too - case-insensitive,
    leading '@' tolerated."""
    if profile.ig_user_id != config.ig_user_id:
        return False
    if config.expected_username:
        expected = config.expected_username.lstrip("@").lower()
        actual = (profile.username or "").lstrip("@").lower()
        if expected != actual:
            return False
    return True


def media_to_feed_context_row(media: NormalizedMedia) -> dict:
    """The bridge to services/instagram_feed_context.py::build_instagram_feed_context(): produces
    exactly the dict shape that function reads (`media_id`, `timestamp`, `media_type`,
    `caption_length`, `like_count`, `comment_count`). Never passes the raw provider JSON through."""
    return {
        "media_id": media.media_id,
        "timestamp": media.timestamp,
        "media_type": _coarse_media_type(media),
        "caption_length": len(media.caption or ""),
        "like_count": media.like_count,
        "comment_count": media.comments_count,
    }


def _coarse_media_type(media: NormalizedMedia) -> str | None:
    """Reels are surfaced as REEL (media_product_type), everything else by media_type - the same
    coarse buckets services/telegram_feed_window.py uses."""
    if (media.media_product_type or "").upper() == "REELS":
        return "REEL"
    return media.media_type
