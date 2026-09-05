"""NINJA Social Intelligence Foundation §9/§10/§106: deterministic phase derivation. Pure unit
tests - no DB, no LLM - `LaunchCampaign` rows are constructed in-memory only (never added to a
session), mirroring the pure-function testing style already used for services/campaign_planner.py's
own sibling deterministic modules (e.g. services/editorial_scoring.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from database.models.campaign import CampaignStatus, DateConfidence, LaunchCampaign
from services.campaign_planner import CampaignPhase, build_campaign_plan, derive_phase

_NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _campaign(**overrides) -> LaunchCampaign:
    defaults = dict(
        id=uuid4(), product_id=uuid4(), name="Test Campaign", status=CampaignStatus.DRAFT,
        date_confidence=DateConfidence.UNKNOWN, planned_launch_date=None, start_at=None, end_at=None,
    )
    defaults.update(overrides)
    return LaunchCampaign(**defaults)


def test_draft_has_no_phase() -> None:
    assert derive_phase(_campaign(status=CampaignStatus.DRAFT), now=_NOW) is None


def test_cancelled_has_no_phase() -> None:
    assert derive_phase(_campaign(status=CampaignStatus.CANCELLED), now=_NOW) is None


def test_tentative_with_concrete_date_still_only_awareness() -> None:
    """§10's own critical safety contract: a TENTATIVE campaign with a real planned_launch_date
    must NEVER resolve to COUNTDOWN/FEATURE_REVEAL/LAUNCH - only the generic AWARENESS phase,
    regardless of how close that date is."""
    campaign = _campaign(
        status=CampaignStatus.TENTATIVE, planned_launch_date=(_NOW.date() + timedelta(days=1)),
        date_confidence=DateConfidence.ESTIMATED,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.AWARENESS


def test_confirmed_far_out_is_awareness() -> None:
    campaign = _campaign(
        status=CampaignStatus.CONFIRMED, planned_launch_date=_NOW.date() + timedelta(days=60),
        date_confidence=DateConfidence.EXACT,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.AWARENESS


def test_confirmed_at_t_minus_25_is_awareness() -> None:
    campaign = _campaign(
        status=CampaignStatus.CONFIRMED, planned_launch_date=_NOW.date() + timedelta(days=25),
        date_confidence=DateConfidence.EXACT,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.AWARENESS


def test_confirmed_at_t_minus_10_is_product_teasing() -> None:
    campaign = _campaign(
        status=CampaignStatus.CONFIRMED, planned_launch_date=_NOW.date() + timedelta(days=10),
        date_confidence=DateConfidence.EXACT,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.PRODUCT_TEASING


def test_confirmed_at_t_minus_2_is_countdown() -> None:
    campaign = _campaign(
        status=CampaignStatus.CONFIRMED, planned_launch_date=_NOW.date() + timedelta(days=2),
        date_confidence=DateConfidence.EXACT,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.COUNTDOWN


def test_confirmed_at_t0_is_launch() -> None:
    campaign = _campaign(
        status=CampaignStatus.CONFIRMED, planned_launch_date=_NOW.date(),
        date_confidence=DateConfidence.EXACT,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.LAUNCH


def test_confirmed_with_no_date_falls_back_to_awareness() -> None:
    campaign = _campaign(status=CampaignStatus.CONFIRMED, planned_launch_date=None)
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.AWARENESS


def test_delayed_invalidates_countdown_preserves_awareness() -> None:
    """§10: a DELAYED campaign must never resolve to a stale COUNTDOWN/LAUNCH phase, but generic
    awareness content remains valid."""
    campaign = _campaign(
        status=CampaignStatus.DELAYED, planned_launch_date=_NOW.date() + timedelta(days=1),
        date_confidence=DateConfidence.EXACT,
    )
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.AWARENESS


def test_launched_recently_is_launch_phase() -> None:
    campaign = _campaign(status=CampaignStatus.LAUNCHED, start_at=_NOW - timedelta(hours=2))
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.LAUNCH


def test_launched_a_few_days_ago_is_post_launch() -> None:
    campaign = _campaign(status=CampaignStatus.LAUNCHED, start_at=_NOW - timedelta(days=3))
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.POST_LAUNCH


def test_launched_long_ago_is_retention() -> None:
    campaign = _campaign(status=CampaignStatus.LAUNCHED, start_at=_NOW - timedelta(days=30))
    assert derive_phase(campaign, now=_NOW) == CampaignPhase.RETENTION


def test_completed_is_retention() -> None:
    assert derive_phase(_campaign(status=CampaignStatus.COMPLETED), now=_NOW) == CampaignPhase.RETENTION


def test_build_campaign_plan_is_deterministic_for_same_state_and_time() -> None:
    campaign = _campaign(
        status=CampaignStatus.CONFIRMED, planned_launch_date=_NOW.date() + timedelta(days=2),
        date_confidence=DateConfidence.EXACT, key_messages=["a", "b"], approved_claims=["c"],
        restricted_claims=["d"], required_cta="BUY",
    )
    plan1 = build_campaign_plan(campaign, now=_NOW)
    plan2 = build_campaign_plan(campaign, now=_NOW)
    assert plan1 == plan2
    assert plan1.phase == CampaignPhase.COUNTDOWN
    assert plan1.key_messages == ["a", "b"]
    assert plan1.approved_claims == ["c"]
    assert plan1.restricted_claims == ["d"]
    assert plan1.required_cta == "BUY"
