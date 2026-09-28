"""Zero-model OFFLINE REPLAY of the disclosure-chronology non-regression fix (founder task 2026-09-28, after the tenth paid viral canary).
No provider / LLM / image call, no database write.

  1. canary 10: the saved FIRST and CORRECTED Director outputs - the invariants of the first, the non-regression of the corrected, every
     deterministic validator, and the REAL correction-mode path with the semantic judge as a sentinel (canary 10's final judge was never
     reached, so no verdict exists and none is invented);
  2. canaries 6 and 7 (real split chronology: the behaviour 'this summer', disclosed 25 September): the invariants of their first outputs
     and three LOCAL chronology-breaking corrections (drop the disclosure, move the event time, move the disclosure date) that must fail.
Usage: python scripts/_instagram_chronology_replay.py <out dir>
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts/instagram_feed_product"


class JudgeReached(Exception):
    pass


def evidence(run: str, call: str) -> list[str]:
    c = json.loads((ART / run / "post/calls" / call).read_text(encoding="utf-8"))
    text = "\n".join(t for m in c["request"] for t in m["text"])
    return [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]


def output(run: str, name: str) -> dict:
    return json.loads((ART / run / "post" / name).read_text(encoding="utf-8"))["structured_output"]


async def real_path(raw: dict, di) -> dict:
    import services.instagram_creative_director as cd
    import services.instagram_viral_editorial_judge as judge_mod

    async def sentinel(*_a, **_k):
        raise JudgeReached()

    real = judge_mod.judge_viral_copy
    judge_mod.judge_viral_copy = sentinel
    cd.set_raw_output_sink(lambda *_a: None)
    try:
        await cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di, archetype="trend_generative")
        return {"result": "PASS"}
    except JudgeReached:
        return {"result": "REACHED_SEMANTIC_JUDGE", "judge": "NOT RUN OFFLINE (canary 10 never reached its final judge; no verdict is invented)"}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        return {"result": type(exc).__name__, "detail": str(exc)[:1500], "findings": list(getattr(exc, "findings", []) or [])}
    finally:
        judge_mod.judge_viral_copy = real  # never leak the stub
        cd.set_raw_output_sink(None)


def _shown(inv: dict) -> dict:
    return {k: v for k, v in inv.items() if k != "ledger"}


def main() -> None:
    import scripts._instagram_correction_structure_replay as structure
    from services.instagram_factual_status import build_status_ledger, factual_invariants, non_regression_findings

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    run10 = "viral_nominated_canary10_20260928"
    ev10 = evidence(run10, "02_director.json")
    first10, corrected10 = output(run10, "director_raw_output_initial.json"), output(run10, "director_raw_output.json")
    ledger10 = build_status_ledger(ev10)
    base10 = factual_invariants(first10["slides"], first10.get("final_caption") or "", ledger10, ev10)
    di = structure.director_input(ev10, note="EDITORIAL CORRECTION (replay)", invariants=base10)
    report: dict = {"provider_calls": 0, "image_calls": 0, "canary10": {
        "first_invariants": _shown(base10),
        "corrected_non_regression": non_regression_findings(base10, corrected10["slides"], corrected10.get("final_caption") or "", ledger10, ev10),
        "corrected_deterministic": structure.deterministic(corrected10, ev10),
        "corrected_real_path_correction_mode": asyncio.run(real_path(corrected10, di)),
    }}
    for run, call in (("viral_nominated_canary6_20260927", "03_director.json"), ("viral_nominated_canary7_20260927", "02_director.json")):
        ev = evidence(run, call)
        first = output(run, "director_raw_output_initial.json")
        ledger = build_status_ledger(ev)
        base = factual_invariants(first["slides"], first.get("final_caption") or "", ledger, ev)
        text = json.dumps(first, ensure_ascii=False)
        probes = {
            "drop_disclosure": [("раскры", "сдела"), ("Раскры", "Сдела"), ("сообщил", "сделал"), ("рассказал", "сделал"), ("признал", "сделал"), ("25 сентября", ""), ("стало известно", "")],
            "move_event_time": [("этим летом", "этой весной"), ("летом", "весной")],
            "move_disclosure_date": [("25 сентября", "24 сентября")],
        }
        results = {}
        for name, swaps in probes.items():
            broken_text = text
            for a, b in swaps:
                broken_text = broken_text.replace(a, b)
            broken = json.loads(broken_text)
            results[name] = non_regression_findings(base, broken["slides"], broken.get("final_caption") or "", ledger, ev)
        results["unchanged_first_output"] = non_regression_findings(base, first["slides"], first.get("final_caption") or "", ledger, ev)
        report[run] = {"first_invariants": _shown(base), "chronology_line": next((e for e in ev if e.startswith("CHRONOLOGY")), None),
                       "probes": results}
    (out / "chronology_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str)[:7000])


if __name__ == "__main__":
    main()
