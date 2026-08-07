"""Phase 19 M6 - builds the REAL/HUMAN-REVIEW calibration packet from
scripts/_phase19_m6_real_replay_predictions.json (produced by
scripts/_phase19_m6_real_data_replay.py's read-only replay of real NewsEvent titles through the
real services.story_memory.match_story(), against a disposable DB). Mirrors scripts/_phase18_5_
build_human_review_packet.py's own established pattern exactly: deterministic stratified sample
(fixed random seed), every human_decision/human_notes field left genuinely blank - never
pre-filled or guessed.

Two kinds of items are selected:

1. Stratified-by-outcome sample - up to N of each match_story() outcome (new_story get a random
   spot-check sample; every non-"new_story" outcome type is included up to its own cap, since
   these are the rarer, most decision-relevant predictions for a human to check).
2. Cross-category/cross-topic-bucket entity-overlap candidates - a bounded, disclosed HEURISTIC
   (never a scored claim) surfacing real event pairs that share a distinctive (2+ word) entity
   within a 72-hour window but landed in different topic_buckets - exactly the shape of the known
   Muse-Code failure class (docs/phase18_10_editorial_intelligence_report.md sec7-9), applied to
   real, current production data instead of a hand-picked historical example.

Deliberately a throwaway helper script (same "not part of the production code path, not
unit-tested itself" convention as scripts/_phase18_5_build_human_review_packet.py).
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

_PREDICTIONS_PATH = Path(__file__).with_name("_phase19_m6_real_replay_predictions.json")
_OUTPUT_PATH = Path(__file__).with_name("_phase19_m6_human_review_selection.json")

_NON_NEW_STORY_SAMPLE_SIZE = 15  # per outcome type (story_update/supporting_source/semantic_duplicate/uncertain_match)
_NEW_STORY_SPOT_CHECK_SAMPLE_SIZE = 20
_CROSS_CATEGORY_CANDIDATE_LIMIT = 20
_CROSS_CATEGORY_WINDOW_HOURS = 72
_MIN_GROUP_SIZE = 2
_MAX_GROUP_SIZE = 5  # larger groups are almost certainly a generic recurring entity, not one story

random.seed(19.6)  # deterministic sample selection, reproducible across runs


def _stratified_outcome_sample(predictions: list[dict]) -> dict[str, list[dict]]:
    by_outcome: dict[str, list[dict]] = defaultdict(list)
    for p in predictions:
        by_outcome[p["outcome"]].append(p)

    selected: dict[str, list[dict]] = {}
    for outcome, pool in by_outcome.items():
        cap = _NEW_STORY_SPOT_CHECK_SAMPLE_SIZE if outcome == "new_story" else _NON_NEW_STORY_SAMPLE_SIZE
        n = min(cap, len(pool))
        selected[outcome] = random.sample(pool, n) if pool else []
    return selected


def _cross_category_candidates(predictions: list[dict]) -> list[dict]:
    """Heuristic-only: groups real events sharing a distinctive (2+ word) entity within a bounded
    time window, then keeps only groups spanning more than one topic_bucket - candidate
    cross-category same-story pairs the hard topic_bucket gate would have kept apart, for a human
    to actually judge (never itself a scored precision/recall claim - see the calibration report's
    explicit separation of this from the synthetic fixtures' real metrics)."""
    entity_index: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(predictions):
        for entity in p.get("entities", []):
            if " " in entity.strip():  # multi-word only - a single common word is far too noisy
                entity_index[entity].append(i)

    candidate_groups: list[dict] = []
    for entity, indices in entity_index.items():
        if len(indices) < _MIN_GROUP_SIZE:
            continue
        # Bound to a plausible single-story time window: greedily cluster by proximity rather
        # than requiring the whole group to fall in one window (an entity could recur across
        # unrelated stories months apart - only nearby occurrences are a plausible same-story
        # candidate).
        timed = sorted(
            (
                (datetime.fromisoformat(predictions[i]["collected_at"]), i)
                for i in indices
                if predictions[i]["collected_at"]
            ),
            key=lambda pair: pair[0],
        )
        cluster: list[int] = []
        clusters: list[list[int]] = []
        for ts, i in timed:
            if cluster and (ts - timed[len(cluster) - 1][0]) > timedelta(hours=_CROSS_CATEGORY_WINDOW_HOURS):
                clusters.append(cluster)
                cluster = []
            cluster.append(i)
        if cluster:
            clusters.append(cluster)

        for cluster_indices in clusters:
            if not (_MIN_GROUP_SIZE <= len(cluster_indices) <= _MAX_GROUP_SIZE):
                continue
            topic_buckets = {predictions[i]["topic_bucket"] for i in cluster_indices}
            if len(topic_buckets) < 2:
                continue  # same-topic_bucket cases are already covered by the stratified sample
            candidate_groups.append(
                {
                    "shared_entity": entity,
                    "topic_buckets": sorted(topic_buckets),
                    "events": [
                        {
                            "title": predictions[i]["title"],
                            "category": predictions[i]["category"],
                            "topic_bucket": predictions[i]["topic_bucket"],
                            "collected_at": predictions[i]["collected_at"],
                            "outcome": predictions[i]["outcome"],
                            "real_event_id": predictions[i]["real_event_id"],
                        }
                        for i in cluster_indices
                    ],
                }
            )

    candidate_groups.sort(key=lambda g: len(g["events"]), reverse=True)
    return candidate_groups[:_CROSS_CATEGORY_CANDIDATE_LIMIT]


def main() -> None:
    predictions = json.loads(_PREDICTIONS_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(predictions)} real machine predictions.")

    stratified = _stratified_outcome_sample(predictions)
    cross_category = _cross_category_candidates(predictions)

    output = {
        "generated_from_predictions_count": len(predictions),
        "stratified_by_outcome": stratified,
        "cross_category_entity_overlap_candidates": cross_category,
    }
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    total_stratified = sum(len(v) for v in stratified.values())
    print(f"Stratified-by-outcome sample: {total_stratified} items")
    for outcome, rows in stratified.items():
        print(f"  {outcome}: {len(rows)}")
    print(f"Cross-category entity-overlap candidate groups: {len(cross_category)}")
    print(f"Written to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
