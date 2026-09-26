"""Zero-cost audit of KAGE-FIRST VIRAL SELECTION on a real production candidate pool (read-only export, one JSON object per line).

BEFORE = the planner read as committed at a given git revision (loaded from `git show <rev>:services/instagram_feed_product.py`);
AFTER  = the current working-tree read. The same stage-1 read and the same strong-only slot rule decide both - no provider call.
Usage: python scripts/_instagram_viral_selection_audit.py <pool.jsonl> <out dir> [<before rev>]
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
CONFIRMED = ("story_update", "supporting_source", "semantic_duplicate")


def _module_at(rev: str) -> types.ModuleType:
    source = subprocess.run(["git", "show", f"{rev}:services/instagram_feed_product.py"], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", check=True).stdout
    module = types.ModuleType("feed_product_before")
    module.__dict__["__name__"] = "feed_product_before"
    sys.modules["feed_product_before"] = module  # dataclasses resolve their module through sys.modules
    exec(compile(source, "feed_product_before", "exec"), module.__dict__)  # noqa: S102 - the repository's own committed source
    return module


def _age(row: dict, now: datetime) -> str:
    published = datetime.fromisoformat(str(row["published_at"]).replace("Z", "+00:00"))
    return f"{(now - published).total_seconds() / 3600:.1f}h"


def main() -> None:
    import services.instagram_feed_product as after_module

    pool, out = Path(sys.argv[1]), Path(sys.argv[2])
    rev = sys.argv[3] if len(sys.argv) > 3 else "HEAD"
    out.mkdir(parents=True, exist_ok=True)
    before_module = _module_at(rev)
    rows, seen = [], set()
    for line in pool.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
    now = max(datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")) for r in rows)

    def reads(module):
        result = []
        for r in rows:
            c = module.FeedCandidate(id=r["id"], title=r["title"] or "", summary=r["summary"] or "", source_name=r["source_name"] or "",
                                     source_type=r["source_type"] or "", category=r["category"] or "", views=r["views"],
                                     coverage=int(r["event_count"] or 1) if (r["is_first"] or r["match_type"] in CONFIRMED) else 1)
            result.append((r, module.read_candidate(c)))
        return result

    def viral_top(pairs):
        eligible = [(r, rd) for r, rd in pairs if rd.format.value == "meme_trend"]
        return sorted(eligible, key=lambda x: (not x[1].strong, -x[1].rank))[:10]

    before, after = reads(before_module), reads(after_module)
    after_by_id = {r["id"]: rd for r, rd in after}

    def entry(r, rd, verdict):
        title = r["title"] or ""
        return {"headline": title, "source": r["source_name"], "age": _age(r, now), "published_at": r["published_at"],
                "ingested_at": r["created_at"], "kage_core": after_module.kage_core(after_module._clean_title(title, (r["source_name"] or "").lower())),
                "viral_signal": {"event_oddity": after_module.event_oddity(title), "distribution_only": bool(after_module._DISTRIBUTION.search(title))
                                 and not after_module.event_oddity(title)},
                **verdict}

    table_before = []
    for r, rd in viral_top(before):
        now_read = after_by_id[r["id"]]
        eligible = now_read.format.value == "meme_trend" and now_read.strong
        table_before.append(entry(r, rd, {"before": f"{rd.format.value} strong={rd.strong} rank={rd.rank}",
                                          "after": f"{now_read.format.value} strong={now_read.strong}", "eligible": eligible,
                                          "why": now_read.reason}))
    table_after = [entry(r, rd, {"after": f"{rd.format.value} strong={rd.strong} rank={rd.rank}", "eligible": rd.strong, "why": rd.reason})
                   for r, rd in viral_top(after)]
    report = {"pool_size": len(rows), "pool_latest_ingest": str(now), "before_rev": rev,
              "before_top10": table_before, "after_top10": table_after,
              "rejected_by_new_rule": [e["headline"] for e in table_before if not e["eligible"]],
              "preserved_by_new_rule": [e["headline"] for e in table_before if e["eligible"]]}
    (out / "selection_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = [f"# KAGE-first viral selection audit - {len(rows)} production events (latest ingest {now:%Y-%m-%d %H:%M} UTC), zero provider calls", "",
          "## BEFORE: the committed planner's top-10 viral candidates, judged by the new rule", "",
          "| # | headline | source | age | KAGE core | event oddity | before | after | eligible | why |", "|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {i} | {e['headline'][:90]} | {e['source']} | {e['age']} | {', '.join(e['kage_core']) or '-'} | {e['viral_signal']['event_oddity']} | "
           f"{e['before']} | {e['after']} | {'YES' if e['eligible'] else 'NO'} | {e['why']} |" for i, e in enumerate(table_before, 1)]
    md += ["", "## AFTER: re-ranked top-10 viral candidates (only strong reads can fill the slot)", "",
           "| # | headline | source | age | KAGE core | event oddity | read | eligible | why |", "|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {i} | {e['headline'][:90]} | {e['source']} | {e['age']} | {', '.join(e['kage_core']) or '-'} | {e['viral_signal']['event_oddity']} | "
           f"{e['after']} | {'YES' if e['eligible'] else 'no (weak)'} | {e['why']} |" for i, e in enumerate(table_after, 1)]
    (out / "selection_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
