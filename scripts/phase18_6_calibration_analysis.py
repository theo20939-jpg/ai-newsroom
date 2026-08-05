"""Phase 18.6 - meme opportunity calibration analysis (docs/phase18_6_meme_calibration_report.md).

Thin driver: reads `scripts/phase18_6_calibration_dataset.json` (after a human has filled in each
record's `human_*` fields in place) and calls `services.meme_calibration`'s pure metric functions.
No LLM call, no network call, no database access at all in this file - purely a local JSON-in,
report-out tool.

If no record has been reviewed yet (every `human_decision` still `null`), prints an honest
"Calibration dataset prepared, human review pending." notice instead of fabricating metrics from
empty data - mirrors `docs/phase18_5_metrics_report.md`'s own "do not invent results" discipline.

Usage: `python scripts/phase18_6_calibration_analysis.py [--dataset PATH] [--output PATH]`
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from schemas.meme_calibration import MemeCalibrationDataset
from services.meme_calibration import (
    category_analysis,
    opportunity_classifier_metrics,
    safety_analysis,
    score_correlation,
)

_DEFAULT_DATASET_PATH = Path(__file__).parent / "phase18_6_calibration_dataset.json"


def analyze(dataset: MemeCalibrationDataset) -> dict[str, object]:
    reviewed_count = sum(1 for r in dataset.records if r.is_reviewed)
    if reviewed_count == 0:
        return {
            "status": "pending",
            "message": "Calibration dataset prepared, human review pending.",
            "total_records": len(dataset.records),
            "reviewed_records": 0,
        }
    return {
        "status": "complete" if reviewed_count == len(dataset.records) else "partial",
        "total_records": len(dataset.records),
        "reviewed_records": reviewed_count,
        "opportunity_classifier_metrics": opportunity_classifier_metrics(dataset.records),
        "score_correlation": score_correlation(dataset.records),
        "category_analysis": category_analysis(dataset.records),
        "safety_analysis": safety_analysis(dataset.records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=None, help="Optional path to write the JSON report to")
    args = parser.parse_args()

    dataset = MemeCalibrationDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
    report = analyze(dataset)
    rendered = json.dumps(report, indent=2, ensure_ascii=False, default=str)

    print(rendered)
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
