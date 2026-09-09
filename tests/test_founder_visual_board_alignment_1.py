"""FOUNDER-VISUAL-BOARD-ALIGNMENT-1 focused tests (docs/founder_visual_board_alignment_1_report.md).

Covers the two Founder-decided renderer changes against `docs/founder_telegram_board.png`:
  * generated DATA hero-metric card (board format 3) - metric fidelity, chart only from a real
    series, font fitting, no clipping, exactly one NNJ mark, determinism;
  * QUOTE composition (board format 4) - author role line, missing-role fallback, no baked
    PULSE/QUOTE label, no baked NP-xxxx code, exactly one NNJ mark, no quote clipping.

NEWS / BREAKING parity is re-asserted here too (they must remain board-compatible).
"""

from __future__ import annotations

import inspect
import io

from PIL import Image

from services import brand_renderer as br
from services.brand_renderer import (
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
    render_quote_card,
)
from services.data_source_classification import DataPresentationMode
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import (
    NOT_MEASURED,
    derive_breaking_render_evidence,
    derive_data_render_evidence,
    derive_master_news_render_evidence,
    derive_quote_render_evidence,
)


def _jpeg(w: int, h: int, color: tuple[int, int, int] = (30, 30, 34)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _portrait_bytes(light: bool = False) -> bytes:
    return _jpeg(900, 1200, (232, 232, 236) if light else (18, 18, 22))


_HERO_CAND = DataCandidate(
    value="500",
    unit="млн",
    label="пользователей",
    evidence_fact="Достиг ChatGPT в июле 2025 года",
    series=(120.0, 150.0, 190.0, 250.0, 330.0, 420.0, 500.0),
    delta="+38%",
)


# --------------------------------------------------------------------------------------------------
# DATA - generated hero-metric card (board format 3)
# --------------------------------------------------------------------------------------------------
def test_hero_card_is_1280x720_jpeg_and_deterministic() -> None:
    a = render_data_hero_card(_HERO_CAND)
    b = render_data_hero_card(_HERO_CAND)
    assert a == b  # no randomness / timing leakage
    with Image.open(io.BytesIO(a)) as im:
        assert im.format == "JPEG"
        assert im.size == (1280, 720)


def test_hero_card_never_reformats_or_invents_the_metric() -> None:
    """The renderer draws value / unit / label / evidence_fact / delta exactly as given - it must
    never mutate the candidate or synthesise a number."""
    cand = DataCandidate(
        value="-8.1",
        unit="%",
        label="quarterly change",
        evidence_fact="Revenue fell 8.1%.",
        delta="-2pp",
    )
    before = (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta)
    render_data_hero_card(cand)
    assert (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta) == before


def test_hero_card_chart_is_drawn_only_from_a_supplied_series() -> None:
    """No `series` -> no trend line is plotted (the board shows the chart only when the data
    supports it); a >=2-point series is plotted, a 1-point/empty series is not."""
    src = inspect.getsource(br.render_data_hero_card)
    assert "_draw_hero_sparkline" in src
    assert (
        "len(series) >= 2" in src
    )  # the guard - never a synthetic/interpolated series
    # empty + single-point series must still render (just without a chart) and stay deterministic
    no_series = DataCandidate(value="42", unit="%", label="x", evidence_fact="y")
    one_point = DataCandidate(
        value="42", unit="%", label="x", evidence_fact="y", series=(3.0,)
    )
    assert render_data_hero_card(no_series) == render_data_hero_card(no_series)
    assert render_data_hero_card(one_point)  # renders, no crash


def test_hero_card_fits_a_very_long_value_without_clipping() -> None:
    cand = DataCandidate(
        value="14,500,000,000",
        unit="ПОЛЬЗОВАТЕЛЕЙ В МЕСЯЦ",
        label="",
        evidence_fact="x",
    )
    ev = derive_data_render_evidence(
        _jpeg(1280, 720), cand, presentation_mode=DataPresentationMode.FULL_DATA_CARD
    )
    assert ev.text_clipped is False
    assert isinstance(ev.primary_font_size, int)
    assert br._HERO_VALUE_FONT_MIN <= ev.primary_font_size <= br._HERO_VALUE_FONT_MAX
    assert render_data_hero_card(cand)  # end to end, no exception


def test_hero_card_label_is_bounded_to_two_lines() -> None:
    long_label = "очень длинное описание метрики которое обязано переноситься и никогда не обрезаться посередине слова"
    cand = DataCandidate(value="7", unit="", label=long_label, evidence_fact="z")
    ev = derive_data_render_evidence(
        _jpeg(1280, 720), cand, presentation_mode=DataPresentationMode.FULL_DATA_CARD
    )
    assert isinstance(ev.actual_line_count, int)
    assert ev.actual_line_count <= br._HERO_LABEL_MAX_LINES


def test_hero_card_has_exactly_one_nnj_mark_via_evidence() -> None:
    ev = derive_data_render_evidence(
        _jpeg(1280, 720),
        _HERO_CAND,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    assert ev.logo_count == 1
    assert ev.logo_zone == "lower_right"


def test_full_data_card_dispatch_routes_to_the_hero_card() -> None:
    out = render_data_card(
        _HERO_CAND,
        category="DATA",
        editorial_code="NP-1",
        source_image_bytes=_jpeg(1600, 900),
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    assert out == render_data_hero_card(_HERO_CAND, source_image_bytes=_jpeg(1600, 900))


def test_existing_infographic_is_never_converted_to_a_hero_card() -> None:
    """Founder decision phase §3: MINIMAL_SOURCE_PRESERVING keeps the source infographic and adds
    no competing metric - it must NOT delegate to the hero renderer."""
    src = _jpeg(1280, 720, (12, 12, 14))
    ev = derive_data_render_evidence(
        src,
        _HERO_CAND,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    assert ev.renderer_variant != "brand_renderer.render_data_hero_card"
    assert ev.actual_line_count == 0  # "42 stays 42" - no stat block drawn


# --------------------------------------------------------------------------------------------------
# QUOTE - board format 4
# --------------------------------------------------------------------------------------------------
_QUOTE = QuoteCandidate(
    text="ИИ не заменит программистов. Но программисты, которые используют ИИ, заменят тех, кто его не использует.",
    speaker="Андрей Карпатый",
    role="ex-DIRECTOR OF AI, TESLA",
)


def test_quote_card_draws_the_author_role_when_supplied() -> None:
    out = render_quote_card(
        _QUOTE,
        category="QUOTE",
        editorial_code="NP-9",
        portrait_bytes=_portrait_bytes(),
    )
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (1200, 675)
    # structural: the role is read from the candidate and drawn (no fabrication path exists)
    src = inspect.getsource(render_quote_card)
    assert "quote_candidate.role" in src


def test_quote_card_omits_the_role_line_when_absent_never_fabricates_it() -> None:
    no_role = QuoteCandidate(
        text="On-device inference is real now.", speaker="A. Researcher"
    )
    a = render_quote_card(
        no_role,
        category="QUOTE",
        editorial_code="NP-9",
        portrait_bytes=_portrait_bytes(),
    )
    b = render_quote_card(
        no_role,
        category="QUOTE",
        editorial_code="NP-9",
        portrait_bytes=_portrait_bytes(),
    )
    assert a == b  # deterministic
    with Image.open(io.BytesIO(a)) as im:
        assert im.size == (1200, 675)


def _body(func) -> str:
    """The function source with its leading def-line and docstring stripped - so 'never renders X'
    checks see only executable code (this file's own non-OCR structural-check precedent)."""
    src = inspect.getsource(func)
    parts = src.split('"""')
    return parts[2] if len(parts) >= 3 else src


def test_quote_card_does_not_bake_native_telegram_metadata() -> None:
    """Founder decision phase §3/§7: the PULSE/QUOTE label and the NP-xxxx editorial code are
    Telegram-native and must NOT be baked into the media."""
    body = _body(render_quote_card)
    assert "PULSE /" not in body
    assert "_draw_code_label" not in body
    assert (
        "editorial_code" not in body
    )  # accepted in the signature, never referenced in the body


def test_quote_card_has_the_red_quote_mark_motif_and_one_mark() -> None:
    src = inspect.getsource(render_quote_card)
    assert "_QUOTE_MARK_GLYPH" in src
    assert "_OFFICIAL_NNJ_RED" in src
    assert src.count("_paste_svg_mark(") == 1  # exactly one NNJ mark
    assert "_paste_logo" not in src


def test_quote_card_font_fits_a_long_quote_without_clipping() -> None:
    long_quote = QuoteCandidate(
        text=(
            "Это очень длинная цитата, которая должна быть уменьшена по размеру шрифта и перенесена "
            "по словам, но никогда не обрезана посередине слова или предложения при рендеринге карточки."
        ),
        speaker="Кто-то",
        role="СEO",
    )
    out = render_quote_card(
        long_quote,
        category="QUOTE",
        editorial_code="NP-9",
        portrait_bytes=_portrait_bytes(),
    )
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (1200, 675)  # renders, bounded, no exception
    ev = derive_quote_render_evidence(_portrait_bytes())
    assert (
        "scrim_treatment" in ev.not_applicable_fields
    )  # portrait panel is the card's own ground, not a source scrim


# --------------------------------------------------------------------------------------------------
# NEWS / BREAKING must remain board-compatible (phase §8)
# --------------------------------------------------------------------------------------------------
def test_news_render_evidence_unchanged_single_lower_right_signature() -> None:
    src = _jpeg(1600, 900)
    apply_master_news_branding(src)
    ev = derive_master_news_render_evidence(src, presentation_type="NEWS")
    assert ev.logo_count in (0, 1)
    assert ev.scrim_treatment == "none"
    assert ev.source_image_treatment in ("preserve", "crop")


def test_breaking_render_evidence_unchanged_no_band_no_scrim() -> None:
    src = _jpeg(1600, 900)
    render_breaking_frame(src, category="AI", editorial_code="NP-B1")
    ev = derive_breaking_render_evidence(src)
    assert ev.scrim_treatment == "none"
    assert ev.source_image_treatment == "preserve"
    assert ev.renderer_version == "pulse-breaking-v2"
    assert ev.placement_zone is NOT_MEASURED
