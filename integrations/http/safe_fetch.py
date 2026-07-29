"""SSRF-safe, DNS-rebinding-resistant external fetch boundary (Phase 16 M2, docs/
phase16_m2_secure_fetch_and_validation_report.md).

The single shared network-security boundary for every outbound HTTP call Image Intelligence
makes (article-page HTML, candidate image bytes). No adapter, service, or workflow file builds
its own `httpx.AsyncClient` for this purpose - everything routes through `safe_fetch()` here.

Core mechanism (empirically verified against a real HTTPS site before this module was written -
see docs/phase16_m2_secure_fetch_and_validation_report.md §4): DNS resolution is performed exactly
once per connection attempt, via `asyncio`'s own resolver (`loop.getaddrinfo`), and every resolved
address is validated against the blocklist below *before* any connection is attempted. The actual
TCP connection is then pinned to one validated IP literal via a custom `httpcore.AsyncNetworkBackend`
- connecting to an IP literal never triggers a second DNS lookup (`getaddrinfo` on a literal IP is
a local parse, not a network query), which is what makes this resistant to DNS rebinding (an
attacker's DNS server cannot change the answer between validation and connection, because there is
no second lookup for it to change). TLS SNI and certificate-hostname verification, and the HTTP
`Host` header, are all left as the *original* hostname throughout - `httpcore`'s own connection
logic defaults `server_hostname` to `self._origin.host` (see `httpcore._async.connection.
AsyncHTTPConnection._connect`), which we never override, and the `Host` header is built by the
request layer from the original URL, never touched by the pinned backend. This is why pinning the
socket to a different address never weakens certificate validation.

Redirects are never followed automatically (`AsyncConnectionPool`/`httpcore.Request` have no
redirect-following behavior of their own) - `safe_fetch()` handles them in an explicit loop,
re-running the full scheme/hostname/DNS/IP validation and re-pinning a fresh connection for every
hop, never forwarding any header across a redirect.
"""
import asyncio
import enum
import hashlib
import ipaddress
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpcore
import httpx
from httpx._types import AsyncByteStream

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

# Carrier-grade NAT / shared address space (RFC 6598) - NOT covered by ipaddress.is_private,
# verified empirically (docs/phase16_m2_secure_fetch_and_validation_report.md §6).
_EXTRA_BLOCKED_NETWORKS = (ipaddress.ip_network("100.64.0.0/10"),)

USER_AGENT = "ai-newsroom-image-intelligence/1.0"


class FetchErrorCode(str, enum.Enum):
    """Centralized, structured error taxonomy - never a raw exception string reaches a caller or
    a log line, since raw exception text can carry resolved IPs, internal paths, or other detail
    not safe to persist into EditorialTask.workflow.step_results."""

    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    CREDENTIALS_IN_URL = "credentials_in_url"
    HOSTNAME_MISSING = "hostname_missing"
    DNS_FAILURE = "dns_failure"
    BLOCKED_IP = "blocked_ip"
    BLOCKED_REDIRECT = "blocked_redirect"
    REDIRECT_LOOP = "redirect_loop"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    TOTAL_TIMEOUT = "total_timeout"
    TLS_FAILURE = "tls_failure"
    HTTP_ERROR = "http_error"
    CONTENT_LENGTH_EXCEEDED = "content_length_exceeded"
    STREAM_LIMIT_EXCEEDED = "stream_limit_exceeded"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    CANCELLED = "cancelled"
    INTERNAL_FETCH_ERROR = "internal_fetch_error"


class SafeFetchError(Exception):
    """Carries only a structured `code` and a short, safe `detail` - never the raw underlying
    exception's message (which might embed a resolved IP or internal path)."""

    def __init__(self, code: FetchErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


@dataclass(frozen=True)
class SafeFetchPolicy:
    """Bounded limits for one fetch operation. Every field is required (no unlimited fallback) -
    callers (services/article_metadata.py for HTML, services/image_validation.py's caller for
    images) each construct their own policy from core/config.py settings."""

    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_timeout_seconds: float
    max_redirects: int
    max_bytes: int


@dataclass(frozen=True)
class SafeFetchResult:
    """Only bounded, safe metadata plus the body bytes (already capped at `policy.max_bytes`).
    Never carries cookies, authorization headers, full response headers, proxy details, or any
    DNS/connection internals."""

    requested_url: str
    final_url: str
    status_code: int
    redirect_count: int
    declared_content_type: str | None
    received_byte_count: int
    duration_seconds: float
    body: bytes


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Ignores the hostname `connect_tcp` is given and connects to the single, already-validated
    IP literal instead - the actual DNS-rebinding defense (see module docstring)."""

    def __init__(self, pinned_ip: str) -> None:
        self._pinned_ip = pinned_ip
        self._delegate = httpcore.AnyIOBackend()

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ) -> httpcore.AsyncNetworkStream:
        return await self._delegate.connect_tcp(
            self._pinned_ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class _PinnedByteStream(AsyncByteStream):
    """Adapts an `httpcore.Response`'s raw (possibly compressed) byte stream to the shape
    `httpx.Response.aiter_bytes()` requires - subclassing `httpx._types.AsyncByteStream` is
    required (not just duck-typing): `httpx.Response.aiter_raw()` does an explicit `isinstance`
    check and raises otherwise (verified empirically, see the M2 report §4)."""

    def __init__(self, response: httpcore.Response) -> None:
        self._response = response

    async def __aiter__(self):
        async for chunk in self._response.aiter_stream():
            yield chunk

    async def aclose(self) -> None:
        await self._response.aclose()


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """`.is_private` alone already covers loopback, RFC1918, link-local (including the
    169.254.169.254 cloud-metadata address), unspecified, IPv6 ULA (fd00::/8), TEST-NET
    documentation ranges, and - verified empirically - IPv4-mapped IPv6 forms of any of the above
    (`::ffff:10.0.0.1`.is_private == True). `.is_multicast` and `.is_reserved` are separate checks
    Python's `is_private` does not fold in. CGNAT (100.64.0.0/10) is not covered by any of the
    above and is blocked explicitly."""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return any(ip in network for network in _EXTRA_BLOCKED_NETWORKS)


async def _getaddrinfo(hostname: str, port: int) -> list:
    """The sole DNS resolution call site - a dedicated, by-name-monkeypatchable seam (mirrors
    services/collector.py's own established "keyword-only, defaulted testability seam"
    convention) so tests can simulate arbitrary resolver results (mixed public/private, metadata
    IPs, etc.) without depending on real DNS or real asyncio loop internals."""
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)


async def _resolve_safe_ip(hostname: str, port: int) -> str:
    """Exactly one DNS resolution per connection attempt. Returns one validated-safe IP literal.
    Raises `blocked_ip` if resolution succeeded but every resolved address is unsafe (covers both
    "resolves only to private addresses" and "mixed public/private" - only ever a safe address is
    returned, the mixed case is never given a chance to pick the unsafe one)."""
    try:
        infos = await _getaddrinfo(hostname, port)
    except (socket.gaierror, UnicodeError) as error:
        raise SafeFetchError(FetchErrorCode.DNS_FAILURE, type(error).__name__) from error

    candidates = []
    for info in infos:
        raw_ip = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])  # strip IPv6 zone id if present
        except ValueError:
            continue
        if not _is_blocked_ip(ip):
            candidates.append(raw_ip)

    if not candidates:
        raise SafeFetchError(FetchErrorCode.BLOCKED_IP, "no safe resolved address")
    return candidates[0]


def _validate_url(url: str) -> httpx.URL:
    """Structural validation only (scheme/userinfo/hostname presence) - DNS/IP validation happens
    separately in `_resolve_safe_ip`, immediately before each connection attempt."""
    try:
        parsed = httpx.URL(url)
    except Exception as error:
        raise SafeFetchError(FetchErrorCode.INVALID_URL, type(error).__name__) from error

    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SafeFetchError(FetchErrorCode.UNSUPPORTED_SCHEME, scheme or "missing")

    if parsed.username or parsed.password:
        raise SafeFetchError(FetchErrorCode.CREDENTIALS_IN_URL)

    if not parsed.host:
        raise SafeFetchError(FetchErrorCode.HOSTNAME_MISSING)

    return parsed


async def _single_hop(
    url: httpx.URL, *, policy: SafeFetchPolicy, extra_headers: dict[str, str] | None = None
) -> tuple[httpcore.Response, str]:
    """One connection attempt: resolve+validate DNS, pin the connection, send the request, and
    return the raw httpcore.Response (caller owns closing it) plus the validated (unused, host is
    already known safe) pinned IP for logging/testing purposes."""
    port = url.port or _DEFAULT_PORT_BY_SCHEME[url.scheme]
    pinned_ip = await _resolve_safe_ip(url.host, port)

    ssl_context = ssl.create_default_context() if url.scheme == "https" else None
    pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl_context,
        network_backend=_PinnedNetworkBackend(pinned_ip),
        max_connections=1,
        max_keepalive_connections=0,
        retries=0,
    )
    is_default_port = url.port is None or url.port == _DEFAULT_PORT_BY_SCHEME[url.scheme]
    encoded_host = url.host.encode("idna")
    host_header = encoded_host if is_default_port else encoded_host + f":{port}".encode("ascii")
    headers = [(b"Host", host_header), (b"User-Agent", USER_AGENT.encode("ascii"))]
    for name, value in (extra_headers or {}).items():
        headers.append((name.encode("ascii"), value.encode("ascii")))

    request = httpcore.Request(
        method="GET",
        url=httpcore.URL(
            scheme=url.scheme.encode("ascii"),
            host=url.host.encode("idna"),
            port=port,
            target=(url.raw_path or b"/"),
        ),
        headers=headers,
        extensions={"timeout": {"connect": policy.connect_timeout_seconds, "read": policy.read_timeout_seconds}},
    )

    try:
        response = await pool.handle_async_request(request)
    except httpcore.ConnectTimeout as error:
        await pool.aclose()
        raise SafeFetchError(FetchErrorCode.CONNECT_TIMEOUT) from error
    except (httpcore.ReadTimeout, httpcore.WriteTimeout, httpcore.PoolTimeout) as error:
        await pool.aclose()
        raise SafeFetchError(FetchErrorCode.READ_TIMEOUT) from error
    except httpcore.ConnectError as error:
        await pool.aclose()
        cause = error.__cause__
        if isinstance(cause, ssl.SSLError):
            raise SafeFetchError(FetchErrorCode.TLS_FAILURE) from error
        raise SafeFetchError(FetchErrorCode.INTERNAL_FETCH_ERROR, "connect_error") from error
    except Exception as error:
        await pool.aclose()
        raise SafeFetchError(FetchErrorCode.INTERNAL_FETCH_ERROR, type(error).__name__) from error

    return response, pinned_ip


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    lower_name = name.lower()
    for key, value in headers:
        if key.lower() == lower_name:
            return value.decode("latin-1")
    return None


async def _read_bounded(response: httpcore.Response, *, max_bytes: int) -> bytes:
    """Streams decompressed bytes (via httpx's decoder, so a gzip/br/zstd bomb is caught at its
    *expanded* size, never the wire size) and aborts the instant the cap is exceeded - never
    buffers past the limit."""
    declared_length = _header_value(response.headers, b"content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_bytes:
                raise SafeFetchError(FetchErrorCode.CONTENT_LENGTH_EXCEEDED)
        except ValueError:
            pass  # malformed Content-Length - fall through to streaming enforcement regardless

    httpx_response = httpx.Response(
        status_code=response.status, headers=response.headers, stream=_PinnedByteStream(response)
    )
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in httpx_response.aiter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > max_bytes:
                raise SafeFetchError(FetchErrorCode.STREAM_LIMIT_EXCEEDED)
            chunks.append(chunk)
    except (httpcore.ReadTimeout, httpcore.WriteTimeout, httpcore.PoolTimeout) as error:
        raise SafeFetchError(FetchErrorCode.READ_TIMEOUT) from error
    except (httpcore.ReadError, httpcore.RemoteProtocolError, httpcore.NetworkError) as error:
        raise SafeFetchError(FetchErrorCode.HTTP_ERROR, type(error).__name__) from error
    return b"".join(chunks)


def _resolve_redirect_target(current_url: httpx.URL, location: str) -> httpx.URL:
    if not location or "\x00" in location:
        raise SafeFetchError(FetchErrorCode.BLOCKED_REDIRECT, "malformed_location")
    try:
        resolved = urljoin(str(current_url), location)
        target = httpx.URL(resolved)
    except Exception as error:
        raise SafeFetchError(FetchErrorCode.BLOCKED_REDIRECT, "unparseable_location") from error
    if target.username or target.password:
        raise SafeFetchError(FetchErrorCode.CREDENTIALS_IN_URL)
    if target.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SafeFetchError(FetchErrorCode.UNSUPPORTED_SCHEME, target.scheme)
    if not target.host:
        raise SafeFetchError(FetchErrorCode.HOSTNAME_MISSING)
    return target


async def safe_fetch(url: str, *, policy: SafeFetchPolicy) -> SafeFetchResult:
    """The sole entry point. Validates `url`, then fetches it through the pinned, bounded
    connection above, following redirects explicitly (never via httpx/httpcore's own
    redirect-following, which does not exist at this layer) up to `policy.max_redirects` hops -
    every hop is independently scheme/hostname/DNS/IP-revalidated and freshly pinned, and no
    header is ever forwarded across a hop (a fresh, minimal header set is built each time inside
    `_single_hop`). Raises `SafeFetchError` on any failure; never raises a bare exception."""
    start = time.monotonic()
    requested_url = url
    current_url = _validate_url(url)
    seen_urls: set[str] = set()
    redirect_count = 0

    async def _run() -> SafeFetchResult:
        nonlocal redirect_count, current_url
        while True:
            normalized = str(current_url)
            if normalized in seen_urls:
                raise SafeFetchError(FetchErrorCode.REDIRECT_LOOP)
            seen_urls.add(normalized)

            response, _pinned_ip = await _single_hop(current_url, policy=policy)
            try:
                if response.status in _REDIRECT_STATUS_CODES:
                    location = _header_value(response.headers, b"location")
                    await response.aclose()
                    if redirect_count >= policy.max_redirects:
                        raise SafeFetchError(FetchErrorCode.TOO_MANY_REDIRECTS)
                    current_url = _resolve_redirect_target(current_url, location or "")
                    redirect_count += 1
                    continue

                body = await _read_bounded(response, max_bytes=policy.max_bytes)
                declared_content_type = _header_value(response.headers, b"content-type")
                return SafeFetchResult(
                    requested_url=requested_url,
                    final_url=normalized,
                    status_code=response.status,
                    redirect_count=redirect_count,
                    declared_content_type=declared_content_type,
                    received_byte_count=len(body),
                    duration_seconds=time.monotonic() - start,
                    body=body,
                )
            finally:
                await response.aclose()

    try:
        return await asyncio.wait_for(_run(), timeout=policy.total_timeout_seconds)
    except asyncio.TimeoutError as error:
        raise SafeFetchError(FetchErrorCode.TOTAL_TIMEOUT) from error
    except asyncio.CancelledError:
        raise SafeFetchError(FetchErrorCode.CANCELLED)
    except SafeFetchError:
        raise
    except Exception as error:
        raise SafeFetchError(FetchErrorCode.INTERNAL_FETCH_ERROR, type(error).__name__) from error


def sha256_hex(data: bytes) -> str:
    """Shared, single implementation of the content-hash convention this repo already uses
    (services/collector.py::_compute_hash, services/image_intelligence.py's candidate identity) -
    exposed here since services/image_validation.py needs it for the technical-metadata SHA-256
    fingerprint and no existing shared helper covers raw bytes (only strings)."""
    return hashlib.sha256(data).hexdigest()
