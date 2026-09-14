"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §9/§13/§15: ambiguous-write reconciliation. No real
network call - `_FakeReader` never touches the network."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from services.instagram_ambiguous_write_reconciliation import reconcile_ambiguous_publish

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeMedia:
    media_id: str
    caption: str | None
    timestamp: str | None
    permalink: str | None = None


class _FakeReader:
    def __init__(self, media: list[_FakeMedia] | None = None, *, raises: Exception | None = None):
        self._media = media or []
        self._raises = raises

    async def fetch_recent_media(self, limit: int = 30) -> list[_FakeMedia]:
        if self._raises is not None:
            raise self._raises
        return self._media


async def test_confirmed_published_when_a_matching_recent_post_exists() -> None:
    now = datetime.now(timezone.utc)
    reader = _FakeReader([
        _FakeMedia(media_id="123", caption="Apple just announced the new foldable iPhone today.", timestamp=now.isoformat(), permalink="https://instagram.com/p/abc/"),
    ])
    outcome = await reconcile_ambiguous_publish(
        reader, expected_caption_prefix="Apple just announced the new foldable iPhone today.", attempted_at=now,
    )
    assert outcome.resolution == "confirmed_published"
    assert outcome.matched_media_id == "123"
    assert outcome.matched_permalink == "https://instagram.com/p/abc/"


async def test_confirmed_absent_when_no_matching_post_and_window_elapsed() -> None:
    old_attempt = datetime.now(timezone.utc) - timedelta(minutes=30)
    reader = _FakeReader([])
    outcome = await reconcile_ambiguous_publish(reader, expected_caption_prefix="Something that never posted.", attempted_at=old_attempt, window_minutes=5)
    assert outcome.resolution == "confirmed_absent"


async def test_unknown_when_window_has_not_elapsed_yet() -> None:
    """Never concludes "absent" prematurely - if the readback window has not actually passed,
    the correct answer is still "unknown", not a false confirmation of absence."""
    just_now = datetime.now(timezone.utc)
    reader = _FakeReader([])
    outcome = await reconcile_ambiguous_publish(reader, expected_caption_prefix="Just attempted.", attempted_at=just_now, window_minutes=15)
    assert outcome.resolution == "unknown"


async def test_unknown_when_the_readback_itself_fails_never_raises() -> None:
    reader = _FakeReader(raises=RuntimeError("simulated network error on the read side too"))
    outcome = await reconcile_ambiguous_publish(reader, expected_caption_prefix="Anything.", attempted_at=datetime.now(timezone.utc))
    assert outcome.resolution == "unknown"


async def test_unrelated_recent_post_does_not_count_as_a_match() -> None:
    old_attempt = datetime.now(timezone.utc) - timedelta(minutes=30)
    reader = _FakeReader([
        _FakeMedia(media_id="999", caption="Totally unrelated post about something else.", timestamp=datetime.now(timezone.utc).isoformat()),
    ])
    outcome = await reconcile_ambiguous_publish(reader, expected_caption_prefix="Apple just announced the new foldable iPhone.", attempted_at=old_attempt, window_minutes=5)
    assert outcome.resolution == "confirmed_absent"


async def test_post_outside_the_time_window_does_not_count_as_a_match() -> None:
    old_attempt = datetime.now(timezone.utc) - timedelta(minutes=30)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=5)
    reader = _FakeReader([
        _FakeMedia(media_id="1", caption="Apple just announced the new foldable iPhone.", timestamp=long_ago.isoformat()),
    ])
    outcome = await reconcile_ambiguous_publish(reader, expected_caption_prefix="Apple just announced the new foldable iPhone.", attempted_at=old_attempt, window_minutes=5)
    assert outcome.resolution == "confirmed_absent"
