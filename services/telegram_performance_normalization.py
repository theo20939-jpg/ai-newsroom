"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §8: time-window normalization.
A 24h-old post and a 15-minute-old post are never directly comparable on raw counts - every rate
below is computed only when its denominator (age_seconds) is a real, positive, already-elapsed
duration, and returns None (never a fabricated 0.0) when the numerator metric itself is None
(spec §5's "unavailable != zero" carried through into every derived rate)."""
from __future__ import annotations

from database.models.telegram_post_performance import TelegramPostPerformanceSnapshot

_SECONDS_PER_HOUR = 3600.0


def _rate_per_hour(count: int | None, age_seconds: int) -> float | None:
    if count is None:
        return None
    if age_seconds <= 0:
        return None
    return count / (age_seconds / _SECONDS_PER_HOUR)


def views_velocity_per_hour(snapshot: TelegramPostPerformanceSnapshot) -> float | None:
    return _rate_per_hour(snapshot.views, snapshot.age_seconds)


def reaction_rate_per_hour(snapshot: TelegramPostPerformanceSnapshot) -> float | None:
    return _rate_per_hour(snapshot.reactions_total, snapshot.age_seconds)


def forward_rate_per_hour(snapshot: TelegramPostPerformanceSnapshot) -> float | None:
    return _rate_per_hour(snapshot.forwards, snapshot.age_seconds)


def comment_rate_per_hour(snapshot: TelegramPostPerformanceSnapshot) -> float | None:
    return _rate_per_hour(snapshot.comments_total, snapshot.age_seconds)


def reaction_per_view_ratio(snapshot: TelegramPostPerformanceSnapshot) -> float | None:
    """Engagement-per-reach ratio - deliberately NOT time-normalized (both numerator and
    denominator carry the same age bias, so it cancels out), but still None (never 0.0) whenever
    either side is unavailable or views is zero."""
    if snapshot.reactions_total is None or snapshot.views is None:
        return None
    if snapshot.views == 0:
        return None
    return snapshot.reactions_total / snapshot.views


def same_window_snapshots(
    snapshots: list[TelegramPostPerformanceSnapshot], *, window: str,
) -> list[TelegramPostPerformanceSnapshot]:
    """Comparable-baseline helper (spec §7/§8): callers must only compare snapshots captured at the
    SAME nominal window (e.g. all "1h" snapshots), never a "24h" snapshot against a "15m" one, even
    if their raw `age_seconds` happen to be numerically close."""
    return [s for s in snapshots if s.window.value == window]
