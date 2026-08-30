"""Phase V2.27/V2.27A: bounded, server-side download of a hosted-platform video, so it can be
uploaded to Telegram as a native video instead of only ever appearing as a plain caption link
(the pre-V2.27 behavior - see services/image_preview_notifier.py::_hosted_platform_link_line()).
Supports YouTube/Vimeo (Phase V2.27) and, as of Phase V2.27A, an already-article-evidenced
third-party embedded-player URL (`VideoPlatform.EMBEDDED_PLAYER` - see services/video_discovery.py
::is_safe_embed_url()'s own docstring for exactly what evidence qualifies and what safety checks
apply) - never DIRECT_HOSTED (Telegram fetches that URL itself, no local download needed) or
UNKNOWN.

Security/resource-safety contract (Phase V2.27 §9 - every point below is enforced, not aspirational):
  - YOUTUBE/VIMEO: only a URL `services/video_discovery.py::classify_video_url()` already
    classified as YOUTUBE or VIMEO may reach yt-dlp - re-checked HERE too (defense in depth, never
    trust a caller's own prior classification alone). Since that classifier only recognizes a
    small, fixed set of real YouTube/Vimeo hostnames (youtube.com/youtube-nocookie.com/youtu.be/
    vimeo.com/player.vimeo.com), a localhost or private-network URL can never pass this gate.
  - EMBEDDED_PLAYER (Phase V2.27A): only a URL `services/video_discovery.py::is_safe_embed_url()`
    still accepts on re-check may reach yt-dlp - see that function's own docstring for its real,
    disclosed limitations (a denylist heuristic against an arbitrary third-party host, not a full
    SSRF-hardened boundary like integrations/http/safe_fetch.py's own DNS-pinning).
  - `--no-playlist` is passed explicitly, on top of the platform-appropriate classifier's own
    path-shape filtering (a channel/user/@handle/playlist/results URL already classifies as
    UNKNOWN/rejected before reaching this module at all) - two independent layers against
    playlist/channel expansion.
  - No cookies, no login, no `--username`/`--password`/`--netrc` flag is ever passed - only
    normal, publicly-viewable videos are supported, exactly as required.
  - Bounded wall-clock time (`asyncio.wait_for`, `settings.hosted_video_download_timeout_seconds`)
    - the subprocess is killed, never left to run unbounded, on timeout.
  - Bounded size: yt-dlp's own `--max-filesize` pre-check, PLUS a real on-disk byte-count
    re-check after download (the pre-check is a best-effort estimate from declared metadata, not
    always accurate for every source/format - never trusted alone).
  - Bounded duration: yt-dlp's own `--match-filter` skips/aborts before downloading anything once
    declared duration is known to exceed the cap.
  - One deterministic, single-use temp directory per call (`tempfile.mkdtemp()`), always removed
    in a `finally` block regardless of outcome - never an orphaned temp file, never any video
    bytes written anywhere else in the filesystem (never the repo, never a shared/uncleaned path).

Telegram-compatibility contract (Phase V2.27 §3): yt-dlp's own format selector already prefers an
H.264/AAC MP4 stream pair (already Telegram-compatible - no extra work needed, the "remux" case).
Only when that is genuinely unavailable does this module fall back to a bounded ffmpeg re-encode
(the "transcode" case, `settings.hosted_video_ffmpeg_timeout_seconds`) - never invoked
unnecessarily.

Fail-open contract (Phase V2.27 §7): every failure mode below returns a `HostedVideoDownloadResult`
with `video_bytes=None` and a descriptive `outcome`/`reason` - this module never raises past its
own boundary, mirroring every other best-effort boundary in this codebase (e.g. services/
editorial_recomposition.py's own "fails open to the original bytes" contract). The caller
(worker/content_cycle.py) is responsible for what happens next (drop the video, keep any images,
degrade to text-only) - this module has no opinion about NEWS delivery at all.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from core.config import settings
from schemas.video_candidate import VideoPlatform
from services.video_discovery import classify_video_url, is_safe_embed_url

logger = logging.getLogger(__name__)

HOSTED_VIDEO_DOWNLOAD_STARTED = "HOSTED_VIDEO_DOWNLOAD_STARTED"
HOSTED_VIDEO_DOWNLOAD_OK = "HOSTED_VIDEO_DOWNLOAD_OK"
HOSTED_VIDEO_DOWNLOAD_REJECTED = "HOSTED_VIDEO_DOWNLOAD_REJECTED"
HOSTED_VIDEO_DOWNLOAD_FAILED = "HOSTED_VIDEO_DOWNLOAD_FAILED"
HOSTED_VIDEO_NATIVE_READY = "HOSTED_VIDEO_NATIVE_READY"

# H.264/AAC MP4 is preferred directly from yt-dlp's own format selection (no local re-encode
# needed) - falls back to any MP4, then to whatever the extractor considers "best", in that order.
_YT_DLP_FORMAT = "bv*[vcodec~='^(avc|h264)']+ba[acodec~='^(mp4a|aac)']/b[ext=mp4]/b"
_COMPATIBLE_VCODEC_PREFIXES = ("avc1", "h264")
_COMPATIBLE_ACODEC_PREFIXES = ("mp4a", "aac")
_STDERR_LOG_MAX_CHARS = 400


@dataclass(frozen=True)
class HostedVideoDownloadResult:
    outcome: str
    video_bytes: bytes | None
    source_format: str | None
    final_format: str | None
    remuxed: bool
    transcoded: bool
    byte_size: int | None
    duration_seconds: int | None
    reason: str | None


def _rejected(reason: str) -> HostedVideoDownloadResult:
    return HostedVideoDownloadResult(
        outcome=HOSTED_VIDEO_DOWNLOAD_REJECTED, video_bytes=None, source_format=None,
        final_format=None, remuxed=False, transcoded=False, byte_size=None, duration_seconds=None,
        reason=reason,
    )


def _failed(reason: str) -> HostedVideoDownloadResult:
    return HostedVideoDownloadResult(
        outcome=HOSTED_VIDEO_DOWNLOAD_FAILED, video_bytes=None, source_format=None,
        final_format=None, remuxed=False, transcoded=False, byte_size=None, duration_seconds=None,
        reason=reason,
    )


async def _run_bounded(args: list[str], *, timeout_seconds: float) -> tuple[int | None, bytes, bytes]:
    """Runs `args` as a subprocess (never shell=True - args are passed as a list, never a shell
    string) with a hard wall-clock bound. Returns (returncode, stdout, stderr); returncode is
    `None` on timeout (the process is killed first). Never raises for a timeout or a non-zero
    return code - only for a genuinely missing executable (`FileNotFoundError`), which the caller
    catches."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        return proc.returncode, stdout, stderr
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return None, b"", b""


def _read_info_json(tmp_dir: str) -> dict | None:
    matches = glob.glob(str(Path(tmp_dir) / "video.info.json"))
    if not matches:
        return None
    try:
        return json.loads(Path(matches[0]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _find_downloaded_media_file(tmp_dir: str) -> Path | None:
    candidates = [
        Path(p) for p in glob.glob(str(Path(tmp_dir) / "video.*"))
        if not p.endswith(".info.json") and not p.endswith(".part")
    ]
    return candidates[0] if candidates else None


def _is_telegram_compatible(info: dict | None, ext: str | None) -> bool:
    if ext != "mp4" or info is None:
        return False
    vcodec = str(info.get("vcodec") or "").lower()
    acodec = str(info.get("acodec") or "").lower()
    video_ok = vcodec.startswith(_COMPATIBLE_VCODEC_PREFIXES)
    audio_ok = acodec.startswith(_COMPATIBLE_ACODEC_PREFIXES) or acodec in ("", "none")
    return video_ok and audio_ok


async def _transcode_to_compatible_mp4(source: Path, tmp_dir: str) -> Path | None:
    """Bounded ffmpeg fallback - only reached when yt-dlp's own format selection could not
    directly produce an H.264/AAC MP4. Never invoked for the common case."""
    output = Path(tmp_dir) / "video_compat.mp4"
    args = [
        "ffmpeg", "-y", "-i", str(source),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-movflags", "+faststart", str(output),
    ]
    try:
        returncode, _stdout, stderr = await _run_bounded(
            args, timeout_seconds=settings.hosted_video_ffmpeg_timeout_seconds,
        )
    except FileNotFoundError:
        logger.warning("hosted_video_ffmpeg_not_installed")
        return None
    if returncode != 0 or not output.exists():
        logger.warning(
            "hosted_video_ffmpeg_failed",
            extra={"returncode": returncode, "stderr": stderr[:_STDERR_LOG_MAX_CHARS].decode("utf-8", "replace")},
        )
        return None
    return output


async def download_hosted_video(
    url: str, platform: VideoPlatform, *, event_id: UUID, draft_id: UUID | None,
) -> HostedVideoDownloadResult:
    """The one entry point. `platform` must already be YOUTUBE or VIMEO (re-validated below,
    never trusted from the caller alone) - never call this for DIRECT_HOSTED (Telegram fetches
    that URL itself, no local download needed) or UNKNOWN."""
    if platform not in (VideoPlatform.YOUTUBE, VideoPlatform.VIMEO, VideoPlatform.EMBEDDED_PLAYER):
        return _rejected("not_a_hosted_platform_url")
    if platform in (VideoPlatform.YOUTUBE, VideoPlatform.VIMEO):
        if classify_video_url(url) != platform:
            # Defense in depth: the URL no longer classifies the way the caller believes it does
            # (e.g. a stale persisted row, or a caller bug) - never trust a passed-in platform
            # alone.
            logger.warning(
                "hosted_video_download_reclassification_mismatch",
                extra={"event_id": str(event_id), "draft_id": str(draft_id) if draft_id else None},
            )
            return _rejected("url_reclassification_mismatch")
    else:  # EMBEDDED_PLAYER - re-checked against is_safe_embed_url(), never classify_video_url()
        if not is_safe_embed_url(url):
            logger.warning(
                "hosted_video_download_embed_url_no_longer_safe",
                extra={"event_id": str(event_id), "draft_id": str(draft_id) if draft_id else None},
            )
            return _rejected("embed_url_reclassification_mismatch")

    log_extra_base = {
        "platform": platform.value, "event_id": str(event_id),
        "draft_id": str(draft_id) if draft_id else None,
    }
    logger.info(HOSTED_VIDEO_DOWNLOAD_STARTED, extra=log_extra_base)

    tmp_dir = tempfile.mkdtemp(prefix="hosted_video_")
    try:
        output_template = str(Path(tmp_dir) / "video.%(ext)s")
        args = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            "--write-info-json",
            "--merge-output-format", "mp4",
            "-f", _YT_DLP_FORMAT,
            "--max-filesize", str(settings.hosted_video_max_bytes),
            "--match-filter", f"duration <= {settings.hosted_video_max_duration_seconds}",
            "-o", output_template,
            url,
        ]
        try:
            returncode, _stdout, stderr = await _run_bounded(
                args, timeout_seconds=settings.hosted_video_download_timeout_seconds,
            )
        except FileNotFoundError:
            logger.error("hosted_video_yt_dlp_not_installed", extra=log_extra_base)
            return _failed("yt_dlp_not_installed")

        if returncode is None:
            logger.warning(HOSTED_VIDEO_DOWNLOAD_FAILED, extra={**log_extra_base, "reason": "timeout"})
            return _failed("timeout")

        if returncode != 0:
            stderr_text = stderr[:_STDERR_LOG_MAX_CHARS].decode("utf-8", "replace")
            reason = _classify_yt_dlp_error(stderr_text)
            logger.warning(HOSTED_VIDEO_DOWNLOAD_FAILED, extra={**log_extra_base, "reason": reason})
            return _failed(reason)

        media_path = _find_downloaded_media_file(tmp_dir)
        if media_path is None:
            logger.warning(HOSTED_VIDEO_DOWNLOAD_FAILED, extra={**log_extra_base, "reason": "no_output_file"})
            return _failed("no_output_file")

        byte_size = media_path.stat().st_size
        if byte_size > settings.hosted_video_max_bytes:
            logger.warning(
                HOSTED_VIDEO_DOWNLOAD_FAILED, extra={**log_extra_base, "reason": "oversize", "byte_size": byte_size},
            )
            return _failed("oversize")

        info = _read_info_json(tmp_dir)
        duration = None
        if info is not None:
            raw_duration = info.get("duration")
            duration = int(raw_duration) if isinstance(raw_duration, (int, float)) else None
        if duration is not None and duration > settings.hosted_video_max_duration_seconds:
            logger.warning(
                HOSTED_VIDEO_DOWNLOAD_FAILED,
                extra={**log_extra_base, "reason": "duration_exceeded", "duration": duration},
            )
            return _failed("duration_exceeded")

        source_ext = media_path.suffix.lstrip(".")
        source_format = f"{info.get('vcodec')}/{info.get('acodec')}/{source_ext}" if info else source_ext
        logger.info(
            HOSTED_VIDEO_DOWNLOAD_OK,
            extra={**log_extra_base, "byte_size": byte_size, "duration": duration, "format": source_ext},
        )

        final_path = media_path
        transcoded = False
        if not _is_telegram_compatible(info, source_ext):
            transcoded_path = await _transcode_to_compatible_mp4(media_path, tmp_dir)
            if transcoded_path is None:
                logger.warning(
                    HOSTED_VIDEO_DOWNLOAD_FAILED, extra={**log_extra_base, "reason": "ffmpeg_compat_failed"},
                )
                return _failed("ffmpeg_compat_failed")
            final_path = transcoded_path
            transcoded = True

        final_bytes = final_path.read_bytes()
        final_byte_size = len(final_bytes)
        if final_byte_size > settings.hosted_video_max_bytes:
            logger.warning(
                HOSTED_VIDEO_DOWNLOAD_FAILED,
                extra={**log_extra_base, "reason": "oversize_after_transcode", "byte_size": final_byte_size},
            )
            return _failed("oversize_after_transcode")

        logger.info(
            HOSTED_VIDEO_NATIVE_READY,
            extra={
                **log_extra_base, "duration": duration, "byte_size": final_byte_size,
                "source_format": source_format, "final_format": "mp4/h264/aac",
                "remuxed": True, "transcoded": transcoded,
            },
        )
        return HostedVideoDownloadResult(
            outcome=HOSTED_VIDEO_NATIVE_READY, video_bytes=final_bytes, source_format=source_format,
            final_format="mp4/h264/aac", remuxed=True, transcoded=transcoded, byte_size=final_byte_size,
            duration_seconds=duration, reason=None,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_KNOWN_UNAVAILABLE_MARKERS = (
    ("private video", "private_video"),
    ("video unavailable", "video_unavailable"),
    ("sign in to confirm", "age_or_signin_required"),
    ("this video is not available", "not_available_in_region"),
    ("has been removed", "removed"),
    ("does not exist", "not_found"),
    ("copyright", "copyright_blocked"),
)


def _classify_yt_dlp_error(stderr_text: str) -> str:
    lowered = stderr_text.lower()
    for marker, code in _KNOWN_UNAVAILABLE_MARKERS:
        if marker in lowered:
            return code
    if "did not match" in lowered or "requested format" in lowered:
        return "no_matching_format"
    return "yt_dlp_error"
