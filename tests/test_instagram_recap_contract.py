"""KAGE weekly recap contract (5-8 stories) downstream of the weekly editor, and the image-generation capability boundary.

The editor may select 5-8 stories; the recap bundle, the Creative Director contract and the carousel renderer must carry every one of
them - never a silent slice. With image generation off, the Director is told so through the existing media note and a generated slide
fails the existing media-first contract (the Director's one existing contract retry then applies). No provider, no network."""
from __future__ import annotations

import io
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

import services.instagram_recap_bundle as bundle_module
from core.config import settings
from schemas.instagram_creative import InstagramCarouselCreative
from services.instagram_art_validator import validate_instagram_art
from services.instagram_automatic_trigger import _carousel_media_note, generated_media_available
from services.instagram_media_first import MediaFirstContractError, assert_media_first
from services.instagram_platform_renderer import derive_asset_identity, render_instagram_carousel
from services.instagram_recap_bundle import MAX_RECAP_STORIES, build_instagram_recap_bundle
from tests.test_instagram_phase_b5_visual_dna_declarative import _carousel_output_with_layouts, _package_for, _r
from tests.test_instagram_phase_b6_media_first import _media, _slide_dict, _text


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), color).save(buf, format="PNG")
    return buf.getvalue()


class _Session:
    def __init__(self, titles: dict) -> None:
        self.titles = titles

    async def get(self, _model, event_id):
        title = self.titles.get(event_id)
        return None if title is None else SimpleNamespace(id=event_id, title=title, content=None)

    async def scalar(self, _stmt):
        return None


def _selected(n: int):
    candidates = [SimpleNamespace(story_id=uuid4(), representative_event_id=uuid4()) for _ in range(n)]
    return candidates, {c.representative_event_id: f"Story {i}" for i, c in enumerate(candidates, 1)}


@pytest.fixture()
def _no_media(monkeypatch):
    async def none(session, *, news_event_id, limit):
        return []

    monkeypatch.setattr(bundle_module, "get_editorial_image_candidates", none)


@pytest.mark.asyncio
@pytest.mark.parametrize("n", [5, 6, 7, 8])
async def test_every_accepted_editor_pick_reaches_the_bundle(n, _no_media):
    candidates, titles = _selected(n)
    bundle = await build_instagram_recap_bundle(_Session(titles), selected=candidates)
    assert bundle is not None and [s.title for s in bundle.stories] == [f"Story {i}" for i in range(1, n + 1)]
    assert bundle.subjects == [f"story_{i}" for i in range(1, n + 1)]


@pytest.mark.asyncio
async def test_a_selection_outside_the_contract_is_refused_loudly_never_sliced(_no_media, caplog):
    candidates, titles = _selected(MAX_RECAP_STORIES + 1)
    with caplog.at_level(logging.ERROR, logger=bundle_module.__name__):
        assert await build_instagram_recap_bundle(_Session(titles), selected=candidates) is None
    assert any(r.getMessage() == "instagram_recap_bundle_over_contract" for r in caplog.records)


@pytest.mark.asyncio
async def test_a_story_whose_event_vanished_is_logged_not_silently_dropped(_no_media, caplog):
    candidates, titles = _selected(7)
    titles.pop(candidates[3].representative_event_id)
    with caplog.at_level(logging.ERROR, logger=bundle_module.__name__):
        bundle = await build_instagram_recap_bundle(_Session(titles), selected=candidates)
    assert bundle is not None and len(bundle.stories) == 6
    assert any(r.getMessage() == "instagram_recap_story_event_missing" for r in caplog.records)


def _recap_carousel(n: int) -> InstagramCarouselCreative:
    flow = _r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="flow_diagram", tone="accent", flow_steps=["НЕДЕЛЯ", "ГЛАВНОЕ", "ИТОГ"])
    slides = [_slide_dict("hook", "Неделя в семи сюжетах", "graphic", [flow, _text(y=0.56)])]
    for i in range(1, n + 1):
        slides.append(_slide_dict("story", f"Сюжет {i}: что произошло", "source", [_media(f"story_{i}", 0.0, 0.0, 1.0, 0.55), _text(y=0.62)],
                                  subject=f"story_{i}", must_match_story=True))
    slides.append(_slide_dict("closing", "Вот и вся неделя", "graphic", [flow, _text(y=0.56)]))
    return InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides, "content_archetype": "news_recap"})


@pytest.mark.parametrize("n", [5, 6, 7, 8])
def test_the_renderer_carries_five_to_eight_recap_stories_each_with_its_own_image(n):
    carousel = _recap_carousel(n)
    assert_media_first(list(carousel.slides), available_subjects={f"story_{i}" for i in range(1, n + 1)}, unsuitable_subjects=set(),
                       generated_media_available=False)
    raw = {f"story_{i}": _png((20 * i, 60, 120)) for i in range(1, n + 1)}
    subject_assets = {k: (Image.open(io.BytesIO(data)).convert("RGB"), derive_asset_identity(data)) for k, data in raw.items()}
    package = _package_for(carousel)
    renders = render_instagram_carousel(package, subject_assets=subject_assets)
    assert len(renders) == n + 2  # hook + every story + closing, within Instagram's 10-slide bound
    for i in range(1, n + 1):
        assert {m["identity"] for m in renders[i].evidence.notes["media_regions"]} == {subject_assets[f"story_{i}"][1]}
    art = validate_instagram_art(package, renders)
    assert not any("slide_count" in issue or "exceeds" in issue for issue in art.blocking_issues), art.blocking_issues


def test_with_image_generation_off_the_director_is_told_so_and_never_offered_a_generated_visual(monkeypatch):
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "off")
    assert generated_media_available() is False
    recap = SimpleNamespace(stories=[SimpleNamespace(key="story_1", image_bytes=None)])
    for note in (_carousel_media_note(source_image=None, recap_bundle=None, media_first=True),
                 _carousel_media_note(source_image=None, recap_bundle=recap, media_first=True)):
        assert "image generation is OFF" in note and "Plan a GENERATED" not in note and "first-class option" not in note
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "live")
    assert "first-class option" in _carousel_media_note(source_image=None, recap_bundle=None, media_first=True)


def test_a_generated_slide_fails_the_contract_when_generation_is_off():
    slides = [_slide_dict("hook", "Ты это видел?", "generated", [_media("generated", 0.0, 0.0, 1.0, 0.55), _text(y=0.62)],
                          brief="Две станции: маленький сервер справляет простую задачу, пока огромный кластер простаивает рядом")]
    with pytest.raises(MediaFirstContractError, match="image generation is off"):
        assert_media_first(slides, available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)
