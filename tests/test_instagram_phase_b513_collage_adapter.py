"""Phase B.5.1.3: deterministic collage geometry adapter. Zero cost: no provider, no network. The validator thresholds are NOT changed."""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

import services.instagram_collage_adapter as ca
from schemas.instagram_creative import InstagramSlideLayout
from services import instagram_layout_validation as lv
from services.instagram_automatic_trigger import _resolve_carousel_slide_assets
from services.instagram_b4_observability import build_b4_observability
from services.instagram_collage_adapter import MAX_DISPLACEMENT, MAX_SCALE_CHANGE, adapt_collage
from services.instagram_layout_signature import infer_family
from services.instagram_layout_validation import _area, _inter_area, _rect, validate_layout
from services.instagram_platform_renderer import render_instagram_carousel
from tests.test_instagram_phase_b5_visual_dna_declarative import _carousel_with, _layout, _package_for, _r, _slide

_COPY = "Заголовок коллажа про модель"


def _text():
    return _r("text", 0.07, 0.06, 0.6, 0.16, content_ref="copy", scale_token="HEADLINE_L", align="left", valign="top", max_lines=3)


def _media(x, y, w, h, z, *, frame="paper", tilt=0, ref="source"):
    return _r("media", x, y, w, h, z=z, content_ref=ref, crop_mode="cover", frame=frame, tilt_deg=tilt)


def _collage(*regions, text=None) -> InstagramSlideLayout:
    return InstagramSlideLayout.model_validate({**_layout([text or _text(), *regions], background="ink", density="MEDIUM"), "arrangement": "collage"})


def _medias(layout: InstagramSlideLayout):
    return [r for r in layout.regions if r.kind == "media"]


def _codes(layout: InstagramSlideLayout) -> set[str]:
    return set(validate_layout(layout, slide_copy=_COPY, resolvable_subjects={"source"}).rejection_codes)


def _overlap_share(a, b) -> float:
    return _inter_area(_rect(a), _rect(b)) / min(_area(_rect(a)), _area(_rect(b)))


FLAT = lambda: _collage(  # noqa: E731  three near-equal fragments: the primary is not clearly primary
    _media(0.05, 0.30, 0.42, 0.30, 1), _media(0.52, 0.32, 0.38, 0.30, 2, frame="torn", tilt=-4), _media(0.60, 0.68, 0.24, 0.20, 3, frame="die_cut", tilt=7))
COLLIDING = lambda: _collage(  # noqa: E731  the small die-cut fragment sits almost entirely inside the primary
    _media(0.10, 0.30, 0.70, 0.45, 1), _media(0.70, 0.20, 0.24, 0.20, 2, frame="torn", tilt=-5), _media(0.65, 0.60, 0.16, 0.13, 3, frame="die_cut", tilt=8))


# ------------------------------------------------------------------------------------------ thresholds are untouched


def test_validator_thresholds_are_unchanged() -> None:
    assert lv._COLLAGE_MAX_OVERLAP == 0.55 and lv._COLLAGE_MIN_HIERARCHY == 1.5 and lv._COLLAGE_MIN_SPREAD == 2.5
    assert ca.MAX_DISPLACEMENT == 0.12 and ca.MAX_SCALE_CHANGE == 0.20


# ------------------------------------------------------------------------------------------ hierarchy


def test_flat_collage_is_deterministically_given_a_clear_primary_and_passes_the_unchanged_validator() -> None:
    layout = FLAT()
    assert _codes(layout) == {"collage_hierarchy_flat"}
    first = adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    assert first is not None and first.validated.accepted and first.reasons == ("collage_hierarchy_flat",)
    areas = [_area(_rect(r)) for r in _medias(first.layout)]
    ordered = sorted(areas, reverse=True)
    assert ordered[0] >= 1.5 * ordered[1] and ordered[0] >= 2.5 * ordered[-1]
    original = _medias(layout)
    assert areas.index(max(areas)) == [_area(_rect(r)) for r in original].index(max(_area(_rect(r)) for r in original))  # the primary stays primary
    second = adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    assert first.executed_media_regions == second.executed_media_regions  # same input, same geometry
    assert first.max_scale_change <= MAX_SCALE_CHANGE and first.max_region_displacement == 0.0  # resizes only, nothing relocated


def test_the_adapter_only_changes_media_geometry_and_preserves_intent() -> None:
    layout = FLAT()
    adapted = adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"}).layout
    for before, after in zip(layout.regions, adapted.regions):
        assert (before.kind, before.z, before.content_ref, before.frame, before.tilt_deg, before.crop_mode, before.graphic_type, before.tone) == \
               (after.kind, after.z, after.content_ref, after.frame, after.tilt_deg, after.crop_mode, after.graphic_type, after.tone)
        if before.kind != "media":
            assert (before.x, before.y, before.w, before.h) == (after.x, after.y, after.w, after.h)
    assert (adapted.background, adapted.palette, adapted.logo_position, adapted.arrangement) == (layout.background, layout.palette, layout.logo_position, layout.arrangement)
    assert infer_family(adapted.model_dump()) == infer_family(layout.model_dump()) == "internet_culture_collage"


# ------------------------------------------------------------------------------------------ collision


def test_colliding_collage_is_repositioned_within_the_bound_smaller_fragment_first() -> None:
    layout = COLLIDING()
    assert _codes(layout) == {"media_regions_collide"}
    adapted = adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    assert adapted is not None and adapted.validated.accepted and adapted.reasons == ("media_regions_collide",)
    before, after = _medias(layout), _medias(adapted.layout)
    assert (after[0].x, after[0].y, after[0].w, after[0].h) == (before[0].x, before[0].y, before[0].w, before[0].h)  # the primary is fixed
    assert (after[1].x, after[1].y) == (before[1].x, before[1].y)                                                      # the uninvolved fragment is untouched
    assert (after[2].x, after[2].y) != (before[2].x, before[2].y)                                                      # the smaller colliding one moved
    assert all(_overlap_share(a, b) <= 0.55 for i, a in enumerate(after) for b in after[i + 1:])
    assert 0 < adapted.max_region_displacement <= MAX_DISPLACEMENT and adapted.max_scale_change == 0.0
    assert adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"}).executed_media_regions == adapted.executed_media_regions  # deterministic


def test_the_planned_layered_relation_survives_and_the_collage_does_not_become_a_grid() -> None:
    layout = COLLIDING()
    adapted = adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    after = _medias(adapted.layout)
    assert any(_inter_area(_rect(a), _rect(b)) > 0 for i, a in enumerate(after) for b in after[i + 1:])  # still layered, not three separate tiles
    areas = sorted((_area(_rect(r)) for r in after), reverse=True)
    assert areas[0] >= 1.5 * areas[1] and areas[0] >= 2.5 * areas[-1] and len({round(a, 3) for a in areas}) == 3
    assert [r.z for r in after] == [1, 2, 3]  # z-order preserved
    assert [r.tilt_deg for r in after] == [0, -5, 8] and [r.frame for r in after] == ["paper", "torn", "die_cut"]


# ------------------------------------------------------------------------------------------ fail closed


def test_an_impossible_collage_is_not_forced_and_keeps_the_legacy_fallback() -> None:
    impossible = _collage(_media(0.0, 0.0, 1.0, 1.0, 1), _media(0.4, 0.4, 0.2, 0.2, 2, frame="torn", tilt=-4), _media(0.7, 0.7, 0.2, 0.2, 3, frame="die_cut", tilt=6))
    assert "media_regions_collide" in _codes(impossible)
    assert adapt_collage(impossible, slide_copy=_COPY, resolvable_subjects={"source"}) is None  # cannot be resolved inside the bound
    photo = Image.new("RGB", (1200, 900), (90, 120, 160))
    ImageDraw.Draw(photo).ellipse([200, 150, 900, 700], fill=(230, 190, 60))
    carousel = _carousel_with([
        _slide("hook", "Первый экран", _layout([_r("text", 0.08, 0.2, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_L")]), slide_purpose="hook"),
        _slide("takeaway", _COPY, impossible.model_dump(), media_subject="source", media_function="hero", visual_family="internet_culture_collage",
               visual_family_reason="fragments", slide_purpose="takeaway"),
    ])
    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=photo, source_ref="r")
    results = render_instagram_carousel(_package_for(carousel), subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()})
    notes = results[1].evidence.notes
    assert notes["layout_plan_applied"] is False and "media_regions_collide" in notes["layout_plan_rejected"] and notes["fallback_role_layout_used"] is True
    assert notes.get("collage_geometry_adapted") is None and notes["overlay_operations_executed"] == 0


def test_unrelated_rejections_are_never_adapted() -> None:
    text_on_media = _collage(_media(0.10, 0.30, 0.70, 0.45, 1), _media(0.70, 0.20, 0.24, 0.20, 2), _media(0.65, 0.60, 0.16, 0.13, 3),
                             text=_r("text", 0.15, 0.35, 0.5, 0.2, content_ref="copy", scale_token="HEADLINE_L", align="left", valign="top", max_lines=3))
    assert {"media_regions_collide", "text_over_media"} <= _codes(text_on_media)
    assert adapt_collage(text_on_media, slide_copy=_COPY, resolvable_subjects={"source"}) is None  # a text/media problem is never "fixed" by moving fragments
    stage = InstagramSlideLayout.model_validate({**_layout([_text(), _media(0.1, 0.3, 0.7, 0.45, 1), _media(0.15, 0.35, 0.6, 0.4, 2)], density="MEDIUM"), "arrangement": "standard"})
    assert adapt_collage(stage, slide_copy=_COPY, resolvable_subjects={"source"}) is None  # not a collage


# ------------------------------------------------------------------------------------------ the real B.5.1.2 geometries


REAL = {  # media geometry the real Creative Director planned in B.5.1.2 (x, y, w, h, z, frame, tilt)
    "recap_slide_2": [(0.08, 0.36, 0.72, 0.48, 1, "paper", 0), (0.67, 0.20, 0.24, 0.20, 2, "torn", -6), (0.68, 0.73, 0.16, 0.13, 3, "die_cut", 7)],
    "recap_slide_6": [(0.08, 0.34, 0.76, 0.49, 1, "paper", 0), (0.67, 0.23, 0.24, 0.18, 2, "torn", 6), (0.70, 0.75, 0.15, 0.12, 3, "die_cut", -8)],
    "trend_hook": [(0.48, 0.08, 0.44, 0.34, 1, "paper", -5), (0.08, 0.48, 0.68, 0.30, 2, "torn", 3), (0.70, 0.58, 0.20, 0.16, 3, "die_cut", 8)],
}


@pytest.mark.parametrize("name", sorted(REAL))
def test_the_real_rejected_collage_plans_are_adapted_minimally(name: str) -> None:
    text = _r("text", 0.07, 0.10, 0.36, 0.25, content_ref="copy", scale_token="HEADLINE_L", align="left", valign="top", max_lines=4) if name == "trend_hook" else None
    layout = _collage(*[_media(x, y, w, h, z, frame=f, tilt=t) for x, y, w, h, z, f, t in REAL[name]], text=text)
    assert _codes(layout) in ({"media_regions_collide"}, {"collage_hierarchy_flat"})
    adapted = adapt_collage(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    assert adapted is not None and adapted.validated.accepted
    assert adapted.max_region_displacement <= 0.03 and adapted.max_scale_change <= 0.06  # a small nudge, not a rebuild


# ------------------------------------------------------------------------------------------ pipeline: executed family + observability


def test_pipeline_executes_the_collage_records_the_adaptation_and_the_family_matches(monkeypatch) -> None:
    photo = Image.new("RGB", (1200, 900), (90, 120, 160))
    ImageDraw.Draw(photo).ellipse([200, 150, 900, 700], fill=(230, 190, 60))
    plan = COLLIDING().model_dump()

    def build():
        carousel = _carousel_with([
            _slide("hook", "Первый экран", _layout([_r("text", 0.08, 0.2, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_L")]), slide_purpose="hook"),
            _slide("takeaway", _COPY, plan, media_subject="source", media_function="hero", visual_family="internet_culture_collage",
                   visual_family_reason="fragments", slide_purpose="takeaway"),
        ])
        assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=photo, source_ref="r")
        package = _package_for(carousel)
        return carousel, package, render_instagram_carousel(package, subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()})

    monkeypatch.setattr(ca, "adapt_collage", lambda *a, **k: None)  # BEFORE: without the adapter the plan falls back
    _, _, before = build()
    assert before[1].evidence.notes["layout_plan_applied"] is False and "media_regions_collide" in before[1].evidence.notes["layout_plan_rejected"]
    monkeypatch.undo()
    carousel, package, after = build()
    notes = after[1].evidence.notes
    assert notes["layout_plan_applied"] is True and notes["collage_geometry_adapted"] is True and notes["collage_adaptation_reasons"] == ["media_regions_collide"]
    assert len(notes["requested_media_regions"]) == len(notes["executed_media_regions"]) == 3
    assert notes["requested_media_regions"] != notes["executed_media_regions"] and notes["overlay_operations_executed"] == 0
    from services.instagram_art_validator import validate_instagram_art

    obs = build_b4_observability(carousel=carousel, prompt_version="9.1", renders=after, art=validate_instagram_art(package, after), slide_identities={}, deliberate_fallback_subjects=[])
    slide = obs["slides"][1]
    assert slide["visual_family_chosen"] == slide["visual_family_executed"] == "internet_culture_collage" and slide["visual_family_matches"] is True
    assert slide["collage_geometry_adapted"] is True and slide["max_region_displacement"] <= MAX_DISPLACEMENT and slide["executed_media_regions"]
    assert obs["slides"][0]["collage_geometry_adapted"] is None  # non-collage slides carry no collage fields
