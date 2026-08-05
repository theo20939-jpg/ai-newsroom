"""Phase 18.7 - calibration replay (docs/phase18_7_calibration_results.md).

Offline, zero-database-access comparison: reads the already-committed `scripts/
phase18_6_calibration_dataset.json` (Phase 18.6's own 50-item packet: 20 Group A/MEDIUM, 20 Group
B/LOW, 10 Group C/BLOCKED) and, for each item, computes what the v2 calibration layer
(`services.meme_calibration_rules`) would have produced on top of the v1 result already stored in
that file - never re-queries the database, never recomputes v1 from scratch (the dataset's own
`algorithm_score`/`algorithm_level` fields are the real, already-computed v1 output; recomputing
v1 fresh here would require the original `research_output`, which was not persisted, and could
silently drift from the real stored result).

Uses `title` + `content_excerpt` (the same 280-character excerpt already captured in the Phase
18.6 dataset, not the full article) as the text the calibration functions scan - a known,
documented approximation (docs/phase18_7_calibration_results.md's own "Known limitations"
section), not a full-corpus recomputation.

No LLM call, no network call, no database access of any kind in this file.

Usage: `python scripts/phase18_7_calibration_replay.py`
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from schemas.meme_calibration import MemeCalibrationDataset
from services.meme_calibration_rules import compute_calibration_delta, detect_sensitive_categories_v2

_DATASET_PATH = Path(__file__).parent / "phase18_6_calibration_dataset.json"
_OUTPUT_PATH = Path(__file__).parent / "_phase18_7_calibration_replay_results.json"

_READY_THRESHOLD = 55
_REVIEW_THRESHOLD = 35


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _label_for_score(score: int) -> str:
    if score >= _READY_THRESHOLD:
        return "HIGH"
    if score >= _REVIEW_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def _replay_opportunity_record(record: dict) -> dict:
    text = _normalize(f"{record['title']} {record['content_excerpt']}").lower()
    delta, evidence = compute_calibration_delta(text, record["source_name"])
    adjusted = max(0, min(100, record["algorithm_score"] + delta))
    new_label = _label_for_score(adjusted)
    return {
        "event_id": record["event_id"],
        "group": record["group"],
        "before_score": record["algorithm_score"],
        "before_label": record["algorithm_level"],
        "after_score": adjusted,
        "after_label": new_label,
        "calibration_delta": delta,
        "calibration_evidence": evidence,
        "label_changed": new_label != record["algorithm_level"],
    }


def _replay_safety_record(record: dict) -> dict:
    text = _normalize(f"{record['title']} {record['content_excerpt']}").lower()
    result = detect_sensitive_categories_v2(text)

    if not result.base_categories:
        # The 280-char excerpt doesn't even reproduce v1's own original match (the real trigger
        # phrase lives further into the full article than this dataset's stored excerpt covers) -
        # this is a replay-data limitation, not evidence the v2 calibration layer fixed anything.
        # Must never be reported as an "unblocked" calibration success.
        return {
            "event_id": record["event_id"], "group": record["group"], "before_label": "BLOCKED",
            "after_label": "CANNOT_VERIFY_FROM_EXCERPT", "suppressed_evidence": [], "remaining_evidence": [],
            "label_changed": False, "cannot_verify_from_excerpt": True,
        }

    unblocked = len(result.categories) == 0
    return {
        "event_id": record["event_id"],
        "group": record["group"],
        "before_label": "BLOCKED",
        "after_label": "UNBLOCKED" if unblocked else "BLOCKED",
        "suppressed_evidence": result.suppressed_evidence,
        "remaining_evidence": result.evidence,
        "label_changed": unblocked,
        "cannot_verify_from_excerpt": False,
    }


def replay() -> dict:
    dataset = MemeCalibrationDataset.model_validate_json(_DATASET_PATH.read_text(encoding="utf-8"))
    records = [r.model_dump(mode="json") for r in dataset.records]

    opportunity_results = [
        _replay_opportunity_record(r) for r in records if r["group"] != "SAFETY_BLOCKED"
    ]
    safety_results = [
        _replay_safety_record(r) for r in records if r["group"] == "SAFETY_BLOCKED"
    ]

    return {
        "dataset_generated_at": dataset.generated_at.isoformat(),
        "opportunity_results": opportunity_results,
        "safety_results": safety_results,
        "summary": {
            "group_a_medium_changed": sum(
                1 for r in opportunity_results if r["group"] == "MEDIUM_CANDIDATE" and r["label_changed"]
            ),
            "group_b_low_changed": sum(
                1 for r in opportunity_results if r["group"] == "LOW_RANDOM" and r["label_changed"]
            ),
            "group_c_unblocked": sum(1 for r in safety_results if r["label_changed"]),
            "group_c_cannot_verify_from_excerpt": sum(
                1 for r in safety_results if r["cannot_verify_from_excerpt"]
            ),
            "group_c_total": len(safety_results),
        },
    }


def main() -> None:
    result = replay()
    _OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Written to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
