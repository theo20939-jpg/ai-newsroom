"""OFFLINE differential regression of the viral evidence preflight (founder task 2026-09-29: launch story evidence contract). No provider /
LLM / image call, no database, no network.

Every evidence attempt saved by the earlier paid viral canaries (artifacts/instagram_feed_product/*/outcome.json + its
post/evidence_attempts/NN_package.json) is checked twice with IDENTICAL inputs - the event's saved hook and actuality, the saved package
lines, the attempt's own titles as headlines, the canary's clock:
  OLD = services/instagram_viral_nomination.py at <base ref> (loaded from git), NEW = the working tree.
The saved packages were built by the OLD fact selection; the preflight difference is what this measures. Also reported: whether OLD with
these inputs reproduces the status the canary itself recorded (the headline set is approximated by the attempt's titles).
Usage: python scripts/_instagram_launch_evidence_regression.py <base ref> <out json>
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _old_module(ref: str):
    source = subprocess.run(["git", "show", f"{ref}:services/instagram_viral_nomination.py"], cwd=ROOT, capture_output=True, check=True).stdout
    path = Path(tempfile.mkdtemp()) / "old_instagram_viral_nomination.py"
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("old_instagram_viral_nomination", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def _lines(package: dict) -> list[str]:
    return [item["text"] for key in ("steps", "facts", "limitations") for item in package.get(key) or []]


def main() -> None:
    ref, out = sys.argv[1], Path(sys.argv[2])
    import services.instagram_viral_nomination as new

    old = _old_module(ref)
    rows = []
    for outcome_path in sorted((ROOT / "artifacts/instagram_feed_product").glob("**/outcome.json")):
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        verdict, attempts = outcome.get("verdict"), outcome.get("evidence_attempts") or []
        if not verdict or not attempts:
            continue
        now = datetime.fromisoformat(outcome["now"])
        actuality = SimpleNamespace(type=verdict["actuality"])
        for attempt in attempts:
            package_path = outcome_path.parent / "post/evidence_attempts" / f"{attempt['order']:02d}_package.json"
            if not package_path.exists():
                continue
            lines = _lines(json.loads(package_path.read_text(encoding="utf-8")))
            headlines = [h for h in (attempt.get("title"), (outcome.get("planned_copy") or {}).get("title"), outcome.get("selected_event")) if h]
            before = old.evidence_preflight(verdict["hook"], lines, actuality=actuality, now=now, headlines=headlines)
            after = new.evidence_preflight(verdict["hook"], lines, actuality=actuality, now=now, headlines=headlines)
            rows.append({"run": str(outcome_path.parent.relative_to(ROOT)), "attempt": attempt["order"], "source": attempt.get("source"),
                         "hook": verdict["hook"][:140], "recorded": attempt.get("preflight"), "old": before.status, "new": after.status,
                         "old_checks": before.checks, "new_checks": after.checks,
                         "changed": before.status != after.status or before.checks != after.checks})
    report = {"base_ref": ref, "attempts": len(rows), "old_reproduces_recorded": sum(r["old"] == r["recorded"] for r in rows),
              "status_changed": [r for r in rows if r["old"] != r["new"]], "checks_changed": [r for r in rows if r["changed"]],
              "rows": rows, "provider_calls": 0, "image_calls": 0}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"attempts {len(rows)} | OLD reproduces recorded {report['old_reproduces_recorded']}/{len(rows)} | status changed "
          f"{len(report['status_changed'])} | any check changed {len(report['checks_changed'])}")
    for r in rows:
        mark = "CHANGED" if r["changed"] else "same"
        print(f"  {mark:7} {r['run'][29:]:48} #{r['attempt']} {str(r['source'])[:22]:22} recorded={r['recorded']} old={r['old']} new={r['new']}")
    for r in report["checks_changed"]:
        diff = {k: (r["old_checks"].get(k), v) for k, v in r["new_checks"].items() if r["old_checks"].get(k) != v}
        print("  DIFF", r["run"][29:], r["attempt"], diff)


if __name__ == "__main__":
    main()
