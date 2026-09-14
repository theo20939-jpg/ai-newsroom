"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §6/§15: the real media-hosting mechanism. No real
network write anywhere in this file - `is_safe_public_base_url()` does real DNS resolution for a
handful of well-known/synthetic hostnames, never an HTTP request."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from services.instagram_media_hosting import (
    MAX_ASSET_BYTES,
    MediaHostingError,
    build_public_media_url,
    get_publication_asset,
    is_safe_public_base_url,
    media_hosting_readiness,
    register_publication_asset,
)


def _real_jpeg_bytes(size: tuple[int, int] = (400, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(120, 40, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_register_and_lookup_round_trip() -> None:
    data = _real_jpeg_bytes()
    asset = register_publication_asset(data, package_id="pkg-1")
    assert len(asset.asset_id) == 32
    fetched = get_publication_asset(asset.asset_id)
    assert fetched is not None
    assert fetched.local_path.read_bytes() == data


def test_identical_bytes_produce_the_same_asset_id_no_duplicate_file() -> None:
    data = _real_jpeg_bytes()
    a = register_publication_asset(data, package_id="pkg-a")
    b = register_publication_asset(data, package_id="pkg-b")
    assert a.asset_id == b.asset_id
    assert a.local_path == b.local_path


def test_oversized_asset_rejected() -> None:
    with pytest.raises(MediaHostingError):
        register_publication_asset(b"x" * (MAX_ASSET_BYTES + 1), package_id="pkg-big")


def test_non_image_bytes_rejected() -> None:
    with pytest.raises(MediaHostingError):
        register_publication_asset(b"not an image at all", package_id="pkg-bad")


def test_png_rejected_only_jpeg_accepted_for_instagram() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200)).save(buf, format="PNG")
    with pytest.raises(MediaHostingError):
        register_publication_asset(buf.getvalue(), package_id="pkg-png")


def test_lookup_rejects_malformed_id_never_touches_filesystem() -> None:
    assert get_publication_asset("../../etc/passwd") is None
    assert get_publication_asset("not-hex-at-all-just-garbage-text!!") is None
    assert get_publication_asset("") is None
    assert get_publication_asset("a" * 31) is None  # one char short


def test_lookup_of_never_registered_id_is_none() -> None:
    assert get_publication_asset("f" * 32) is None


# ---------------------------------------------------------------------------
# §15 - reject localhost/private URLs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    None,
    "",
    "http://example.com/x",  # not https
    "https://localhost/x",
    "https://127.0.0.1/x",
    "https://0.0.0.0/x",
    "https://192.168.1.10/x",  # private IPv4
    "https://10.0.0.5/x",  # private IPv4
    "https://[::1]/x",  # loopback IPv6
    "not-a-url-at-all",
])
def test_unsafe_or_local_urls_rejected(url: str | None) -> None:
    assert is_safe_public_base_url(url) is False


def test_real_public_https_domain_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))])
    assert is_safe_public_base_url("https://cdn.example.com") is True


def test_hostname_resolving_only_to_private_ips_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", ("10.0.0.5", 0))])
    assert is_safe_public_base_url("https://internal.example.com") is False


def test_hostname_that_does_not_resolve_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _raise(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    assert is_safe_public_base_url("https://nonexistent.example.invalid") is False


def test_build_public_media_url_returns_none_when_base_url_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default production state - `instagram_media_public_base_url` unset -> never fabricates a URL."""
    from core.config import settings

    monkeypatch.setattr(settings, "instagram_media_public_base_url", None)
    asset = register_publication_asset(_real_jpeg_bytes(), package_id="pkg-nourl")
    assert build_public_media_url(asset) is None


def test_build_public_media_url_returns_none_for_an_unsafe_configured_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "instagram_media_public_base_url", "http://localhost:8000")
    asset = register_publication_asset(_real_jpeg_bytes(), package_id="pkg-unsafe")
    assert build_public_media_url(asset) is None


def test_build_public_media_url_succeeds_for_a_real_safe_configured_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uses a mocked DNS resolution (never live network dependency in a unit test - mirrors this
    repo's own established "no real network in tests" convention) reporting a real public IP for
    a synthetic CDN hostname."""
    import socket

    from core.config import settings

    monkeypatch.setattr(settings, "instagram_media_public_base_url", "https://cdn.example.com")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))])
    asset = register_publication_asset(_real_jpeg_bytes(), package_id="pkg-safe")
    url = build_public_media_url(asset)
    assert url == f"https://cdn.example.com/media/instagram/{asset.asset_id}.jpg"


def test_media_hosting_readiness_is_false_by_default_in_this_environment() -> None:
    """Confirms the honest, disclosed current state: code is real and tested, but nothing is
    configured to make it publicly reachable yet."""
    readiness = media_hosting_readiness()
    assert readiness["code_path_ready"] is True
    assert readiness["media_hosting_ready"] is False


def test_media_hosting_readiness_true_once_a_real_safe_base_url_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from core.config import settings

    monkeypatch.setattr(settings, "instagram_media_public_base_url", "https://cdn.example.com")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))])
    assert media_hosting_readiness()["media_hosting_ready"] is True


# ---------------------------------------------------------------------------
# §15 - the serving route itself.
# ---------------------------------------------------------------------------


def test_route_serves_a_registered_asset_and_404s_for_unknown_ids() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    data = _real_jpeg_bytes()
    asset = register_publication_asset(data, package_id="pkg-route")
    client = TestClient(app, base_url="http://localhost")

    ok = client.get(f"/media/instagram/{asset.asset_id}.jpg")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"
    assert ok.content == data

    missing = client.get("/media/instagram/" + "0" * 32 + ".jpg")
    assert missing.status_code == 404


def test_route_never_serves_an_arbitrary_path() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, base_url="http://localhost")
    # FastAPI's own path-matching already prevents "../" from reaching the handler as a literal
    # traversal segment, but the handler's own validation (exact 32-hex match) is the real backstop
    # - proven directly against get_publication_asset() above; here we confirm the route layer
    # itself never returns anything but 404 for a non-matching pattern.
    resp = client.get("/media/instagram/whatever-not-a-real-id.jpg")
    assert resp.status_code == 404
