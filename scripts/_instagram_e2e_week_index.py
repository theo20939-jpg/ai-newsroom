"""Chronological founder review of the KAGE E2E week run (zero-cost): index.html + one contact sheet per post.

Reads the run directory written by scripts/_instagram_e2e_week.py and changes nothing in it except adding `index.html` and
`<post>/contact_sheet.png`. Usage: python scripts/_instagram_e2e_week_index.py <run dir>
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from PIL import Image

DAYS = {"2026-08-05": "WED 5 AUG", "2026-08-06": "THU 6 AUG", "2026-08-07": "FRI 7 AUG", "2026-08-08": "SAT 8 AUG", "2026-08-09": "SUN 9 AUG",
        "2026-08-10": "MON 10 AUG", "2026-08-11": "TUE 11 AUG"}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def contact_sheet(post_dir: Path) -> Path | None:
    slides = sorted((post_dir / "slides").glob("slide_*.png")) if (post_dir / "slides").exists() else []
    if not slides:
        return None
    thumbs = []
    for s in slides:
        with Image.open(s) as im:
            im = im.convert("RGB")
            im.thumbnail((360, 450))
            thumbs.append(im.copy())
    w = sum(t.width for t in thumbs) + 12 * (len(thumbs) + 1)
    h = max(t.height for t in thumbs) + 24
    sheet = Image.new("RGB", (w, h), (11, 11, 13))
    x = 12
    for t in thumbs:
        sheet.paste(t, (x, 12))
        x += t.width + 12
    out = post_dir / "contact_sheet.png"
    sheet.save(out, optimize=True)
    return out


def slide_copy(package) -> list[str]:
    if not isinstance(package, dict):
        return []
    creative = package.get("creative") or {}
    slides = creative.get("slides") if isinstance(creative, dict) else None
    if not slides:
        for value in package.values():
            if isinstance(value, dict) and isinstance(value.get("slides"), list):
                slides = value["slides"]
                break
    out = []
    for s in slides or []:
        if isinstance(s, dict):
            head = s.get("slide_copy") or ""
            body = s.get("slide_body") or ""
            out.append(f"[{s.get('role', '')}] {head}" + (f" — {body}" if body else ""))
    return out


def main() -> None:
    run = Path(sys.argv[1])
    summary = _load(run / "run_summary.json") or {}
    cards = []
    for row in summary.get("posts", []):
        d = run / row["key"]
        sheet = contact_sheet(d)
        package = _load(d / "package.json")
        presentation = _load(d / "presentation.json") or {}
        copy = slide_copy(package)
        calls = row.get("calls", [])
        cost = sum(float(c.get("cost_usd") or 0) for c in calls)
        label = DAYS.get(row.get("day", ""), "WEEKLY RECAP")
        cards.append(f"""
<section class="post">
  <h2>{html.escape(label)} · {html.escape(row.get('format', ''))} · slot {row.get('slot', '-')}</h2>
  <p class="story">{html.escape(row.get('title', ''))}</p>
  <p class="meta">stage <b>{html.escape(str(row.get('stage')))}</b> · {html.escape(str(row.get('reason')))} · gate {html.escape(str(row.get('gate')))}
   · evidence {html.escape(str(row.get('evidence', '-')))} · source media {html.escape(str(row.get('source_media', '-')))}
   · slides {row.get('slides', 0)} · calls {len(calls)} · ${cost:.4f}</p>
  {f'<img src="{html.escape(sheet.relative_to(run).as_posix())}" alt="slides">' if sheet else '<p class="none">no render</p>'}
  <ol class="copy">{''.join(f'<li>{html.escape(c)}</li>' for c in copy)}</ol>
  <details><summary>caption / control text</summary><pre>{html.escape(presentation.get('control_text') or '')}</pre></details>
</section>""")
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>KAGE week review</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{{--bg:#0B0B0D;--card:#1A1A1D;--ink:#EDEDED;--mute:#8E8E93;--accent:#7F5FFF}}
body{{background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:22px}} .post{{background:var(--card);border-radius:12px;padding:16px;margin:0 0 20px}}
h2{{font-size:16px;color:var(--accent);margin:0 0 6px}} .story{{font-weight:600;margin:0 0 6px}} .meta{{color:var(--mute);font-size:13px}}
img{{max-width:100%;height:auto;display:block;margin:10px 0;border-radius:6px}} .copy{{font-size:14px}} pre{{white-space:pre-wrap;font-size:13px}}
.none{{color:#ff8a8a}}
</style></head><body>
<h1>KAGE Instagram — E2E week 5–11 Aug 2026 (first-pass, unrepaired)</h1>
<p class="meta">actual cost ${html.escape(str(summary.get('actual_cost_usd')))} · cap ${html.escape(str(summary.get('cap_usd')))} ·
provider calls {summary.get('provider_calls')} {html.escape(json.dumps(summary.get('calls_by_kind', {})))} · image generation {html.escape(str(summary.get('image_generation_mode')))}</p>
{''.join(cards)}
</body></html>"""
    (run / "index.html").write_text(page, encoding="utf-8")
    print(run / "index.html")


if __name__ == "__main__":
    main()
