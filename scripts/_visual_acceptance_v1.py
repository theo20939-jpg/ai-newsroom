"""NINJA PULSE Visual System v1 - offline visual acceptance pack.

Fully offline: no Telegram sends, no production workers, no VPS, no LLM/paid calls. Exercises
services/presentation_director.py + services/brand_renderer.py directly (the same pure functions
worker/content_cycle.py calls under presentation_director_mode="enforce"), against a curated set
of representative/synthetic cases covering NEWS/BREAKING/DATA/QUOTE, media shapes, failure
injection, and layout variation (spec §33).

Run: python scripts/_visual_acceptance_v1.py
Output: tmp/visual_acceptance_v1/ - one rendered preview per visual case, index.html contact
sheet, and a machine-readable report.json/report.csv.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from services.brand_renderer import render_branded_media  # noqa: E402
from services.presentation_director import (  # noqa: E402
    BREAKING,
    DATA,
    NEWS,
    QUOTE,
    build_editorial_code,
    decide_presentation,
)

OUT_DIR = Path("tmp/visual_acceptance_v1")


def _synthetic_photo(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@dataclass
class AcceptanceCase:
    case_id: str
    group: str
    title: str
    content: str | None = None
    treatment: str = "STANDARD"
    scoring_score: int | None = 78
    research_facts: list[str] | None = None
    quote_text: str | None = None
    quote_speaker: str | None = None
    source_photo: bytes | None = None
    expected_type: str | None = None  # None = "no specific expectation, just observe"


def _photo(shape: str) -> bytes | None:
    return {
        "landscape_light": _synthetic_photo(1600, 900, (210, 220, 230)),
        "landscape_dark": _synthetic_photo(1600, 900, (15, 18, 24)),
        "portrait": _synthetic_photo(900, 1600, (60, 90, 120)),
        "square": _synthetic_photo(1080, 1080, (90, 60, 40)),
        "none": None,
    }[shape]


def build_cases() -> list[AcceptanceCase]:
    cases: list[AcceptanceCase] = []

    # --- NEWS: representative product/tech stories across categories -----------------
    news_specs = [
        ("news_ai_model_launch", "OpenAI releases new reasoning model", "landscape_light"),
        ("news_chatgpt_feature", "Anthropic adds voice mode to Claude", "landscape_dark"),
        ("news_gadget", "Samsung unveils Galaxy S27", "portrait"),
        ("news_hardware", "Nvidia releases RTX 6090", "landscape_light"),
        ("news_software", "Microsoft launches new Copilot feature", "square"),
        ("news_security", "Apple releases iOS security update fixing actively exploited bug", "landscape_dark"),
        ("news_science_tech", "New chip fabrication process promises 30% efficiency gains, researchers say", "landscape_light"),
    ]
    for case_id, title, shape in news_specs:
        cases.append(AcceptanceCase(
            case_id=case_id, group="NEWS", title=title, treatment="STANDARD", scoring_score=78,
            source_photo=_photo(shape), expected_type=NEWS,
        ))

    # --- BREAKING ---------------------------------------------------------------------
    breaking_specs = [
        ("breaking_gpt_launch", "OpenAI unveils GPT-6, its most capable model yet",
         {"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"}),
        ("breaking_global_outage", "GitHub is down worldwide, engineers investigating",
         {"main_body": "GitHub outage affects millions.", "viral_potential": "HIGH"}),
        ("breaking_critical_exploit", "Critical vulnerability actively exploited in Microsoft Windows",
         {"main_body": "Microsoft warns of actively exploited critical vulnerability.", "viral_potential": "HIGH"}),
        ("breaking_landmark_ruling", "Meta faces landmark antitrust ruling that could force Instagram divestiture",
         {"main_body": "Meta faces landmark antitrust ruling.", "viral_potential": "HIGH"}),
    ]
    for case_id, title, copy_output in breaking_specs:
        cases.append(AcceptanceCase(
            case_id=case_id, group="BREAKING", title=title, treatment="MAJOR", scoring_score=95,
            source_photo=_photo("landscape_dark"), expected_type=BREAKING,
        ))
        cases[-1].content = None
        cases[-1]._copywriting_output = copy_output  # type: ignore[attr-defined]

    # --- DATA ---------------------------------------------------------------------------
    data_specs = [
        ("data_verified_integer", "ChatGPT reaches new milestone",
         "ChatGPT reached 500 million weekly users, OpenAI said.",
         ["ChatGPT reached 500 million weekly users in August 2026."]),
        ("data_verified_percentage", "Cloud provider reports major efficiency gain",
         "The company reported a 38% improvement in energy efficiency this quarter.",
         ["Internal benchmarks showed a 38% improvement in energy efficiency this quarter."]),
        ("data_verified_currency", "Startup closes major funding round",
         "The company raised $250 million in its latest funding round.",
         ["Company filings confirm a $250 million funding round this month."]),
        ("data_unverified_fallback_news", "ChatGPT reaches new milestone (unverified)",
         "ChatGPT reached 550 million weekly users, OpenAI said.",
         ["ChatGPT reached 500 million weekly users in August 2026."]),
    ]
    for case_id, title, main_body, facts in data_specs:
        expected = NEWS if "unverified" in case_id else DATA
        c = AcceptanceCase(
            case_id=case_id, group="DATA", title=title, treatment="STANDARD", scoring_score=80,
            research_facts=facts, source_photo=None, expected_type=expected,
        )
        c._copywriting_output = {"main_body": main_body}  # type: ignore[attr-defined]
        cases.append(c)

    # --- QUOTE ----------------------------------------------------------------------------
    quote_specs = [
        ("quote_verified_with_author", "OpenAI exec speaks out", "We are building a new interface.", "Jane Doe", QUOTE),
        ("quote_missing_attribution", "Someone speaks", "We are building a new interface.", None, NEWS),
        ("quote_paraphrase_like_invalid", "OpenAI exec speaks out (paraphrase)", None, None, NEWS),
    ]
    for case_id, title, quote_text, quote_speaker, expected in quote_specs:
        c = AcceptanceCase(
            case_id=case_id, group="QUOTE", title=title, treatment="STANDARD", scoring_score=78,
            quote_text=quote_text, quote_speaker=quote_speaker, source_photo=_photo("portrait"),
            expected_type=expected,
        )
        c._copywriting_output = {"main_body": "He shared his perspective on the matter."}  # type: ignore[attr-defined]
        cases.append(c)

    # --- MEDIA shapes (NEWS, varying media availability) -----------------------------------
    media_specs = [
        ("media_single_photo", "Google adds Gemini live translation to Android", "landscape_light"),
        ("media_text_only", "Company launches new developer tool", "none"),
    ]
    for case_id, title, shape in media_specs:
        cases.append(AcceptanceCase(
            case_id=case_id, group="MEDIA", title=title, treatment="STANDARD", scoring_score=76,
            source_photo=_photo(shape), expected_type=NEWS,
        ))
    # album/video are exercised structurally, not visually, in this offline pack - see report
    # §"known limitations" (worker/content_cycle.py's own album/video plumbing is unchanged by
    # this checkpoint and already covered by tests/test_router_media_integration.py).

    # --- FAILURE injection ------------------------------------------------------------------
    failure_specs = [
        ("failure_missing_logo", "Anthropic adds voice mode to Claude", "_missing_logo"),
        ("failure_invalid_media", "Anthropic adds voice mode to Claude", "_invalid_bytes"),
    ]
    for case_id, title, mode in failure_specs:
        cases.append(AcceptanceCase(
            case_id=case_id, group="FAILURE", title=title, treatment="STANDARD", scoring_score=78,
            source_photo=b"not-an-image" if mode == "_invalid_bytes" else _photo("landscape_light"),
            expected_type=NEWS,
        ))
        cases[-1]._failure_mode = mode  # type: ignore[attr-defined]

    # DATA/QUOTE evidence-mismatch failures (already covered above as data_unverified_fallback_
    # news / quote_missing_attribution / quote_paraphrase_like_invalid) - not duplicated here.

    # --- LAYOUT variation ---------------------------------------------------------------------
    layout_specs = [
        ("layout_short_headline", "GPT-6 launches", "landscape_light"),
        ("layout_long_headline",
         "OpenAI unveils GPT-6 with dramatically improved reasoning, multimodal understanding, and a new real-time voice interface built for developers",
         "landscape_light"),
        ("layout_ru_headline", "OpenAI выпустила новую модель", "landscape_dark"),
        ("layout_en_headline", "OpenAI releases new model", "landscape_dark"),
        ("layout_dark_image", "Nvidia releases RTX 6090", "landscape_dark"),
        ("layout_light_image", "Nvidia releases RTX 6090", "landscape_light"),
        ("layout_portrait_image", "Samsung unveils Galaxy S27", "portrait"),
        ("layout_landscape_image", "Samsung unveils Galaxy S27", "landscape_light"),
    ]
    for case_id, title, shape in layout_specs:
        cases.append(AcceptanceCase(
            case_id=case_id, group="LAYOUT", title=title, treatment="STANDARD", scoring_score=78,
            source_photo=_photo(shape), expected_type=NEWS,
        ))

    return cases


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    report_rows: list[dict] = []
    render_durations_ms: list[float] = []

    for case in cases:
        copywriting_output = getattr(case, "_copywriting_output", {"main_body": case.title})
        failure_mode = getattr(case, "_failure_mode", None)

        decision = decide_presentation(
            title=case.title, content=case.content, copywriting_output=copywriting_output,
            treatment=case.treatment, scoring_score=case.scoring_score,
            research_facts=case.research_facts, quote_text=case.quote_text, quote_speaker=case.quote_speaker,
            fallback_category=None,
        )

        editorial_code = build_editorial_code_stub(case.case_id)
        source_bytes = case.source_photo

        render_success = None
        render_fallback = None
        template_version = None
        preview_path = None

        needs_render = decision.presentation_type in (DATA, QUOTE, BREAKING) or source_bytes is not None
        if needs_render:
            import services.brand_renderer as brand_renderer_module
            original_path = brand_renderer_module._LOGO_PNG_PATH
            if failure_mode == "_missing_logo":
                brand_renderer_module._LOGO_PNG_PATH = Path("assets/brand/does_not_exist.png")
            try:
                started = time.monotonic()
                result = render_branded_media(
                    presentation_type=decision.presentation_type, source_image_bytes=source_bytes,
                    category=decision.category, editorial_code=editorial_code,
                    branding_strength=decision.branding_strength,
                    data_candidate=decision.data_candidate, quote_candidate=decision.quote_candidate,
                )
                render_durations_ms.append((time.monotonic() - started) * 1000)
            finally:
                brand_renderer_module._LOGO_PNG_PATH = original_path

            render_success = result.success
            render_fallback = result.fallback_reason
            template_version = result.template_version
            if result.success and result.image_bytes is not None:
                preview_path = OUT_DIR / f"{case.case_id}.jpg"
                preview_path.write_bytes(result.image_bytes)
            elif source_bytes and len(source_bytes) > 20:
                # Fail-safe demonstration: original media preserved when render fails.
                preview_path = OUT_DIR / f"{case.case_id}_original_fallback.jpg"
                try:
                    with Image.open(io.BytesIO(source_bytes)) as img:
                        img.convert("RGB").save(preview_path, format="JPEG")
                except Exception:
                    preview_path = None

        row = {
            "case_id": case.case_id, "group": case.group, "title": case.title,
            "presentation_type": decision.presentation_type, "category": decision.category,
            "expected_type": case.expected_type,
            "match_expected": decision.presentation_type == case.expected_type if case.expected_type else None,
            "branding_strength": decision.branding_strength, "caption_position": decision.caption_position,
            "major_impact_override": getattr(decision, "major_impact_override", None),
            "data_candidate": asdict(decision.data_candidate) if decision.data_candidate else None,
            "quote_candidate": asdict(decision.quote_candidate) if decision.quote_candidate else None,
            "reason": decision.reason,
            "source_media_shape": "photo" if source_bytes and len(source_bytes) > 20 else "none/invalid",
            "brand_render_attempted": needs_render,
            "brand_render_success": render_success,
            "brand_render_fallback_reason": render_fallback,
            "template_version": template_version,
            "preview_file": preview_path.name if preview_path else None,
        }
        report_rows.append(row)

    _write_report_json(report_rows)
    _write_report_csv(report_rows)
    _write_index_html(report_rows)
    _print_summary(report_rows, render_durations_ms)


def build_editorial_code_stub(case_id: str) -> str:
    from uuid import uuid5, NAMESPACE_URL
    return build_editorial_code(uuid5(NAMESPACE_URL, case_id))


def _write_report_json(rows: list[dict]) -> None:
    (OUT_DIR / "report.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_report_csv(rows: list[dict]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(OUT_DIR / "report.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in row.items()})


def _write_index_html(rows: list[dict]) -> None:
    cards = []
    for row in rows:
        img_tag = f'<img src="{row["preview_file"]}" loading="lazy">' if row["preview_file"] else '<div class="noimg">no preview</div>'
        match_note = ""
        if row["expected_type"]:
            ok = "OK" if row["match_expected"] else "MISMATCH"
            match_note = f'<div class="match {"ok" if row["match_expected"] else "bad"}">{ok}: expected {row["expected_type"]}</div>'
        cards.append(f"""
        <div class="card">
          {img_tag}
          <div class="meta">
            <b>{row['case_id']}</b> ({row['group']})<br>
            {row['title'][:70]}<br>
            type={row['presentation_type']} cat={row['category']} brand={row['branding_strength']}<br>
            render: attempted={row['brand_render_attempted']} success={row['brand_render_success']}<br>
            {match_note}
          </div>
        </div>""")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>NINJA PULSE Visual Acceptance v1</title>
<style>
body {{ font-family: sans-serif; background:#111; color:#eee; margin:0; padding:16px; }}
.grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap:16px; }}
.card {{ background:#1b1b1b; border-radius:8px; overflow:hidden; }}
.card img {{ width:100%; display:block; background:#000; }}
.noimg {{ padding:40px; text-align:center; color:#888; }}
.meta {{ padding:8px; font-size:12px; }}
.match.ok {{ color:#4caf50; }}
.match.bad {{ color:#f44336; font-weight:bold; }}
</style></head><body>
<h1>NINJA PULSE Visual Acceptance v1 - {len(rows)} cases</h1>
<div class="grid">{''.join(cards)}</div>
</body></html>"""
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")


def _print_summary(rows: list[dict], durations_ms: list[float]) -> None:
    from collections import Counter
    type_counts = Counter(r["presentation_type"] for r in rows)
    fallback_count = sum(1 for r in rows if r["brand_render_success"] is False)
    evidence_fail_count = sum(
        1 for r in rows if r["expected_type"] == NEWS and r["presentation_type"] == NEWS
        and r["group"] in ("DATA", "QUOTE")
    )
    mismatches = [r["case_id"] for r in rows if r["expected_type"] and not r["match_expected"]]

    print(f"Total cases: {len(rows)}")
    print(f"Type distribution: {dict(type_counts)}")
    print(f"Render fallback (brand_render_success=False) count: {fallback_count}")
    print(f"Evidence-guard fallback-to-NEWS count (DATA/QUOTE groups): {evidence_fail_count}")
    print(f"Expectation mismatches: {mismatches or 'none'}")
    if durations_ms:
        sorted_d = sorted(durations_ms)
        p50 = sorted_d[len(sorted_d)//2]
        p95 = sorted_d[min(len(sorted_d)-1, int(len(sorted_d)*0.95))]
        print(f"Render duration ms: P50={p50:.1f} P95={p95:.1f} max={max(sorted_d):.1f}")
    print(f"Output dir: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    run()
