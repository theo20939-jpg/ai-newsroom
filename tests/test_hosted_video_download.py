"""Phase V2.27: services.hosted_video_download tests. External downloads are ALWAYS mocked here
(asyncio.create_subprocess_exec) - this suite never invokes a real yt-dlp/ffmpeg binary and never
hits YouTube/Vimeo, per the phase's own explicit instruction."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core.config import settings
from schemas.video_candidate import VideoPlatform
from services.hosted_video_download import (
    HOSTED_VIDEO_DOWNLOAD_FAILED,
    HOSTED_VIDEO_DOWNLOAD_REJECTED,
    HOSTED_VIDEO_NATIVE_READY,
    download_hosted_video,
)

_EVENT_ID = uuid4()
_DRAFT_ID = uuid4()
_YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123"
_VIMEO_URL = "https://vimeo.com/76979871"


def _fake_proc(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"", hang: bool = False) -> AsyncMock:
    proc = AsyncMock()
    if hang:
        async def _communicate():
            import asyncio
            await asyncio.sleep(5)
        proc.communicate = _communicate
    else:
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _write_download_output(tmp_path, *, ext: str = "mp4", video_bytes: bytes = b"fake-mp4-bytes", info: dict | None = None) -> None:
    (tmp_path / f"video.{ext}").write_bytes(video_bytes)
    if info is not None:
        (tmp_path / "video.info.json").write_text(json.dumps(info), encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "hosted_video_download_timeout_seconds", 5.0)
    monkeypatch.setattr(settings, "hosted_video_max_bytes", 50_000_000)
    monkeypatch.setattr(settings, "hosted_video_max_duration_seconds", 180)
    monkeypatch.setattr(settings, "hosted_video_ffmpeg_timeout_seconds", 5.0)


def _patch_mkdtemp(tmp_path):
    return patch("services.hosted_video_download.tempfile.mkdtemp", return_value=str(tmp_path))


# ---------------------------------------------------------------------------
# TEST 1/2 - YouTube/Vimeo URL -> native downloadable video path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_youtube_url_downloads_to_native_ready(tmp_path) -> None:
    info = {"duration": 42, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_NATIVE_READY
    assert result.video_bytes == b"fake-mp4-bytes"
    assert result.duration_seconds == 42
    assert result.byte_size == len(b"fake-mp4-bytes")
    assert result.remuxed is True
    assert result.transcoded is False  # already-compatible H.264/AAC MP4 - no ffmpeg needed


@pytest.mark.asyncio
async def test_vimeo_url_downloads_to_native_ready(tmp_path) -> None:
    """TEST 2 (Phase V2.27 spec): Vimeo follows the exact same path as YouTube."""
    info = {"duration": 15, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_VIMEO_URL, VideoPlatform.VIMEO, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_NATIVE_READY
    assert result.video_bytes == b"fake-mp4-bytes"
    assert result.duration_seconds == 15


# ---------------------------------------------------------------------------
# TEST 3 - channel/profile/playlist URL rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_url_rejected_before_any_subprocess_call() -> None:
    """A URL classify_video_url() does not recognize as a real single-video shape must never
    reach yt-dlp at all - this is the same strict classifier services/video_discovery.py already
    uses to reject channel/user/playlist URLs during discovery, reused here as the download
    gate's own defense-in-depth re-check."""
    channel_url = "https://www.youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        result = await download_hosted_video(channel_url, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_REJECTED
    assert result.video_bytes is None
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_direct_hosted_platform_rejected_never_invokes_downloader() -> None:
    """This module is exclusively for YOUTUBE/VIMEO - a DIRECT_HOSTED platform must never reach
    it (Telegram fetches that URL itself)."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        result = await download_hosted_video(
            "https://cdn.example.com/clip.mp4", VideoPlatform.DIRECT_HOSTED, event_id=_EVENT_ID, draft_id=_DRAFT_ID,
        )

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_REJECTED
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 4 - timeout fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_timeout_falls_back_safely(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "hosted_video_download_timeout_seconds", 0.05)

    async def _create_subprocess_exec(*args, **kwargs):
        return _fake_proc(hang=True)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.reason == "timeout"
    assert result.video_bytes is None
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []  # cleaned up, nothing orphaned


# ---------------------------------------------------------------------------
# TEST 5 - oversized video fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_download_rejected_after_the_fact(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "hosted_video_max_bytes", 10)  # tiny cap - the fake file exceeds it
    info = {"duration": 5, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, video_bytes=b"x" * 1000, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.reason == "oversize"
    assert result.video_bytes is None


@pytest.mark.asyncio
async def test_duration_exceeding_cap_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "hosted_video_max_duration_seconds", 60)
    info = {"duration": 999, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.reason == "duration_exceeded"


# ---------------------------------------------------------------------------
# TEST 6 - unsupported codec -> bounded ffmpeg compatibility path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incompatible_codec_triggers_bounded_ffmpeg_transcode(tmp_path) -> None:
    info = {"duration": 20, "vcodec": "vp9", "acodec": "opus"}  # NOT Telegram-preferred

    call_log: list[list[str]] = []

    async def _create_subprocess_exec(*args, **kwargs):
        call_log.append(list(args))
        if args[0] == "yt-dlp":
            _write_download_output(tmp_path, ext="webm", video_bytes=b"raw-webm-bytes", info=info)
            return _fake_proc(returncode=0)
        if args[0] == "ffmpeg":
            # Real ffmpeg would read the webm and write video_compat.mp4 - simulate that.
            (tmp_path / "video_compat.mp4").write_bytes(b"transcoded-mp4-bytes")
            return _fake_proc(returncode=0)
        raise AssertionError(f"unexpected executable: {args[0]}")

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_NATIVE_READY
    assert result.transcoded is True
    assert result.video_bytes == b"transcoded-mp4-bytes"
    assert any(call[0] == "ffmpeg" for call in call_log)


@pytest.mark.asyncio
async def test_ffmpeg_failure_fails_the_whole_download(tmp_path) -> None:
    info = {"duration": 20, "vcodec": "vp9", "acodec": "opus"}

    async def _create_subprocess_exec(*args, **kwargs):
        if args[0] == "yt-dlp":
            _write_download_output(tmp_path, ext="webm", video_bytes=b"raw-webm-bytes", info=info)
            return _fake_proc(returncode=0)
        return _fake_proc(returncode=1, stderr=b"ffmpeg: unknown error")

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.reason == "ffmpeg_compat_failed"


# ---------------------------------------------------------------------------
# yt-dlp non-zero exit / unavailable video
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yt_dlp_nonzero_exit_classified_as_failed(tmp_path) -> None:
    async def _create_subprocess_exec(*args, **kwargs):
        return _fake_proc(returncode=1, stderr=b"ERROR: Private video. Sign in if you've been granted access.")

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.reason == "private_video"
    assert result.video_bytes is None


# ---------------------------------------------------------------------------
# TEST 11 - temp-file cleanup on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temp_directory_cleaned_up_after_successful_download(tmp_path) -> None:
    info = {"duration": 10, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_NATIVE_READY
    assert not tmp_path.exists()  # shutil.rmtree() always runs, success or failure


# ---------------------------------------------------------------------------
# TEST 12 - cleanup on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temp_directory_cleaned_up_after_yt_dlp_failure(tmp_path) -> None:
    async def _create_subprocess_exec(*args, **kwargs):
        # yt-dlp itself may leave partial artifacts behind even on failure - real-world behavior.
        (tmp_path / "video.part").write_bytes(b"partial-download")
        return _fake_proc(returncode=1, stderr=b"ERROR: network failure")

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert not tmp_path.exists()  # cleaned up despite the failure - no orphaned partial file


@pytest.mark.asyncio
async def test_yt_dlp_binary_missing_fails_open() -> None:
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
        result = await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.reason == "yt_dlp_not_installed"


# ---------------------------------------------------------------------------
# Security: no playlist/cookie flags ever passed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yt_dlp_invocation_never_includes_cookies_or_login_flags(tmp_path) -> None:
    info = {"duration": 10, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}
    captured_args: list[str] = []

    async def _create_subprocess_exec(*args, **kwargs):
        captured_args.extend(args)
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        await download_hosted_video(_YOUTUBE_URL, VideoPlatform.YOUTUBE, event_id=_EVENT_ID, draft_id=_DRAFT_ID)

    assert "--no-playlist" in captured_args
    for forbidden in ("--cookies", "--username", "--password", "--netrc"):
        assert forbidden not in captured_args
    assert "--max-filesize" in captured_args
    assert "--match-filter" in captured_args


# ---------------------------------------------------------------------------
# Phase V2.27A - EMBEDDED_PLAYER (source-site/third-party embedded player, Case C)
# ---------------------------------------------------------------------------

_EMBED_URL = "https://player.example-publisher.com/embed/story-12345"


@pytest.mark.asyncio
async def test_embedded_player_url_downloads_to_native_ready(tmp_path) -> None:
    """TEST 2 (Phase V2.27A spec): a real, article-evidenced third-party embed URL resolves via
    the exact same yt-dlp invocation as YouTube/Vimeo (yt-dlp's own generic/site extractors, no
    new per-site code here)."""
    info = {"duration": 25, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(
            _EMBED_URL, VideoPlatform.EMBEDDED_PLAYER, event_id=_EVENT_ID, draft_id=_DRAFT_ID,
        )

    assert result.outcome == HOSTED_VIDEO_NATIVE_READY
    assert result.video_bytes == b"fake-mp4-bytes"


@pytest.mark.asyncio
async def test_embedded_player_url_no_longer_safe_at_download_time_rejected() -> None:
    """Defense in depth: even if the caller believed the URL was still safe, a re-check against
    is_safe_embed_url() happens here too - a channel/playlist-shaped URL is rejected before any
    subprocess call, mirroring the YouTube/Vimeo reclassification-mismatch check."""
    unsafe_url = "https://player.example.com/channel/some-show"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        result = await download_hosted_video(
            unsafe_url, VideoPlatform.EMBEDDED_PLAYER, event_id=_EVENT_ID, draft_id=_DRAFT_ID,
        )

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_REJECTED
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_embedded_player_resolver_failure_returns_failed(tmp_path) -> None:
    """TEST 6 (Phase V2.27A spec): yt-dlp genuinely cannot resolve the third-party embed (no
    matching extractor, or the page has no real video) - a real, expected outcome, never a crash;
    the caller (worker/content_cycle.py) drops the video and falls back to images/text."""
    async def _create_subprocess_exec(*args, **kwargs):
        return _fake_proc(returncode=1, stderr=b"ERROR: Unsupported URL, no extractor found")

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(
            _EMBED_URL, VideoPlatform.EMBEDDED_PLAYER, event_id=_EVENT_ID, draft_id=_DRAFT_ID,
        )

    assert result.outcome == HOSTED_VIDEO_DOWNLOAD_FAILED
    assert result.video_bytes is None


@pytest.mark.asyncio
async def test_embedded_player_temp_dir_cleaned_up_on_success_and_failure(tmp_path) -> None:
    """TEST 10 (Phase V2.27A spec): the SAME cleanup guarantee already proven for YouTube/Vimeo
    applies unchanged to EMBEDDED_PLAYER - the temp-dir lifecycle in download_hosted_video() is
    completely platform-agnostic."""
    info = {"duration": 10, "vcodec": "avc1.640028", "acodec": "mp4a.40.2"}

    async def _create_subprocess_exec(*args, **kwargs):
        _write_download_output(tmp_path, info=info)
        return _fake_proc(returncode=0)

    with (
        _patch_mkdtemp(tmp_path),
        patch("asyncio.create_subprocess_exec", side_effect=_create_subprocess_exec),
    ):
        result = await download_hosted_video(
            _EMBED_URL, VideoPlatform.EMBEDDED_PLAYER, event_id=_EVENT_ID, draft_id=_DRAFT_ID,
        )

    assert result.outcome == HOSTED_VIDEO_NATIVE_READY
    assert not tmp_path.exists()


# ---------------------------------------------------------------------------
# TEST 1 (Phase V2.27A spec) - yt-dlp/ffmpeg dependency path available in Docker assumptions.
# Structural only - this suite cannot build a real Docker image; it proves the exact source
# changes exist and are shaped correctly for `pip install .` / `apt-get install` to provision them.
# ---------------------------------------------------------------------------


def test_pyproject_declares_yt_dlp_dependency() -> None:
    from pathlib import Path

    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"yt-dlp>=' in text


def test_dockerfile_installs_ffmpeg_in_the_existing_apt_layer_not_a_new_one() -> None:
    from pathlib import Path

    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert text.count("apt-get install") == 1  # still exactly one apt-get install layer
    assert "fonts-dejavu-core ffmpeg" in text
