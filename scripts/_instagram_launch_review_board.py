"""Founder review board for the KAGE Instagram launch canary: one HTML page + one combined contact sheet over the REAL run outputs
(slides in order, caption / package, gate, grounding, retries, cost). Nothing is re-rendered or edited here.
Usage: python scripts/_instagram_launch_review_board.py <canary dir>   (expects <dir>/daily/<post>/ and <dir>/recap/weekly_recap/)
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SECTIONS = (
    ("SINGLE", "daily/2026-08-05_2_meme_trend", "DeepSeek Telegram bot — 460 targets, zero autonomous breaches (Habr), planned TREND, natural routing"),
    ("CAROUSEL", "daily/2026-08-06_1_ai_hack", "Adobe tools inside ChatGPT (ZDNET + Adobe blog), planned AI_HACK, natural routing"),
    ("REEL", "daily/2026-08-10_2_meme_trend", "AI agent hacked a gym booking system (vc.ru), planned TREND, REEL offered as the only format (bounded canary)"),
    ("WEEKLY RECAP", "recap/weekly_recap", "the frozen 7-story week 5–11 Aug 2026 (weekly editor v2 picks)"),
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> None:
    root = Path(sys.argv[1])
    blocks, sheet_rows = [], []
    for name, rel, story in SECTIONS:
        d = root / rel
        outcome = _load(d / "outcome.json") or {}
        package = _load(d / "package.json") or {}
        presentation = _load(d / "presentation.json") or {}
        rejected = _load(d / "director_validation_error.json")
        slides = sorted((d / "slides").glob("slide_*.png")) if (d / "slides").exists() else []
        calls = outcome.get("calls") or []
        cost = sum(float(c.get("cost_usd") or 0) for c in calls)
        directors = sum(1 for c in calls if c["kind"] == "DIRECTOR")
        facts = [
            ("Story", story), ("Outcome", f"{outcome.get('stage')} — {outcome.get('reason')}"),
            ("Evidence", f"{outcome.get('evidence', '-')} {outcome.get('evidence_why', '') or ''}"),
            ("Art / editorial gate", f"{presentation.get('gate_decision', 'not reached')} — {presentation.get('gate_reason', '') or ''}"),
            ("Director retry", f"yes — attempt 1 rejected: {rejected['error'][:300]}" if rejected and directors > 1 else "no"),
            ("Provider calls / cost", f"{len(calls)} calls ({', '.join(sorted({c['kind'] for c in calls}))}) — ${cost:.4f}"),
        ]
        rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in facts)
        imgs = "".join(f'<a href="{html.escape(str(s.relative_to(root)).replace(chr(92), "/"))}"><img src="{html.escape(str(s.relative_to(root)).replace(chr(92), "/"))}" '
                       f'alt="{name} slide {i}"></a>' for i, s in enumerate(slides, 1)) or "<p class='none'>No rendered asset - the run stopped before the Creative Director (see Outcome).</p>"
        caption = package.get("caption") or ""
        blocks.append(f"<section><h2>{name}</h2><table>{rows}</table><div class='slides'>{imgs}</div>"
                      f"<h3>Caption</h3><pre>{html.escape(caption) or '—'}</pre></section>")
        if slides:
            sheet_rows.append((name, [Image.open(s).convert("RGB") for s in slides]))
    page = ("<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>KAGE launch canary</title><style>body{font:15px/1.45 system-ui,sans-serif;margin:24px;max-width:1400px;background:#fafafa;color:#111}"
            "section{background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px;margin:0 0 24px}table{border-collapse:collapse;margin:8px 0}"
            "th{text-align:left;padding:4px 12px 4px 0;vertical-align:top;white-space:nowrap}td{padding:4px 0}.slides{display:flex;flex-wrap:wrap;gap:10px}"
            ".slides img{width:216px;border:1px solid #ccc}pre{white-space:pre-wrap;background:#f3f3f3;padding:10px;border-radius:6px}"
            ".none{color:#a00;font-weight:600}@media (prefers-color-scheme:dark){body{background:#111;color:#eee}section{background:#1b1b1b;border-color:#333}"
            "pre{background:#222}}</style></head><body><h1>KAGE Instagram — final launch E2E canary</h1>"
            "<p>Real stories, live providers, image generation off. Slides are the actual rendered files (click for full resolution). "
            "Art gate PASS is not product acceptance.</p>" + "".join(blocks) + "</body></html>")
    (root / "review.html").write_text(page, encoding="utf-8")
    if sheet_rows:
        tw, th, label = 216, 270, 28
        width = max(len(ims) for _, ims in sheet_rows) * (tw + 8) + 16
        sheet = Image.new("RGB", (width, len(sheet_rows) * (th + label + 12) + 12), "white")
        draw = ImageDraw.Draw(sheet)
        y = 8
        for name, ims in sheet_rows:
            draw.text((10, y + 6), name, fill="black")
            for i, im in enumerate(ims):
                sheet.paste(im.resize((tw, th)), (8 + i * (tw + 8), y + label))
            y += th + label + 12
        sheet.save(root / "contact_sheet.png")
    print(root / "review.html")


if __name__ == "__main__":
    main()
