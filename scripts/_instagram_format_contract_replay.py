"""Offline replay (zero-cost) of the failed 2026-09-25 E2E week against the downstream format contract.

Reads the saved paid-run outputs (artifacts/.../e2e_week_2026-08-05_11/run) - no provider call, no network, no DB:
  - every daily post: its planned format (frozen selection), the saved Phase A decision, the OLD gate verdict
    (format_from_editorial_decision must equal the planned format) and the NEW routing (the planned format is authoritative; only a
    non-taxonomy failure or BLOCKING evidence stops a post);
  - Kimi: the saved Creative Director copy re-checked with the new Russian-prose / technical-literal rule;
  - Adobe: the saved ungrounded Phase A quote against the old evidence items - the cause was an attribution + heading glued onto the
    quoted sentence (the quote is a substring of one glued item), not an ellipsis; the new block split extracts that sentence whole;
  - the weekly recap: the saved Phase A decision against the recap coverage contract (7 stories).
Usage: python scripts/_instagram_format_contract_replay.py <run dir> <out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.instagram_creative_director as cd  # noqa: E402
from schemas.instagram_creative import InstagramEditorialDecision  # noqa: E402
from services.instagram_automatic_trigger import planned_product  # noqa: E402
from services.instagram_feed_product import FeedFormat, format_from_editorial_decision  # noqa: E402

PLANNED = {"ai_hack": FeedFormat.AI_HACK, "meme_trend": FeedFormat.MEME_TREND}
DEDUP_COPY = "2026-08-11_2_meme_trend"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _phase_a(post_dir: Path) -> dict | None:
    files = sorted((post_dir / "calls").glob("*phase_a*")) if (post_dir / "calls").exists() else []
    for f in files:
        out = (_load(f) or {}).get("response", {}).get("structured_output")
        if out:
            return out
    return None


def main() -> None:
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for post_dir in sorted(p for p in run.iterdir() if p.is_dir() and p.name.startswith("2026")):
        fmt = post_dir.name.split("_", 2)[2]
        planned = PLANNED[fmt]
        outcome = _load(post_dir / "outcome.json") or {}
        package = _load(post_dir / "evidence_package.json") or {}
        decision = _phase_a(post_dir)
        taxonomy = format_from_editorial_decision(decision) if decision else None
        old_reason = outcome.get("reason", "")
        dropped_by_taxonomy = old_reason.startswith("feed_format_mismatch")
        non_taxonomy_failure = old_reason if (old_reason and not dropped_by_taxonomy and outcome.get("stage") not in ("OK",)) else None
        routable = package.get("quality") != "BLOCKING"  # the contract keeps the planned product; only BLOCKING evidence stops it pre-Director
        rows.append({
            "post": post_dir.name, "planned_format": planned_product(planned, None)[0], "evidence": package.get("quality"),
            "phase_a_taxonomy": taxonomy.value if taxonomy else None, "old_outcome": old_reason,
            "old_gate": "DROPPED (taxonomy)" if dropped_by_taxonomy else "passed" if decision else "no decision",
            "new_routing": "CONTINUES as " + planned_product(planned, None)[0] if routable else "STOPS: evidence BLOCKING",
            "other_failure_in_the_paid_run": non_taxonomy_failure,
        })
    # Kimi: the saved Creative Director copy under the new language rule
    kimi = _load(run / "2026-08-05_1_ai_hack" / "director_raw_output.json") or {}
    so = kimi.get("structured_output") or {}
    fields = [s.get("slide_copy") or "" for s in so.get("slides", [])] + [s.get("slide_body") or "" for s in so.get("slides", [])] + [
        so.get("final_cta") or "", so.get("final_caption") or ""]
    try:
        cd.assert_russian_final_text(fields, locale="ru")
        kimi_language = "PASS"
    except cd.CreativeLanguageError as exc:
        kimi_language = f"FAIL: {exc}"
    # Adobe: the saved ungrounded quote vs the old (glued) evidence items
    adobe_dir = run / "2026-08-06_1_ai_hack"
    adobe_decision = _phase_a(adobe_dir) or {}
    adobe_package = _load(adobe_dir / "evidence_package.json") or {}
    old_items = [i["text"] for k in ("steps", "facts", "limitations") for i in adobe_package.get(k, [])]
    old_lines = [adobe_package.get("premise")] + old_items
    ungrounded = [q for q in adobe_decision.get("evidence_used", []) if q not in old_lines and not q.startswith("SOURCE MEDIA")]
    cause = [{"quote": q[:120], "old_line_was_clipped": any(line.endswith("…") and line.rstrip("…").strip() == q.strip() for line in old_items),
              "quote_is_substring_of_a_glued_item": any(q in line and q != line for line in old_items)} for q in ungrounded]
    # the recap: the saved Phase A decision against the coverage contract
    recap_decision = _phase_a(run / "weekly_recap") or {}
    bundle = _load(run / "weekly_recap" / "bundle.json") or {}
    keys = [s["key"] for s in bundle.get("stories", [])]
    try:
        cd.assert_recap_coverage(InstagramEditorialDecision.model_validate({**recap_decision, "coverage_plan": recap_decision.get("coverage_plan")}), keys)
        recap_contract = "PASSES (saved decision covered every story)"
    except cd.RecapCoverageContractError as exc:
        recap_contract = f"REJECTED before the Creative Director: {exc}"
    report = {
        "daily": rows,
        # the 12 daily posts after dedup: the Tuesday gym copy (2026-08-11_2) is the frozen cross-language dedup's case - it still
        # reaches Phase A, where the duplicate guard (not the taxonomy) decides it
        "ai_hack_routable": sum(1 for r in rows if r["planned_format"] == "AI_HACK" and r["new_routing"].startswith("CONTINUES")),
        "trend_routable": sum(1 for r in rows if r["planned_format"] == "TREND" and r["new_routing"].startswith("CONTINUES")
                              and r["post"] != DEDUP_COPY),
        "dedup_copy": DEDUP_COPY,
        "dropped_by_taxonomy_in_paid_run": sum(1 for r in rows if r["old_gate"].startswith("DROPPED")),
        "weekly_recap": {"routable_as": planned_product(None, bundle)[0] if bundle else None, "stories_in_bundle": len(keys),
                         "saved_decision_coverage_plan": recap_decision.get("coverage_plan"), "coverage_contract": recap_contract},
        "kimi_language_under_new_rule": kimi_language,
        "adobe_ungrounded_cause": cause,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['post']:26} {r['planned_format']:8} ev={str(r['evidence']):10} taxonomy={str(r['phase_a_taxonomy']):13} "
              f"old={r['old_gate']:18} new={r['new_routing']}")
    print(json.dumps({k: v for k, v in report.items() if k != "daily"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
