"""INSTAGRAM GROWTH ENGINE v2, spec §28: AudioTrend contract. `availability`/`rights_status` stay
UNKNOWN by default - services/instagram_platform_capabilities.py's own "audio_trend_data" capability
is UNKNOWN (no first-party or third-party audio-trend data source is wired anywhere), and this
module never fakes a live acquisition mechanism on top of that."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioTrend:
    platform: str
    audio_reference: str
    trend_state: str
    velocity: float = 0.0
    age_days: float = 0.0
    format_fit: str = ""
    campaign_fit: float = 0.0
    availability: str = "unknown"
    rights_status: str = "unknown"
    confidence: float = 0.1
    source: str = "unknown"
