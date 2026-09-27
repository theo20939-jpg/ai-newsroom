"""Zero-model OFFLINE REPLAY of the seventh canary's FIRST Director output after the proposition-aware thesis repair (founder task
2026-09-27). No provider / LLM / image call, no database write, no publication.

  1. slides 3 / 4 under the OLD comparison (4-letter content_stems + shared Latin name, >= 3 shared stems) and under the new one;
  2. the first output and the local quote-correction fixture (scripts/_instagram_quote_use_replay.py) through every deterministic validator
     and the REAL path with the semantic judge as a sentinel (NOT RUN OFFLINE - canary 7 never ran it, a run is a provider call).
Usage: python scripts/_instagram_thesis_proposition_replay.py <out dir>
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    import scripts._instagram_quote_use_replay as q
    from services.instagram_editorial_critic import anchors, content_stems
    from services.instagram_factual_status import build_status_ledger, distinct_by_role, factual_invariants, ledger_lines, slide_thesis_role
    from services.instagram_viral_format import (
        EditorialCorrectionRequired,
        distinct_propositions,
        proposition_role,
        same_proposition,
        thesis_relation,
        thesis_tokens,
    )

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    first = json.loads((q.CANARY / "director_raw_output_initial.json").read_text(encoding="utf-8"))["structured_output"]
    evidence = q.evidence_lines()
    s3, s4 = first["slides"][2], first["slides"][3]
    t3, t4 = f"{s3['slide_copy']} {s3['slide_body']}", f"{s4['slide_copy']} {s4['slide_body']}"
    old_shared = content_stems(t3) & content_stems(t4)
    old_names = {a for a in anchors(t3) & anchors(t4) if not any(c.isdigit() for c in a)}
    pair = {
        "old": {"slide_3_stems": sorted(content_stems(t3)), "slide_4_stems": sorted(content_stems(t4)), "shared_stems": sorted(old_shared),
                "shared_names": sorted(old_names), "rule": "shared_names non-empty AND len(shared_stems) >= 3",
                "roles_old": [slide_thesis_role(s3, 3), slide_thesis_role(s4, 4)], "distinct_by_role": distinct_by_role(s3, s4, 3),
                "duplicate": bool(old_names) and len(old_shared) >= 3},
        "new": {"slide_3_tokens": sorted(thesis_tokens(t3)), "slide_4_tokens": sorted(thesis_tokens(t4)),
                "shared_tokens": sorted(thesis_tokens(t3) & thesis_tokens(t4)), "roles": [proposition_role(s3), proposition_role(s4)],
                "distinct_propositions": distinct_propositions(s3, s4), "thesis_relation": thesis_relation(s3, s4, earlier_slides=first["slides"][:3]),
                "same_proposition": same_proposition(s3, s4)},
    }
    first_stage = q.stage(first, evidence, q.director_input(evidence))
    ledger = build_status_ledger(evidence)
    invariants = factual_invariants(first["slides"], first.get("final_caption") or "", ledger, evidence)
    note = EditorialCorrectionRequired(first_stage["deterministic_carried_to_judge"], factual_contract=ledger_lines(ledger),
                                       factual_invariants=invariants).correction_note
    fixture = copy.deepcopy(first)
    fixture["final_caption"] = first["final_caption"].replace(q.QUOTED_SENTENCE, q.FIXTURE_SENTENCE)
    report = {"provider_calls": 0, "image_calls": 0, "slides_3_4": pair, "first_output": first_stage,
              "fixture": {"change": [q.QUOTED_SENTENCE, q.FIXTURE_SENTENCE], **q.stage(fixture, evidence, q.director_input(evidence, note=note, invariants=invariants))}}
    (out / "thesis_proposition_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"slides_3_4": pair,
                      **{k: {kk: report[k][kk] for kk in ("quote_gate", "named_person_risks", "status_violations", "unsupported_targets",
                                                         "hook_lengths", "deterministic_carried_to_judge", "real_path")}
                         for k in ("first_output", "fixture")}}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
