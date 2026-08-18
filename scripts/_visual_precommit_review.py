"""NINJA PULSE Visual System v1 - pre-commit production-readiness correction.

Fully offline: no Telegram sends, no production workers, no VPS, no LLM/paid calls, no network.
Generates:
  1. A small human visual review pack (spec item 8): 3 NEWS w/ photo, 2 BREAKING, 2 DATA,
     2 QUOTE, 1 NEWS without usable media - at least half containing Cyrillic text.
  2. NEWS branding-strength comparison previews (spec item 4) - MINIMAL vs EDITORIAL on the
     identical source photo, so a human can directly judge how strong the (always red-badged,
     see services/brand_renderer.py's own module docstring) NNJ mark looks on ordinary NEWS.
  3. A real render-performance benchmark (spec item 7) across >=30 iterations spanning all four
     presentation types - actual measured wall-clock durations, not a claim by construction.

Run: python scripts/_visual_precommit_review.py
Output: tmp/visual_precommit_review/ - rendered JPEGs, index.html, report.json.
"""
from __future__ import annotations

import io
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from services.brand_renderer import render_branded_media  # noqa: E402
from services.presentation_director import (  # noqa: E402
    BREAKING,
    DATA,
    NEWS,
    QUOTE,
    DataCandidate,
    QuoteCandidate,
    build_editorial_code,
)

OUT_DIR = Path("tmp/visual_precommit_review")


def _synthetic_photo(width: int, height: int, color: tuple[int, int, int], *, noise: bool = True) -> bytes:
    """A slightly-textured synthetic "photo" (not a flat single color) - closer to what a real
    downloaded article image looks like for judging how the brand mark reads over real content,
    without downloading anything or depending on network/fixture files."""
    img = Image.new("RGB", (width, height), color)
    if noise:
        px = img.load()
        for y in range(0, height, 7):
            for x in range(0, width, 11):
                shade = 20 if (x // 50 + y // 50) % 2 == 0 else -20
                r, g, b = color
                px[x, y] = (max(0, min(255, r + shade)), max(0, min(255, g + shade)), max(0, min(255, b + shade)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _code(case_id: str) -> str:
    return build_editorial_code(uuid5(NAMESPACE_URL, case_id))


def _save(case_id: str, image_bytes: bytes) -> str:
    filename = f"{case_id}.jpg"
    (OUT_DIR / filename).write_bytes(image_bytes)
    return filename


def build_review_pack(durations_ms: list[float]) -> list[dict]:
    rows: list[dict] = []

    # --- 3 NEWS with real-looking source-photo backgrounds (2 RU, 1 EN - Cyrillic-majority) ---
    news_cases = [
        ("review_news_1_en", "Google adds Gemini live translation to Android", "AI",
         _synthetic_photo(1600, 900, (60, 110, 160))),
        ("review_news_2_ru", "Anthropic добавила голосовой режим в Claude", "AI",
         _synthetic_photo(1600, 900, (20, 22, 26))),
        ("review_news_3_ru", "Nvidia выпустила видеокарту RTX 6090", "TECH",
         _synthetic_photo(1080, 1350, (140, 90, 40))),
    ]
    for case_id, title, category, photo in news_cases:
        started = time.monotonic()
        result = render_branded_media(
            presentation_type=NEWS, source_image_bytes=photo, category=category,
            editorial_code=_code(case_id), branding_strength="MINIMAL",
        )
        durations_ms.append((time.monotonic() - started) * 1000)
        rows.append({
            "case_id": case_id, "group": "NEWS", "title": title, "presentation_type": NEWS,
            "template_version": result.template_version, "render_success": result.success,
            "preview_file": _save(case_id, result.image_bytes) if result.image_bytes else None,
        })

    # --- 1 NEWS without usable media (RU) ---
    case_id = "review_news_4_no_media_ru"
    title = "Google запустила новый API для разработчиков"
    rows.append({
        "case_id": case_id, "group": "NEWS", "title": title, "presentation_type": NEWS,
        "template_version": None, "render_success": None,
        "preview_file": None,  # no source photo, no DATA/QUOTE grounding - real production
        # behavior here is a text-only send (see brand_renderer.py's own render_branded_media():
        # NEWS with source_image_bytes=None raises ValueError "no source image available to
        # brand", caught by the fail-safe boundary - never rendered, never blocks delivery).
        "note": "no source media - production path sends plain text, brand renderer is never invoked",
    })

    # --- 2 BREAKING (1 RU, 1 EN) ---
    breaking_cases = [
        ("review_breaking_1_ru", "OpenAI представила GPT-6 — самую мощную модель на сегодня", "AI"),
        ("review_breaking_2_en", "GitHub is down worldwide, engineers investigating", "SOFTWARE"),
    ]
    for case_id, title, category in breaking_cases:
        photo = _synthetic_photo(1600, 900, (18, 18, 22))
        started = time.monotonic()
        result = render_branded_media(
            presentation_type=BREAKING, source_image_bytes=photo, category=category,
            editorial_code=_code(case_id), branding_strength="STRONG",
        )
        durations_ms.append((time.monotonic() - started) * 1000)
        rows.append({
            "case_id": case_id, "group": "BREAKING", "title": title, "presentation_type": BREAKING,
            "template_version": result.template_version, "render_success": result.success,
            "preview_file": _save(case_id, result.image_bytes) if result.image_bytes else None,
        })

    # --- 2 DATA (1 RU, 1 EN) - grounded, deterministic values -----------------------------
    data_cases = [
        ("review_data_1_ru", "ChatGPT достиг нового рубежа",
         DataCandidate(value="500", unit="млн", label="пользователей в неделю",
                        evidence_fact="ChatGPT достиг 500 млн пользователей в неделю в августе 2026 года.")),
        ("review_data_2_en", "Cloud provider reports major efficiency gain",
         DataCandidate(value="38", unit="%", label="improvement in energy efficiency this quarter",
                        evidence_fact="Internal benchmarks showed a 38% improvement in energy efficiency.")),
    ]
    for case_id, title, candidate in data_cases:
        started = time.monotonic()
        result = render_branded_media(
            presentation_type=DATA, source_image_bytes=None, category="AI",
            editorial_code=_code(case_id), data_candidate=candidate,
        )
        durations_ms.append((time.monotonic() - started) * 1000)
        rows.append({
            "case_id": case_id, "group": "DATA", "title": title, "presentation_type": DATA,
            "data_candidate": asdict(candidate),
            "template_version": result.template_version, "render_success": result.success,
            "preview_file": _save(case_id, result.image_bytes) if result.image_bytes else None,
        })

    # --- 2 QUOTE (1 RU, 1 EN) ---------------------------------------------------------------
    quote_cases = [
        ("review_quote_1_ru", "Представитель OpenAI высказался",
         QuoteCandidate(text="Мы создаём новый интерфейс.", speaker="Джейн Доу")),
        ("review_quote_2_en", "OpenAI exec speaks out",
         QuoteCandidate(text="We are building a new interface.", speaker="Jane Doe")),
    ]
    for case_id, title, candidate in quote_cases:
        portrait = _synthetic_photo(900, 1200, (40, 50, 70))
        started = time.monotonic()
        result = render_branded_media(
            presentation_type=QUOTE, source_image_bytes=portrait, category="AI",
            editorial_code=_code(case_id), quote_candidate=candidate,
        )
        durations_ms.append((time.monotonic() - started) * 1000)
        rows.append({
            "case_id": case_id, "group": "QUOTE", "title": title, "presentation_type": QUOTE,
            "quote_candidate": asdict(candidate),
            "template_version": result.template_version, "render_success": result.success,
            "preview_file": _save(case_id, result.image_bytes) if result.image_bytes else None,
        })

    return rows


def build_branding_comparison(durations_ms: list[float]) -> list[dict]:
    """Spec item 4's explicit instruction: "If NEWS currently uses a visually heavy red badge, DO
    NOT redesign it in this checkpoint. Instead generate comparison previews so the human can
    judge it." Same source photo, same title, MINIMAL vs EDITORIAL branding_strength side by
    side - the only two variants NEWS actually uses in production (`STRONG` is never assigned to
    NEWS by decide_presentation() - see services/presentation_director.py's own
    `_BRANDING_BY_TREATMENT` mapping - only BREAKING ever gets STRONG)."""
    rows: list[dict] = []
    photo = _synthetic_photo(1600, 900, (70, 100, 130))
    title = "Nvidia releases RTX 6090"
    for strength in ("MINIMAL", "EDITORIAL"):
        case_id = f"compare_news_branding_{strength.lower()}"
        started = time.monotonic()
        result = render_branded_media(
            presentation_type=NEWS, source_image_bytes=photo, category="TECH",
            editorial_code=_code(case_id), branding_strength=strength,
        )
        durations_ms.append((time.monotonic() - started) * 1000)
        rows.append({
            "case_id": case_id, "group": "COMPARE", "title": title, "presentation_type": NEWS,
            "branding_strength": strength, "template_version": result.template_version,
            "render_success": result.success,
            "preview_file": _save(case_id, result.image_bytes) if result.image_bytes else None,
        })
    return rows


def run_extra_benchmark_iterations(durations_ms: list[float]) -> None:
    """The review pack above already renders 9 real images (1 NEWS has no media, so 6 NEWS/
    BREAKING/QUOTE + 2 DATA + 2 comparison = 11 real renders). Pad to >=30 total measured
    iterations, still covering all four presentation types, using deterministic synthetic inputs
    - no network, no LLM, purely repeated calls to the same real render_branded_media()."""
    photo = _synthetic_photo(1600, 900, (90, 90, 90))
    portrait = _synthetic_photo(900, 1200, (50, 60, 80))
    data_candidate = DataCandidate(value="500", unit="million", label="weekly users", evidence_fact="fact")
    quote_candidate = QuoteCandidate(text="We are building a new interface.", speaker="Jane Doe")

    plan = (
        [("NEWS", photo, None, None)] * 6
        + [("BREAKING", photo, None, None)] * 5
        + [("DATA", None, data_candidate, None)] * 5
        + [("QUOTE", portrait, None, quote_candidate)] * 5
    )
    for i, (ptype, source, dcand, qcand) in enumerate(plan):
        started = time.monotonic()
        render_branded_media(
            presentation_type=ptype, source_image_bytes=source, category="AI",
            editorial_code=f"NP-{i:04d}", data_candidate=dcand, quote_candidate=qcand,
        )
        durations_ms.append((time.monotonic() - started) * 1000)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(round((len(sorted_values) - 1) * pct)))
    return sorted_values[idx]


def _write_index_html(pack_rows: list[dict], compare_rows: list[dict]) -> None:
    def card(row: dict) -> str:
        img = f'<img src="{row["preview_file"]}" loading="lazy">' if row.get("preview_file") else '<div class="noimg">no preview (see note)</div>'
        note = row.get("note", "")
        return f"""<div class="card"><b>{row['case_id']}</b> ({row['group']})<br>{img}
        <div class="meta">{row['title'][:80]}<br>type={row['presentation_type']} tmpl={row.get('template_version')}<br>{note}</div></div>"""

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>NINJA PULSE Pre-Commit Visual Review</title>
<style>
body {{ font-family: sans-serif; background:#111; color:#eee; margin:0; padding:16px; }}
h2 {{ margin-top:32px; }}
.grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(300px,1fr)); gap:16px; }}
.card {{ background:#1b1b1b; border-radius:8px; overflow:hidden; padding-bottom:8px; }}
.card img {{ width:100%; display:block; background:#000; }}
.noimg {{ padding:40px; text-align:center; color:#888; }}
.meta {{ padding:8px; font-size:12px; }}
</style></head><body>
<h1>NINJA PULSE Visual System v1 - Pre-Commit Human Review Pack</h1>
<h2>Review pack (10 cases: 3 NEWS+photo, 1 NEWS no-media, 2 BREAKING, 2 DATA, 2 QUOTE)</h2>
<div class="grid">{''.join(card(r) for r in pack_rows)}</div>
<h2>NEWS branding-strength comparison (MINIMAL vs EDITORIAL, same source photo)</h2>
<div class="grid">{''.join(card(r) for r in compare_rows)}</div>
</body></html>"""
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    durations_ms: list[float] = []

    pack_rows = build_review_pack(durations_ms)
    compare_rows = build_branding_comparison(durations_ms)
    run_extra_benchmark_iterations(durations_ms)

    cyrillic_count = sum(
        1 for r in pack_rows
        if any("Ѐ" <= ch <= "ӿ" for ch in r["title"])
        or any("Ѐ" <= ch <= "ӿ" for ch in json.dumps(r.get("data_candidate") or r.get("quote_candidate") or {}, ensure_ascii=False))
    )

    report = {
        "review_pack": pack_rows,
        "branding_comparison": compare_rows,
        "cyrillic_case_count_of_10": cyrillic_count,
        "benchmark": {
            "count": len(durations_ms),
            "min_ms": round(min(durations_ms), 2),
            "p50_ms": round(_percentile(sorted(durations_ms), 0.50), 2),
            "p95_ms": round(_percentile(sorted(durations_ms), 0.95), 2),
            "max_ms": round(max(durations_ms), 2),
        },
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_index_html(pack_rows, compare_rows)

    print(f"Review pack cases: {len(pack_rows)} (Cyrillic in {cyrillic_count}/10)")
    print(f"Comparison cases: {len(compare_rows)}")
    print(f"Benchmark: {report['benchmark']}")
    print(f"Output dir: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    run()
