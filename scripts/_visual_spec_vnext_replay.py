"""VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1 §6/§7 - LOCAL final replay of the four approved
formats against the EXACT vNEXT candidate specs (read read-only from the dev control-plane DB):

    telegram_news     v3 CANDIDATE  (adaptive - no logo_zone)
    telegram_breaking v3 CANDIDATE  (adaptive - no logo_zone)
    telegram_data     v3 CANDIDATE  (font 88-200, max_line_count 2, safe_margin - truthful for BOTH
                                     the hero card and the source-preserving MINIMAL render)
    telegram_quote    v2 CANDIDATE  (deterministic lower_right mark)

For each canary it prints the SPEC_MATCH dimension status + reason codes + checked/not-measured
fields, and the merged Art Director decision. No Telegram send, no DB writes.

    python scripts/_visual_spec_vnext_replay.py
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

_BAKE = Path("assets/brand/newsroom_visuals/v2_1_bakeoff_sources")
_INFOGRAPHIC = Path(
    "assets/brand/newsroom_visuals/v1/references/data/data_template_white.png"
)


def _jpeg(w: int, h: int, color: tuple[int, int, int]) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG", quality=90)
    return b.getvalue()


def _portrait(light: bool) -> bytes:
    bg = (232, 232, 236) if light else (16, 16, 20)
    im = Image.new("RGB", (900, 1200), bg)
    d = ImageDraw.Draw(im)
    d.ellipse([300, 240, 620, 620], fill=(206, 168, 150) if light else (150, 120, 108))
    d.rectangle([250, 600, 680, 1200], fill=(64, 68, 78))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return b.getvalue()


async def _candidates() -> dict:
    """Reads the vNEXT CANDIDATE rows from the dev control-plane DB (read-only) and returns, for
    each scope, an in-memory DesignSpecVersion carrying the CANDIDATE's exact parameters but
    status=ACTIVE - so `_evaluate_spec_match()` runs its full field-by-field enforcement (§17:
    real CANDIDATE rows never change acceptance; this replay asks "if these params were ACTIVE,
    would the accepted render conform?")."""
    from core.config import settings
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from database.models.design_spec_version import (
        DesignSpecStatus,
        DesignSpecType,
        DesignSpecVersion,
    )

    want = {
        "telegram_news": 3,
        "telegram_breaking": 3,
        "telegram_data": 3,
        "telegram_quote": 2,
    }
    engine = create_async_engine(settings.database_url)
    out: dict = {}
    try:
        async with AsyncSession(engine) as session:
            rows = (
                (
                    await session.execute(
                        select(DesignSpecVersion).where(
                            DesignSpecVersion.status == DesignSpecStatus.CANDIDATE
                        )
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                if want.get(r.scope) == r.version:
                    out[r.scope] = DesignSpecVersion(
                        platform="telegram",
                        surface="channel",
                        presentation_type=r.scope.split("_")[-1].upper(),
                        spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
                        scope=r.scope,
                        version=r.version,
                        status=DesignSpecStatus.ACTIVE,
                        parameters=dict(r.parameters),
                    )
            session.expunge_all()
    finally:
        await engine.dispose()
    return out


def _spec_dim(active_spec, evidence, *, source_type=None, presentation_mode=None):
    from services.telegram_art_director import (
        ArtDirectorDecision,
        ArtDirectorIssueCode,
        ArtDirectorResult,
    )
    from services.telegram_art_director_spec_evaluation import (
        ArtDirectorDimension,
        SpecEvaluationInput,
        evaluate_against_spec_and_references,
        merge_spec_evaluation_into_result,
    )

    base = ArtDirectorResult(
        decision=ArtDirectorDecision.PASS_WITH_NOTES, severity="none"
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
    dim = next(
        d
        for d in spec_result.dimensions
        if d.dimension is ArtDirectorDimension.SPEC_MATCH
    )
    hard = [
        rc
        for d in spec_result.dimensions
        if d.hard_failure
        for rc in (d.reason_codes or [d.dimension.value])
    ]
    _ = ArtDirectorIssueCode  # keep import meaningful
    return dim, merged, hard


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

    spec = await _candidates()
    missing = {
        "telegram_news",
        "telegram_breaking",
        "telegram_data",
        "telegram_quote",
    } - set(spec)
    if missing:
        print("MISSING vNEXT candidates:", missing, "- run the propose scripts first")
        return 1
    print("vNEXT candidates:", {k: f"v{v.version}" for k, v in spec.items()})
    print()

    # 16:9 sources so NEWS/BREAKING source_image_treatment == preserve (a non-16:9 source is a
    # renderer-independent mechanical crop-to-canvas, reported truthfully - not a spec problem;
    # documented separately in the report).
    clean = _jpeg(1600, 900, (60, 66, 78))  # clean photo -> mark lands lower_right

    def _busy_16x9() -> bytes:
        im = Image.new("RGB", (1600, 900), (40, 44, 52))
        d = ImageDraw.Draw(im)
        import random

        rng = random.Random(7)
        # dense edge content across the whole BOTTOM band -> both bottom corners unsafe ->
        # select_master_news_branding escalates to an upper corner (adaptive)
        for _ in range(9000):
            x, y = rng.randrange(1600), rng.randrange(560, 900)
            d.point(
                (x, y),
                fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)),
            )
        b = io.BytesIO()
        im.save(b, "JPEG", quality=92)
        return b.getvalue()

    busy_bottom = _busy_16x9()

    rows: list[tuple] = []

    # NEWS x2 (clean + busy) vs telegram_news v3
    for tag, src in [("NEWS clean", clean), ("NEWS busy", busy_bottom)]:
        _b, _dec = apply_master_news_branding(src)
        ev = derive_master_news_render_evidence(src, presentation_type="NEWS")
        dim, merged, hard = _spec_dim(spec["telegram_news"], ev)
        rows.append(
            (
                tag,
                ev.logo_zone,
                dim.status.value,
                dim.reason_codes,
                dim.checked_fields,
                dim.not_measured_fields,
                merged.decision.value,
                hard,
            )
        )

    # BREAKING x2 vs telegram_breaking v3
    for tag, src in [("BREAKING clean", clean), ("BREAKING busy", busy_bottom)]:
        render_breaking_frame(src, category="AI", editorial_code="NP-1")
        ev = derive_breaking_render_evidence(src)
        dim, merged, hard = _spec_dim(spec["telegram_breaking"], ev)
        rows.append(
            (
                tag,
                ev.logo_zone,
                dim.status.value,
                dim.reason_codes,
                dim.checked_fields,
                dim.not_measured_fields,
                merged.decision.value,
                hard,
            )
        )

    # DATA generated hero vs telegram_data v2
    dc_hero = DataCandidate(
        value="500",
        unit="млн",
        label="пользователей",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
        series=(120.0, 190.0, 260.0, 360.0, 500.0),
        delta="+38%",
    )
    render_data_card(
        dc_hero,
        category="DATA",
        editorial_code="NP-1",
        source_image_bytes=clean,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    ev = derive_data_render_evidence(
        clean, dc_hero, presentation_mode=DataPresentationMode.FULL_DATA_CARD
    )
    dim, merged, hard = _spec_dim(
        spec["telegram_data"],
        ev,
        source_type=SourceType.PHOTO,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    rows.append(
        (
            "DATA generated hero",
            ev.logo_zone,
            dim.status.value,
            dim.reason_codes,
            dim.checked_fields,
            dim.not_measured_fields,
            merged.decision.value,
            hard,
        )
    )

    # DATA existing infographic vs telegram_data v2 (source-dependent: MINIMAL)
    dc_min = DataCandidate(
        value="500", unit="млн", label="пользователей", evidence_fact="x"
    )
    render_data_card(
        dc_min,
        category="DATA",
        editorial_code="NP-1",
        source_image_bytes=_INFOGRAPHIC.read_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    ev = derive_data_render_evidence(
        _INFOGRAPHIC.read_bytes(),
        dc_min,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    dim, merged, hard = _spec_dim(
        spec["telegram_data"],
        ev,
        source_type=SourceType.EXISTING_INFOGRAPHIC,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    rows.append(
        (
            "DATA existing infographic",
            ev.logo_zone,
            dim.status.value,
            dim.reason_codes,
            dim.checked_fields,
            dim.not_measured_fields,
            merged.decision.value,
            hard,
        )
    )

    # QUOTE full-role + missing-role vs telegram_quote v2
    for tag, qc in [
        (
            "QUOTE full-role",
            QuoteCandidate(
                text="ИИ не заменит программистов, но усилит их.",
                speaker="А. Карпатый",
                role="ex-DIRECTOR OF AI, TESLA",
            ),
        ),
        (
            "QUOTE missing-role",
            QuoteCandidate(
                text="On-device inference is real now.", speaker="A. Researcher"
            ),
        ),
    ]:
        render_quote_card(
            qc,
            category="QUOTE",
            editorial_code="NP-1",
            portrait_bytes=_portrait("full" in tag),
        )
        ev = derive_quote_render_evidence(_portrait(True))
        dim, merged, hard = _spec_dim(spec["telegram_quote"], ev)
        rows.append(
            (
                tag,
                ev.logo_zone,
                dim.status.value,
                dim.reason_codes,
                dim.checked_fields,
                dim.not_measured_fields,
                merged.decision.value,
                hard,
            )
        )

    print(
        f"{'format':<28} {'actual zone':<12} {'SPEC_MATCH':<16} {'merged':<16} reason/notes"
    )
    print("-" * 110)
    bad = []
    for tag, zone, status, rc, chk, nm, merged_d, hard in rows:
        note = ""
        if rc:
            note = "reasons=" + ",".join(rc)
        elif nm:
            note = "not_measured=" + ",".join(nm)
        else:
            note = "checked=" + ",".join(chk)
        print(f"{tag:<28} {str(zone):<12} {status:<16} {merged_d:<16} {note}")
        if hard:
            bad.append(f"{tag}: HARD FAILURE {hard}")
        if status == "fail":
            bad.append(f"{tag}: SPEC_MATCH FAIL {rc}")
        if merged_d in ("block",):
            bad.append(f"{tag}: Art merged={merged_d}")
    print()
    if bad:
        print("REPLAY PROBLEMS:")
        for b in bad:
            print("  -", b)
        return 1
    print(
        "REPLAY OK - no SPEC_MATCH FAIL, no hard failure, no Art BLOCK against the vNEXT candidates."
    )
    print(
        "(PARTIAL_EVIDENCE where present is a truthful measurement gap - explained in the report.)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
