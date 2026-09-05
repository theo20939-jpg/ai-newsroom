"""INSTAGRAM GROWTH ENGINE v2, spec Part M (§27/§28/§49/§51): Creator Radar, Audio Intelligence,
Profile Funnel, and Winner Amplification - lean contract/behavior tests."""
from __future__ import annotations

from services.instagram_audio_intelligence import AudioTrend
from services.instagram_creator_radar import CreatorOpportunity, CreatorProfile
from services.instagram_format_director import ContentFormat
from services.instagram_growth_strategist import suggest_amplification
from services.instagram_profile_funnel import ProfileFunnelObservation, ProfileFunnelStep


def test_creator_opportunity_never_carries_a_contact_action() -> None:
    opportunity = CreatorOpportunity(
        creator_handle="@creator1", collab_type="guest_reel", objective="reach", reason="strong audience overlap",
    )
    assert not hasattr(opportunity, "send_message")
    assert not hasattr(opportunity, "contact")


def test_creator_profile_defaults_are_low_confidence_not_fabricated() -> None:
    profile = CreatorProfile(handle="@creator2", platform="instagram")
    assert profile.confidence <= 0.5
    assert profile.evidence == []


def test_audio_trend_defaults_to_unknown_availability_and_rights() -> None:
    audio = AudioTrend(platform="instagram", audio_reference="track-123", trend_state="emerging")
    assert audio.availability == "unknown"
    assert audio.rights_status == "unknown"


def test_profile_funnel_observation_count_defaults_to_none_not_zero() -> None:
    observation = ProfileFunnelObservation(content_id="c1", step=ProfileFunnelStep.PROFILE_VISIT)
    assert observation.count is None


def test_winner_amplification_never_suggests_automatic_duplication() -> None:
    suggestions = suggest_amplification(winner_content_id="c1", winner_format=ContentFormat.REEL)
    assert any("Stories amplification" in s for s in suggestions)
    assert any("Carousel expansion" in s for s in suggestions)
    assert any("never an automatic duplicate" in s for s in suggestions)
