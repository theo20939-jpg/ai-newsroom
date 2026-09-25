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


def test_the_closer_gets_a_strip_and_fewer_than_three_stories_or_a_story_slide_keep_their_plan():
    from services.instagram_recap_frames import recap_frame_layout

    strip = [r for r in recap_frame_layout(_plan(["story_1", "story_4", "story_6"]), role="closing")["regions"] if r["kind"] == "media"]
    assert len({round(r["y"], 4) for r in strip}) == 1 and len(strip) == 3
    assert recap_frame_layout(_plan(["story_1", "story_4"]), role="hook") is None
    assert recap_frame_layout(_plan(["story_1", "story_4", "story_6"]), role="story") is None


def test_a_story_slide_shows_its_photo_once():
    from services.instagram_recap_frames import single_photo_story_layout

    single = single_photo_story_layout(_plan(["story_7", "story_7", "story_7"]), role="story")
    media = [r for r in single["regions"] if r["kind"] == "media"]
    assert len(media) == 1 and media[0]["h"] == pytest.approx(0.3)  # the largest crop is the one kept
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
