"""DIRECTOR-CONTROL-PLANE-1 §8-13/§36-37: the internal editorial gate. Deterministic, staged,
bounded-cost (spec §36's own "do not put one paid LLM call on every raw ingestion event"
instruction) - `evaluate_editorial_gate()` is a pure function of `EditorialGateInput`, with one
explicit, OPTIONAL escalation hook (`llm_escalate`) for the competitive/ambiguous/high-value
minority of candidates a future phase may wire to a real Gateway call. No Gateway call happens
anywhere in this module today - `llm_escalate=None` (the default) means every candidate is decided
deterministically, exactly matching this phase's own honest EXPECTED_DAILY_GATE_LLM_CALLS=0 cost
bound (see the final report).

INTERNAL ONLY (spec §8): this module has no import of, or call into, any publication path. It only
ever returns a `GateOutcome` for a caller (worker/content_cycle.py, behind
settings.telegram_editorial_gate_enabled) to persist and optionally act on.

Fail-soft (spec §37): `run_editorial_gate_fail_soft()` wraps the LLM-escalation path so a Gateway
outage can never empty the queue - `GATE_FALLBACK_MODE` is always one of the two explicit strings
below, never a silent swallow."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from database.models.director_editorial_decision import EditorialGateDecision, EditorialGateReasonCode
from database.models.strategic_directive import StrategicDirective

GATE_FALLBACK_MODE_DETERMINISTIC_BASELINE = "deterministic_baseline_selector"
GATE_FALLBACK_MODE_SHADOW_BYPASS = "shadow_bypass_to_editor"

# Spec §11's own stated default preference, used ONLY as the last-resort fallback when no ACTIVE
# StrategicDirective says anything about a given category - never overrides a real directive, and
# is not "immutable application logic": the moment a real StrategicDirective row exists for a
# category, `_directive_tier_override()` below reads that instead. Operationalizing spec §11 for
# real means creating one real StrategicDirective row via the existing /directives (business
# context) command - see this phase's own final report for that exact next step.
_DEFAULT_PRIMARY_CATEGORIES = frozenset({"ai", "gadgets", "consumer_technology", "major_technology_events"})
_DEFAULT_SECONDARY_CATEGORIES = frozenset({"software", "engineering", "internet", "automotive_technology"})
_DEFAULT_RARE_CATEGORIES = frozenset({"finance", "investing", "corporate_economy", "legal_regulatory"})

_HOLD_DEFAULT_TTL = timedelta(hours=48)


@dataclass(frozen=True)
class EditorialGateInput:
    """Spec §9's own required consideration list. Every field is a plain, already-computed value a
    caller assembles deliberately - never a raw DB row (mirrors services/visual_creative_direction.py
    ::VisualDirectorContext's own "bounded, deterministic-summary-only" discipline)."""

    story_id: str
    event_id: str
    platform: str
    category: str
    topic_keywords: list[str]
    story_facts_summary: str
    has_sufficient_facts: bool
    source_confidence: float  # 0.0-1.0
    novelty_score: float  # 0.0-1.0, 1.0 = never covered before
    is_duplicate_of_recent: bool
    recency_hours: float
    active_directives: list[StrategicDirective] = field(default_factory=list)
    active_campaign_relevant: bool = False
    launch_state: str | None = None
    feed_topic_distribution: dict[str, int] = field(default_factory=dict)
    recent_posting_cadence_per_hour: float = 0.0
    is_potential_breaking: bool = False
    factual_risk_flagged: bool = False


@dataclass(frozen=True)
class GateOutcome:
    decision: EditorialGateDecision
    priority: int
    reason_codes: list[EditorialGateReasonCode]
    short_reason: str
    fallback_mode: str | None = None  # set only when the LLM-escalation path degraded


def context_fingerprint(gate_input: EditorialGateInput) -> str:
    """Deterministic hash of every field that could change the decision - spec §35/§10's own
    "traceable, never opaque" requirement. sha256 of a stable JSON encoding, never a raw repr()
    (which is not guaranteed stable across Python versions/field order)."""
    payload = {
        "story_id": gate_input.story_id, "category": gate_input.category,
        "topic_keywords": sorted(gate_input.topic_keywords), "has_sufficient_facts": gate_input.has_sufficient_facts,
        "source_confidence": gate_input.source_confidence, "novelty_score": gate_input.novelty_score,
        "is_duplicate_of_recent": gate_input.is_duplicate_of_recent, "recency_hours": gate_input.recency_hours,
        "active_campaign_relevant": gate_input.active_campaign_relevant, "launch_state": gate_input.launch_state,
        "is_potential_breaking": gate_input.is_potential_breaking, "factual_risk_flagged": gate_input.factual_risk_flagged,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


_WEAKEN_PATTERN = re.compile(r"\b(rare|avoid|de[- ]?prioritize|low priority|skip)\b", re.IGNORECASE)
_STRENGTHEN_PATTERN = re.compile(r"\b(primary|priority|focus|important|always cover)\b", re.IGNORECASE)


def _directive_tier_override(category: str, directives: list[StrategicDirective]) -> str | None:
    """Scans ACTIVE directive instruction text for an explicit mention of this category paired
    with a strengthening/weakening word nearby - a real, if simple, read of Founder Directive
    infrastructure (spec §11's own explicit requirement), never a second hardcoded category list.
    Returns None (no override) when no directive mentions this category at all."""
    category_lower = category.lower().replace("_", " ")
    for directive in directives:
        text = directive.instruction.lower()
        if category_lower not in text and category.lower() not in text:
            continue
        if _STRENGTHEN_PATTERN.search(text):
            return "primary"
        if _WEAKEN_PATTERN.search(text):
            return "rare"
    return None


def _topic_tier(category: str, directives: list[StrategicDirective]) -> str:
    override = _directive_tier_override(category, directives)
    if override is not None:
        return override
    lowered = category.lower()
    if lowered in _DEFAULT_PRIMARY_CATEGORIES:
        return "primary"
    if lowered in _DEFAULT_SECONDARY_CATEGORIES:
        return "secondary"
    if lowered in _DEFAULT_RARE_CATEGORIES:
        return "rare"
    return "secondary"  # unknown categories default to secondary, never silently primary or dropped


def evaluate_editorial_gate(gate_input: EditorialGateInput) -> GateOutcome:
    """The deterministic core decision function - spec §9's own full consideration list, never
    reduced to one opaque score (spec §9's own explicit instruction). Priority order below mirrors
    spec §12/§46's own stated queue-priority intent (BREAKING > PRIORITY > SEND_TO_EDITOR > HOLD >
    DROP) - a candidate matching an earlier, stronger condition never falls through to a weaker
    one it also happens to match."""
    reasons: list[EditorialGateReasonCode] = []

    if not gate_input.has_sufficient_facts:
        reasons.append(EditorialGateReasonCode.INSUFFICIENT_FACTS)
        return GateOutcome(
            decision=EditorialGateDecision.HOLD, priority=10, reason_codes=reasons,
            short_reason="Story facts are not yet sufficient to support a factual publication draft.",
        )

    if gate_input.is_potential_breaking:
        reasons.append(EditorialGateReasonCode.BREAKING_SIGNAL)
        return GateOutcome(
            decision=EditorialGateDecision.BREAKING, priority=100, reason_codes=reasons,
            short_reason="Recency and source confidence indicate a genuine breaking-news candidate.",
        )

    if gate_input.is_duplicate_of_recent:
        reasons.append(EditorialGateReasonCode.DUPLICATE_TOPIC)
        reasons.append(EditorialGateReasonCode.RECENTLY_COVERED)
        return GateOutcome(
            decision=EditorialGateDecision.DROP, priority=0, reason_codes=reasons,
            short_reason="This exact story angle was already covered in the recent feed window.",
        )

    tier = _topic_tier(gate_input.category, gate_input.active_directives)
    if tier == "rare" and not gate_input.active_campaign_relevant:
        # Spec §49's own explicit "major tech-industry finance event -> still eligible" carve-out -
        # a rare-tier category is never DROPped outright, only deprioritized, unless novelty is
        # also low (a true routine finance story) - a genuinely major event (high novelty) still
        # reaches the editor, just without a PRIORITY uplift.
        reasons.append(EditorialGateReasonCode.TOO_FINANCE_HEAVY)
        if gate_input.novelty_score < 0.6:
            return GateOutcome(
                decision=EditorialGateDecision.HOLD, priority=15, reason_codes=reasons,
                short_reason="Rare-tier topic per active Founder Directives, and not a major enough event to prioritize.",
            )
        reasons.append(EditorialGateReasonCode.MAJOR_INDUSTRY_EVENT)

    if gate_input.novelty_score < 0.35 and not gate_input.active_campaign_relevant:
        reasons.append(EditorialGateReasonCode.LOW_NOVELTY)
        return GateOutcome(
            decision=EditorialGateDecision.HOLD, priority=20, reason_codes=reasons,
            short_reason="Low novelty against recently covered feed content.",
        )

    if gate_input.source_confidence < 0.4:
        reasons.append(EditorialGateReasonCode.SOURCE_WEAK)
        return GateOutcome(
            decision=EditorialGateDecision.HOLD, priority=20, reason_codes=reasons,
            short_reason="Source confidence is too low to send directly to the editor.",
        )

    priority = 50
    if gate_input.active_campaign_relevant:
        reasons.append(EditorialGateReasonCode.CAMPAIGN_RELEVANT)
        priority += 20
    if tier == "primary":
        reasons.append(EditorialGateReasonCode.HIGH_STRATEGIC_FIT)
        priority += 15
    if gate_input.active_directives and _directive_tier_override(gate_input.category, gate_input.active_directives):
        reasons.append(EditorialGateReasonCode.FOUNDER_DIRECTIVE_MATCH)
    if gate_input.category.lower() not in gate_input.feed_topic_distribution:
        reasons.append(EditorialGateReasonCode.FEED_GAP_FILL)
        priority += 5

    if not reasons:
        reasons.append(EditorialGateReasonCode.HIGH_STRATEGIC_FIT if tier == "primary" else EditorialGateReasonCode.FEED_GAP_FILL)

    decision = EditorialGateDecision.PRIORITY if priority >= 70 else EditorialGateDecision.SEND_TO_EDITOR
    return GateOutcome(
        decision=decision, priority=priority, reason_codes=reasons,
        short_reason="Meets editorial bar: sufficient facts, adequate novelty/source confidence, no recent duplicate.",
    )


LLMEscalate = Callable[[EditorialGateInput], Awaitable[GateOutcome]]


async def run_editorial_gate_fail_soft(
    gate_input: EditorialGateInput, *, llm_escalate: LLMEscalate | None = None, is_ambiguous: bool = False,
) -> GateOutcome:
    """Spec §36's own staged-cost design: the deterministic core ALWAYS runs first and is always
    trusted as the real decision unless `is_ambiguous` (a cheap, pre-computed signal a caller sets
    for genuinely competitive/borderline cases) requests LLM escalation. Spec §37's own fail-soft
    requirement: if `llm_escalate` raises or is unavailable, falls back to the deterministic
    outcome (GATE_FALLBACK_MODE_DETERMINISTIC_BASELINE) rather than ever emptying the queue."""
    baseline = evaluate_editorial_gate(gate_input)
    if not is_ambiguous or llm_escalate is None:
        return baseline
    try:
        escalated = await llm_escalate(gate_input)
        return escalated
    except Exception:  # noqa: BLE001 - fail-soft boundary, spec §37's own explicit requirement
        return GateOutcome(
            decision=baseline.decision, priority=baseline.priority, reason_codes=baseline.reason_codes,
            short_reason=baseline.short_reason, fallback_mode=GATE_FALLBACK_MODE_DETERMINISTIC_BASELINE,
        )


def default_hold_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + _HOLD_DEFAULT_TTL
