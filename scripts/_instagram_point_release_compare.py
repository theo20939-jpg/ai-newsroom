"""Compare the BEFORE / AFTER point-release replays (scripts/_instagram_point_release_replay.py) pool by pool: winner, eligible field
(added / removed events) and every software-release event whose verdict changed. No provider / LLM / image call.
Usage: python scripts/_instagram_point_release_compare.py <before dir> <after dir> <out json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

POOLS = ["natural", "canary", "canary2", "canary3", "canary4", "canary5", "canary6", "canary7", "canary8", "canary9", "canary10"]


def main() -> None:
    before_dir, after_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    report = {}
    for name in POOLS:
        b = json.loads((before_dir / f"{name}.json").read_text(encoding="utf-8"))
        a = json.loads((after_dir / f"{name}.json").read_text(encoding="utf-8"))
        b_keys, a_keys = [e["event"] for e in b["eligible"]], [e["event"] for e in a["eligible"]]
        b_sw = {e["event"]: e for e in b["software_release_events"]}
        a_sw = {e["event"]: e for e in a["software_release_events"]}
        changed = []
        for key in sorted(set(b_sw) | set(a_sw)):
            x, y = b_sw.get(key), a_sw.get(key)
            if x is None or y is None or (x["eligible"], x["strength"], x["mechanisms"], x["points"]) != (
                    y["eligible"], y["strength"], y["mechanisms"], y["points"]):
                changed.append({"event": key, "before": x and {k: x[k] for k in ("eligible", "failed_gate", "strength", "mechanisms", "points",
                                                                                  "broad_reason")},
                                "after": y and {k: y[k] for k in ("eligible", "failed_gate", "strength", "mechanisms", "points", "broad_reason")}})
        report[name] = {"winner_before": b["winner"], "winner_after": a["winner"], "winner_same": b["winner"] == a["winner"],
                        "eligible_before": len(b_keys), "eligible_after": len(a_keys),
                        "removed": [k for k in b_keys if k not in a_keys], "added": [k for k in a_keys if k not in b_keys],
                        "order_same_otherwise": [k for k in b_keys if k in a_keys] == [k for k in a_keys if k in b_keys],
                        "software_verdicts_changed": changed}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, r in report.items():
        print(f"== {name}: winner {'SAME' if r['winner_same'] else 'CHANGED'} | eligible {r['eligible_before']} -> {r['eligible_after']} | "
              f"order of the rest same: {r['order_same_otherwise']}")
        for k in r["removed"]:
            print(f"   - removed: {k[:110]}")
        for k in r["added"]:
            print(f"   + added:   {k[:110]}")
        for c in r["software_verdicts_changed"]:
            b, a = c["before"] or {}, c["after"] or {}
            print(f"   ~ {c['event'][:80]}: {b.get('strength')} {b.get('mechanisms')} eligible={b.get('eligible')} -> "
                  f"{a.get('strength')} {a.get('mechanisms')} eligible={a.get('eligible')}")


if __name__ == "__main__":
    main()
