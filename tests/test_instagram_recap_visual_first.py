"""Weekly recap product pass (2026-09-26): a recap is VISUAL-FIRST.
  - each story's picture may come from any of its OWN premise-relevant events (a real photo beats the representative's flat text card),
    never from a polluted Story member and never from another story;
  - a news_recap carousel is planned with prompt 10.10 (weekly-roundup cover, image-led story beats, fact blocks only as a fallback);
    every other archetype keeps 10.9;
  - every story needs a slide of its OWN: the week's cover and the closer never stand in for a story.
No provider, no network."""
from __future__ import annotations

import io
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

import services.instagram_creative_director as cd
import services.instagram_recap_bundle as bundle_module
from integrations.prompts.file_repository import FilePromptRepository
from tests.test_instagram_downstream_blockers import _carousel, _flow, _poll

PROMPTS = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")


def _photo(seed: int, size=(1200, 800)) -> bytes:
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for _ in range(400):  # many colours: a photo, not a flat card
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        draw.ellipse([x, y, x + rnd.randrange(20, 160), y + rnd.randrange(20, 160)],
                     fill=(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _card() -> bytes:
    img = Image.new("RGB", (1200, 630), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    for row in range(8):  # a flat headline / article card: rows of thin dark "text" strokes across a white page
        for col in range(0, 1080, 18):
            draw.rectangle([60 + col, 60 + row * 64, 60 + col + 9, 60 + row * 64 + 28], fill=(30, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _store(monkeypatch, by_event: dict):
    async def candidates(session, *, news_event_id, limit):
        return [SimpleNamespace(candidate_id=f"{news_event_id}:{i}", is_expired=False, data=d) for i, d in enumerate(by_event.get(news_event_id, []))]

    monkeypatch.setattr(bundle_module, "get_editorial_image_candidates", candidates)
    monkeypatch.setattr(bundle_module, "read_candidate_bytes", lambda c: c.data)


@pytest.mark.asyncio
async def test_a_member_events_real_photo_beats_the_representatives_flat_card(monkeypatch):
    rep, member = uuid4(), uuid4()
    photo = _photo(1)
    _store(monkeypatch, {rep: [_card()], member: [photo]})
    data, ref = await bundle_module._story_media(object(), [rep, member])
    assert data == photo and ref == f"{member}:0"


@pytest.mark.asyncio
async def test_the_representatives_own_photo_still_comes_first(monkeypatch):
    rep, member = uuid4(), uuid4()
    own = _photo(2)
    _store(monkeypatch, {rep: [own], member: [_photo(3)]})
    assert (await bundle_module._story_media(object(), [rep, member]))[0] == own


@pytest.mark.asyncio
async def test_a_flat_card_is_only_a_fallback_and_a_tiny_image_never_carries_a_slide(monkeypatch):
    rep, member = uuid4(), uuid4()
    card = _card()
    _store(monkeypatch, {rep: [card], member: [_photo(4, size=(300, 300))]})
    assert (await bundle_module._story_media(object(), [rep, member]))[0] == card


def test_only_premise_relevant_member_events_may_give_the_story_its_picture():
    rep, relevant, polluted = uuid4(), uuid4(), uuid4()
    headlines = ["Google Assistant will disappear from your phone next month"]
    bodies = [(f"event:{relevant}:article", "Google Assistant is going away: Google will replace Google Assistant with Gemini on Android phones "
                                             "starting September 4, the company said."),
              (f"event:{polluted}:body", "The best microwaves of 2026, tested: our favourite models for every kitchen and budget.")]
    ids = bundle_module._kept_event_ids(headlines[0], headlines, bodies, rep)
    assert relevant in ids and polluted not in ids


def test_discovery_is_off_unless_image_intelligence_is_on(monkeypatch):
    from core.config import settings

    assert settings.image_intelligence_mode == "off"  # production default: the recap reads stored candidates only


@pytest.mark.asyncio
async def test_recap_uses_prompt_10_10_and_other_archetypes_keep_10_9(monkeypatch):
    seen = []

    async def call(gateway, repo, *, prompt_name, director_input, prompt_version):
        seen.append(prompt_version)
        return {}, None

    carousel = SimpleNamespace(slides=[SimpleNamespace(role="story", media_subject=f"story_{i}") for i in range(1, 5)])
    monkeypatch.setattr(cd, "_call_creative_director", call)
    monkeypatch.setattr(cd, "_validate_carousel_output", lambda *a, **kw: SimpleNamespace(carousel=carousel))
    recap = cd.CreativeDirectorInput(objective="o", format="carousel", opportunity_summary="s", is_recap_bundle=True, planned_format="WEEKLY_RECAP",
                                     planned_archetype="news_recap", recap_required_subjects=[f"story_{i}" for i in range(1, 5)])
    await cd.generate_carousel_creative(object(), PROMPTS, director_input=recap)
    hack = cd.CreativeDirectorInput(objective="o", format="carousel", opportunity_summary="s", planned_format="AI_HACK", planned_archetype="ai_hack")
    await cd.generate_carousel_creative(object(), PROMPTS, director_input=hack)
    assert seen == ["10.10", "10.9"]
    text = PROMPTS.resolve(cd.CAROUSEL_PROMPT_NAME, "10.10").rules
    assert any("WEEKLY ROUNDUP" in r and "WEEK''S COVER".replace("''", "'") in r for r in text)


def test_prompt_10_10_changes_only_the_news_recap_direction():
    old = PROMPTS.resolve(cd.CAROUSEL_PROMPT_NAME, "10.9")
    new = PROMPTS.resolve(cd.CAROUSEL_PROMPT_NAME, "10.10")
    assert old.system == new.system and old.output_schema == new.output_schema and len(old.rules) == len(new.rules)
    changed = [i for i, (a, b) in enumerate(zip(old.rules, new.rules)) if a != b]
    assert len(changed) == 1 and "news_recap" in new.rules[changed[0]]
    for marker in ("ai_hack:", "news_insight:", "trend_generative:"):  # the other archetypes' text is untouched
        assert old.rules[changed[0]].split(marker)[1][:200] == new.rules[changed[0]].split(marker)[1][:200]


@pytest.mark.asyncio
async def test_a_story_carried_only_by_the_cover_or_the_closer_is_not_covered(monkeypatch):
    slides = [SimpleNamespace(role="hook", media_subject="story_1")] + [
        SimpleNamespace(role="story", media_subject=f"story_{i}") for i in range(2, 5)] + [SimpleNamespace(role="closing", media_subject="story_1")]
    monkeypatch.setattr(cd, "_call_creative_director", AsyncMock(return_value=({}, None)))
    monkeypatch.setattr(cd, "_validate_carousel_output", lambda *a, **kw: SimpleNamespace(carousel=SimpleNamespace(slides=slides)))
    director_input = cd.CreativeDirectorInput(objective="o", format="carousel", opportunity_summary="s", is_recap_bundle=True, planned_format="WEEKLY_RECAP",
                                              planned_archetype="news_recap", recap_required_subjects=[f"story_{i}" for i in range(1, 5)])
    with pytest.raises(cd.MediaFirstContractError, match=r"story_1"):
        await cd.generate_carousel_creative(object(), PROMPTS, director_input=director_input)


# --- the rendered result: cover grid, closing strip, one photo per story, one sentence of context ------------------------------------

def _plan(media_refs, role_extra=()):
    regions = [{"kind": "surface", "x": 0, "y": 0, "w": 1, "h": 1, "z": 0, "surface": "ink"}]
    regions += [{"kind": "media", "x": 0.1 * i, "y": 0.5, "w": 0.3, "h": 0.2 + 0.05 * i, "z": 1 + i, "content_ref": ref, "tilt_deg": 4.0,
                 "frame": "torn"} for i, ref in enumerate(media_refs)]
    regions += [{"kind": "text", "x": 0.07, "y": 0.08, "w": 0.36, "h": 0.2, "z": 6, "content_ref": "copy_lead"}, *role_extra]
    return {"background": "ink", "arrangement": "collage", "density": "HIGH", "media_dominance": "BALANCED", "visual_weight": "MIXED",
            "regions": regions}


def test_a_recap_cover_showing_several_stories_becomes_a_clean_grid_under_the_copy():
    from services.instagram_recap_frames import recap_frame_layout

    framed = recap_frame_layout(_plan(["story_2", "story_3", "story_5", "story_7", "story_2"]), role="hook")
    media = [r for r in framed["regions"] if r["kind"] == "media"]
    assert [r["content_ref"] for r in media] == ["story_2", "story_3", "story_5", "story_7"]  # the Director's stories, its order, once each
    assert all(r["frame"] == "none" and "tilt_deg" not in r for r in media) and framed["arrangement"] == "standard"
    text = [r for r in framed["regions"] if r["kind"] == "text"]
    assert {r["content_ref"] for r in text} == {"copy", "body"} and max(r["y"] + r["h"] for r in text) <= min(r["y"] for r in media)
    for a in media:  # tiles never overlap
        for b in media:
            if a is not b:
                assert a["x"] + a["w"] <= b["x"] + 1e-9 or b["x"] + b["w"] <= a["x"] + 1e-9 or a["y"] + a["h"] <= b["y"] + 1e-9 or b["y"] + b["h"] <= a["y"] + 1e-9


def test_the_closer_gets_landscape_tiles_and_fewer_than_three_stories_or_a_story_slide_keep_their_plan():
    from services.instagram_recap_frames import recap_frame_layout

    tiles = [r for r in recap_frame_layout(_plan(["story_1", "story_4", "story_6", "story_7"]), role="closing")["regions"] if r["kind"] == "media"]
    assert len(tiles) == 4 and all(r["w"] * 1080 > r["h"] * 1350 for r in tiles)  # wide tiles for wide news photos, never slivers
    assert recap_frame_layout(_plan(["story_1", "story_4"]), role="hook") is None
    assert recap_frame_layout(_plan(["story_1", "story_4", "story_6"]), role="story") is None


def test_a_story_slide_shows_its_photo_once():
    from services.instagram_recap_frames import single_photo_story_layout

    plan = _plan(["story_7", "story_7", "story_7"])
    plan["regions"][3].update({"x": 0.0, "y": 0.45, "w": 1.0, "h": 0.55})  # the largest crop: a dominant photo band
    single = single_photo_story_layout(plan, role="story")
    media = [r for r in single["regions"] if r["kind"] == "media"]
    assert len(media) == 1 and media[0]["h"] == pytest.approx(0.55)  # the largest crop is the one kept
    assert single_photo_story_layout(_plan(["story_7"]), role="story") is None


def test_a_recap_body_is_shortened_only_at_a_sentence_boundary():
    from services.instagram_carousel_layouts import _first_sentence

    assert _first_sentence("GPT-5.6 Luna теперь доступна бесплатно. OpenAI также убирает лимиты.") == "GPT-5.6 Luna теперь доступна бесплатно."
    assert _first_sentence("Показ 27 августа в 22:00 по Москве.") == "Показ 27 августа в 22:00 по Москве."


@pytest.mark.asyncio
async def test_a_recap_cover_with_one_storys_image_goes_back_to_the_director(monkeypatch):
    region = lambda ref: SimpleNamespace(kind="media", content_ref=ref)  # noqa: E731
    hook = SimpleNamespace(role="hook", media_subject="story_1", layout=SimpleNamespace(regions=[region("story_1")]))
    slides = [hook] + [SimpleNamespace(role="story", media_subject=f"story_{i}", layout=None) for i in range(1, 5)]
    monkeypatch.setattr(cd, "_call_creative_director", AsyncMock(return_value=({}, None)))
    monkeypatch.setattr(cd, "_validate_carousel_output", lambda *a, **kw: SimpleNamespace(carousel=SimpleNamespace(slides=slides)))
    keys = [f"story_{i}" for i in range(1, 5)]
    director_input = cd.CreativeDirectorInput(objective="o", format="carousel", opportunity_summary="s", is_recap_bundle=True, planned_format="WEEKLY_RECAP",
                                              planned_archetype="news_recap", recap_required_subjects=keys, available_media_subjects=tuple(keys))
    with pytest.raises(cd.MediaFirstContractError, match="weekly recap cover"):
        await cd.generate_carousel_creative(object(), PROMPTS, director_input=director_input)
    hook.layout.regions = [region(k) for k in keys[:3]]
    await cd.generate_carousel_creative(object(), PROMPTS, director_input=director_input)  # three stories on the cover: accepted
    no_photos = cd.CreativeDirectorInput(**{**director_input.__dict__, "available_media_subjects": ("story_1",)})
    hook.layout.regions = [region("story_1")]
    await cd.generate_carousel_creative(object(), PROMPTS, director_input=no_photos)  # fewer than three photos exist: not required


def test_the_rendered_recap_cover_and_closer_keep_every_story_they_show():
    """Real rendering: a cover / closer collage of four stories stays four stories (it used to collapse to one edge-to-edge photo)."""
    from services.instagram_carousel_layouts import render_carousel_slide
    from services.instagram_platform_renderer import InstagramRenderProfile, profile_spec

    assets = {f"story_{i}": (Image.open(io.BytesIO(_photo(i))), f"id{i}") for i in range(1, 5)}
    for role in ("hook", "closing"):
        result = render_carousel_slide(
            spec=profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE), role=role, index=0 if role == "hook" else 8, total=9,
            slide_copy="Неделя, когда ИИ вышел из чата", slide_body="Google отключает Assistant, Meta выпускает Muse, OpenAI делает колонку.",
            source_evidence=None, package_identity="p", media_mode="SOURCE", layout_plan=_plan([f"story_{i}" for i in range(1, 5)]),
            subject_assets=assets, recap=True)
        assert [m["subject"] for m in result.notes["media_regions"]] == [f"story_{i}" for i in range(1, 5)], role
        assert result.notes.get("recap_frame") is True


# --- final product verification fixes -----------------------------------------------------------------------------------------------

def test_a_cover_headline_that_repeats_a_story_headline_is_caught_and_a_week_headline_is_not():
    story = lambda copy, key: SimpleNamespace(role="story", slide_copy=copy, media_subject=key)  # noqa: E731
    hook = lambda copy: SimpleNamespace(role="hook", slide_copy=copy)  # noqa: E731
    stories = [story("Assistant уходит 4 сентября", "story_2"), story("GTA VI забирает финал недели", "story_7")]
    assert cd._cover_repeats_a_story([hook("4 сентября Assistant исчезнет"), *stories])[1] == "story_2"  # the real recap v2 cover
    assert cd._cover_repeats_a_story([hook("7 историй недели: от Gemini до GTA VI"), *stories]) is None
    assert cd._cover_repeats_a_story([hook("Неделя, когда ИИ вышел за пределы чата"), *stories]) is None


def test_a_story_slides_duplicate_crops_leave_decoration_behind_and_a_small_single_photo_keeps_the_plan():
    from services.instagram_recap_frames import single_photo_story_layout

    plan = _plan(["story_7", "story_7"])
    plan["regions"][1].update({"x": 0.04, "y": 0.43, "w": 0.92, "h": 0.48})
    plan["regions"].append({"kind": "graphic", "x": 0.07, "y": 0.25, "w": 0.2, "h": 0.05, "z": 7, "graphic_type": "underline_scribble"})
    single = single_photo_story_layout(plan, role="story")
    assert not any(r.get("graphic_type") == "underline_scribble" for r in single["regions"])
    headline = next(r for r in single["regions"] if r["kind"] == "text")
    assert (headline["x"], headline["w"]) == (0.07, 0.86)  # the copy takes the removed crops' width above the photo
    small = _plan(["story_3", "story_3", "story_3"])  # every crop smaller than the dominance bound
    assert single_photo_story_layout(small, role="story") is None


def test_a_side_panel_headline_sits_right_above_its_body():
    from schemas.instagram_creative import InstagramSlideLayout
    from services.instagram_media_scale_adapter import adapt_media_scale

    layout = InstagramSlideLayout.model_validate({
        "background": "ink", "density": "MEDIUM", "media_dominance": "BALANCED", "visual_weight": "MIXED",
        "regions": [{"kind": "surface", "x": 0, "y": 0, "w": 1, "h": 1}, {"kind": "media", "x": 0.55, "y": 0.2, "w": 0.4, "h": 0.4, "content_ref": "story_3"},
                    {"kind": "text", "x": 0.07, "y": 0.2, "w": 0.4, "h": 0.2, "content_ref": "copy"},
                    {"kind": "text", "x": 0.07, "y": 0.5, "w": 0.4, "h": 0.1, "content_ref": "body"}]})
    adapted = adapt_media_scale(layout, slide_copy="Meta делает Muse\n\nВ семействе — Muse Spark.", force=True, orientation="side_right")
    texts = {r.content_ref: r for r in adapted.layout.regions if r.kind == "text"}
    assert texts["copy"].valign == "bottom" and texts["body"].valign == "top"
    banded = adapt_media_scale(layout, slide_copy="Meta делает Muse\n\nВ семействе — Muse Spark.", force=True, orientation="text_top")
    assert all(r.valign == "top" for r in banded.layout.regions if r.kind == "text")  # bands are unchanged



# --- final visual remediation: no meaningless fact cells, no truncated words, subject-aware framing ------------------------------------

def test_topic_labels_roles_and_truncated_words_are_not_fact_cells_but_real_numbers_are():
    from services.instagram_recap_frames import meaningful_fact_graphic

    safety = "Модели OpenAI и Anthropic пошли вразнос. Британский AI Security Institute сообщил о harmful activity во время тестирования."
    assert not meaningful_fact_graphic(["Тестирование", "Поведение моделей", "Риск выявлен"], safety)
    hassabis = "У Demis Hassabis новая роль. Он оставляет должность CEO Google DeepMind и становится председателем подразделения."
    assert not meaningful_fact_graphic(["CEO Google DeepMind", "Председатель подраздел"], hassabis)  # 'подраздел' is a cut word
    assert meaningful_fact_graphic(["30B параметров", "1 GPU", "Muse Glimmer"], "Muse Glimmer: 30B параметров, 1 GPU.")


def test_a_weak_fact_cell_story_becomes_an_editorial_slide_with_its_photo_away_from_the_logo():
    from services.instagram_recap_frames import editorial_story_layout

    plan = _plan(["story_4"])
    plan["logo_position"] = "BOTTOM_LEFT"
    plan["regions"].append({"kind": "graphic", "x": 0.07, "y": 0.6, "w": 0.86, "h": 0.25, "z": 3, "graphic_type": "flow_diagram",
                            "flow_steps": ["Тестирование", "Поведение моделей", "Риск выявлен"]})
    editorial = editorial_story_layout(plan, role="story", slide_text="Модели пошли вразнос. Институт сообщил о тестировании.")
    kinds = [r["kind"] for r in editorial["regions"]]
    assert "graphic" not in kinds and kinds.count("media") == 1 and {"copy", "body"} <= {r.get("content_ref") for r in editorial["regions"]}
    photo = next(r for r in editorial["regions"] if r["kind"] == "media")
    assert photo["x"] > 0.3  # the logo sits bottom-left: the photo takes the right side
    data = _plan(["story_3"])
    data["regions"].append({"kind": "graphic", "x": 0.07, "y": 0.6, "w": 0.86, "h": 0.25, "z": 3, "graphic_type": "flow_diagram",
                            "flow_steps": ["30B параметров", "1 GPU"]})
    assert editorial_story_layout(data, role="story", slide_text="30B параметров, 1 GPU.") is None  # real data keeps its graphic


def _subject_photo(size=(2000, 1000), box=(200, 250, 700, 950)) -> Image.Image:
    img = Image.new("RGB", size, (40, 40, 44))
    draw = ImageDraw.Draw(img)
    rnd = random.Random(7)
    for _ in range(300):  # a busy, colourful subject on the LEFT of a flat wide frame
        x, y = rnd.randrange(box[0], box[2]), rnd.randrange(box[1], box[3])
        draw.ellipse([x, y, x + 60, y + 60], fill=(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    return img


def test_a_photo_is_framed_on_its_subject_not_on_the_rectangle_centre():
    from services.instagram_focal_crop import cover_window, focus_of, frame_photo

    img = _subject_photo()
    focus = focus_of(img)
    assert focus.x < 0.4 and focus.box[2] <= 0.45  # the subject is found on the left
    window = cover_window(img.size, (500, 500), focus)
    assert window[0] <= focus.box[0] + 0.02 and window[2] >= focus.box[2] - 0.02  # the square crop keeps it, a centre crop would not
    _tile, treatment = frame_photo(img, 500, 500)
    assert treatment == "focal_cover"
    _tile, treatment = frame_photo(_subject_photo(box=(100, 250, 1900, 950)), 200, 600)  # a wide subject in a tall slot
    assert treatment == "whole_on_blurred_extension"  # never a sliver of the subject


def test_focal_framing_is_on_for_the_recap_only():
    from services.instagram_declarative_layout import FOCAL_FRAMING

    assert FOCAL_FRAMING.get() is False


# --- final cropping + closing-slide polish: photo-shaped framing, subscription end card -----------------------------------------------

def test_the_cover_mosaic_gives_each_photo_a_tile_of_its_own_shape():
    from services.instagram_recap_frames import CANVAS_ASPECT, recap_frame_layout

    aspects = {"story_2": 2.0, "story_5": 1.5, "story_3": 1.5, "story_7": 1.78}
    framed = recap_frame_layout(_plan(list(aspects)), role="hook", aspects=aspects)
    for tile in (r for r in framed["regions"] if r["kind"] == "media"):
        tile_aspect = tile["w"] / tile["h"] * CANVAS_ASPECT
        assert tile_aspect == pytest.approx(aspects[tile["content_ref"]], rel=0.02)  # nothing cut to fit an identical box
        assert 0.04 - 1e-6 <= tile["x"] and tile["x"] + tile["w"] <= 0.96 + 1e-6 and tile["y"] + tile["h"] <= 0.875 + 1e-6


def test_the_recap_ends_on_the_subscription_end_card():
    from services.instagram_recap_frames import RECAP_CTA_BODY, RECAP_CTA_HEADLINE, recap_frame_layout, with_recap_cta

    slides = [_carousel([_flow("hook", "Неделя в AI"), _poll("story", "История: A | B"), _flow("takeaway", "Итог")])[0]]
    closing_slide = slides[0].model_copy(update={"role": "closing", "slide_copy": "Сохрани карту недели"})
    carousel = SimpleNamespace(slides=[*slides, closing_slide], model_copy=lambda update: SimpleNamespace(slides=update["slides"]))
    closing = with_recap_cta(carousel).slides[-1]
    assert (closing.slide_copy, closing.slide_body) == (RECAP_CTA_HEADLINE, RECAP_CTA_BODY)
    card = recap_frame_layout(_plan(["story_2", "story_5", "story_3"]), role="closing", slide_text=RECAP_CTA_HEADLINE)
    refs = [r["content_ref"] for r in card["regions"] if r["kind"] == "media"]
    lead = max((r for r in card["regions"] if r["kind"] == "media"), key=lambda r: r["w"] * r["h"])
    assert lead["content_ref"] == "story_2" and len(refs) == 3  # the week's lead story is the front print
    assert {"copy_lead", "copy_rest", "body"} <= {r.get("content_ref") for r in card["regions"] if r["kind"] == "text"}


def test_the_end_card_renders_with_its_prints_and_passes_the_layout_validator():
    from services.instagram_carousel_layouts import render_carousel_slide
    from services.instagram_platform_renderer import InstagramRenderProfile, profile_spec
    from services.instagram_recap_frames import RECAP_CTA_BODY, RECAP_CTA_HEADLINE

    assets = {f"story_{i}": (Image.open(io.BytesIO(_photo(i))), f"id{i}") for i in range(1, 4)}
    result = render_carousel_slide(spec=profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE), role="closing", index=8, total=9,
                                   slide_copy=RECAP_CTA_HEADLINE, slide_body=RECAP_CTA_BODY, source_evidence=None, package_identity="p",
                                   media_mode="SOURCE", layout_plan=_plan(["story_1", "story_2", "story_3"]), subject_assets=assets, recap=True)
    assert result.notes.get("recap_frame") is True and len(result.notes["media_regions"]) == 3


def test_a_photo_band_takes_the_photos_shape_within_bounds():
    from services.instagram_media_scale_adapter import _band_height

    assert _band_height(2.0) == pytest.approx(0.4)   # a 2:1 phone shot: a 40% band holds it uncropped
    assert _band_height(3.5) == 0.36                  # a panorama never becomes a sliver
    assert _band_height(1.0) == 0.52                  # a square portrait keeps the proven slot (focal crop keeps the face)
