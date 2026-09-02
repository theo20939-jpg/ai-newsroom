"""PRESENTATION RECOVERY (2026-09-02): deterministic, offline visual acceptance harness.

Generates representative preview JPEGs for NEWS/BREAKING/DATA/QUOTE/RECAP using the real
production renderers (never a mock/stub renderer) against synthetic local fixtures - no network,
no LLM, no Telegram. Manual reviewer aid only, mirroring the established `assets/brand/
newsroom_visuals/<case>/` precedent (e.g. v2_2_bakeoff_live/manifest.json) - not wired into CI,
not a pytest suite, run manually:

    python -m scripts.presentation_recovery_visual_acceptance

Output: assets/brand/newsroom_visuals/v_presentation_recovery/<type>/*.jpg plus one manifest.json
per case recording the exact synthetic input used, for reproducibility.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from services.brand_renderer import build_recap_fallback_background, render_breaking_frame, render_data_card, render_quote_card
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import DataCandidate, QuoteCandidate

OUT_DIR = Path("assets/brand/newsroom_visuals/v_presentation_recovery")


def _synthetic_photo(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _save(subdir: str, filename: str, image_bytes: bytes) -> Path:
    directory = OUT_DIR / subdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(image_bytes)
    return path


def _manifest(subdir: str, entries: dict) -> None:
    directory = OUT_DIR / subdir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_news() -> None:
    light = _synthetic_photo(1600, 900, (235, 235, 235))
    dark = _synthetic_photo(1600, 900, (15, 15, 15))
    light_branded, light_decision = apply_master_news_branding(light)
    dark_branded, dark_decision = apply_master_news_branding(dark)
    _save("news", "01_light_background.jpg", light_branded)
    _save("news", "02_dark_background.jpg", dark_branded)
    _manifest("news", {
        "light_background_source": {"color": [235, 235, 235], "size": [1600, 900]},
        "light_upper_mark_red": light_decision.upper_mark.image is not None,
        "dark_background_source": {"color": [15, 15, 15], "size": [1600, 900]},
        "dark_upper_mark_red": dark_decision.upper_mark.image is not None,
    })


def generate_breaking() -> None:
    photo = _synthetic_photo(1600, 900, (60, 60, 90))
    out = render_breaking_frame(photo, category="AI", editorial_code="NP-VIS1")
    _save("breaking", "01_breaking.jpg", out)
    _manifest("breaking", {"source": {"color": [60, 60, 90], "size": [1600, 900]}, "category": "AI"})


def generate_data() -> None:
    photo = _synthetic_photo(1600, 900, (20, 20, 20))
    simple = DataCandidate(value="35", unit="%", label="quarterly profit growth", evidence_fact="Profits grew 35% this quarter.")
    long_label = DataCandidate(
        value="14,500,000", unit="", label="monthly active developers building on the platform worldwide across every region",
        evidence_fact="14,500,000 monthly active developers worldwide.",
    )
    difficult = DataCandidate(value="-8.1", unit="%", label="revenue decline", evidence_fact="Revenue fell 8.1% this quarter.")
    for name, candidate in (("01_simple", simple), ("02_long_label", long_label), ("03_difficult_negative", difficult)):
        out = render_data_card(candidate, category="AI", editorial_code="NP-VIS2", source_image_bytes=photo)
        _save("data", f"{name}.jpg", out)
    _manifest("data", {
        "source": {"color": [20, 20, 20], "size": [1600, 900]},
        "simple": {"value": simple.value, "unit": simple.unit, "label": simple.label},
        "long_label": {"value": long_label.value, "unit": long_label.unit, "label": long_label.label},
        "difficult_negative": {"value": difficult.value, "unit": difficult.unit, "label": difficult.label},
    })


def generate_quote() -> None:
    candidate = QuoteCandidate(text="We are building the next generation of the platform.", speaker="Jane Doe, CTO")
    out = render_quote_card(candidate, category="AI", editorial_code="NP-VIS3")
    _save("quote", "01_quote.jpg", out)
    _manifest("quote", {"text": candidate.text, "speaker": candidate.speaker})


def generate_recap() -> None:
    """RECAP: the unbranded Tier 3 background (candidate/research stage) alongside the same
    background AFTER apply_master_news_branding() (Final Post Review preview / real publication
    stage) - proving both stages share one visual identity, only the branding timing differs."""
    unbranded = build_recap_fallback_background("Google Pixel 11 Pro Fold launch", category="TECH")
    assert unbranded.success and unbranded.image_bytes is not None
    _save("recap", "01_unbranded_candidate_stage.jpg", unbranded.image_bytes)
    branded, decision = apply_master_news_branding(unbranded.image_bytes)
    _save("recap", "02_branded_review_and_publish_stage.jpg", branded)
    _manifest("recap", {
        "subject": "Google Pixel 11 Pro Fold launch", "category": "TECH",
        "branded_upper_mark_present": decision.upper_mark.image is not None,
    })


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_news()
    generate_breaking()
    generate_data()
    generate_quote()
    generate_recap()
    print(f"Visual acceptance artifacts written under {OUT_DIR}")


if __name__ == "__main__":
    main()
