"""INSTAGRAM-EXECUTION-FOUNDATION-1 sections 16-21: the official Instagram publication adapter,
hard-disabled by default, and a real shadow-publish path that exercises the COMPLETE flow with
ZERO network writes.

Uses the SAME official architecture `services/instagram_account_reader.py` already established -
Instagram API with Instagram Login (`graph.instagram.com`), NOT the Facebook-Page-token
architecture (section 16's own explicit instruction: only switch if the repository already
requires it - it does not; the reader never uses Facebook Login either). Read scopes
(`instagram_business_basic`, `instagram_business_manage_insights`) stay exactly as the reader
already declares them; this module's own scope
(`settings.instagram_write_scopes = ("instagram_business_content_publish",)`) is a SEPARATE,
disclosed constant, never silently merged into the read path or requested by any live OAuth flow
(section 17).

Conceptual flow modeled (section 16), matching the real Instagram Graph API media-publish
contract:

    SINGLE / CAROUSEL child:  POST {ig_user_id}/media          (image_url or is_carousel_item)
    CAROUSEL parent:          POST {ig_user_id}/media          (media_type=CAROUSEL, children=[...])
    REEL:                     POST {ig_user_id}/media          (media_type=REELS, video_url, cover)
    poll:                     GET  {container_id}?fields=status_code
    publish:                  POST {ig_user_id}/media_publish  (creation_id={container_id})

`HttpInstagramPublishClient` implements this with real `httpx` calls - present, complete, but
NEVER invoked by any test or by the shadow path in this phase (no live credential, no live call -
section 26/29). `ShadowInstagramPublishClient` implements the identical `InstagramPublishClient`
protocol deterministically, in-memory, with zero network access - the orchestration function
(`publish_instagram_content`) is IDENTICAL either way; only the injected client differs."""
from __future__ import annotations

import asyncio
import enum
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

import httpx

from core.config import settings
from services.instagram_content_package import InstagramContentPackage
from services.instagram_editorial_gate import InstagramGateOutcome

logger = logging.getLogger(__name__)

_MAX_STATUS_POLLS = 5
_MAX_RETRYABLE_ATTEMPTS = 2  # bounded - never an unbounded retry loop (section 20)
_DEFAULT_TIMEOUT_SECONDS = 15.0


class InstagramPublishErrorCode(str, enum.Enum):
    PUBLICATION_DISABLED = "publication_disabled"     # settings.instagram_publication_enabled is False
    GATE_NOT_PERMITTED = "gate_not_permitted"          # editorial gate is not READY_FOR_EDITOR
    NOT_APPROVED = "not_approved"                      # no explicit editor_approved=True for a live publish
    NOT_CONFIGURED = "not_configured"                  # no access token / account id configured
    AUTH_ERROR = "auth_error"                          # 401/403 from the provider
    INVALID_MEDIA = "invalid_media"                    # 400-class media rejection
    PROCESSING_TIMEOUT = "processing_timeout"          # container never reached FINISHED within the poll bound
    PUBLISH_FAILED = "publish_failed"                  # the publish call itself failed after a finished container
    RATE_LIMITED = "rate_limited"                      # 429 / usage-limit response
    TRANSIENT = "transient"                             # 5xx - retryable
    NETWORK = "network"                                 # connect/timeout/DNS error


_RETRYABLE_CODES = frozenset({InstagramPublishErrorCode.RATE_LIMITED, InstagramPublishErrorCode.TRANSIENT, InstagramPublishErrorCode.NETWORK})


class InstagramPublishError(Exception):
    def __init__(self, code: InstagramPublishErrorCode, *, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        self.retryable = code in _RETRYABLE_CODES
        super().__init__(f"{code.value}" + (f": {detail}" if detail else ""))


class ContainerStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    ERROR = "error"
    EXPIRED = "expired"


class PublicationStatus(str, enum.Enum):
    SHADOW_SUCCESS = "shadow_success"
    LIVE_SUCCESS = "live_success"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class PublicationResult:
    """The canonical result object (section 21). `container_ids`/`media_id` are populated only
    for a LIVE publish (shadow ids are still recorded, but `shadow=True` marks them non-real -
    never confused with a real Meta-issued id by a downstream consumer)."""

    platform: str
    account_key: str
    package_id: str
    content_format: str
    status: PublicationStatus
    shadow: bool
    container_ids: list[str] = field(default_factory=list)
    media_id: str | None = None
    failure_class: str | None = None
    retryable: bool = False
    attempts_used: int = 0
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform, "account_key": self.account_key, "package_id": self.package_id,
            "content_format": self.content_format, "status": self.status.value, "shadow": self.shadow,
            "container_ids": list(self.container_ids), "media_id": self.media_id,
            "failure_class": self.failure_class, "retryable": self.retryable, "attempts_used": self.attempts_used,
            "requested_at": self.requested_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class InstagramPublishClient(Protocol):
    """The injectable HTTP/API client boundary (section 20) - `publish_instagram_content()` never
    imports `httpx` itself or knows whether it is talking to the real API or a deterministic fake."""

    async def create_media_container(
        self, *, account_id: str, caption: str, image_ref: str | None, video_ref: str | None,
        is_carousel_item: bool, media_type: str | None,
    ) -> str: ...

    async def create_carousel_container(self, *, account_id: str, caption: str, children: list[str]) -> str: ...

    async def get_container_status(self, container_id: str) -> ContainerStatus: ...

    async def publish_container(self, *, account_id: str, container_id: str) -> str: ...


@dataclass
class HttpInstagramPublishClient:
    """The REAL official adapter - present and complete, never invoked in this phase (no test
    calls it; nothing in this phase sets `instagram_publication_enabled=True`). Mirrors
    `services/instagram_account_reader.py`'s own request/error-mapping discipline exactly: a fixed
    timeout, a structured error taxonomy, the raw provider body/token never surfaced."""

    access_token: str
    base_url: str = "https://graph.instagram.com"
    api_version: str = "v23.0"
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=f"{self.base_url}/{self.api_version}", timeout=self.timeout_seconds)

    def _map_error(self, response: httpx.Response) -> InstagramPublishError:
        status = response.status_code
        if status in (401, 403):
            return InstagramPublishError(InstagramPublishErrorCode.AUTH_ERROR, detail=f"http {status}")
        if status == 429:
            return InstagramPublishError(InstagramPublishErrorCode.RATE_LIMITED, detail=f"http {status}")
        if status == 400:
            return InstagramPublishError(InstagramPublishErrorCode.INVALID_MEDIA, detail=f"http {status}")
        if status >= 500:
            return InstagramPublishError(InstagramPublishErrorCode.TRANSIENT, detail=f"http {status}")
        return InstagramPublishError(InstagramPublishErrorCode.PUBLISH_FAILED, detail=f"http {status}")

    async def _post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "access_token": self.access_token}
        try:
            async with self._client() as client:
                response = await client.post(path, params=params)
        except httpx.TimeoutException as exc:
            raise InstagramPublishError(InstagramPublishErrorCode.NETWORK, detail="timeout") from exc
        except httpx.HTTPError as exc:
            raise InstagramPublishError(InstagramPublishErrorCode.NETWORK, detail=str(exc)) from exc
        if response.status_code >= 400:
            raise self._map_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise InstagramPublishError(InstagramPublishErrorCode.PUBLISH_FAILED, detail="malformed response") from exc

    async def create_media_container(
        self, *, account_id: str, caption: str, image_ref: str | None, video_ref: str | None,
        is_carousel_item: bool, media_type: str | None,
    ) -> str:
        params: dict[str, Any] = {"caption": caption}
        if image_ref:
            params["image_url"] = image_ref
        if video_ref:
            params["video_url"] = video_ref
        if is_carousel_item:
            params["is_carousel_item"] = "true"
        if media_type:
            params["media_type"] = media_type
        body = await self._post(f"/{account_id}/media", params)
        return str(body["id"])

    async def create_carousel_container(self, *, account_id: str, caption: str, children: list[str]) -> str:
        body = await self._post(
            f"/{account_id}/media", {"media_type": "CAROUSEL", "caption": caption, "children": ",".join(children)},
        )
        return str(body["id"])

    async def get_container_status(self, container_id: str) -> ContainerStatus:
        try:
            async with self._client() as client:
                response = await client.get(f"/{container_id}", params={"fields": "status_code", "access_token": self.access_token})
        except httpx.TimeoutException as exc:
            raise InstagramPublishError(InstagramPublishErrorCode.NETWORK, detail="timeout") from exc
        if response.status_code >= 400:
            raise self._map_error(response)
        code = response.json().get("status_code", "")
        return {"FINISHED": ContainerStatus.FINISHED, "IN_PROGRESS": ContainerStatus.IN_PROGRESS,
                "ERROR": ContainerStatus.ERROR, "EXPIRED": ContainerStatus.EXPIRED}.get(code, ContainerStatus.ERROR)

    async def publish_container(self, *, account_id: str, container_id: str) -> str:
        body = await self._post(f"/{account_id}/media_publish", {"creation_id": container_id})
        return str(body["id"])


@dataclass
class ShadowInstagramPublishClient:
    """Deterministic, in-memory, zero-network simulation of the SAME protocol. Container/media ids
    are stable hashes of the caller's own inputs (never random) so a shadow run is reproducible.
    `finish_after_polls` controls how many `get_container_status` calls report IN_PROGRESS before
    FINISHED - lets a test exercise the polling loop deterministically without a real delay."""

    finish_after_polls: int = 0
    _poll_counts: dict[str, int] = field(default_factory=dict)

    def _fake_id(self, *parts: str) -> str:
        return "shadow_" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    async def create_media_container(
        self, *, account_id: str, caption: str, image_ref: str | None, video_ref: str | None,
        is_carousel_item: bool, media_type: str | None,
    ) -> str:
        return self._fake_id("container", account_id, caption, image_ref or "", video_ref or "", str(is_carousel_item))

    async def create_carousel_container(self, *, account_id: str, caption: str, children: list[str]) -> str:
        return self._fake_id("carousel", account_id, caption, *children)

    async def get_container_status(self, container_id: str) -> ContainerStatus:
        seen = self._poll_counts.get(container_id, 0)
        self._poll_counts[container_id] = seen + 1
        if seen < self.finish_after_polls:
            return ContainerStatus.IN_PROGRESS
        return ContainerStatus.FINISHED

    async def publish_container(self, *, account_id: str, container_id: str) -> str:
        return self._fake_id("media", account_id, container_id)


async def _poll_until_finished(
    client: InstagramPublishClient, container_id: str, *, sleep_fn: Callable[[float], Awaitable[None]],
) -> None:
    for attempt in range(_MAX_STATUS_POLLS):
        status = await client.get_container_status(container_id)
        if status is ContainerStatus.FINISHED:
            return
        if status in (ContainerStatus.ERROR, ContainerStatus.EXPIRED):
            raise InstagramPublishError(InstagramPublishErrorCode.INVALID_MEDIA, detail=f"container status={status.value}")
        await sleep_fn(min(2.0 * (attempt + 1), 8.0))  # bounded backoff, never unbounded
    raise InstagramPublishError(InstagramPublishErrorCode.PROCESSING_TIMEOUT, detail=f"container never finished after {_MAX_STATUS_POLLS} polls")


async def _with_retries(
    fn: Callable[[], Awaitable[Any]], *, sleep_fn: Callable[[float], Awaitable[None]],
) -> tuple[Any, int]:
    attempts = 0
    last_error: InstagramPublishError | None = None
    while attempts < _MAX_RETRYABLE_ATTEMPTS + 1:
        attempts += 1
        try:
            return await fn(), attempts
        except InstagramPublishError as exc:
            last_error = exc
            exc.attempts_used = attempts  # type: ignore[attr-defined]
            if not exc.retryable or attempts > _MAX_RETRYABLE_ATTEMPTS:
                raise
            await sleep_fn(min(1.0 * attempts, 4.0))
    assert last_error is not None
    raise last_error


async def publish_instagram_content(
    package: InstagramContentPackage, gate_outcome: InstagramGateOutcome, *, client: InstagramPublishClient,
    account_id: str, shadow: bool = True, editor_approved: bool = False,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> PublicationResult:
    """The ONE orchestration entrypoint, identical for shadow and (future) live publish - only
    `client`/`shadow` differ. Fails CLOSED, in this exact order, before touching the client at all:

      1. the editorial gate must be READY_FOR_EDITOR (section 13) - BLOCK/HOLD never reach the client;
      2. a LIVE (`shadow=False`) attempt requires `settings.instagram_publication_enabled=True`
         (section 18) AND `editor_approved=True` - missing either fails closed with no client call;
      3. shadow publish always works (for testing/simulation) regardless of the flag (section 19).
    """
    requested_at = datetime.now(timezone.utc)

    if not gate_outcome.permits_publication:
        return PublicationResult(
            platform="instagram", account_key=package.account_key, package_id=package.package_id,
            content_format=package.content_format.value, status=PublicationStatus.BLOCKED, shadow=shadow,
            failure_class=InstagramPublishErrorCode.GATE_NOT_PERMITTED.value, requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
        )

    if not shadow:
        if not settings.instagram_publication_enabled:
            return PublicationResult(
                platform="instagram", account_key=package.account_key, package_id=package.package_id,
                content_format=package.content_format.value, status=PublicationStatus.BLOCKED, shadow=shadow,
                failure_class=InstagramPublishErrorCode.PUBLICATION_DISABLED.value, requested_at=requested_at,
                completed_at=datetime.now(timezone.utc),
            )
        if not editor_approved:
            return PublicationResult(
                platform="instagram", account_key=package.account_key, package_id=package.package_id,
                content_format=package.content_format.value, status=PublicationStatus.BLOCKED, shadow=shadow,
                failure_class=InstagramPublishErrorCode.NOT_APPROVED.value, requested_at=requested_at,
                completed_at=datetime.now(timezone.utc),
            )

    container_ids: list[str] = []
    attempts_used = 0
    try:
        if package.content_format.value == "single":
            image_ref = f"pending-media-ref:{package.package_id}"  # the real adapter takes an already-uploaded/reachable image URL; this phase never uploads one (no live media host wired)
            container_id, attempts_used = await _with_retries(
                lambda: client.create_media_container(
                    account_id=account_id, caption=package.caption, image_ref=image_ref, video_ref=None,
                    is_carousel_item=False, media_type=None,
                ),
                sleep_fn=sleep_fn,
            )
            container_ids.append(container_id)
            await _poll_until_finished(client, container_id, sleep_fn=sleep_fn)
            media_id, _ = await _with_retries(
                lambda: client.publish_container(account_id=account_id, container_id=container_id), sleep_fn=sleep_fn,
            )

        elif package.content_format.value == "carousel":
            slide_count = package.slide_count or 0
            child_ids: list[str] = []
            for i in range(slide_count):
                image_ref = f"pending-media-ref:{package.package_id}:{i}"

                def _create_child(image_ref: str = image_ref) -> Awaitable[str]:
                    return client.create_media_container(
                        account_id=account_id, caption="", image_ref=image_ref, video_ref=None,
                        is_carousel_item=True, media_type=None,
                    )

                child_id, attempts_used = await _with_retries(_create_child, sleep_fn=sleep_fn)
                child_ids.append(child_id)
                await _poll_until_finished(client, child_id, sleep_fn=sleep_fn)
            container_ids.extend(child_ids)
            parent_id, attempts_used = await _with_retries(
                lambda: client.create_carousel_container(account_id=account_id, caption=package.caption, children=child_ids),
                sleep_fn=sleep_fn,
            )
            container_ids.append(parent_id)
            await _poll_until_finished(client, parent_id, sleep_fn=sleep_fn)
            media_id, _ = await _with_retries(
                lambda: client.publish_container(account_id=account_id, container_id=parent_id), sleep_fn=sleep_fn,
            )

        elif package.content_format.value == "reel":
            if not package.external_video_asset_ref:
                raise InstagramPublishError(InstagramPublishErrorCode.INVALID_MEDIA, detail="REEL package has no external_video_asset_ref")
            container_id, attempts_used = await _with_retries(
                lambda: client.create_media_container(
                    account_id=account_id, caption=package.caption, image_ref=None,
                    video_ref=package.external_video_asset_ref, is_carousel_item=False, media_type="REELS",
                ),
                sleep_fn=sleep_fn,
            )
            container_ids.append(container_id)
            await _poll_until_finished(client, container_id, sleep_fn=sleep_fn)
            media_id, _ = await _with_retries(
                lambda: client.publish_container(account_id=account_id, container_id=container_id), sleep_fn=sleep_fn,
            )
        else:
            raise InstagramPublishError(InstagramPublishErrorCode.INVALID_MEDIA, detail=f"unsupported format {package.content_format.value!r}")

    except InstagramPublishError as exc:
        logger.warning("instagram_publish_failed", extra={"code": exc.code.value, "package_id": package.package_id, "shadow": shadow})
        attempts_used = getattr(exc, "attempts_used", attempts_used)
        return PublicationResult(
            platform="instagram", account_key=package.account_key, package_id=package.package_id,
            content_format=package.content_format.value, status=PublicationStatus.FAILED, shadow=shadow,
            container_ids=container_ids, failure_class=exc.code.value, retryable=exc.retryable,
            attempts_used=attempts_used, requested_at=requested_at, completed_at=datetime.now(timezone.utc),
        )

    return PublicationResult(
        platform="instagram", account_key=package.account_key, package_id=package.package_id,
        content_format=package.content_format.value,
        status=PublicationStatus.SHADOW_SUCCESS if shadow else PublicationStatus.LIVE_SUCCESS, shadow=shadow,
        container_ids=container_ids, media_id=media_id, attempts_used=attempts_used,
        requested_at=requested_at, completed_at=datetime.now(timezone.utc),
    )
