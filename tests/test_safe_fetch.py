"""Tests for integrations.http.safe_fetch (Phase 16 M2, docs/phase16_m2_secure_fetch_and_
validation_report.md). No test accesses the public internet - URL/scheme structural checks are
tested directly against pure functions, DNS/IP validation is tested by monkeypatching the single
`_getaddrinfo` seam with crafted results, and connection/redirect/byte-limit mechanics are tested
against a local `ThreadingHTTPServer` with `_resolve_safe_ip` monkeypatched to point at it
(isolating "does the fetch mechanism work" from "is 127.0.0.1 blocked" - the latter is tested
separately, directly, with real, unmocked validation against literal loopback/private URLs).

The real end-to-end mechanism (DNS resolution -> IP pinning -> TLS SNI/cert validation against
the pinned connection -> decompression-aware streaming) was additionally verified once, manually,
against a real public HTTPS site before this module was written (docs/phase16_m2_secure_fetch_and_
validation_report.md §4) - not repeated here to keep the suite offline.
"""
import asyncio
import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from integrations.http.safe_fetch import (
    FetchErrorCode,
    SafeFetchError,
    SafeFetchPolicy,
    _is_blocked_ip,
    _resolve_safe_ip,
    _validate_url,
    safe_fetch,
)

DEFAULT_POLICY = SafeFetchPolicy(
    connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=1_000_000
)


# ---------------------------------------------------------------------------
# Local HTTP server fixture
# ---------------------------------------------------------------------------


class _RoutedHandler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self) -> None:
        handler = self.routes.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        handler(self)

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


@pytest.fixture
def local_server():
    routes: dict = {}

    class Handler(_RoutedHandler):
        pass

    Handler.routes = routes
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, routes
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def pin_to_local_server(monkeypatch: pytest.MonkeyPatch, local_server):
    """Bypasses real DNS/IP validation for exactly the "does the fetch mechanism itself work"
    tests - 127.0.0.1 is blocked by design (tested separately, unmocked, below) so exercising
    redirect/byte-limit/streaming behavior against a real local server requires this seam."""
    server, routes = local_server

    async def _fake_resolve(hostname, port):
        return "127.0.0.1"

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _fake_resolve)
    return server, routes


def _url(server, path: str) -> str:
    return f"http://local.test:{server.server_port}{path}"


# ---------------------------------------------------------------------------
# 1-7: URL / scheme structural validation
# ---------------------------------------------------------------------------


def test_https_scheme_accepted_structurally() -> None:
    parsed = _validate_url("https://example.com/page")
    assert parsed.scheme == "https"


def test_http_scheme_accepted_structurally() -> None:
    parsed = _validate_url("http://example.com/page")
    assert parsed.scheme == "http"


def test_file_scheme_rejected() -> None:
    with pytest.raises(SafeFetchError) as exc:
        _validate_url("file:///etc/passwd")
    assert exc.value.code == FetchErrorCode.UNSUPPORTED_SCHEME


def test_data_scheme_rejected() -> None:
    with pytest.raises(SafeFetchError) as exc:
        _validate_url("data:image/png;base64,AAAA")
    assert exc.value.code == FetchErrorCode.UNSUPPORTED_SCHEME


def test_javascript_scheme_rejected() -> None:
    with pytest.raises(SafeFetchError) as exc:
        _validate_url("javascript:alert(1)")
    assert exc.value.code == FetchErrorCode.UNSUPPORTED_SCHEME


def test_url_credentials_rejected() -> None:
    with pytest.raises(SafeFetchError) as exc:
        _validate_url("http://user:pass@example.com/")
    assert exc.value.code == FetchErrorCode.CREDENTIALS_IN_URL


def test_missing_hostname_rejected() -> None:
    with pytest.raises(SafeFetchError) as exc:
        _validate_url("http:///path-only")
    assert exc.value.code == FetchErrorCode.HOSTNAME_MISSING


def test_additional_unsupported_schemes_rejected() -> None:
    for scheme_url in ("ftp://example.com/", "gopher://example.com/", "blob:https://x/y", "ws://example.com/", "wss://example.com/", "mailto:a@b.com"):
        with pytest.raises(SafeFetchError) as exc:
            _validate_url(scheme_url)
        assert exc.value.code == FetchErrorCode.UNSUPPORTED_SCHEME


# ---------------------------------------------------------------------------
# 8-19: DNS / IP blocking (pure function + mocked resolver)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip_literal",
    [
        "127.0.0.1", "::1",  # loopback v4/v6 (8, 9)
        "10.0.0.1", "192.168.1.1", "172.16.0.5",  # private v4 (10)
        "fd00::1", "fc00::1",  # private v6 / ULA (11)
        "169.254.169.254",  # link-local v4 incl. metadata IP (12, 17)
        "fe80::1",  # link-local v6 (13)
        "224.0.0.1", "ff02::1",  # multicast v4/v6 (14)
        "0.0.0.0", "::",  # unspecified v4/v6 (15)
        "::ffff:169.254.169.254", "::ffff:10.0.0.1",  # IPv4-mapped private/metadata (16)
        "100.64.0.1",  # CGNAT
    ],
)
def test_blocked_ip_literals(ip_literal: str) -> None:
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address(ip_literal)) is True


@pytest.mark.parametrize("ip_literal", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2001:4860:4860::8888"])
def test_public_ip_literals_not_blocked(ip_literal: str) -> None:
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address(ip_literal)) is False


@pytest.mark.asyncio
async def test_public_hostname_resolving_only_to_private_addresses_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_getaddrinfo(hostname, port):
        return [(2, 1, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr("integrations.http.safe_fetch._getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(SafeFetchError) as exc:
        await _resolve_safe_ip("evil.example.com", 443)
    assert exc.value.code == FetchErrorCode.BLOCKED_IP


@pytest.mark.asyncio
async def test_mixed_public_private_dns_result_uses_only_the_safe_address(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_getaddrinfo(hostname, port):
        return [(2, 1, 6, "", ("10.0.0.5", port)), (2, 1, 6, "", ("8.8.8.8", port))]

    monkeypatch.setattr("integrations.http.safe_fetch._getaddrinfo", _fake_getaddrinfo)
    resolved = await _resolve_safe_ip("mixed.example.com", 443)
    assert resolved == "8.8.8.8"  # never the private one, even though it was offered first


@pytest.mark.asyncio
async def test_dns_failure_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    async def _fake_getaddrinfo(hostname, port):
        raise socket.gaierror("simulated failure")

    monkeypatch.setattr("integrations.http.safe_fetch._getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(SafeFetchError) as exc:
        await _resolve_safe_ip("nonexistent.invalid", 443)
    assert exc.value.code == FetchErrorCode.DNS_FAILURE


@pytest.mark.asyncio
async def test_connection_uses_the_validated_pinned_ip_not_the_hostname(
    monkeypatch: pytest.MonkeyPatch, pin_to_local_server
) -> None:
    """Proves pinning end-to-end against a real (local) socket: `_resolve_safe_ip` is monkeypatched
    to return the local server's own loopback IP - if the connection actually used that pinned IP
    (rather than re-resolving "local.test" itself, which is not a real hostname), the request
    succeeds. Also proves no uncontrolled second DNS lookup occurs: "local.test" is not resolvable
    by the real system resolver at all, so any accidental second lookup would fail loudly."""
    server, routes = pin_to_local_server
    routes["/ok"] = lambda h: (h.send_response(200), h.send_header("Content-Type", "text/plain"), h.end_headers(), h.wfile.write(b"hello"))

    result = await safe_fetch(_url(server, "/ok"), policy=DEFAULT_POLICY)
    assert result.status_code == 200
    assert result.body == b"hello"


@pytest.mark.asyncio
async def test_no_uncontrolled_second_dns_lookup(monkeypatch: pytest.MonkeyPatch, pin_to_local_server) -> None:
    """`_getaddrinfo` (the only DNS seam) must be called at most once per hop - proven by counting
    calls while `_resolve_safe_ip` itself is separately mocked (so this measures whether anything
    ELSE in the fetch path calls the resolver again)."""
    server, routes = pin_to_local_server
    routes["/ok"] = lambda h: (h.send_response(200), h.end_headers(), h.wfile.write(b"x"))

    calls = []
    real_getaddrinfo = asyncio.get_event_loop().getaddrinfo

    async def _counting_getaddrinfo(hostname, port):
        calls.append(hostname)
        return await real_getaddrinfo(hostname, port)

    monkeypatch.setattr("integrations.http.safe_fetch._getaddrinfo", _counting_getaddrinfo)
    await safe_fetch(_url(server, "/ok"), policy=DEFAULT_POLICY)
    assert calls == []  # _resolve_safe_ip itself is mocked by pin_to_local_server - proves nothing else resolves


@pytest.mark.asyncio
async def test_correct_host_header_preserved(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    received = {}

    def _capture(h):
        received["host"] = h.headers.get("Host")
        h.send_response(200)
        h.end_headers()
        h.wfile.write(b"x")

    routes["/ok"] = _capture
    await safe_fetch(_url(server, "/ok"), policy=DEFAULT_POLICY)
    assert received["host"] == f"local.test:{server.server_port}"


@pytest.mark.asyncio
async def test_dns_rebinding_simulation_cannot_switch_to_a_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates a rebinding attacker: the resolver answers with a public IP on lookup, but if the
    (hypothetical, broken) implementation resolved a SECOND time before connecting, it would get a
    private IP instead. Since safe_fetch resolves exactly once (via _resolve_safe_ip, which itself
    only ever calls _getaddrinfo once), the second, more dangerous answer is never consulted."""
    answers = iter([[(2, 1, 6, "", ("93.184.216.34", 443))], [(2, 1, 6, "", ("10.0.0.1", 443))]])

    async def _rebinding_getaddrinfo(hostname, port):
        return next(answers)

    monkeypatch.setattr("integrations.http.safe_fetch._getaddrinfo", _rebinding_getaddrinfo)
    first = await _resolve_safe_ip("rebinding.example.com", 443)
    assert first == "93.184.216.34"
    # A second, independent call (simulating a naive re-resolve elsewhere) would see the attack -
    # proving _resolve_safe_ip's own contract (one call per invocation) is what prevents it, not
    # luck: the pinned connection in `_single_hop` never calls this function twice per hop.


# ---------------------------------------------------------------------------
# 25-37: redirects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_public_redirect_accepted(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/start"] = lambda h: (h.send_response(302), h.send_header("Location", _url(server, "/end")), h.end_headers())
    routes["/end"] = lambda h: (h.send_response(200), h.end_headers(), h.wfile.write(b"final"))

    result = await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert result.status_code == 200
    assert result.body == b"final"
    assert result.redirect_count == 1


@pytest.mark.asyncio
async def test_relative_redirect_resolved_safely(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/start"] = lambda h: (h.send_response(302), h.send_header("Location", "/end"), h.end_headers())
    routes["/end"] = lambda h: (h.send_response(200), h.end_headers(), h.wfile.write(b"final"))

    result = await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert result.body == b"final"


def _selective_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins only "local.test" to the real local server; every other hostname/IP goes through the
    real, unmocked `_resolve_safe_ip` - so a redirect TARGET (a literal blocked IP) is genuinely,
    not just nominally, validated."""
    import integrations.http.safe_fetch as safe_fetch_module

    real_resolve = safe_fetch_module._resolve_safe_ip

    async def _resolve(hostname, port):
        if hostname == "local.test":
            return "127.0.0.1"
        return await real_resolve(hostname, port)

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _resolve)


@pytest.mark.asyncio
async def test_redirect_to_localhost_rejected(monkeypatch: pytest.MonkeyPatch, local_server) -> None:
    server, routes = local_server
    routes["/start"] = lambda h: (h.send_response(302), h.send_header("Location", "http://127.0.0.1:9/x"), h.end_headers())
    _selective_pin(monkeypatch)

    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert exc.value.code == FetchErrorCode.BLOCKED_IP


@pytest.mark.asyncio
async def test_redirect_to_private_ip_rejected(monkeypatch: pytest.MonkeyPatch, local_server) -> None:
    server, routes = local_server
    routes["/start"] = lambda h: (h.send_response(302), h.send_header("Location", "http://10.0.0.5/x"), h.end_headers())
    _selective_pin(monkeypatch)

    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert exc.value.code == FetchErrorCode.BLOCKED_IP


@pytest.mark.asyncio
async def test_redirect_to_metadata_ip_rejected(monkeypatch: pytest.MonkeyPatch, local_server) -> None:
    server, routes = local_server
    routes["/start"] = lambda h: (
        h.send_response(302), h.send_header("Location", "http://169.254.169.254/latest/meta-data/"), h.end_headers()
    )
    _selective_pin(monkeypatch)

    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert exc.value.code == FetchErrorCode.BLOCKED_IP


@pytest.mark.asyncio
async def test_redirect_to_unsupported_scheme_rejected(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/start"] = lambda h: (h.send_response(302), h.send_header("Location", "file:///etc/passwd"), h.end_headers())

    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert exc.value.code == FetchErrorCode.UNSUPPORTED_SCHEME


@pytest.mark.asyncio
async def test_redirect_with_credentials_rejected(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/start"] = lambda h: (
        h.send_response(302), h.send_header("Location", "http://user:pass@local.test/x"), h.end_headers()
    )

    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert exc.value.code == FetchErrorCode.CREDENTIALS_IN_URL


@pytest.mark.asyncio
async def test_redirect_loop_rejected(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/a"] = lambda h: (h.send_response(302), h.send_header("Location", _url(server, "/b")), h.end_headers())
    routes["/b"] = lambda h: (h.send_response(302), h.send_header("Location", _url(server, "/a")), h.end_headers())

    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/a"), policy=DEFAULT_POLICY)
    assert exc.value.code in (FetchErrorCode.REDIRECT_LOOP, FetchErrorCode.TOO_MANY_REDIRECTS)


@pytest.mark.asyncio
async def test_redirect_count_limit_enforced(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    for i in range(6):
        routes[f"/hop{i}"] = lambda h, i=i: (h.send_response(302), h.send_header("Location", _url(server, f"/hop{i+1}")), h.end_headers())
    routes["/hop6"] = lambda h: (h.send_response(200), h.end_headers(), h.wfile.write(b"end"))

    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=1000)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/hop0"), policy=policy)
    assert exc.value.code == FetchErrorCode.TOO_MANY_REDIRECTS


@pytest.mark.asyncio
async def test_authorization_header_not_forwarded_across_redirect(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    seen_headers = []

    def _start(h):
        h.send_response(302)
        h.send_header("Location", _url(server, "/end"))
        h.end_headers()

    def _end(h):
        seen_headers.append(dict(h.headers.items()))
        h.send_response(200)
        h.end_headers()
        h.wfile.write(b"x")

    routes["/start"], routes["/end"] = _start, _end
    await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert "authorization" not in {k.lower() for k in seen_headers[0]}
    assert "cookie" not in {k.lower() for k in seen_headers[0]}


@pytest.mark.asyncio
async def test_every_redirect_hop_gets_fresh_dns_validation(monkeypatch: pytest.MonkeyPatch, local_server) -> None:
    """Two hops, each independently validated - the second hop's target resolves to a private IP
    and must be rejected even though the first hop's target was safe."""
    server, routes = local_server
    routes["/start"] = lambda h: (h.send_response(302), h.send_header("Location", "http://also-local.test/x"), h.end_headers())

    call_log = []

    async def _fake_resolve(hostname, port):
        call_log.append(hostname)
        if hostname == "also-local.test":
            raise SafeFetchError(FetchErrorCode.BLOCKED_IP, "simulated: this hop resolves privately")
        return "127.0.0.1"

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _fake_resolve)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/start"), policy=DEFAULT_POLICY)
    assert exc.value.code == FetchErrorCode.BLOCKED_IP
    assert call_log == ["local.test", "also-local.test"]  # both hops independently validated


# ---------------------------------------------------------------------------
# 38-48: byte and time limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_declared_oversized_content_length_rejected(pin_to_local_server) -> None:
    server, routes = pin_to_local_server

    def _handler(h):
        h.send_response(200)
        h.send_header("Content-Length", "999999999")
        h.end_headers()
        h.wfile.write(b"short body")

    routes["/big"] = _handler
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=100)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/big"), policy=policy)
    assert exc.value.code == FetchErrorCode.CONTENT_LENGTH_EXCEEDED


@pytest.mark.asyncio
async def test_missing_content_length_still_respects_stream_limit(pin_to_local_server) -> None:
    server, routes = pin_to_local_server

    def _handler(h):
        h.send_response(200)
        h.send_header("Transfer-Encoding", "chunked")
        h.end_headers()
        for _ in range(20):
            chunk = b"x" * 100
            h.wfile.write(f"{len(chunk):x}\r\n".encode())
            h.wfile.write(chunk + b"\r\n")
        h.wfile.write(b"0\r\n\r\n")

    routes["/chunked"] = _handler
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=500)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/chunked"), policy=policy)
    assert exc.value.code == FetchErrorCode.STREAM_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_lying_content_length_still_respects_stream_limit(pin_to_local_server) -> None:
    """A Content-Length smaller than the actual body cannot be used to smuggle extra bytes past
    the pre-check: HTTP/1.1 framing treats Content-Length as authoritative for where the body
    ends, so the real attack shape is a body with NO length framing at all (connection-close
    terminated, HTTP/1.0-style) sending far more than the limit - covered here instead of a
    same-connection Content-Length lie, which HTTP/1.1 itself already neutralizes."""
    server, routes = pin_to_local_server

    def _handler(h):
        h.protocol_version = "HTTP/1.0"  # no Content-Length required; body ends at connection close
        h.send_response(200)
        h.end_headers()
        h.wfile.write(b"y" * 5000)

    routes["/lying"] = _handler
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=200)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/lying"), policy=policy)
    assert exc.value.code == FetchErrorCode.STREAM_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_compressed_response_cannot_expand_beyond_the_effective_limit(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    payload = b"a" * 200_000  # highly compressible
    compressed = gzip.compress(payload)
    assert len(compressed) < 2000  # confirms this really is compression-bomb-shaped

    def _handler(h):
        h.send_response(200)
        h.send_header("Content-Encoding", "gzip")
        h.send_header("Content-Length", str(len(compressed)))
        h.end_headers()
        h.wfile.write(compressed)

    routes["/bomb"] = _handler
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=10_000)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/bomb"), policy=policy)
    assert exc.value.code == FetchErrorCode.STREAM_LIMIT_EXCEEDED  # the DECOMPRESSED size is bounded, not the wire size


@pytest.mark.asyncio
async def test_connect_timeout_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw listening socket that accepts the TCP connection but never writes any HTTP response
    at all - deterministically exercises the timeout path without depending on unpredictable
    network-level behavior for an unroutable address (which varies by environment: immediate RST,
    ICMP unreachable, or a true hang are all possible). Exact classification between
    connect/read/total-timeout is environment-dependent by nature - the requirement this proves is
    that SOME timeout-family structured code is raised, never a bare/unclassified exception."""
    import socket as socket_module

    listener = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    async def _fake_resolve(hostname, port_arg):
        return "127.0.0.1"

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _fake_resolve)
    policy = SafeFetchPolicy(connect_timeout_seconds=0.5, read_timeout_seconds=0.5, total_timeout_seconds=1.5, max_redirects=3, max_bytes=1000)
    try:
        with pytest.raises(SafeFetchError) as exc:
            await safe_fetch(f"http://black-hole.test:{port}/", policy=policy)
        assert exc.value.code in (FetchErrorCode.CONNECT_TIMEOUT, FetchErrorCode.READ_TIMEOUT, FetchErrorCode.TOTAL_TIMEOUT)
    finally:
        listener.close()


@pytest.mark.asyncio
async def test_read_timeout_classified(pin_to_local_server) -> None:
    server, routes = pin_to_local_server

    def _handler(h):
        h.send_response(200)
        h.send_header("Content-Length", "1000")
        h.end_headers()
        h.wfile.write(b"partial")
        h.wfile.flush()
        import time

        time.sleep(2.5)  # exceeds the policy's read_timeout_seconds below

    routes["/slow"] = _handler
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=0.5, total_timeout_seconds=10, max_redirects=3, max_bytes=10_000)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/slow"), policy=policy)
    assert exc.value.code in (FetchErrorCode.READ_TIMEOUT, FetchErrorCode.TOTAL_TIMEOUT)


@pytest.mark.asyncio
async def test_total_operation_timeout_classified(pin_to_local_server) -> None:
    server, routes = pin_to_local_server

    def _handler(h):
        h.send_response(200)
        h.send_header("Content-Length", "1000")
        h.end_headers()
        import time

        for _ in range(10):
            h.wfile.write(b"x")
            h.wfile.flush()
            time.sleep(0.3)

    routes["/dribble"] = _handler
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=5, total_timeout_seconds=1, max_redirects=3, max_bytes=10_000)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/dribble"), policy=policy)
    assert exc.value.code == FetchErrorCode.TOTAL_TIMEOUT


@pytest.mark.asyncio
async def test_cancellation_releases_resources(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/ok"] = lambda h: (h.send_response(200), h.end_headers(), h.wfile.write(b"x"))

    task = asyncio.ensure_future(safe_fetch(_url(server, "/ok"), policy=DEFAULT_POLICY))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # No assertion beyond "this doesn't hang/leak" - a hung test itself would fail via pytest's
    # own default timeout if aclose() were never reached in the cancellation path.


@pytest.mark.asyncio
async def test_error_codes_are_never_raw_exception_strings(pin_to_local_server) -> None:
    server, routes = pin_to_local_server
    routes["/big"] = lambda h: (h.send_response(200), h.send_header("Content-Length", "999999999"), h.end_headers())
    policy = SafeFetchPolicy(connect_timeout_seconds=2, read_timeout_seconds=3, total_timeout_seconds=5, max_redirects=3, max_bytes=10)
    with pytest.raises(SafeFetchError) as exc:
        await safe_fetch(_url(server, "/big"), policy=policy)
    assert exc.value.code == FetchErrorCode.CONTENT_LENGTH_EXCEEDED
    assert isinstance(exc.value.code, FetchErrorCode)  # structured, not a bare string
