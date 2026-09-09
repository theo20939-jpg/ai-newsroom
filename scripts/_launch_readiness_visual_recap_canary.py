"""LAUNCH-READINESS-VISUAL-RECAP-PARALLEL-1 - LOCAL visual canary (no Telegram send, no DB writes).

Renders the four Founder-board Telegram formats (NEWS / BREAKING / DATA / QUOTE) through their
REAL production code paths, plus the RECAP fallback background, on bounded fixtures; derives the
renderer-truthful RenderEvidence; runs the shadow Art Director + Design-Spec merge against the
ACTIVE specs read read-only from the dev control-plane DB; asserts the launch invariants; and
writes every render + a JSON record + a single contact sheet under artifacts/visual_recap_canary/.

Run:  python scripts/_launch_readiness_visual_recap_canary.py
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

OUT = Path("artifacts/visual_recap_canary")
OUT.mkdir(parents=True, exist_ok=True)

_BAKE = Path("assets/brand/newsroom_visuals/v2_1_bakeoff_sources")
_INFOGRAPHIC = Path(
    "assets/brand/newsroom_visuals/v1/references/data/data_template_white.png"
)


def _jpeg(img: Image.Image, q: int = 92) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, format="JPEG", quality=q)
    return b.getvalue()


def _synth_dark_photo() -> bytes:
    im = Image.new("RGB", (1600, 900), (14, 16, 20))
    d = ImageDraw.Draw(im)
    for y in range(900):
        d.line([(0, y), (1600, y)], fill=(10 + y // 40, 12 + y // 45, 18 + y // 30))
    d.ellipse([560, 250, 1040, 700], fill=(60, 70, 90))
    d.ellipse([690, 360, 780, 450], fill=(120, 170, 240))
    return _jpeg(im)


def _synth_light_photo() -> bytes:
    im = Image.new("RGB", (1600, 900), (238, 240, 244))
    d = ImageDraw.Draw(im)
    d.ellipse([520, 210, 1080, 720], fill=(210, 214, 222))
    d.rectangle([120, 120, 360, 360], fill=(190, 196, 206))
    return _jpeg(im)


def _synth_portrait(light: bool) -> bytes:
    bg = (232, 232, 236) if light else (18, 18, 22)
    skin = (208, 170, 150) if light else (150, 120, 108)
    im = Image.new("RGB", (900, 1200), bg)
    d = ImageDraw.Draw(im)
    d.ellipse([300, 240, 620, 620], fill=skin)  # head
    d.rectangle([250, 600, 680, 1200], fill=(70, 74, 84))  # shoulders
    return _jpeg(im)


def _synth_infographic_with_number() -> bytes:
    """A raw generated 'infographic' carrying its OWN printed metric - the destroy-test fixture."""
    im = Image.new("RGB", (1600, 900), (12, 12, 14))
    d = ImageDraw.Draw(im)
    d.text((120, 120), "MONTHLY ACTIVE USERS", fill=(235, 235, 235))
    d.text((120, 220), "500M", fill=(237, 28, 36))
    for i in range(40):
        d.line(
            [
                (120 + i * 34, 780 - (i * i) % 260),
                (154 + i * 34, 780 - ((i + 1) ** 2) % 260),
            ],
            fill=(237, 28, 36),
            width=4,
        )
    return _jpeg(im)


def _dc(value: str, unit: str, label: str):
    from services.presentation_director import DataCandidate

    return DataCandidate(
        value=value, unit=unit, label=label, evidence_fact=f"{value} {unit} - {label}"
    )


def _qc(text: str, speaker: str):
    from services.presentation_director import QuoteCandidate

    return QuoteCandidate(text=text, speaker=speaker)


def _serialise(obj):
    if is_dataclass(obj):
        return {k: _serialise(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_serialise(v) for v in obj]
    if hasattr(obj, "value") and type(obj).__mro__[1].__name__ == "Enum":
        return obj.value
    if repr(obj) == "NOT_MEASURED":
        return "NOT_MEASURED"
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


async def _load_active_specs():
    from core.config import settings
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from database.models.design_spec_version import DesignSpecStatus, DesignSpecVersion

    engine = create_async_engine(settings.database_url)
    specs: dict[str, DesignSpecVersion] = {}
    try:
        async with AsyncSession(engine) as session:
            rows = (
                (
                    await session.execute(
                        select(DesignSpecVersion).where(
                            DesignSpecVersion.status == DesignSpecStatus.ACTIVE
                        )
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                specs[r.scope] = r
            session.expunge_all()
    finally:
        await engine.dispose()
    return specs


def _art(
    base_result,
    *,
    active_spec,
    render_evidence,
    source_type=None,
    presentation_mode=None,
):
    from services.telegram_art_director_spec_evaluation import (
        SpecEvaluationInput,
        evaluate_against_spec_and_references,
        merge_spec_evaluation_into_result,
    )

    spec_result = evaluate_against_spec_and_references(
        SpecEvaluationInput(
            base_result=base_result,
            active_spec=active_spec,
            render_evidence=render_evidence,
            source_type=source_type,
            presentation_mode=presentation_mode,
        )
    )
    merged = merge_spec_evaluation_into_result(base_result, spec_result)
    return spec_result, merged


def _pixel_input(rendered: bytes, caption: str, ptype: str, rv: str, meta: dict):
    from services.telegram_art_director import (
        PixelInputContract,
        evaluate_art_direction_shadow,
    )

    pi = PixelInputContract(
        rendered_bytes=rendered,
        caption=caption,
        presentation_type=ptype,
        renderer_version=rv,
        renderer_decision_metadata=meta,
    )
    return evaluate_art_direction_shadow(pi)


async def main() -> int:
    from services.brand_renderer import (
        render_breaking_frame,
        render_data_card,
        render_quote_card,
        build_recap_fallback_background,
    )
    from services.nnj_master_news_overlay import apply_master_news_branding
    from services.data_source_classification import DataPresentationMode, SourceType
    from services.render_evidence import (
        derive_breaking_render_evidence,
        derive_data_render_evidence,
        derive_master_news_render_evidence,
        derive_quote_render_evidence,
    )

    specs = await _load_active_specs()
    print("ACTIVE specs:", {k: f"v{v.version}" for k, v in specs.items()})

    dark = _synth_dark_photo()
    light = _synth_light_photo()
    dramatic = _BAKE.joinpath("case1_hero_product_iphone.jpg").read_bytes()
    bright_real = _BAKE.joinpath("case3_bright_promotional_scene.jpg").read_bytes()
    infographic = _INFOGRAPHIC.read_bytes()
    infographic_num = _synth_infographic_with_number()
    portrait_light = _synth_portrait(light=True)
    portrait_dark = _synth_portrait(light=False)

    records: list[dict] = []
    failures: list[str] = []

    def _md_from_decision(dec) -> dict:
        return {
            "upper_mark": {"placement": dec.upper_mark.placement.value},
            "lower_signature": {"placement": dec.lower_signature.placement.value},
            "degradation_mode": dec.degradation_mode,
        }

    # ---- NEWS (live path = apply_master_news_branding) --------------------------------------
    for name, src in [("news_01_dark_photo", dark), ("news_02_light_photo", light)]:
        branded, dec = apply_master_news_branding(src)
        branded_bytes = (
            branded if isinstance(branded, (bytes, bytearray)) else _png(branded)
        )
        (OUT / f"{name}.png").write_bytes(_png_from_jpeg(branded_bytes))
        ev = derive_master_news_render_evidence(src, presentation_type="NEWS")
        base = _pixel_input(
            branded_bytes,
            "OpenAI представила новое устройство",
            "NEWS",
            "master_news_v1",
            _md_from_decision(dec),
        )
        spec_result, merged = _art(
            base, active_spec=specs.get("telegram_news"), render_evidence=ev
        )
        rec = _record(
            name, "NEWS", ev, spec_result, merged, dec_meta=_md_from_decision(dec)
        )
        records.append(rec)
        if rec["logo_count"] not in (0, 1):
            failures.append(f"{name}: logo_count={rec['logo_count']} (expected 0/1)")
        if rec["merged_decision"] == "block":
            failures.append(
                f"{name}: Art Director BLOCK on an accepted NEWS render - {rec['hard_failures']}"
            )

    # ---- BREAKING (live path = render_breaking_frame) -------------------------------------
    for name, src in [
        ("breaking_03_dark_dramatic", dramatic),
        ("breaking_04_light_photo", light),
    ]:
        out = render_breaking_frame(src, category="AI", editorial_code="NP-0002")
        (OUT / f"{name}.png").write_bytes(_png_from_jpeg(out))
        ev = derive_breaking_render_evidence(src)
        base = _pixel_input(
            out, "Apple готовит новый iPhone", "BREAKING", "pulse-breaking-v2", {}
        )
        spec_result, merged = _art(
            base, active_spec=specs.get("telegram_breaking"), render_evidence=ev
        )
        rec = _record(name, "BREAKING", ev, spec_result, merged)
        records.append(rec)
        if rec["scrim_treatment"] not in ("none", "NOT_MEASURED"):
            failures.append(
                f"{name}: BREAKING scrim_treatment={rec['scrim_treatment']} (band must be retired)"
            )
        if rec["merged_decision"] == "block":
            failures.append(
                f"{name}: Art Director BLOCK on an accepted BREAKING render - {rec['hard_failures']}"
            )

    # ---- DATA (A) existing infographic -> MINIMAL_SOURCE_PRESERVING --------------------------
    # Real infographic reference (carries its own printed axis/label content).
    dc = _dc("500", "млн", "активных пользователей за 3 месяца")
    out = render_data_card(
        dc,
        category="DATA",
        editorial_code="NP-0186",
        source_image_bytes=infographic,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    (OUT / "data_05_existing_infographic.png").write_bytes(_png_from_jpeg(out))
    ev = derive_data_render_evidence(
        infographic,
        dc,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    base = _pixel_input(
        out, "ChatGPT достиг 500 млн пользователей", "DATA", "pulse-data-v1", {}
    )
    spec_result, merged = _art(
        base,
        active_spec=specs.get("telegram_data"),
        render_evidence=ev,
        source_type=SourceType.EXISTING_INFOGRAPHIC,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    rec = _record("data_05_existing_infographic", "DATA", ev, spec_result, merged)
    records.append(rec)
    if rec["actual_line_count"] not in (0, "NOT_MEASURED"):
        failures.append(
            f"data_05: MINIMAL_SOURCE_PRESERVING drew a stat block (line_count={rec['actual_line_count']}) - number-preserve violated"
        )
    if rec["merged_decision"] == "block":
        failures.append(
            f"data_05: Art Director BLOCK on source-preserving infographic render - {rec['hard_failures']}"
        )

    # ---- DATA (A') the DESTROY test: infographic wrongly rendered FULL_DATA_CARD -> must BLOCK
    out_bad = render_data_card(
        dc,
        category="DATA",
        editorial_code="NP-0186",
        source_image_bytes=infographic_num,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    (OUT / "data_05b_infographic_full_card_DESTROY_TEST.png").write_bytes(
        _png_from_jpeg(out_bad)
    )
    ev_bad = derive_data_render_evidence(
        infographic_num, dc, presentation_mode=DataPresentationMode.FULL_DATA_CARD
    )
    base_bad = _pixel_input(
        out_bad, "ChatGPT достиг 500 млн", "DATA", "pulse-data-v1", {}
    )
    spec_bad, merged_bad = _art(
        base_bad,
        active_spec=specs.get("telegram_data"),
        render_evidence=ev_bad,
        source_type=SourceType.EXISTING_INFOGRAPHIC,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    rec_bad = _record(
        "data_05b_infographic_full_card_DESTROY_TEST",
        "DATA",
        ev_bad,
        spec_bad,
        merged_bad,
    )
    records.append(rec_bad)
    if rec_bad["merged_decision"] != "block":
        failures.append(
            f"data_05b DESTROY TEST: infographic + FULL_DATA_CARD did NOT BLOCK (got {rec_bad['merged_decision']}) - INFOGRAPHIC_DESTROYED guard failed"
        )

    # ---- DATA (B) normal photo -> FULL_DATA_CARD -----------------------------------------
    dc2 = _dc("+38", "%", "рост за 3 месяца")
    out = render_data_card(
        dc2,
        category="DATA",
        editorial_code="NP-0186",
        source_image_bytes=bright_real,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    (OUT / "data_06_generated_card.png").write_bytes(_png_from_jpeg(out))
    ev = derive_data_render_evidence(
        bright_real, dc2, presentation_mode=DataPresentationMode.FULL_DATA_CARD
    )
    base = _pixel_input(
        out, "Рост составил 38% за квартал", "DATA", "pulse-data-v1", {}
    )
    spec_result, merged = _art(
        base,
        active_spec=specs.get("telegram_data"),
        render_evidence=ev,
        source_type=SourceType.PHOTO,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    rec = _record("data_06_generated_card", "DATA", ev, spec_result, merged)
    records.append(rec)
    if rec["merged_decision"] == "block":
        failures.append(
            f"data_06: Art Director BLOCK on an accepted generated DATA card - {rec['hard_failures']}"
        )

    # ---- QUOTE -----------------------------------------------------------------------------
    qc = _qc(
        "ИИ не заменит программистов. Но программисты, использующие ИИ, заменят тех, кто его не использует.",
        "Дженсен Хуанг",
    )
    for name, portrait in [
        ("quote_07_light_portrait", portrait_light),
        ("quote_08_dark_portrait", portrait_dark),
    ]:
        out = render_quote_card(
            qc, category="QUOTE", editorial_code="NP-0187", portrait_bytes=portrait
        )
        (OUT / f"{name}.png").write_bytes(_png_from_jpeg(out))
        ev = derive_quote_render_evidence(portrait)
        base = _pixel_input(out, qc.text, "QUOTE", "pulse-quote-v1", {})
        spec_result, merged = _art(
            base, active_spec=specs.get("telegram_quote"), render_evidence=ev
        )
        rec = _record(name, "QUOTE", ev, spec_result, merged)
        records.append(rec)
        if rec["logo_count"] != 1:
            failures.append(
                f"{name}: QUOTE logo_count={rec['logo_count']} (expected 1)"
            )
        if rec["merged_decision"] == "block":
            failures.append(
                f"{name}: Art Director BLOCK on an accepted QUOTE render - {rec['hard_failures']}"
            )

    # ---- RECAP fallback background (unbranded by contract) --------------------------------
    rr = build_recap_fallback_background("APPLE EVENT 2026 - ГЛАВНОЕ", category="RECAP")
    if rr.success and rr.image_bytes:
        (OUT / "recap_09_fallback_background.png").write_bytes(
            _png_from_jpeg(rr.image_bytes)
        )
        records.append(
            {
                "name": "recap_09_fallback_background",
                "format": "RECAP",
                "note": "Tier-3 fallback background - carries NO branding by contract; "
                "apply_master_news_branding() adds the single NNJ mark once at "
                "Final Post Review + publication time.",
                "render_success": True,
                "template_version": rr.template_version,
            }
        )
    else:
        failures.append(
            f"recap_09: fallback background render failed - {rr.fallback_reason}"
        )

    (OUT / "canary_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _contact_sheet(records)

    print(f"\nwrote {len(records)} canary records to {OUT}")
    if failures:
        print("\nCANARY FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print(
        "\nCANARY PASS - all launch invariants held (single NNJ mark, BREAKING band retired, "
        "number-preserve on infographic, INFOGRAPHIC_DESTROYED blocks, no BLOCK on accepted renders)"
    )
    return 0


def _png(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, format="PNG")
    return b.getvalue()


def _png_from_jpeg(jpeg_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(jpeg_bytes)) as im:
        return _png(im.copy())


def _record(name, fmt, ev, spec_result, merged, dec_meta=None) -> dict:
    ev_d = _serialise(ev)
    dims = {
        d.dimension.value: {
            "status": d.status.value,
            "hard_failure": d.hard_failure,
            "reason_codes": d.reason_codes,
            "checked": d.checked_fields,
            "not_measured": d.not_measured_fields,
        }
        for d in spec_result.dimensions
    }
    return {
        "name": name,
        "format": fmt,
        "renderer_variant": ev.renderer_variant,
        "renderer_version": ev.renderer_version,
        "canvas": [ev_d.get("canvas_width"), ev_d.get("canvas_height")],
        "logo_count": ev_d.get("logo_count"),
        "logo_zone": ev_d.get("logo_zone"),
        "placement_zone": ev_d.get("placement_zone"),
        "scrim_treatment": ev_d.get("scrim_treatment"),
        "source_image_treatment": ev_d.get("source_image_treatment"),
        "source_preserved": ev_d.get("source_preserved"),
        "actual_line_count": ev_d.get("actual_line_count"),
        "primary_font_size": ev_d.get("primary_font_size"),
        "not_applicable_fields": ev_d.get("not_applicable_fields"),
        "spec_overall": spec_result.overall_decision.value,
        "spec_dimensions": dims,
        "hard_failures": list(spec_result.hard_failure_reason_codes),
        "merged_decision": merged.decision.value,
        "merged_issue_codes": [c.value for c in merged.issue_codes],
        "merged_instructions": merged.instructions,
        "renderer_decision_metadata": dec_meta,
    }


def _contact_sheet(records: list[dict]) -> None:
    order = [
        "news_01_dark_photo",
        "news_02_light_photo",
        "breaking_03_dark_dramatic",
        "breaking_04_light_photo",
        "data_05_existing_infographic",
        "data_05b_infographic_full_card_DESTROY_TEST",
        "data_06_generated_card",
        "quote_07_light_portrait",
        "quote_08_dark_portrait",
        "recap_09_fallback_background",
    ]
    cols, cell_w, cell_h, pad, header = 3, 520, 320, 18, 46
    rows = (len(order) + cols - 1) // cols
    sheet = Image.new(
        "RGB",
        (cols * (cell_w + pad) + pad, rows * (cell_h + header + pad) + pad),
        (16, 16, 18),
    )
    d = ImageDraw.Draw(sheet)
    by_name = {r["name"]: r for r in records}
    for i, nm in enumerate(order):
        cx = pad + (i % cols) * (cell_w + pad)
        cy = pad + (i // cols) * (cell_h + header + pad)
        p = OUT / f"{nm}.png"
        if p.exists():
            with Image.open(p) as opened:
                thumb = opened.convert("RGB")
                thumb.thumbnail((cell_w, cell_h))
                sheet.paste(thumb, (cx, cy + header))
        r = by_name.get(nm, {})
        d.text((cx, cy + 2), nm, fill=(240, 240, 240))
        d.text(
            (cx, cy + 20),
            f"logo={r.get('logo_count')} zone={r.get('logo_zone')} scrim={r.get('scrim_treatment')} "
            f"art={r.get('merged_decision')}",
            fill=(237, 28, 36)
            if r.get("merged_decision") == "block"
            else (170, 200, 170),
        )
    sheet.save(OUT / "CONTACT_SHEET.png")
    print("wrote", OUT / "CONTACT_SHEET.png")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
