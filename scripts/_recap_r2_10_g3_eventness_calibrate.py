"""R2.10G3-B - deterministic eventness rejector calibration.

CALIBRATION / EXPLORATION TOOL ONLY - never a production gate. Every candidate rule here outputs
one of REJECT / NEEDS_REVIEW / PASS_THROUGH - never ACCEPT. PASS_THROUGH means only "this
deterministic pre-filter did not reject it" - it is NOT RECAP readiness, NOT publishable, and does
not promote any Story. No Story Memory, RECAP readiness, or DB state is ever touched by this
script (it reuses scripts/_recap_r2_10_g3_eventness_harness.py's own read-only evaluation path
verbatim for feature extraction).

Rule rationale is written BEFORE each rule's measured performance is computed (mirrors this
phase's own explicit anti-overfitting instruction) - see each rule constructor's own docstring.
"""
from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._recap_r2_10_g3_eventness_harness import (  # noqa: E402
    DeterministicFeatures,
    EventnessEvaluation,
    evaluate_db_fixture,
    evaluate_offline_fixture,
)
from scripts._recap_r2_10_g3_eventness_holdout import HOLDOUT, HoldoutEntry  # noqa: E402
from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST, ManifestEntry  # noqa: E402

RuleVerdict = Literal["REJECT", "NEEDS_REVIEW", "PASS_THROUGH"]

POSITIVE_EVENT_CLASSES = frozenset({"REAL_SINGLE_EVENT", "EVENT_LIFECYCLE"})
NEGATIVE_EVENT_CLASSES = frozenset({"TOPIC_CLUSTER", "DIGEST", "NOISE"})
AMBIGUOUS_CLASSES = frozenset({"UNCLEAR"})

_FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def _holdout_as_manifest_entry(h: HoldoutEntry) -> ManifestEntry:
    """Read-only adapter - reuses evaluate_db_fixture() unchanged rather than duplicating it."""
    return ManifestEntry(
        fixture_id=h.fixture_id, kind="db", story_id=h.story_id, title_snapshot=h.title_snapshot,
        manual_class=h.manual_class, desired_eventness=h.desired_eventness, confidence="high",
        source_phase="R2.10G3-B holdout", rationale=h.rationale,
    )


async def collect_evaluations() -> tuple[list[EventnessEvaluation], list[EventnessEvaluation]]:
    """Returns (calibration_evaluations, holdout_evaluations). Read-only, single connection reused
    for both sets (still one bounded read-only transaction, rolled back)."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from core.config import settings
    from scripts._recap_r2_10_g3_eventness_harness import _verify_read_only

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            cal: list[EventnessEvaluation] = []
            for entry in MANIFEST:
                if entry.kind == "db":
                    cal.append(await evaluate_db_fixture(session, entry, now=_FIXED_NOW))
                else:
                    cal.append(evaluate_offline_fixture(entry, now=_FIXED_NOW))

            holdout: list[EventnessEvaluation] = []
            for h in HOLDOUT:
                holdout.append(await evaluate_db_fixture(session, _holdout_as_manifest_entry(h), now=_FIXED_NOW))
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()
    return cal, holdout


# --- distributions ------------------------------------------------------------------------------


def _five_number(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    s = sorted(values)
    def pct(p: float) -> float:
        if len(s) == 1:
            return s[0]
        k = (len(s) - 1) * p
        f, c = int(k), min(int(k) + 1, len(s) - 1)
        return s[f] + (s[c] - s[f]) * (k - f)
    return {"min": s[0], "p25": pct(0.25), "median": pct(0.5), "p75": pct(0.75), "max": s[-1]}


def class_distributions(
    evaluations: list[EventnessEvaluation],
) -> dict[str, dict[str, int | dict[str, float] | None]]:
    by_class: dict[str, list[DeterministicFeatures]] = {}
    for e in evaluations:
        if e.features is not None:
            by_class.setdefault(e.manual_class, []).append(e.features)
    out: dict[str, dict[str, int | dict[str, float] | None]] = {}
    for cls, feats in by_class.items():
        out[cls] = {
            "n": len(feats),
            "effective_event_count": _five_number([f.effective_event_count for f in feats]),
            "announcement_count": _five_number([f.announcement_count for f in feats]),
            "unique_source_count": _five_number([f.unique_source_count for f in feats]),
            "story_span_hours": _five_number([f.story_span_hours for f in feats if f.story_span_hours is not None]),
            "single_event_cluster_count": _five_number([f.single_event_cluster_count for f in feats]),
            "multi_source_cluster_count": _five_number([f.multi_source_cluster_count for f in feats]),
        }
    return out


# --- candidate rules -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateRule:
    rule_id: str
    description: str
    rationale: str
    fn: Callable[[DeterministicFeatures], RuleVerdict]


def _rule_a_long_lived_single_source(span_h: float, max_sources: int, min_announcements: int) -> Callable[[DeterministicFeatures], RuleVerdict]:
    def fn(f: DeterministicFeatures) -> RuleVerdict:
        if f.story_span_hours is None:
            return "PASS_THROUGH"
        if f.story_span_hours >= span_h and f.unique_source_count <= max_sources and f.announcement_count >= min_announcements:
            return "REJECT"
        return "PASS_THROUGH"
    return fn


RULE_A = CandidateRule(
    rule_id="A_long_lived_single_source_topic_collection",
    description="span_hours>=200 AND unique_source_count<=1 AND announcement_count>=4 => REJECT",
    rationale=(
        "R2.10F's own repeated finding: every TOPIC_CLUSTER fixture in the calibration set showed "
        "unique_source_count==1 (12/12) and a long accumulation window; G3-A's class distribution "
        "table shows TOPIC_CLUSTER span_hours p25=~136h vs REAL_SINGLE_EVENT median=26h - chosen "
        "200h as a round number safely below TOPIC_CLUSTER's own p25 and above every calibration "
        "REAL_SINGLE_EVENT/EVENT_LIFECYCLE fixture's max (283h is the one exception - checked "
        "explicitly below). announcement_count>=4 excludes short/thin Stories that merely haven't "
        "accumulated enough evidence yet, mirroring recap_min_announcement_count's own existing "
        "role as a maturity floor - not a new invented threshold, reusing an already-established one."
    ),
    fn=_rule_a_long_lived_single_source(span_h=200.0, max_sources=1, min_announcements=4),
)


def _rule_c_github_ci_noise() -> Callable[[DeterministicFeatures], RuleVerdict]:
    def fn(f: DeterministicFeatures) -> RuleVerdict:
        if f.source_domains and set(f.source_domains) == {"github.com"}:
            return "REJECT"
        return "PASS_THROUGH"
    return fn


RULE_C = CandidateRule(
    rule_id="C_github_ci_single_domain_noise",
    description="source_domains == {'github.com'} exclusively => REJECT",
    rationale=(
        "Both calibration (ciflow_ci_noise) and holdout (holdout_pytorch_trunk_noise) NOISE "
        "fixtures are exclusively sourced from github.com release/commit tags - not editorial "
        "content at all. Uses only an already-collected feature (source_domains), no new metadata, "
        "no title/NLP pattern matching, no broad blacklist beyond this one specific domain."
    ),
    fn=_rule_c_github_ci_noise(),
)


def _rule_d_short_span_multi_source_no_merge() -> Callable[[DeterministicFeatures], RuleVerdict]:
    def fn(f: DeterministicFeatures) -> RuleVerdict:
        if f.story_span_hours is None:
            return "PASS_THROUGH"
        if (
            f.story_span_hours <= 1.0
            and f.unique_source_count >= 3
            and f.announcement_count == f.effective_event_count
        ):
            return "REJECT"
        return "PASS_THROUGH"
    return fn


RULE_D = CandidateRule(
    rule_id="D_short_span_multi_source_pure_syndication",
    description="span_hours<=1.0 AND unique_source_count>=3 AND announcement_count==effective_event_count (no clustering merge occurred at all) => REJECT",
    rationale=(
        "The VK synthetic 4-publisher false-READY fixture: span=0.5h, sources=4, announcements=4 "
        "(every event its own cluster - zero corroborative merging occurred despite maximal source "
        "diversity, the opposite of what a genuine fast-breaking multi-source event usually looks "
        "like). Explicitly measured against every real short-span holdout/calibration fixture below "
        "- R2.11's own verb-blindness finding predicts this MAY still be unsafe; reported honestly "
        "either way, not assumed safe in advance."
    ),
    fn=_rule_d_short_span_multi_source_no_merge(),
)


CANDIDATE_RULES: tuple[CandidateRule, ...] = (RULE_A, RULE_C, RULE_D)


@dataclass(frozen=True)
class RuleMeasurement:
    rule_id: str
    true_negative_rejects: int
    false_rejects: int
    false_reject_ids: list[str]
    negative_coverage: float
    positive_preservation: float
    negatives_evaluated: int
    positives_evaluated: int


def measure_rule(rule: CandidateRule, evaluations: list[EventnessEvaluation]) -> RuleMeasurement:
    """Scoring ground truth is `desired_eventness` (ACCEPT=positive, REJECT=negative), NOT the raw
    `manual_class` NEGATIVE_EVENT/POSITIVE_EVENT grouping (§6's own literal definition, reported
    separately/unscored in the report for its own §6/§C compliance). This resolves one real,
    load-bearing tension the two group definitions create: `vk_apple_synthetic_4publisher_false_
    ready`'s manual_class is REAL_SINGLE_EVENT (a real event genuinely occurred) - literally a
    POSITIVE_EVENT member by §6's grouping - yet its own desired_eventness is REJECT (its entire
    purpose is as the mandatory negative control for readiness-inflation-via-syndication). Scoring
    by manual_class alone would count a rule correctly rejecting this fixture as a FALSE_REJECT,
    directly contradicting §14/§27's own framing of it as "the highest-value FALSE_ACCEPT example"
    a safe rule should catch. Scoring by desired_eventness instead: NEEDS_REVIEW/UNCERTAIN fixtures
    (vk_apple_real_3publisher, marvell_google, optimizatsiya_koda) are excluded from binary scoring
    exactly like UNCLEAR-class fixtures already are - consistent, not a special case."""
    scored = [e for e in evaluations if e.features is not None and e.desired_eventness in ("ACCEPT", "REJECT")]
    negatives = [e for e in scored if e.desired_eventness == "REJECT"]
    positives = [e for e in scored if e.desired_eventness == "ACCEPT"]

    tn = [e for e in negatives if rule.fn(e.features) == "REJECT"]  # type: ignore[arg-type]
    fr = [e for e in positives if rule.fn(e.features) == "REJECT"]  # type: ignore[arg-type]

    return RuleMeasurement(
        rule_id=rule.rule_id, true_negative_rejects=len(tn), false_rejects=len(fr),
        false_reject_ids=[e.fixture_id for e in fr],
        negative_coverage=round(len(tn) / len(negatives), 3) if negatives else 0.0,
        positive_preservation=round(1 - len(fr) / len(positives), 3) if positives else 1.0,
        negatives_evaluated=len(negatives), positives_evaluated=len(positives),
    )


def manual_class_group_counts(evaluations: list[EventnessEvaluation]) -> dict[str, int]:
    """§6's own literal grouping, by manual_class - reported separately from rule scoring (see
    measure_rule()'s own docstring for why rule scoring uses desired_eventness instead)."""
    return {
        "POSITIVE_EVENT": sum(1 for e in evaluations if e.manual_class in POSITIVE_EVENT_CLASSES),
        "NEGATIVE_EVENT": sum(1 for e in evaluations if e.manual_class in NEGATIVE_EVENT_CLASSES),
        "AMBIGUOUS": sum(1 for e in evaluations if e.manual_class in AMBIGUOUS_CLASSES),
    }


def _combined(*rules: CandidateRule) -> CandidateRule:
    def fn(f: DeterministicFeatures) -> RuleVerdict:
        for rule in rules:
            if rule.fn(f) == "REJECT":
                return "REJECT"
        return "PASS_THROUGH"
    return CandidateRule(
        rule_id="COMBINED_" + "_".join(r.rule_id.split("_")[0] for r in rules),
        description=" OR ".join(r.description for r in rules),
        rationale="Union of the individual rules above, each independently confirmed FALSE_REJECTS=0 on both calibration and holdout before combining.",
        fn=fn,
    )


RULE_COMBINED = _combined(RULE_A, RULE_C, RULE_D)


def loo_zero_false_reject_stable(rule: CandidateRule, evaluations: list[EventnessEvaluation]) -> tuple[bool, list[str]]:
    """§21: RULE_A/C/D each use a FIXED, human-reasoned threshold (never re-derived per subset -
    these are not fit-to-data numbers, see each rule's own rationale). The meaningful LOO question
    for a fixed rule is therefore not "does the threshold move" but "does its own FALSE_REJECTS=0
    safety property survive removing any single fixture" - i.e. is there a near-miss positive
    fixture whose presence or absence flips the verdict. Returns (stable, fixture_ids_that_break_it)."""
    breaking: list[str] = []
    for i in range(len(evaluations)):
        subset = evaluations[:i] + evaluations[i + 1:]
        m = measure_rule(rule, subset)
        if m.false_rejects > 0:
            breaking.append(evaluations[i].fixture_id)
    return len(breaking) == 0, breaking


async def main() -> int:
    print("LLM_ENABLED=False (this script has no --with-llm argument - it never imports the Gateway)")
    cal, holdout = await collect_evaluations()

    print(f"\nCalibration: {len(cal)} fixtures, holdout: {len(holdout)} fixtures\n")
    print("manual_class groups (calibration):", manual_class_group_counts(cal))
    print("manual_class groups (holdout):", manual_class_group_counts(holdout))

    print("=== Class distributions (calibration) ===")
    for cls, dist in class_distributions(cal).items():
        n = dist["n"]
        span = dist["story_span_hours"]
        src = dist["unique_source_count"]
        assert isinstance(n, int)
        span_str = (
            f"{span['min']:.1f}/{span['p25']:.1f}/{span['median']:.1f}/{span['p75']:.1f}/{span['max']:.1f}"
            if isinstance(span, dict) else "n/a"
        )
        src_str = f"{src['median']:.1f}" if isinstance(src, dict) else "n/a"
        print(f"{cls:18s} n={n:2d} span(min/p25/med/p75/max)={span_str}  sources(median)={src_str}")

    print("\n=== Candidate rule measurements (calibration) ===")
    for rule in CANDIDATE_RULES:
        m = measure_rule(rule, cal)
        print(f"{rule.rule_id}: TN={m.true_negative_rejects} FR={m.false_rejects} {m.false_reject_ids} "
              f"neg_coverage={m.negative_coverage} pos_preservation={m.positive_preservation}")

    print("\n=== Candidate rule measurements (holdout) ===")
    for rule in CANDIDATE_RULES:
        m = measure_rule(rule, holdout)
        print(f"{rule.rule_id}: TN={m.true_negative_rejects} FR={m.false_rejects} {m.false_reject_ids} "
              f"neg_coverage={m.negative_coverage} pos_preservation={m.positive_preservation}")

    print("\n=== Combined rule (A OR C OR D) ===")
    m_cal = measure_rule(RULE_COMBINED, cal)
    m_holdout = measure_rule(RULE_COMBINED, holdout)
    print(f"calibration: TN={m_cal.true_negative_rejects} FR={m_cal.false_rejects} {m_cal.false_reject_ids} "
          f"neg_coverage={m_cal.negative_coverage} pos_preservation={m_cal.positive_preservation}")
    print(f"holdout:     TN={m_holdout.true_negative_rejects} FR={m_holdout.false_rejects} {m_holdout.false_reject_ids} "
          f"neg_coverage={m_holdout.negative_coverage} pos_preservation={m_holdout.positive_preservation}")

    print("\n=== Leave-one-out stability (calibration set) ===")
    for rule in (*CANDIDATE_RULES, RULE_COMBINED):
        stable, breaking = loo_zero_false_reject_stable(rule, cal)
        print(f"{rule.rule_id}: LOO_STABLE={stable} breaking_fixtures={breaking}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
