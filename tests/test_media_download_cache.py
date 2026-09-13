"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 15: services.media_download_cache.

Unit-tier only: `safe_fetch` itself is monkeypatched (it is already tested exhaustively in
tests/test_safe_fetch.py) - this module's own tests only prove the NEW bounded-cache/hashing/
safety-limit logic this phase adds on top of it.
"""
from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image

from integrations.http.safe_fetch import FetchErrorCode, SafeFetchError, SafeFetchResult
from services import media_download_cache


def _make_tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


_TINY_PNG = _make_tiny_png()


def _fake_result(body: bytes) -> SafeFetchResult:
    return SafeFetchResult(
        requested_url="https://x.example/a.png", final_url="https://x.example/a.png", status_code=200,
        redirect_count=0, declared_content_type="image/png", received_byte_count=len(body), duration_seconds=0.01,
        body=body,
    )


@pytest.mark.asyncio
async def test_successful_download_writes_a_content_hash_named_file(monkeypatch, tmp_path) -> None:
    async def fake_safe_fetch(url, *, policy):
        return _fake_result(_TINY_PNG)

    monkeypatch.setattr(media_download_cache, "safe_fetch", fake_safe_fetch)

    outcome = await media_download_cache.download_and_validate("https://x.example/a.png", cache_dir=tmp_path)

    assert outcome.ok is True
    assert outcome.sha256 == hashlib.sha256(_TINY_PNG).hexdigest()
    assert outcome.local_path is not None
    assert outcome.local_path.endswith(f"{outcome.sha256}.png")
    assert (tmp_path / f"{outcome.sha256}.png").exists()
    assert outcome.perceptual_hash is not None


@pytest.mark.asyncio
async def test_re_downloading_the_same_bytes_reuses_the_cached_file_never_duplicates(monkeypatch, tmp_path) -> None:
    call_count = 0

    async def fake_safe_fetch(url, *, policy):
        nonlocal call_count
        call_count += 1
        return _fake_result(_TINY_PNG)

    monkeypatch.setattr(media_download_cache, "safe_fetch", fake_safe_fetch)

    first = await media_download_cache.download_and_validate("https://x.example/a.png", cache_dir=tmp_path)
    second = await media_download_cache.download_and_validate("https://x.example/b-different-url-same-bytes.png", cache_dir=tmp_path)

    assert first.local_path == second.local_path  # same content hash -> same cached file
    assert len(list(tmp_path.glob("*"))) == 1


@pytest.mark.asyncio
async def test_safe_fetch_failure_never_raises_returns_structured_error(monkeypatch, tmp_path) -> None:
    async def fake_safe_fetch(url, *, policy):
        raise SafeFetchError(FetchErrorCode.BLOCKED_IP)

    monkeypatch.setattr(media_download_cache, "safe_fetch", fake_safe_fetch)

    outcome = await media_download_cache.download_and_validate("https://x.example/a.png", cache_dir=tmp_path)

    assert outcome.ok is False
    assert outcome.error_code == "blocked_ip"
    assert outcome.local_path is None


@pytest.mark.asyncio
async def test_invalid_image_bytes_are_rejected_never_cached(monkeypatch, tmp_path) -> None:
    async def fake_safe_fetch(url, *, policy):
        return _fake_result(b"not a real image, just html <html>oops</html>")

    monkeypatch.setattr(media_download_cache, "safe_fetch", fake_safe_fetch)

    outcome = await media_download_cache.download_and_validate("https://x.example/a.png", cache_dir=tmp_path)

    assert outcome.ok is False
    assert outcome.error_code is not None
    assert list(tmp_path.glob("*")) == []


@pytest.mark.asyncio
async def test_cache_full_refuses_new_files_never_grows_unbounded(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(media_download_cache, "_MAX_CACHE_FILES", 1)
    # Pre-fill the cache to its bound with an unrelated file.
    (tmp_path / "already_here.jpg").write_bytes(b"x")

    async def fake_safe_fetch(url, *, policy):
        return _fake_result(_TINY_PNG)

    monkeypatch.setattr(media_download_cache, "safe_fetch", fake_safe_fetch)

    outcome = await media_download_cache.download_and_validate("https://x.example/a.png", cache_dir=tmp_path)

    assert outcome.ok is False
    assert outcome.error_code == "cache_full"
