"""VISUAL-SPEC-V2-ACTIVATION-1 - the Founder-approved telegram_news v2 / telegram_breaking v2
Design Specs, applied through the canonical registry lifecycle, drive every accepted render to
SPEC_MATCH=PASS with no placement_zone PARTIAL_EVIDENCE.

The sole approved semantic change vs v1 is: REMOVE placement_zone=lower_left. scripts/
activate_visual_spec_v2.py is the replayable production applier; this test exercises the same
lifecycle + the §4 final matrix in an isolated, rolled-back db_session.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecStatus, DesignSpecType
from services.brand_renderer import render_breaking_frame, render_data_card, render_quote_card
from services.data_source_classification import (
    DataPresentationMode,
    classify_source_presentation,
    select_data_presentation_mode,
)
from services.design_spec_registry import create_candidate_spec, get_active_spec, list_history, promote_candidate
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import (
    derive_breaking_render_evidence,
    derive_data_render_evidence,
    derive_master_news_render_evidence,
    derive_quote_render_evidence,
)
from services.telegram_art_director import ArtDirectorDecision, PixelInputContract, evaluate_art_direction_shadow
from services.telegram_art_director_spec_evaluation import (
    ArtDirectorDimension,
    DimensionStatus,
    SpecEvaluationInput,
    finalize_art_direction,
)

_V1_NEWS = {
    "safe_margin_frac": 0.019, "placement_zone": "lower_left", "logo_zone": "lower_right",
    "scrim_treatment": "none", "source_image_treatment": "preserve",
}
_V1_BREAKING = dict(_V1_NEWS)
_V1_DATA = {
    "font_size_max": 88, "font_size_min": 48, "max_line_count": 2, "safe_margin_frac": 0.019,
    "logo_zone": "lower_right", "scrim_treatment": "none", "source_image_treatment": "preserve",
}
_V1_QUOTE = {
    "safe_margin_frac": 0.019, "logo_zone": "lower_right", "scrim_treatment": "none",
    "source_image_treatment": "preserve",
}
_V2_ONLY_CHANGE = "placement_zone"  # the ONLY key that may differ between v1 and v2

_KIRIN = DataCandidate(value="42", unit="%", label="of Kirin 9050 Pro benchmark improvement", evidence_fact="42% improvement reported")


def _jpeg(im: Image.Image, q: int = 94) -> bytes:
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=q)
    return b.getvalue()


def _photo(w: int = 1280, h: int = 720) -> bytes:
    im = Image.new("RGB", (w, h), (95, 115, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([w * 0.30, h * 0.22, w * 0.66, h * 0.80], fill=(208, 120, 95))
    d.rectangle([w * 0.42, h * 0.30, w * 0.56, h * 0.66], fill=(40, 30, 28))
    return _jpeg(im, 95)


def _kirin_infographic() -> bytes:
    im = Image.new("RGB", (1280, 720), (18, 18, 20))
    ImageDraw.Draw(im).text((120, 260), "42%", fill=(255, 255, 255))
    return _jpeg(im, 95)


def _portrait() -> bytes:
    im = Image.new("RGB", (800, 1000), (40, 40, 50))
    ImageDraw.Draw(im).ellipse([250, 200, 550, 560], fill=(205, 185, 165))
    return _jpeg(im)


def _pin(raw: bytes, pt: str) -> PixelInputContract:
    return PixelInputContract(rendered_bytes=raw, caption="canary", presentation_type=pt,
                              renderer_version="vsv2", renderer_decision_metadata={}, media_source_metadata={})


async def _seed_v1_active(session: AsyncSession, scope: str, params: dict):
    cand = await create_candidate_spec(
        session, scope=scope, spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        platform="telegram", surface="channel", presentation_type=scope.split("_", 1)[1].upper(),
        parameters=params, notes="v1 - Founder-approved (DESIGN-SPEC-ACTIVATION-1)",
    )
    return await promote_candidate(session, cand.id)


async def _activate_v2(session: AsyncSession, scope: str, v1_params: dict):
    """The canonical lifecycle scripts/activate_visual_spec_v2.py performs: create the v2 CANDIDATE
    (placement_zone removed, nothing else changed) then promote it - v1 is SUPERSEDED by the
    lifecycle, never edited in place."""
    v2_params = {k: v for k, v in v1_params.items() if k != _V2_ONLY_CHANGE}
    cand = await create_candidate_spec(
        session, scope=scope, spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        platform="telegram", surface="channel", presentation_type=scope.split("_", 1)[1].upper(),
        parameters=v2_params, created_by=0,
        notes="v2 - Founder-approved (VISUAL-SPEC-V2-ACTIVATION-1): placement_zone removed; no other change.",
    )
    return await promote_candidate(session, cand.id)


@pytest.mark.asyncio
async def test_v2_lifecycle_only_removes_placement_zone_and_supersedes_v1(db_session: AsyncSession) -> None:
    for scope, v1 in (("telegram_news", _V1_NEWS), ("telegram_breaking", _V1_BREAKING)):
        v1_row = await _seed_v1_active(db_session, scope, v1)
        v1_params_before = dict(v1_row.parameters)
        v2_row = await _activate_v2(db_session, scope, v1)

        # canonical lifecycle: v1 -> SUPERSEDED (status only), v2 -> ACTIVE
        await db_session.refresh(v1_row)
        assert v1_row.status is DesignSpecStatus.SUPERSEDED
        assert v1_row.parameters == v1_params_before  # v1 row NOT edited in place
        assert v2_row.status is DesignSpecStatus.ACTIVE
        assert v2_row.version == v1_row.version + 1
        assert v2_row.supersedes == v1_row.id

        # the ONLY difference is the removed placement_zone
        assert set(v1_params_before) - set(v2_row.parameters) == {"placement_zone"}
        assert set(v2_row.parameters) - set(v1_params_before) == set()
        for key, val in v2_row.parameters.items():
            assert v1_params_before[key] == val, f"{scope}.{key} changed - only placement_zone may differ"

        active = await get_active_spec(db_session, scope)
        assert active is not None and active.id == v2_row.id
        history = await list_history(db_session, scope)
        assert {h.status for h in history} == {DesignSpecStatus.SUPERSEDED, DesignSpecStatus.ACTIVE}


@pytest.mark.asyncio
async def test_final_matrix_all_pass_no_placement_zone_partial(db_session: AsyncSession) -> None:
    """§4-7: with telegram_news v2 / telegram_breaking v2 ACTIVE and telegram_data/quote v1 ACTIVE,
    every accepted render is SPEC_MATCH=PASS - and NEWS/BREAKING carry no placement_zone
    PARTIAL_EVIDENCE. DATA/QUOTE/Kirin behaviour is unchanged."""
    await _seed_v1_active(db_session, "telegram_news", _V1_NEWS)
    news_spec = await _activate_v2(db_session, "telegram_news", _V1_NEWS)
    await _seed_v1_active(db_session, "telegram_breaking", _V1_BREAKING)
    breaking_spec = await _activate_v2(db_session, "telegram_breaking", _V1_BREAKING)
    data_spec = await _seed_v1_active(db_session, "telegram_data", _V1_DATA)
    quote_spec = await _seed_v1_active(db_session, "telegram_quote", _V1_QUOTE)

    photo = _photo()

    async def _spec_match(spec, pt, rendered, evidence, *, source_type=None, presentation_mode=None):
        base = evaluate_art_direction_shadow(_pin(rendered, pt))
        merged, se = finalize_art_direction(SpecEvaluationInput(
            base_result=base, active_spec=spec, source_type=source_type,
            presentation_mode=presentation_mode, render_evidence=evidence,
        ))
        dim = next(d for d in se.dimensions if d.dimension is ArtDirectorDimension.SPEC_MATCH)
        return dim, merged

    # NEWS (renderer unchanged) -> PASS, no not_measured
    news_bytes, _ = apply_master_news_branding(photo)
    dim, merged = await _spec_match(news_spec, "NEWS", news_bytes, derive_master_news_render_evidence(photo, presentation_type="NEWS"))
    assert dim.status is DimensionStatus.PASS, dim.rationale
    assert dim.not_measured_fields == []
    assert "placement_zone" not in dim.checked_fields
    assert merged.decision in (ArtDirectorDecision.PASS, ArtDirectorDecision.PASS_WITH_NOTES)

    # BREAKING (corrected renderer) -> PASS, no band scrim mismatch, no not_measured
    brk_bytes = render_breaking_frame(photo, category="tech", editorial_code="NP-B1")
    brk_ev = derive_breaking_render_evidence(photo)
    assert brk_ev.scrim_treatment == "none"
    dim, merged = await _spec_match(breaking_spec, "BREAKING", brk_bytes, brk_ev)
    assert dim.status is DimensionStatus.PASS, dim.rationale
    assert dim.reason_codes == []
    assert dim.not_measured_fields == []
    assert merged.decision in (ArtDirectorDecision.PASS, ArtDirectorDecision.PASS_WITH_NOTES)  # never REWORK

    # DATA infographic (Kirin -> MINIMAL) -> PASS
    st = classify_source_presentation(["possible_banner", "possible_logo"])
    mode = select_data_presentation_mode(st)
    di = render_data_card(_KIRIN, category="tech", editorial_code="NP-K", source_image_bytes=_kirin_infographic(), presentation_mode=mode)
    dim, _ = await _spec_match(data_spec, "DATA", di, derive_data_render_evidence(_kirin_infographic(), _KIRIN, presentation_mode=mode),
                              source_type=st, presentation_mode=mode)
    assert dim.status is DimensionStatus.PASS, dim.rationale

    # DATA photo -> PASS
    st2 = classify_source_presentation([])
    mode2 = select_data_presentation_mode(st2)
    dp = render_data_card(_KIRIN, category="tech", editorial_code="NP-P", source_image_bytes=photo, presentation_mode=mode2)
    dim, _ = await _spec_match(data_spec, "DATA", dp, derive_data_render_evidence(photo, _KIRIN, presentation_mode=mode2),
                              source_type=st2, presentation_mode=mode2)
    assert dim.status is DimensionStatus.PASS, dim.rationale

    # QUOTE -> PASS
    q = render_quote_card(QuoteCandidate(text="On-device inference just got real.", speaker="A. R."),
                          category="tech", editorial_code="NP-Q", portrait_bytes=_portrait())
    dim, _ = await _spec_match(quote_spec, "QUOTE", q, derive_quote_render_evidence(_portrait()))
    assert dim.status is DimensionStatus.PASS, dim.rationale

    # Kirin regression - unchanged
    bad = render_data_card(_KIRIN, category="tech", editorial_code="NP-K", source_image_bytes=_kirin_infographic(),
                           presentation_mode=DataPresentationMode.FULL_DATA_CARD)
    _dim, bad_merged = await _spec_match(
        data_spec, "DATA", bad,
        derive_data_render_evidence(_kirin_infographic(), _KIRIN, presentation_mode=DataPresentationMode.FULL_DATA_CARD),
        source_type=st, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    assert bad_merged.decision is ArtDirectorDecision.BLOCK  # FULL_DATA_CARD over infographic still blocks
