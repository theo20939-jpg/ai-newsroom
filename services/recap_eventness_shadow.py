"""R2.10G3-E1 - production-shaped SHADOW-ONLY deterministic eventness rejector signal.

This module is the SINGLE canonical implementation of RULE_A and RULE_C, exactly as validated
read-only across R2.10G3-A (calibration manifest), R2.10G3-B (calibration, 0 false rejects),
R2.10G3-C (LLM shadow judge - informed the human-review-only policy below), and R2.10G3-D
(adversarial validation): RULE_A calibration/holdout/adversarial false rejects all 0; RULE_C
calibration/holdout/adversarial false rejects all 0, but no labelled fixture in any prior corpus
was a real GitHub-only positive.

R2.10G3-E1's own §16 audit (a fresh, ~940-Story live-DB scan, NOT limited to the labelled corpus)
FOUND real counterexamples: at least 6 genuine GitHub-only real events (a real open-source
language release, "Janet 1.42.0"; several genuine Show-HN-style project launches - e.g.
github.com/Hebbian-Robotics/hflow, github.com/fregacmols/RotaryCell). RULE_C's candidacy is
therefore REVOKED, not merely diagnostic-only-for-lack-of-evidence - this is a real, evidenced
false-reject risk if RULE_C were ever enforced, confirmed rather than merely un-disproven. The
rule's own threshold/logic is unchanged here (§16 explicitly: "Do not change Rule C... just
report") - this module's `_rule_c_triggered()` still fires on the same shape; only its production
candidacy status is downgraded, in the docs/r2_10_g3e1_eventness_shadow_wiring_report.md report,
not in this module's own runtime behavior. `RULE_C_VALIDATION_STATUS` (below) is kept as
diagnostic metadata on every triggered evaluation, unchanged.

RULE_D (`story_span_hours<=1 AND unique_source_count>=3 AND announcement_count==effective_event_
count`) is PERMANENTLY ABSENT from this module - G3-D found 3 real false rejects (a genuine
3-outlet review-embargo-lift event and two ordinary real announcements that gained a third
independent source), disqualifying it. There is no clause here that reproduces RULE_D's shape,
and `tests/test_recap_eventness_shadow.py::test_rule_d_shape_produces_no_signal` asserts this
directly against a fixture matching that exact disqualified shape.

SHADOW ONLY, ALWAYS: `evaluate_eventness_shadow()` is a pure function - no DB access, no network,
no LLM, no side effects - and its return value (`EventnessShadowEvaluation`) is diagnostic
metadata only. `enforcement_applied` is hardcoded `False` on every return; there is no parameter,
flag, or code path anywhere in this module that can make it True. Nothing in this module ever
constructs a rejection reason, changes a readiness state, or touches `publishable`. The one
caller in this codebase (`services/recap_event.py::build_recap_event_snapshot()`) only invokes
this module when `core.config.settings.recap_eventness_shadow_enabled` is True (default False,
enabled nowhere), and only ever attaches the result to a new, additive, default-`None`
`RecapEventSnapshot.eventness_shadow` field - never to any field an existing caller already reads
for a decision.

Diagnostic language discipline (§5): reason codes describe an observed SHAPE correlated with
non-editorial-event content, never a factual editorial-class claim - `LONG_LIVED_SINGLE_SOURCE_
TOPIC_SHAPE`, never e.g. "REJECT_TOPIC_CLUSTER". A shape match is evidence, not proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# --- reason codes (interpretable, shape-based - never a factual editorial-class claim, §5) -------

LONG_LIVED_SINGLE_SOURCE_TOPIC_SHAPE = "LONG_LIVED_SINGLE_SOURCE_TOPIC_SHAPE"
GITHUB_ONLY_SOURCE_SHAPE = "GITHUB_ONLY_SOURCE_SHAPE"

# RULE_A's own frozen thresholds (R2.10G3-B, unchanged - no tuning in this phase, §6).
_RULE_A_MIN_SPAN_HOURS = 200.0
_RULE_A_MAX_UNIQUE_SOURCES = 1
_RULE_A_MIN_ANNOUNCEMENT_COUNT = 4

# RULE_C's own frozen condition (R2.10G3-B, unchanged - no whitelist/blacklist/special-case, §7).
_RULE_C_ONLY_DOMAIN = "github.com"

# §7 - RULE_C's own validation status, carried as data (not merely a comment) so any consumer of
# an EventnessShadowEvaluation sees this caveat without needing to read this module's source.
RULE_C_VALIDATION_STATUS = "SHADOW_ONLY_UNVALIDATED_POSITIVE_COVERAGE"


@dataclass(frozen=True)
class EventnessShadowFeatures:
    """The minimal, already-computed-elsewhere feature subset RULE_A/RULE_C need - deliberately
    NOT a copy of scripts/_recap_r2_10_g3_eventness_harness.py's own richer `DeterministicFeatures`
    (that type carries G3-diagnostic-only fields like `match_type_distribution`/`story_entities`
    this module has no use for) - kept minimal so this module has zero dependency on any scripts/
    module, per this codebase's own layering (services/ must not import scripts/)."""

    story_span_hours: float | None
    unique_source_count: int
    announcement_count: int
    source_domains: frozenset[str]


@dataclass(frozen=True)
class EventnessShadowEvaluation:
    rule_a_triggered: bool
    rule_c_triggered: bool
    triggered_reasons: tuple[str, ...]
    shadow_status: Literal["NO_SIGNAL", "SHADOW_FLAGGED"]
    rule_c_validation_status: str | None  # RULE_C_VALIDATION_STATUS when rule_c_triggered, else None
    enforcement_applied: Literal[False] = False


def _rule_a_triggered(features: EventnessShadowFeatures) -> bool:
    """RULE_A, frozen from R2.10G3-B: span_hours>=200 AND unique_source_count<=1 AND
    announcement_count>=4. Reproduces scripts/_recap_r2_10_g3_eventness_calibrate.py::RULE_A.fn
    exactly - see tests/test_recap_eventness_shadow.py::test_offline_production_parity_across_
    labelled_corpus for the equivalence proof over the full ~90-fixture corpus."""
    if features.story_span_hours is None:
        return False
    return (
        features.story_span_hours >= _RULE_A_MIN_SPAN_HOURS
        and features.unique_source_count <= _RULE_A_MAX_UNIQUE_SOURCES
        and features.announcement_count >= _RULE_A_MIN_ANNOUNCEMENT_COUNT
    )


def _rule_c_triggered(features: EventnessShadowFeatures) -> bool:
    """RULE_C, frozen from R2.10G3-B: every effective source domain equals 'github.com', no
    exceptions, no whitelist/blacklist (§7 - "do not special-case security advisories, releases,
    GitHub organizations, repo names"). Reproduces RULE_C.fn exactly - see the same parity test."""
    return bool(features.source_domains) and features.source_domains == frozenset({_RULE_C_ONLY_DOMAIN})


def evaluate_eventness_shadow(features: EventnessShadowFeatures) -> EventnessShadowEvaluation:
    """Pure. Computes RULE_A/RULE_C only (RULE_D does not exist here - see module docstring).
    Never called with any intent or capability to reject, publish, or otherwise act on a Story -
    the caller decides, independently, whether and where to attach this diagnostic; this function
    itself has no side effects and no awareness of any Story, DB, or request."""
    a = _rule_a_triggered(features)
    c = _rule_c_triggered(features)
    reasons: list[str] = []
    if a:
        reasons.append(LONG_LIVED_SINGLE_SOURCE_TOPIC_SHAPE)
    if c:
        reasons.append(GITHUB_ONLY_SOURCE_SHAPE)
    return EventnessShadowEvaluation(
        rule_a_triggered=a, rule_c_triggered=c, triggered_reasons=tuple(reasons),
        shadow_status="SHADOW_FLAGGED" if reasons else "NO_SIGNAL",
        rule_c_validation_status=RULE_C_VALIDATION_STATUS if c else None,
    )
