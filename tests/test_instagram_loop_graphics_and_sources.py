"""Autonomous Product Quality Loop, iteration 4: graphic slides get the canvas and readable labels
(services.instagram_graphic_scale_adapter, services.instagram_declarative_layout._draw_flow), and a narrow vision check keeps
press / promo / text-card source images out of primary media (services.instagram_source_suitability)."""
from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

import services.instagram_source_suitability as suit
from schemas.instagram_creative import InstagramSlideLayout
from services.instagram_carousel_layouts import render_carousel_slide
from services.instagram_declarative_layout import GRAPHIC_LABEL_MIN_FRAC
from services.instagram_graphic_scale_adapter import MIN_GRAPHIC_AREA, adapt_graphic_scale
from services.instagram_layout_validation import validate_layout
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

SPEC = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)


def _r(kind, x, y, w, h, **kw):
    return {"kind": kind, "x": x, "y": y, "w": w, "h": h, "z": kw.pop("z", 1), **kw}


# the EXACT real iteration-3 NEWS_INSIGHT graphic slide: a 0.84 x 0.28 flow strip under a HEADLINE_L title
REAL_FLOW = {
    "background": "graphite", "density": "LOW", "media_dominance": "NONE", "visual_weight": "GRAPHIC", "show_progress": True,
    "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    "regions": [
        _r("surface", 0, 0, 1, 1, z=0, surface="graphite"),
        _r("text", 0.08, 0.1, 0.76, 0.16, z=2, content_ref="copy", scale_token="HEADLINE_L", on_media=False),
        _r("graphic", 0.08, 0.43, 0.84, 0.28, graphic_type="flow_diagram", flow_steps=["ЗАДАЧА", "ЕЁ СТОИМОСТЬ", "ВЫБОР"]),
    ],
}
REAL_FLOW_COPY = "Сначала — задача. Потом — модель."


def _render_graphic(layout, copy=REAL_FLOW_COPY):
    return render_carousel_slide(spec=SPEC, role="evidence", index=2, total=4, slide_copy=copy, source_evidence=None, package_identity="p",
                                 media_mode=None, layout_plan=layout, subject_assets={})


def _ink_share(image, box):
    """share of non-background pixels inside a normalized box - how much of it the graphic actually fills"""
    x0, y0, x1, y1 = (round(box[0] * image.width), round(box[1] * image.height), round(box[2] * image.width), round(box[3] * image.height))
    crop = image.convert("RGB").crop((x0, y0, x1, y1))
    bg = image.convert("RGB").getpixel((5, image.height - 5))
    px = list(crop.getdata())
    return sum(1 for p in px if max(abs(p[i] - bg[i]) for i in range(3)) > 12) / len(px)


def test_the_real_thin_flow_strip_is_given_the_canvas():
    plan = InstagramSlideLayout.model_validate(REAL_FLOW)
    adapted, notes = adapt_graphic_scale(plan)
    graphic = next(r for r in adapted.regions if r.kind == "graphic")
    assert graphic.w * graphic.h >= MIN_GRAPHIC_AREA > 0.84 * 0.28 and notes["graphic_scale_adapted"] is True
    assert validate_layout(adapted, slide_copy=REAL_FLOW_COPY, resolvable_subjects=set()).accepted
    result = _render_graphic(REAL_FLOW)
    assert "graphic_scale_adapted" in result.notes["layout_adaptations"] and result.notes["graphic_scale_adapted"] is True
    assert _ink_share(result.image, (0.07, 0.39, 0.93, 0.80)) > 0.5  # the cards fill the graphic box, no dead zone around tiny boxes
    headline = max(m["font_px"] for m in result.notes["text_metrics"] if m["ref"] == "copy")
    assert headline >= 0.075 * SPEC.width


def test_flow_labels_are_fitted_to_the_cards_not_a_fixed_small_size():
    import services.instagram_declarative_layout as dl
    sizes = []
    real = dl._fit_label

    def spy(*a, **kw):
        out = real(*a, **kw)
        sizes.append(out[0].size)
        return out

    dl._fit_label = spy
    try:
        _render_graphic(REAL_FLOW)
    finally:
        dl._fit_label = real
    assert len(sizes) == 3 and min(sizes) >= round(GRAPHIC_LABEL_MIN_FRAC * SPEC.width) > round(0.027 * SPEC.width)


def test_slides_with_media_decorative_marks_or_an_already_large_graphic_are_untouched():
    with_media = {**REAL_FLOW, "regions": [*REAL_FLOW["regions"], _r("media", 0.5, 0.75, 0.3, 0.1, content_ref="generated", crop_mode="cover")]}
    assert adapt_graphic_scale(InstagramSlideLayout.model_validate(with_media)) is None
    big = {**REAL_FLOW, "regions": [*REAL_FLOW["regions"][:2], _r("graphic", 0.07, 0.35, 0.86, 0.45, graphic_type="flow_diagram", flow_steps=["A", "B"])]}
    assert adapt_graphic_scale(InstagramSlideLayout.model_validate(big)) is None
    decorative = {**REAL_FLOW, "regions": [*REAL_FLOW["regions"][:2], _r("graphic", 0.1, 0.5, 0.1, 0.06, graphic_type="burst")]}
    assert adapt_graphic_scale(InstagramSlideLayout.model_validate(decorative)) is None


def test_poll_cards_are_scaled_too():
    poll = {**REAL_FLOW, "regions": [
        REAL_FLOW["regions"][0],
        _r("text", 0.08, 0.08, 0.8, 0.12, z=2, content_ref="copy_lead", scale_token="HEADLINE_M", on_media=False),
        _r("graphic", 0.08, 0.3, 0.84, 0.3, graphic_type="poll_cards"),
    ]}
    result = _render_graphic(poll, copy="Какую модель берёшь? Самую умную | Самую дешёвую | Под задачу")
    assert result.notes.get("graphic_scale_adapted") is True and result.text_clipped is False


# ------------------------------------------------------------------------------------------ source suitability (vision)


def test_the_verdict_is_decided_from_structured_fields():
    assert suit.decide({"image_kind": "promo_or_press_graphic", "baked_in_text_prominent": True, "primary_media_suitable": False}) is False
    assert suit.decide({"image_kind": "photograph", "baked_in_text_prominent": True, "primary_media_suitable": True}) is False
    assert suit.decide({"image_kind": "article_or_news_card", "baked_in_text_prominent": False, "primary_media_suitable": True}) is False
    assert suit.decide({"image_kind": "product_render", "baked_in_text_prominent": False, "primary_media_suitable": True}) is True
    assert suit.decide({"image_kind": "photograph", "baked_in_text_prominent": False, "primary_media_suitable": True}) is True


class _Repo:
    def resolve(self, name, version):
        import yaml
        from pathlib import Path
        d = yaml.safe_load((Path(__file__).resolve().parent.parent / "prompts" / name / f"v{version}.yaml").read_text(encoding="utf-8"))
        return SimpleNamespace(system=d["system"], rules=d["rules"], output_schema=d["output_schema"])


def _fake_vision(answers, seen):
    async def call(gateway, request, runtime):
        seen.append(request)
        key = len(seen) - 1
        answer = answers[key]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(error=None, response=SimpleNamespace(structured_output=answer), call=None)
    return call


def test_only_this_posts_candidates_are_checked_one_small_image_each_and_errors_keep_the_deterministic_verdict(monkeypatch):
    seen: list = []
    answers = [
        {"image_kind": "promo_or_press_graphic", "baked_in_text_prominent": True, "primary_media_suitable": False, "reason": "app icon + wordmark"},
        RuntimeError("provider down"),
    ]
    monkeypatch.setattr(suit, "_call_vision", _fake_vision(answers, seen))
    big = Image.new("RGB", (2400, 1600), (40, 90, 60))
    verdicts = asyncio.run(suit.check_primary_suitability(object(), _Repo(), [("story_1", big), ("story_2", big)]))
    assert verdicts["story_1"].suitable is False and verdicts["story_2"].suitable is None and verdicts["story_2"].error
    part = seen[0].messages[1].content[1]
    assert part.mime_type == "image/jpeg" and part.artifact_ref.startswith("data:image/jpeg;base64,")
    import base64
    decoded = Image.open(BytesIO(base64.b64decode(part.artifact_ref.split(",", 1)[1])))
    assert max(decoded.size) <= 768 and seen[0].modalities == ["text", "image"]


def test_the_number_of_checks_per_post_is_bounded(monkeypatch):
    seen: list = []
    ok = {"image_kind": "photograph", "baked_in_text_prominent": False, "primary_media_suitable": True, "reason": "a photo"}
    monkeypatch.setattr(suit, "_call_vision", _fake_vision([ok] * 20, seen))
    img = Image.new("RGB", (800, 600))
    asyncio.run(suit.check_primary_suitability(object(), _Repo(), [(f"s{i}", img) for i in range(20)]))
    assert len(seen) == suit.MAX_CHECKS_PER_POST


def _photo_like():
    """many hues at the profile's 96px scale - passes the deterministic flat-card test, so it is a real vision candidate"""
    return Image.merge("RGB", (
        Image.linear_gradient("L").resize((1200, 900)), Image.linear_gradient("L").rotate(90).resize((1200, 900)),
        Image.radial_gradient("L").resize((1200, 900))))


def test_a_vision_unsuitable_source_is_marked_unsuitable_everywhere_the_director_and_the_contract_read_it(monkeypatch):
    import services.instagram_automatic_trigger as trig
    from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory

    def png(img):
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    photo, flat_card = _photo_like(), Image.new("RGB", (1200, 900), (250, 250, 250))
    bundle = InstagramRecapBundle(stories=(
        RecapStory(key="story_1", story_id="1", event_id="1", title="Wallet", evidence=["[story_1] a"], image_bytes=png(photo), source_ref="1"),
        RecapStory(key="story_2", story_id="2", event_id="2", title="Card", evidence=["[story_2] b"], image_bytes=png(flat_card), source_ref="2"),
    ))
    seen: list = []
    promo = {"image_kind": "promo_or_press_graphic", "baked_in_text_prominent": True, "primary_media_suitable": False, "reason": "promo"}
    monkeypatch.setattr(suit, "_call_vision", _fake_vision([promo], seen))
    flagged = asyncio.run(trig._vision_unsuitable_subjects(gateway=object(), prompt_repository=_Repo(), source_image=None, recap_bundle=bundle))
    assert flagged == frozenset({"story_1"}) and len(seen) == 1  # the deterministic flat card is never sent to vision
    _, unsuitable = trig._carousel_media_subjects(source_image=None, recap_bundle=bundle, vision_unsuitable=flagged)
    assert set(unsuitable) == {"story_1", "story_2"}
    note = trig._carousel_media_note(source_image=None, recap_bundle=bundle, media_first=True, vision_unsuitable=flagged)
    story_1_line = next(line for line in note.splitlines() if line.startswith("subject key 'story_1'"))
    assert "SOURCE_SUITABLE_FOR_FINAL_VISUAL: NO" in story_1_line


# ------------------------------------------------------------------------------------------ iteration 5 (real iteration-4 findings)


def test_a_slide_carrying_both_an_image_and_a_graphic_gives_each_a_band():
    """real iteration-4 AI_HACK slide: media 0.46x0.78 + a flow strip + a narrow text column -> 55px headline, 0.36 media coverage.
    Neither adapter owned it (one refuses graphics, the other refuses media), so nothing grew."""
    from services.instagram_media_scale_adapter import adapt_media_scale
    mixed_plan = {**REAL_FLOW, "regions": [
        REAL_FLOW["regions"][0],
        _r("media", 0, 0.22, 0.46, 0.78, content_ref="generated", crop_mode="cover"),
        _r("text", 0.54, 0.08, 0.38, 0.16, z=2, content_ref="copy", scale_token="HEADLINE_L", on_media=False),
        _r("graphic", 0.54, 0.35, 0.38, 0.28, graphic_type="flow_diagram", flow_steps=["ДЛИННЫЙ ТЕКСТ", "РЕШЕНИЯ", "ЧИСТЫЙ ВЫВОД"]),
    ]}
    copy = "Шаг 1. Оставь только решения."
    adaptation = adapt_media_scale(InstagramSlideLayout.model_validate(mixed_plan), slide_copy=copy)  # the image is under the area floor
    assert adaptation.orientation == "mixed_bands"
    kinds = [r.kind for r in adaptation.layout.regions]
    assert kinds.count("media") == 1 and kinds.count("graphic") == 1  # nothing paid for, and nothing informative, is dropped

    img = Image.new("RGB", (1024, 1280), (90, 90, 96))
    result = render_carousel_slide(spec=SPEC, role="step", index=1, total=4, slide_copy=copy, source_evidence=None, package_identity="p",
                                   media_image=img, media_mode="GENERATED", layout_plan=mixed_plan, subject_assets={"generated": (img, "i")})
    from services.instagram_carousel_layouts import HEADLINE_FLOOR_FRAC
    headline = max(m["font_px"] for m in result.notes["text_metrics"] if m["ref"] == "copy")
    assert result.notes["media_scale_orientation"] == "mixed_bands" and headline >= HEADLINE_FLOOR_FRAC * SPEC.width
    assert result.notes["media_canvas_coverage"] > 0.36


def test_a_photographed_manuscript_is_not_rejected_for_its_own_writing():
    """real iteration-4 false positive: the Apollo papyrus was called unsuitable because its ancient writing is 'prominent text'"""
    papyrus = {"image_kind": "illustration_or_artwork", "baked_in_text_prominent": False, "primary_media_suitable": False,
               "reason": "a classical bust over a manuscript"}
    assert suit.decide(papyrus) is True  # the model's own overall opinion no longer vetoes a real picture
    assert suit.decide({"image_kind": "promo_or_press_graphic", "baked_in_text_prominent": False, "primary_media_suitable": True}) is False
    assert suit.decide({"image_kind": "illustration_or_artwork", "baked_in_text_prominent": True, "primary_media_suitable": True}) is False


def test_the_suitability_prompt_v2_separates_added_text_from_the_photographed_subject():
    import yaml
    from pathlib import Path
    prompts = Path(__file__).resolve().parent.parent / "prompts" / "instagram_source_visual_suitability"
    v1 = yaml.safe_load((prompts / "v1.yaml").read_text(encoding="utf-8"))
    v2 = yaml.safe_load((prompts / "v2.yaml").read_text(encoding="utf-8"))
    assert v1["version"] == "1" and v2["version"] == "2" and suit.PROMPT_VERSION == "2"
    assert v2["output_schema"] == v1["output_schema"] and v2["system"] == v1["system"]
    baked = next(r for r in v2["rules"] if r.startswith("baked_in_text_prominent"))
    assert "ADDED ON TOP" in baked and "manuscript" in baked


def test_a_recoverable_contract_miss_is_retried_once_with_what_it_broke(monkeypatch):
    """real iteration-4 TREND_GENERATIVE: one missing source_evidence handle killed the whole post"""
    import services.instagram_automatic_trigger as trig
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_media_first import MediaFirstContractError

    attempts: list = []

    async def regenerator(director_input, fmt):
        attempts.append(director_input)
        if len(attempts) == 1:
            raise MediaFirstContractError("slide 0: a generated slide needs source_evidence (a cited evidence handle)")
        return "ok"

    monkeypatch.setattr(trig, "build_default_regenerator", lambda gateway, repo: regenerator)
    src = "\n".join(__import__("inspect").getsource(trig.evaluate_and_submit_instagram_opportunity).splitlines())
    assert "contract_retry_note=" in src and "MediaFirstContractError as exc" in src
    base = CreativeDirectorInput(objective="o", format="carousel", opportunity_summary="s", allowed_evidence=["E"], approved_claims=[], restricted_claims=[])
    assert base.contract_retry_note == ""  # never set on a first attempt: existing request text stays byte-identical

    from dataclasses import replace as dc_replace
    retried = dc_replace(base, contract_retry_note="slide 0: needs source_evidence")
    from services.instagram_creative_director import _build_user_text
    assert "PREVIOUS ATTEMPT REJECTED: slide 0: needs source_evidence" in _build_user_text(retried)
    assert "PREVIOUS ATTEMPT REJECTED" not in _build_user_text(base)
