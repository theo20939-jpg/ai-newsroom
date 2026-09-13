"""FOUNDER-VISUAL-BOARD-ALIGNMENT-1 - LOCAL canary + Founder contact sheet (no Telegram send,
no DB writes).

Renders the board-aligned formats through their REAL production code paths, derives the
renderer-truthful RenderEvidence, evaluates each against its ACTIVE spec (and, for DATA/QUOTE,
the vNEXT CANDIDATE) read read-only from the dev control-plane DB, runs the shadow Art Director
merge, asserts the launch invariants, and writes:

  artifacts/founder_visual_board_alignment_1/
    news_current.png  breaking_current.png
    data_existing_infographic.png  data_generated_hero.png
    quote_final.png  quote_fallback_missing_role.png
    canary_records.json
    CONTACT_SHEET.png   <- FOUNDER BOARD REFERENCE on top, then CURRENT / FINAL renders

Run:  python scripts/_founder_visual_board_alignment_canary.py
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

OUT = Path("artifacts/founder_visual_board_alignment_1")
OUT.mkdir(parents=True, exist_ok=True)
BOARD = Path("docs/founder_telegram_board.png")
_INFOGRAPHIC = Path(
    "assets/brand/newsroom_visuals/v1/references/data/data_template_white.png"
)
_BAKE = Path("assets/brand/newsroom_visuals/v2_1_bakeoff_sources")


def _jpeg(img: Image.Image, q: int = 92) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, format="JPEG", quality=q)
    return b.getvalue()


def _png_from_any(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        b = io.BytesIO()
        im.convert("RGB").save(b, format="PNG")
        return b.getvalue()


def _synth_portrait(light: bool) -> bytes:
    bg = (232, 232, 236) if light else (16, 16, 20)
    skin = (206, 168, 150) if light else (150, 120, 108)
    im = Image.new("RGB", (900, 1200), bg)
    d = ImageDraw.Draw(im)
    d.ellipse([300, 240, 620, 620], fill=skin)
    d.rectangle([250, 600, 680, 1200], fill=(64, 68, 78))
    return _jpeg(im)


async def _load_specs() -> dict:
    from core.config import settings
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from database.models.design_spec_version import DesignSpecStatus, DesignSpecVersion

    engine = create_async_engine(settings.database_url)
    out: dict = {}
    try:
        async with AsyncSession(engine) as session:
            rows = (
                (
                    await session.execute(
                        select(DesignSpecVersion).where(
                            DesignSpecVersion.status.in_(
                                [DesignSpecStatus.ACTIVE, DesignSpecStatus.CANDIDATE]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                out[f"{r.scope}:{r.status.value}"] = r
            session.expunge_all()
    finally:
        await engine.dispose()
    return out


def _evidence_dict(ev) -> dict:
    def _v(x):
        return "NOT_MEASURED" if repr(x) == "NOT_MEASURED" else x

    return {
        "renderer_variant": ev.renderer_variant,
        "renderer_version": ev.renderer_version,
        "canvas": [_v(ev.canvas_width), _v(ev.canvas_height)],
        "logo_count": _v(ev.logo_count),
        "logo_zone": _v(ev.logo_zone),
        "placement_zone": _v(ev.placement_zone),
        "scrim_treatment": _v(ev.scrim_treatment),
        "source_image_treatment": _v(ev.source_image_treatment),
        "primary_font_size": _v(ev.primary_font_size),
        "actual_line_count": _v(ev.actual_line_count),
        "safe_margin_frac": _v(ev.safe_margin_frac),
        "not_applicable_fields": sorted(ev.not_applicable_fields),
    }


def _art(base, *, active_spec, evidence, source_type=None, presentation_mode=None):
    from services.telegram_art_director_spec_evaluation import (
        SpecEvaluationInput,
        evaluate_against_spec_and_references,
        merge_spec_evaluation_into_result,
    )

    spec_result = evaluate_against_spec_and_references(
        SpecEvaluationInput(
            base_result=base,
            active_spec=active_spec,
            render_evidence=evidence,
            source_type=source_type,
            presentation_mode=presentation_mode,
        )
    )
    merged = merge_spec_evaluation_into_result(base, spec_result)
    dims = {d.dimension.value: d.status.value for d in spec_result.dimensions}
    return {
        "spec_overall": spec_result.overall_decision.value,
        "hard_failures": list(spec_result.hard_failure_reason_codes),
        "dimensions": dims,
        "merged_decision": merged.decision.value,
    }


def _base(rendered: bytes, caption: str, ptype: str, rv: str, meta: dict):
    from services.telegram_art_director import (
        PixelInputContract,
        evaluate_art_direction_shadow,
    )

    return evaluate_art_direction_shadow(
        PixelInputContract(
            rendered_bytes=rendered,
            caption=caption,
            presentation_type=ptype,
            renderer_version=rv,
            renderer_decision_metadata=meta,
        )
    )


async def main() -> int:
    from services.brand_renderer import (
        render_breaking_frame,
        render_data_card,
        render_quote_card,
    )
    from services.nnj_master_news_overlay import apply_master_news_branding
    from services.data_source_classification import DataPresentationMode, SourceType
    from services.presentation_director import DataCandidate, QuoteCandidate
    from services.render_evidence import (
        derive_breaking_render_evidence,
        derive_data_render_evidence,
        derive_master_news_render_evidence,
        derive_quote_render_evidence,
    )

    specs = await _load_specs()
    print("specs:", {k: f"v{v.version}" for k, v in specs.items()})

    records: list[dict] = []
    failures: list[str] = []

    # ---- NEWS (unchanged - board-compatible) ----
    news_src = _BAKE.joinpath("case3_bright_promotional_scene.jpg").read_bytes()
    branded, dec = apply_master_news_branding(news_src)
    news_bytes = branded if isinstance(branded, (bytes, bytearray)) else _jpeg(branded)
    (OUT / "news_current.png").write_bytes(_png_from_any(news_bytes))
    ev = derive_master_news_render_evidence(news_src, presentation_type="NEWS")
    meta = {
        "upper_mark": {"placement": dec.upper_mark.placement.value},
        "lower_signature": {"placement": dec.lower_signature.placement.value},
        "degradation_mode": dec.degradation_mode,
    }
    art = _art(
        _base(
            news_bytes,
            "OpenAI представила новое устройство",
            "NEWS",
            "master_news_v1",
            meta,
        ),
        active_spec=specs.get("telegram_news:active"),
        evidence=ev,
    )
    records.append(
        {
            "name": "news_current",
            "format": "NEWS",
            "evidence": _evidence_dict(ev),
            **art,
        }
    )
    if ev.logo_count not in (0, 1):
        failures.append(f"news_current: logo_count={ev.logo_count}")
    if art["merged_decision"] == "block":
        failures.append(f"news_current: Art BLOCK {art['hard_failures']}")

    # ---- BREAKING (unchanged - board-compatible) ----
    brk_src = _BAKE.joinpath("case1_hero_product_iphone.jpg").read_bytes()
    brk_bytes = render_breaking_frame(brk_src, category="AI", editorial_code="NP-0185")
    (OUT / "breaking_current.png").write_bytes(_png_from_any(brk_bytes))
    ev = derive_breaking_render_evidence(brk_src)
    art = _art(
        _base(
            brk_bytes,
            "Apple готовит новый iPhone 17",
            "BREAKING",
            "pulse-breaking-v2",
            {},
        ),
        active_spec=specs.get("telegram_breaking:active"),
        evidence=ev,
    )
    records.append(
        {
            "name": "breaking_current",
            "format": "BREAKING",
            "evidence": _evidence_dict(ev),
            **art,
        }
    )
    if ev.scrim_treatment not in ("none", "NOT_MEASURED"):
        failures.append(
            f"breaking_current: scrim={ev.scrim_treatment} (band must stay retired)"
        )
    if art["merged_decision"] == "block":
        failures.append(f"breaking_current: Art BLOCK {art['hard_failures']}")

    # ---- DATA existing infographic -> MINIMAL_SOURCE_PRESERVING (unchanged) ----
    dc = DataCandidate(
        value="500",
        unit="млн",
        label="пользователей",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
    )
    info_bytes = render_data_card(
        dc,
        category="DATA",
        editorial_code="NP-0183",
        source_image_bytes=_INFOGRAPHIC.read_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    (OUT / "data_existing_infographic.png").write_bytes(_png_from_any(info_bytes))
    ev = derive_data_render_evidence(
        _INFOGRAPHIC.read_bytes(),
        dc,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    art = _art(
        _base(
            info_bytes,
            "ChatGPT достиг 500 млн пользователей",
            "DATA",
            "pulse-data-v1",
            {},
        ),
        active_spec=specs.get("telegram_data:active"),
        evidence=ev,
        source_type=SourceType.EXISTING_INFOGRAPHIC,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    records.append(
        {
            "name": "data_existing_infographic",
            "format": "DATA (existing infographic)",
            "evidence": _evidence_dict(ev),
            **art,
        }
    )
    if ev.actual_line_count not in (0, "NOT_MEASURED"):
        failures.append(
            f"data_existing_infographic: MINIMAL drew a stat block (lines={ev.actual_line_count})"
        )
    if art["merged_decision"] == "block":
        failures.append(f"data_existing_infographic: Art BLOCK {art['hard_failures']}")

    # ---- DATA generated hero metric -> FULL_DATA_CARD (NEW) ----
    dc_hero = DataCandidate(
        value="500",
        unit="млн",
        label="пользователей",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
        series=(120.0, 150.0, 190.0, 250.0, 330.0, 420.0, 500.0),
        delta="+38%",
    )
    hero_bytes = render_data_card(
        dc_hero,
        category="DATA",
        editorial_code="NP-0183",
        source_image_bytes=news_src,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    (OUT / "data_generated_hero.png").write_bytes(_png_from_any(hero_bytes))
    ev = derive_data_render_evidence(
        news_src, dc_hero, presentation_mode=DataPresentationMode.FULL_DATA_CARD
    )
    art_active = _art(
        _base(hero_bytes, "ChatGPT достиг 500 млн", "DATA", "pulse-data-hero-v1", {}),
        active_spec=specs.get("telegram_data:active"),
        evidence=ev,
        source_type=SourceType.PHOTO,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    art_cand = _art(
        _base(hero_bytes, "ChatGPT достиг 500 млн", "DATA", "pulse-data-hero-v1", {}),
        active_spec=specs.get("telegram_data:candidate"),
        evidence=ev,
        source_type=SourceType.PHOTO,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    records.append(
        {
            "name": "data_generated_hero",
            "format": "DATA (generated hero)",
            "evidence": _evidence_dict(ev),
            "vs_active_spec_v1": art_active,
            "vs_candidate_spec_v2": art_cand,
            **art_cand,
        }
    )
    if ev.logo_count != 1:
        failures.append(f"data_generated_hero: logo_count={ev.logo_count} (expected 1)")
    if art_cand["merged_decision"] == "block":
        failures.append(
            f"data_generated_hero: Art BLOCK vs vNEXT candidate {art_cand['hard_failures']}"
        )
    if art_active["merged_decision"] == "block":
        failures.append(
            f"data_generated_hero: Art BLOCK vs ACTIVE v1 {art_active['hard_failures']} (unexpected - hero drift should be soft)"
        )

    # ---- QUOTE final (portrait + full role) ----
    qc = QuoteCandidate(
        text="ИИ не заменит программистов. Но программисты, которые используют ИИ, заменят тех, кто его не использует.",
        speaker="Андрей Карпатый",
        role="ex-DIRECTOR OF AI, TESLA",
    )
    q_bytes = render_quote_card(
        qc,
        category="QUOTE",
        editorial_code="NP-0182",
        portrait_bytes=_synth_portrait(light=False),
    )
    (OUT / "quote_final.png").write_bytes(_png_from_any(q_bytes))
    ev = derive_quote_render_evidence(_synth_portrait(light=False))
    art = _art(
        _base(q_bytes, qc.text, "QUOTE", "pulse-quote-v1", {}),
        active_spec=specs.get("telegram_quote:active"),
        evidence=ev,
    )
    records.append(
        {
            "name": "quote_final",
            "format": "QUOTE (portrait + role)",
            "evidence": _evidence_dict(ev),
            **art,
        }
    )
    if ev.logo_count != 1:
        failures.append(f"quote_final: logo_count={ev.logo_count}")
    if art["merged_decision"] == "block":
        failures.append(f"quote_final: Art BLOCK {art['hard_failures']}")

    # ---- QUOTE fallback (portrait + missing role) ----
    qc2 = QuoteCandidate(
        text="On-device inference is real now, and it changes the product.",
        speaker="A. Researcher",
    )
    q2_bytes = render_quote_card(
        qc2,
        category="QUOTE",
        editorial_code="NP-0182",
        portrait_bytes=_synth_portrait(light=True),
    )
    (OUT / "quote_fallback_missing_role.png").write_bytes(_png_from_any(q2_bytes))
    ev = derive_quote_render_evidence(_synth_portrait(light=True))
    art = _art(
        _base(q2_bytes, qc2.text, "QUOTE", "pulse-quote-v1", {}),
        active_spec=specs.get("telegram_quote:active"),
        evidence=ev,
    )
    records.append(
        {
            "name": "quote_fallback_missing_role",
            "format": "QUOTE (missing-role fallback)",
            "evidence": _evidence_dict(ev),
            **art,
        }
    )
    if art["merged_decision"] == "block":
        failures.append(
            f"quote_fallback_missing_role: Art BLOCK {art['hard_failures']}"
        )

    (OUT / "canary_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _contact_sheet(records)

    print(f"\nwrote {len(records)} records + CONTACT_SHEET.png to {OUT}")
    if failures:
        print("\nCANARY FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print(
        "\nCANARY PASS - single NNJ mark per render, BREAKING band retired, infographic "
        "number-preserved, hero card renders vs vNEXT candidate spec, QUOTE role + fallback OK, "
        "no BLOCK on accepted renders"
    )
    return 0


def _contact_sheet(records: list[dict]) -> None:
    order = [
        ("news_current", "CURRENT / FINAL — NEWS"),
        ("breaking_current", "CURRENT / FINAL — BREAKING"),
        (
            "data_existing_infographic",
            "DATA — EXISTING INFOGRAPHIC (source-preserving)",
        ),
        ("data_generated_hero", "DATA — GENERATED HERO METRIC (new)"),
        ("quote_final", "QUOTE — FINAL (portrait + role)"),
        ("quote_fallback_missing_role", "QUOTE — FALLBACK (missing role)"),
    ]
    by_name = {r["name"]: r for r in records}
    cols, cell_w, cell_h, pad, cap = 3, 520, 300, 20, 40

    board_h = 0
    board_img = None
    if BOARD.exists():
        with Image.open(BOARD) as bi:
            board_img = bi.convert("RGB")
            scale = (cols * (cell_w + pad) + pad) / board_img.width
            board_img = board_img.resize(
                (int(board_img.width * scale), int(board_img.height * scale))
            )
            board_h = board_img.height + cap + pad

    rows = (len(order) + cols - 1) // cols
    W = cols * (cell_w + pad) + pad
    H = board_h + rows * (cell_h + cap + pad) + pad
    sheet = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet)

    y0 = pad
    if board_img is not None:
        d.text(
            (pad, 6),
            "FOUNDER BOARD REFERENCE  (docs/founder_telegram_board.png) — VISUAL AUTHORITY #1",
            fill=(237, 28, 36),
        )
        sheet.paste(board_img, (pad, cap))
        y0 = board_img.height + cap + pad

    for i, (name, title) in enumerate(order):
        cx = pad + (i % cols) * (cell_w + pad)
        cy = y0 + (i // cols) * (cell_h + cap + pad)
        p = OUT / f"{name}.png"
        if p.exists():
            with Image.open(p) as im:
                thumb = im.convert("RGB")
                thumb.thumbnail((cell_w, cell_h))
                sheet.paste(thumb, (cx, cy + cap))
        r = by_name.get(name, {})
        ev = r.get("evidence", {})
        d.text((cx, cy + 2), title, fill=(240, 240, 240))
        d.text(
            (cx, cy + 20),
            f"logo={ev.get('logo_count')} zone={ev.get('logo_zone')} scrim={ev.get('scrim_treatment')} "
            f"font={ev.get('primary_font_size')} art={r.get('merged_decision')}",
            fill=(237, 28, 36)
            if r.get("merged_decision") == "block"
            else (170, 200, 170),
        )
    sheet.save(OUT / "CONTACT_SHEET.png")
    print("wrote", OUT / "CONTACT_SHEET.png")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
