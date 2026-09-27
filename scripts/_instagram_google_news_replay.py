"""Zero-model OFFLINE REPLAY of canary 5's in-window Google News copies through the Google News article-token resolver (founder task
2026-09-27). No provider / LLM / image call, no database write, no publication.

Canary 5 (artifacts/instagram_feed_product/viral_nominated_canary5_20260927) stopped at evidence preflight PENDING: of the 13 copies inside
the accepted 24-hour window, 11 were Google News links acquisition could not resolve. For EACH of those 11 exact copies (and nothing
older - the 24-hour window is unchanged; the aged-out iXBT / 3DNews / Techmeme copies are not used), this replay runs the real path:
  acquire_article (resolution + the publisher fetch, provenance)  ->  build_daily_evidence_package (offline: session=None, media off)
  ->  viral_evidence_preflight against the SAME nominated event (the canary's own nomination over its own pool).
It answers: would these in-window copies have provided usable evidence if the resolver had existed during canary 5?
The Hacker News -> bbc.com copy is diagnosed (acquisition result only), not fixed.
Usage: python scripts/_instagram_google_news_replay.py <canary5 pool.jsonl> <canary5 members.jsonl> <canary5 rows.jsonl> <out dir>
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def nominated_event(pool_path: str, members_path: str):
    import scripts._instagram_viral_story_audit as audit
    from services.instagram_feed_product import FeedFormat, _clean_title, kage_core, read_candidate
    from services.instagram_viral_nomination import nominate_viral_events
    from services.instagram_viral_story_gate import ClusterMember

    rows, members = audit.load(pool_path, members_path)
    now = audit._dt(rows[0]["now"])
    by_id = {r["id"]: r for r in rows}
    headlines = [ClusterMember(title=r["title"] or "", source_id=r["source_name"] or "", source_name=r["source_name"] or "",
                               seen_at=audit._dt(r["published_at"]) or audit._dt(r["collected_at"]), collected_at=audit._dt(r["collected_at"]))
                 for r in rows]
    seen: set[str] = set()
    candidates = []
    for r in rows:
        if r["id"] in seen or now - audit._dt(r["collected_at"]) > timedelta(hours=24):  # the accepted 24-hour window, unchanged
            continue
        seen.add(r["id"])
        c = audit.candidate_of(r, members)
        if read_candidate(c).format is not FeedFormat.REJECT and kage_core(_clean_title(c.title, c.source_name.lower())):
            candidates.append(c)
    nomination = nominate_viral_events(candidates, headlines=headlines,
                                       evidence={c.id: by_id[c.id].get("article_text") or "" for c in candidates}, now=now)
    return nomination.best, now


async def replay_copy(row: dict, event, now) -> dict:
    from services.article_acquisition import acquire_article
    from services.instagram_evidence_package import build_daily_evidence_package
    from services.instagram_viral_nomination import viral_evidence_preflight

    ev, src = row["event"], row["source"]
    outcome = await acquire_article(ev["url"], event_id=UUID(ev["id"]))
    package = await build_daily_evidence_package(
        post_id=ev["id"], fmt="meme_trend", title=ev["title"] or "", url=ev["url"], source_type=src.get("type") or "RSS",
        source_name=src.get("name"), stored_body=ev.get("summary") or ev.get("content"), event=None, event_id=UUID(ev["id"]), session=None,
        acquisition_enabled=True, media_mode="off")
    body = [item.exact_text for item in (*package.steps, *package.facts, *package.limitations)]
    published = ev.get("published_at")
    from datetime import datetime
    preflight = viral_evidence_preflight(event, title=ev["title"] or "", body_lines=body,
                                         published_at=datetime.fromisoformat(published) if published else None, now=now)
    article = next((s for s in package.sources if s.source_type in ("ORIGINAL_ARTICLE", "LINKED_ARTICLE")), None)
    return {
        "title": ev["title"], "collected_at": ev.get("collected_at"), "original_url": ev["url"],
        "resolution_status": outcome.resolution_status, "resolution_method": outcome.resolution_method, "resolved_url": outcome.resolved_url,
        "publisher_domain": urlsplit(outcome.resolved_url).hostname if outcome.resolved_url else None,
        "resolution_metadata": outcome.resolution_metadata, "acquisition_status": outcome.status, "acquisition_error": outcome.error_code,
        "extracted_chars": outcome.extracted_char_count, "content_sha256": outcome.content_sha256,
        "evidence_source_url": article.url if article else None, "evidence_source_original_url": article.original_url if article else None,
        "package_quality": package.quality, "body_chars": sum(len(b) for b in body),
        "preflight": preflight.status, "checks": {k: v for k, v in preflight.checks.items() if v != "NOT_USED"}, "preflight_reason": preflight.reason,
    }


async def main_async(pool: str, members: str, rows_path: str, out: Path) -> dict:
    from services.article_acquisition import acquire_article
    from services.text_normalization import is_google_news_redirect_host

    event, now = nominated_event(pool, members)
    rows = [json.loads(line) for line in Path(rows_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    google = [r for r in rows if is_google_news_redirect_host(r["event"].get("url") or "")]
    results = [await replay_copy(r, event, now) for r in google]
    hn = next((r for r in rows if (r["source"].get("name") or "").lower().startswith("hacker news")), None)
    hn_diag = None
    if hn is not None:
        o = await acquire_article(hn["event"]["url"], event_id=UUID(hn["event"]["id"]))
        hn_diag = {"url": hn["event"]["url"], "status": o.status, "error_code": o.error_code, "chars": o.extracted_char_count}
    return {"provider_calls": 0, "image_calls": 0, "now": now.isoformat(), "event": event.key if event else None,
            "google_news_copies": len(google), "resolved": sum(1 for r in results if r["resolved_url"]),
            "usable_bodies": sum(1 for r in results if r["body_chars"] >= 400),
            "preflight_pass": sum(1 for r in results if r["preflight"] == "PASS"), "copies": results, "hacker_news_bbc": hn_diag}


def main() -> None:
    out = Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(main_async(sys.argv[1], sys.argv[2], sys.argv[3], out))
    (out / "google_news_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("event", "google_news_copies", "resolved", "usable_bodies", "preflight_pass", "hacker_news_bbc")},
                     ensure_ascii=False, indent=1))
    for r in report["copies"]:
        print(f"- {r['resolution_status'] or '-':<16} {r['publisher_domain'] or '-':<28} acq={r['acquisition_status']:<20} body={r['body_chars']:<5} "
              f"preflight={r['preflight']:<8} {r['checks']} | {r['title'][:60]}")


if __name__ == "__main__":
    main()
