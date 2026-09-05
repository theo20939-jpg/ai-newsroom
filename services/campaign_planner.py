"""NINJA Social Intelligence Foundation, Part I §9/§10/§16: CampaignPlanner - deterministic phase
derivation + CampaignPlan assembly. Zero LLM calls (spec §104: never call an LLM merely to
calculate T-minus or look up active campaigns) - phase derivation is pure date/status arithmetic,
exactly as testable and deterministic as services/event_recap_scheduler.py's own readiness logic.

Deliberately NOT one hardcoded universal sequence (spec §9): `DEFAULT_LAUNCH_SEQUENCE` is the
spec's own illustrative T-30..T+7+ example, but `derive_phase()` accepts any `sequence` - a future
campaign type may supply its own."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from database.models.campaign import CampaignStatus, DateConfidence, LaunchCampaign


class CampaignPhase:
    """Spec §9's own suggested phase taxonomy - a plain str-constants namespace (not a DB-mapped
    enum, since a phase is never stored on `LaunchCampaign` itself - see module docstring)."""

    AWARENESS = "AWARENESS"
    PROBLEM_FRAMING = "PROBLEM_FRAMING"
    CATEGORY_EDUCATION = "CATEGORY_EDUCATION"
    PRODUCT_TEASING = "PRODUCT_TEASING"
    FEATURE_REVEAL = "FEATURE_REVEAL"
    SOCIAL_PROOF = "SOCIAL_PROOF"
    COUNTDOWN = "COUNTDOWN"
    LAUNCH = "LAUNCH"
    POST_LAUNCH = "POST_LAUNCH"
    RETENTION = "RETENTION"


@dataclass(frozen=True)
class PhaseWindow:
    """One (phase, [days_before_launch_end, days_before_launch_start)) window - e.g.
    `PhaseWindow(CampaignPhase.COUNTDOWN, 3, 1)` means "T-3 (inclusive) through T-1 (exclusive
    of T-0 itself)". `days_before_launch_start` is the FARTHER-from-launch edge (larger number),
    `days_before_launch_end` the CLOSER edge (smaller number) - deliberately named this way so a
    window reads left-to-right the same direction time flows."""

    phase: str
    days_before_launch_start: int
    days_before_launch_end: int


# Spec §9's own illustrative sequence, used as the DEFAULT template only.
DEFAULT_LAUNCH_SEQUENCE: tuple[PhaseWindow, ...] = (
    PhaseWindow(CampaignPhase.AWARENESS, 30, 21),
    PhaseWindow(CampaignPhase.CATEGORY_EDUCATION, 21, 14),
    PhaseWindow(CampaignPhase.PRODUCT_TEASING, 14, 7),
    PhaseWindow(CampaignPhase.FEATURE_REVEAL, 7, 3),
    PhaseWindow(CampaignPhase.COUNTDOWN, 3, 0),
)
_POST_LAUNCH_WINDOW_DAYS = 7


def _days_until(planned_launch_date: date, now: datetime) -> int:
    return (planned_launch_date - now.astimezone(timezone.utc).date()).days


def derive_phase(
    campaign: LaunchCampaign, *, now: datetime, sequence: tuple[PhaseWindow, ...] = DEFAULT_LAUNCH_SEQUENCE,
) -> str | None:
    """`None` means "no active phase" (DRAFT/CANCELLED/COMPLETED, or CONFIRMED/TENTATIVE with no
    usable date at all).

    CRITICAL safety contract (spec §10): exact-date-dependent phases (everything in `sequence`
    that implies a specific T-minus countdown, plus LAUNCH/POST_LAUNCH itself) are only ever
    derived when `campaign.status == CONFIRMED` (or the terminal LAUNCHED/DELAYED states below) -
    a TENTATIVE campaign, even with a concrete `planned_launch_date` set, ALWAYS resolves to the
    generic `AWARENESS` phase alone (spec §10's own "not automatically allowed: exact launch date,
    countdown... unless explicitly allowed" - this function is exactly that gate, not merely a
    docstring promise)."""
    if campaign.status in (CampaignStatus.DRAFT, CampaignStatus.CANCELLED):
        return None
    if campaign.status == CampaignStatus.COMPLETED:
        return CampaignPhase.RETENTION
    if campaign.status == CampaignStatus.DELAYED:
        # §10: invalidates countdown assumptions, preserves generic awareness - never LAUNCH/
        # COUNTDOWN/FEATURE_REVEAL from a now-stale date.
        return CampaignPhase.AWARENESS
    if campaign.status == CampaignStatus.LAUNCHED:
        if campaign.start_at is None:
            return CampaignPhase.LAUNCH
        days_since = (now.astimezone(timezone.utc) - campaign.start_at).days
        return CampaignPhase.LAUNCH if days_since <= 0 else (
            CampaignPhase.POST_LAUNCH if days_since <= _POST_LAUNCH_WINDOW_DAYS else CampaignPhase.RETENTION
        )
    if campaign.status == CampaignStatus.TENTATIVE:
        return CampaignPhase.AWARENESS
    if campaign.status != CampaignStatus.CONFIRMED:
        return None

    # CONFIRMED from here on.
    if campaign.planned_launch_date is None or campaign.date_confidence == DateConfidence.UNKNOWN:
        return CampaignPhase.AWARENESS

    days_left = _days_until(campaign.planned_launch_date, now)
    if days_left < 0:
        return CampaignPhase.POST_LAUNCH if days_left >= -_POST_LAUNCH_WINDOW_DAYS else CampaignPhase.RETENTION
    if days_left == 0:
        return CampaignPhase.LAUNCH
    for window in sequence:
        if window.days_before_launch_end < days_left <= window.days_before_launch_start:
            return window.phase
    # Farther out than the sequence's own earliest window, or between the last window's end
    # and T0 with no matching window (a gap in a custom sequence) - generic awareness, never a
    # fabricated phase.
    return CampaignPhase.AWARENESS


@dataclass(frozen=True)
class CampaignPlan:
    """Spec §16's own output shape - WHAT the business needs, never HOW a platform executes it."""

    campaign_id: str
    product_id: str
    objective: str | None
    phase: str | None
    status: str
    date_confidence: str
    start_at: datetime | None
    end_at: datetime | None
    content_pillars: list[str] = field(default_factory=list)
    key_messages: list[str] = field(default_factory=list)
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)
    required_cta: str | None = None


def build_campaign_plan(campaign: LaunchCampaign, *, now: datetime) -> CampaignPlan:
    """Deterministic assembly only - no LLM call, no invented content pillars beyond what the
    campaign's own `key_messages`/`target_audiences` already state."""
    return CampaignPlan(
        campaign_id=str(campaign.id), product_id=str(campaign.product_id), objective=campaign.objective,
        phase=derive_phase(campaign, now=now), status=campaign.status.value,
        date_confidence=campaign.date_confidence.value, start_at=campaign.start_at, end_at=campaign.end_at,
        content_pillars=list(campaign.key_messages or []), key_messages=list(campaign.key_messages or []),
        approved_claims=list(campaign.approved_claims or []), restricted_claims=list(campaign.restricted_claims or []),
        required_cta=campaign.required_cta,
    )
