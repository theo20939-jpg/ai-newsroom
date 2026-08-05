"""Meme Opportunity Human Calibration (Phase 18.6): pure selection, record-building, markdown
rendering, and metric-computation functions comparing the existing, unmodified `services.
meme_opportunity.assess_meme_opportunity()` classifier against human editorial judgement
(docs/phase18_6_meme_calibration_report.md).

Adds ZERO new meme-opportunity scoring/threshold/safety logic - every `algorithm_score`/
`algorithm_level`/`triggered_signals`/`safety_result` value comes straight from an already-computed
`services.meme_shadow_analytics.MemeShadowRecord` (Phase 18.5), which itself comes straight from
the unmodified Phase 18 M1 classifier. This module only (a) selects which already-classified
records go into the human review packet, (b) formats them for a human to read, and (c) computes
statistics over a *completed* (human-annotated) dataset. No LLM call, no network call, no database
write anywhere in this file.
"""
from __future__ import annotations

import random
import statistics
from datetime import datetime, timezone

from schemas.meme_calibration import (
    MemeCalibrationDataset,
    MemeCalibrationHumanDecision,
    MemeCalibrationRecord,
    MemeCalibrationSafetyOpinion,
    MemeReviewGroup,
)
from schemas.meme_shadow_analytics import MemeOpportunityLabel, MemeShadowRecord

# ---------------------------------------------------------------------------
# Selection (extraction-time)
# ---------------------------------------------------------------------------

_CONTENT_EXCERPT_MAX_CHARS = 280

_GROUP_BY_LABEL: dict[MemeOpportunityLabel, MemeReviewGroup] = {
    MemeOpportunityLabel.MEDIUM: MemeReviewGroup.MEDIUM_CANDIDATE,
    MemeOpportunityLabel.LOW: MemeReviewGroup.LOW_RANDOM,
    MemeOpportunityLabel.BLOCKED: MemeReviewGroup.SAFETY_BLOCKED,
}


def select_diverse_by_category(
    records: list[MemeShadowRecord], count: int, *, seed: float,
) -> list[MemeShadowRecord]:
    """Group A's own selection rule: "highest diversity possible" across categories. Round-robins
    across every distinct category actually present in `records` (shuffled once, deterministically,
    per `seed`, so re-running the same extraction produces the same packet) - one record per
    category per pass - until `count` is reached or the pool is exhausted.

    Honest by construction: if the real classified population only contains N distinct categories
    (e.g. Phase 18.5's own real-data finding that MEDIUM records only ever come from 4 of the 8
    `EventCategory` values), this can never manufacture categories that were never actually
    classified into that group - it returns the maximum diversity the real data actually supports,
    never a padded or synthetic sample."""
    if count <= 0 or not records:
        return []
    rng = random.Random(seed)
    by_category: dict[str, list[MemeShadowRecord]] = {}
    for record in records:
        by_category.setdefault(record.category, []).append(record)
    for pool in by_category.values():
        rng.shuffle(pool)
    categories = sorted(by_category.keys())
    rng.shuffle(categories)

    selected: list[MemeShadowRecord] = []
    while len(selected) < count and any(by_category[c] for c in categories):
        for category in categories:
            if len(selected) >= count:
                break
            pool = by_category[category]
            if pool:
                selected.append(pool.pop())
    return selected


def select_random(records: list[MemeShadowRecord], count: int, *, seed: float) -> list[MemeShadowRecord]:
    """Group B/C's own selection rule: a plain, deterministic random sample without replacement -
    `random.sample` already guarantees no duplicates within one call. Returns every available
    record (never raises) if `count` exceeds the pool size, mirroring Phase 18.5 M3's own
    `min(sample_size, len(pool))` precedent."""
    if count <= 0 or not records:
        return []
    rng = random.Random(seed)
    n = min(count, len(records))
    return rng.sample(records, n)


def _excerpt(content: str | None) -> str:
    text = (content or "").strip()
    if len(text) <= _CONTENT_EXCERPT_MAX_CHARS:
        return text
    return text[:_CONTENT_EXCERPT_MAX_CHARS]


def build_calibration_record(
    shadow_record: MemeShadowRecord,
    *,
    title: str,
    content: str | None,
    published_at: datetime | None,
) -> MemeCalibrationRecord:
    """Pure - normalizes an already-computed `MemeShadowRecord` (Phase 18.5) plus the real event's
    own display fields into one `MemeCalibrationRecord`, with every `human_*` field left at its
    schema-level default (genuinely blank, never a guess)."""
    group = _GROUP_BY_LABEL.get(shadow_record.opportunity_label)
    if group is None:
        raise ValueError(f"no calibration group defined for label {shadow_record.opportunity_label!r}")
    return MemeCalibrationRecord(
        event_id=shadow_record.event_id,
        group=group,
        title=title,
        category=shadow_record.category,
        source_name=shadow_record.source_name,
        published_at=published_at,
        content_excerpt=_excerpt(content),
        algorithm_score=shadow_record.composite_score,
        algorithm_level=shadow_record.opportunity_label.value,
        triggered_signals=list(shadow_record.evidence_patterns),
        safety_result=list(shadow_record.sensitivity_categories),
    )


def build_dataset(records: list[MemeCalibrationRecord], *, now: datetime | None = None) -> MemeCalibrationDataset:
    """Pure - wraps a flat list of already-built records into the versioned collection envelope,
    computing each group's own count directly from the records themselves (never a separately
    tracked, driftable counter)."""
    counts = {group: 0 for group in MemeReviewGroup}
    for record in records:
        counts[record.group] += 1
    return MemeCalibrationDataset(
        generated_at=now or datetime.now(timezone.utc),
        group_a_count=counts[MemeReviewGroup.MEDIUM_CANDIDATE],
        group_b_count=counts[MemeReviewGroup.LOW_RANDOM],
        group_c_count=counts[MemeReviewGroup.SAFETY_BLOCKED],
        records=records,
    )


# ---------------------------------------------------------------------------
# Markdown rendering (extraction-time)
# ---------------------------------------------------------------------------

_GROUP_TITLE: dict[MemeReviewGroup, str] = {
    MemeReviewGroup.MEDIUM_CANDIDATE: "Group A — Current MEDIUM candidates",
    MemeReviewGroup.LOW_RANDOM: "Group B — Random LOW score examples",
    MemeReviewGroup.SAFETY_BLOCKED: "Group C — Safety-blocked examples",
}
_GROUP_ORDER = [MemeReviewGroup.MEDIUM_CANDIDATE, MemeReviewGroup.LOW_RANDOM, MemeReviewGroup.SAFETY_BLOCKED]
_DECISION_OPTIONS = "`ACCEPT` / `WEAK` / `REJECT`"
_REASON_OPTIONS = (
    "`unexpected_result` / `irony` / `conflict` / `absurdity` / `company_drama` / `ai_hype` / "
    "`failure_or_mistake` / `visual_potential` / `community_reaction` / `other`"
)
_SAFETY_OPTIONS = "`safe` / `questionable` / `should_block`"
_NOT_REVIEWED = "_[ not yet reviewed ]_"


def _render_record(index: int, record: MemeCalibrationRecord) -> str:
    signals = ", ".join(record.triggered_signals) if record.triggered_signals else "—"
    safety = ", ".join(record.safety_result) if record.safety_result else "—"
    published = record.published_at.isoformat() if record.published_at else "—"
    return f"""### {index}. {record.title}

**Event information**

- **event_id**: `{record.event_id}`
- **category**: {record.category}
- **source**: {record.source_name or "—"}
- **publication date**: {published}
- **excerpt**: {record.content_excerpt or "—"}

**Existing algorithm output**

- **meme_score**: {record.algorithm_score}
- **opportunity_level**: `{record.algorithm_level}`
- **triggered signals**: {signals}
- **safety result**: {safety}

**Human decision** (fill in manually — do not auto-fill)

- **Meme potential** (0-5): {_NOT_REVIEWED}
- **Decision** ({_DECISION_OPTIONS}): {_NOT_REVIEWED}
- **Meme reason** (multiple allowed — {_REASON_OPTIONS}): {_NOT_REVIEWED}
- **Safety opinion** ({_SAFETY_OPTIONS}): {_NOT_REVIEWED}
- **Human notes**: {_NOT_REVIEWED}

---
"""


def render_markdown_packet(dataset: MemeCalibrationDataset) -> str:
    """Pure formatting only - every human-facing field is rendered as the literal `_[ not yet
    reviewed ]_` placeholder (never a pre-filled guess), mirroring `docs/
    phase18_5_human_review_packet.md`'s own established discipline exactly."""
    by_group: dict[MemeReviewGroup, list[MemeCalibrationRecord]] = {group: [] for group in MemeReviewGroup}
    for record in dataset.records:
        by_group[record.group].append(record)

    sections: list[str] = []
    counter = 1
    for group in _GROUP_ORDER:
        rows = by_group[group]
        sections.append(f"## {_GROUP_TITLE[group]} ({len(rows)} items)\n")
        if not rows:
            sections.append("_No real events were selected into this group._\n\n---\n")
            continue
        for record in rows:
            sections.append(_render_record(counter, record))
            counter += 1

    header = f"""# Phase 18.6 — Meme Opportunity Human Calibration Packet

Status: **ready for human review — every human-decision field below is intentionally blank.**
Nothing in this document was filled in automatically.

**{len(dataset.records)} real news events**, drawn from a read-only, offline run of the existing,
unmodified Phase 18 M1 meme opportunity classifier against real `NewsEvent` rows: {dataset.group_a_count}
Group A (current `MEDIUM` candidates, sampled for maximum category diversity), {dataset.group_b_count}
Group B (random `LOW` examples, to probe for false negatives), {dataset.group_c_count} Group C
(safety-blocked examples, to validate the safety gate). Generated {dataset.generated_at.strftime("%Y-%m-%d")}
by `scripts/phase18_6_generate_calibration_packet.py` — reproducible from
`scripts/phase18_6_calibration_dataset.json`.

## How to use this packet

For each item, record:

- **Meme potential** — 0 (no potential) through 5 (excellent meme opportunity)
- **Decision** — {_DECISION_OPTIONS}
- **Meme reason** — one or more of {_REASON_OPTIONS}
- **Safety opinion** — {_SAFETY_OPTIONS}
- **Human notes** — free text

This is the calibration input `scripts/phase18_6_calibration_analysis.py` reads (from the same-named
JSON file, edited in place) to compute precision/recall/false-positive-rate against the current
classifier, score correlation, category performance, and safety-gate accuracy.

---

"""
    return header + "\n".join(sections)


# ---------------------------------------------------------------------------
# Metrics (analysis-time, over a *completed* dataset)
# ---------------------------------------------------------------------------


def _reviewed(records: list[MemeCalibrationRecord], group: MemeReviewGroup) -> list[MemeCalibrationRecord]:
    return [r for r in records if r.group == group and r.is_reviewed]


def opportunity_classifier_metrics(records: list[MemeCalibrationRecord]) -> dict[str, object]:
    """Group A/B-scoped metrics answering the brief's own "precision, recall, false positive rate,
    false negative examples" request.

    Explicit, documented framing (there is more than one defensible way to binarize a 3-way human
    decision against a 2-group sample, so the choice is stated rather than left implicit):
    - Group A (`MEDIUM`, the classifier's own "positive" prediction) - `precision_strict` counts
      only `ACCEPT` as a true positive; `precision_lenient` counts `ACCEPT` or `WEAK` (i.e. "the
      human found at least some genuine potential"). `false_positive_rate` = 1 - precision_strict
      = share of `REJECT`.
    - Group B (`LOW`, the classifier's own "negative" prediction) - `false_negative_rate` = share
      of reviewed items where the human did NOT reject (found some potential in an item the
      classifier scored too low to surface). `false_negative_examples` lists those `event_id`s for
      qualitative follow-up.
    - True statistical **recall** is NOT computable from this sample (it requires knowing the total
      count of real positives across the full, mostly-unreviewed 12,430-event population, which
      this targeted sample cannot supply) - `recall` is returned as `None` with that reason stated,
      never silently omitted or approximated.
    """
    group_a = _reviewed(records, MemeReviewGroup.MEDIUM_CANDIDATE)
    group_b = _reviewed(records, MemeReviewGroup.LOW_RANDOM)

    precision_strict = precision_lenient = false_positive_rate = None
    if group_a:
        accept = sum(1 for r in group_a if r.human_decision == MemeCalibrationHumanDecision.ACCEPT)
        weak = sum(1 for r in group_a if r.human_decision == MemeCalibrationHumanDecision.WEAK)
        reject = sum(1 for r in group_a if r.human_decision == MemeCalibrationHumanDecision.REJECT)
        precision_strict = accept / len(group_a)
        precision_lenient = (accept + weak) / len(group_a)
        false_positive_rate = reject / len(group_a)

    false_negative_rate = None
    false_negative_examples: list[str] = []
    if group_b:
        non_reject = [r for r in group_b if r.human_decision != MemeCalibrationHumanDecision.REJECT]
        false_negative_rate = len(non_reject) / len(group_b)
        false_negative_examples = [r.event_id for r in non_reject]

    return {
        "group_a_reviewed": len(group_a),
        "group_b_reviewed": len(group_b),
        "precision_strict": precision_strict,
        "precision_lenient": precision_lenient,
        "false_positive_rate": false_positive_rate,
        "recall": None,
        "recall_note": (
            "Not computable from a targeted sample - requires the total count of real positives "
            "across the full population, which this review packet does not cover."
        ),
        "false_negative_rate": false_negative_rate,
        "false_negative_examples": false_negative_examples,
    }


def score_correlation(records: list[MemeCalibrationRecord]) -> dict[str, object]:
    """Pearson correlation between `algorithm_score` (0-100) and `human_score` (0-5) across every
    reviewed record with a `human_score` present, regardless of group - correlation is scale-
    invariant, so the two different scales need no rescaling. Requires at least 2 points with
    non-zero variance in both series (`statistics.correlation`'s own precondition); returns `None`
    with a stated reason otherwise, rather than raising or fabricating a value."""
    scored = [r for r in records if r.is_reviewed and r.human_score is not None]
    if len(scored) < 2:
        return {"n": len(scored), "correlation": None, "note": "Fewer than 2 scored records - correlation undefined."}
    algo = [r.algorithm_score for r in scored]
    human: list[int] = [r.human_score for r in scored if r.human_score is not None]
    if len(set(algo)) < 2 or len(set(human)) < 2:
        return {"n": len(scored), "correlation": None, "note": "No variance in one series - correlation undefined."}
    return {"n": len(scored), "correlation": statistics.correlation(algo, human), "note": None}


def category_analysis(records: list[MemeCalibrationRecord]) -> dict[str, dict[str, object]]:
    """Answers the brief's own "which categories generate best meme opportunities" question:
    average `human_score` per category, among reviewed records that have one, sorted best-first."""
    by_category: dict[str, list[int]] = {}
    for record in records:
        if record.is_reviewed and record.human_score is not None:
            by_category.setdefault(record.category, []).append(record.human_score)
    averages = {category: sum(scores) / len(scores) for category, scores in by_category.items()}
    result: dict[str, dict[str, object]] = {
        category: {"reviewed_count": len(by_category[category]), "average_human_score": averages[category]}
        for category in by_category
    }
    return dict(sorted(result.items(), key=lambda kv: -averages[kv[0]]))


def safety_analysis(records: list[MemeCalibrationRecord]) -> dict[str, object]:
    """Group C-scoped: were the classifier's own safety blocks actually correct? `correct_blocks`
    = human agreed (`should_block`); `false_blocks` = human said `safe` (the block was wrong);
    `questionable_blocks` = human was unsure. `false_block_examples` lists those `event_id`s."""
    group_c = _reviewed(records, MemeReviewGroup.SAFETY_BLOCKED)
    correct = sum(1 for r in group_c if r.safety_review == MemeCalibrationSafetyOpinion.SHOULD_BLOCK)
    false_blocks = [r for r in group_c if r.safety_review == MemeCalibrationSafetyOpinion.SAFE]
    questionable = sum(1 for r in group_c if r.safety_review == MemeCalibrationSafetyOpinion.QUESTIONABLE)
    return {
        "group_c_reviewed": len(group_c),
        "correct_blocks": correct,
        "false_blocks": len(false_blocks),
        "false_block_examples": [r.event_id for r in false_blocks],
        "questionable_blocks": questionable,
    }
