"""One carousel, several pictures: a physical concept every slide repeats is a connective motif once, not the whole carousel."""
from __future__ import annotations

import json
from pathlib import Path

from services.instagram_creative_media import compile_instagram_generation_prompt
from services.instagram_scene_diversity import diversify_slide_briefs, dominant_scene_concepts, slide_scene_plan

ROOT = Path(__file__).resolve().parent.parent
SAVED_29 = ROOT / "artifacts/instagram_feed_product/final_natural_acceptance_20260929/attempt_2/post/package.json"
SAVED_30 = ROOT / "artifacts/instagram_feed_product/sonnet_editorial_acceptance_20260930/resume/post/director_raw_output.json"


def _slide(copy: str, brief: str, source: str = "generated") -> dict:
    return {"slide_copy": copy, "slide_body": "тело", "media_source": source, "generation_brief": brief, "visual_direction": "vd"}


MONOTONE = [_slide(f"s{i}", b) for i, b in enumerate([
    "A brushed metal disc on a dark ground, no text.", "Two metal discs, one brighter, no text.",
    "A stack of metal discs, tallest on the left, no text.", "Metal discs in a row on graphite, no text."])]
DIVERSE = [_slide(f"s{i}", b) for i, b in enumerate([
    "A dark glass slab resting on warm paper, no text.", "A beam of sunlight across a stone ledge, no text.",
    "A row of identical unlit candles, only the last burning, no text.", "An empty shop shelf with one blank card, no text."])]


def test_saved_monotone_sonnet_carousel_is_detected() -> None:
    slides = json.loads(SAVED_29.read_text(encoding="utf-8"))["media_plan"]["slides"]
    assert dominant_scene_concepts([s["generation_brief"] for s in slides]) == ["block"]


def test_saved_current_sonnet_carousel_is_not_flagged() -> None:
    slides = json.loads(SAVED_30.read_text(encoding="utf-8"))["structured_output"]["slides"]
    assert dominant_scene_concepts([s["generation_brief"] for s in slides]) == []


def test_diverse_carousel_is_left_untouched() -> None:
    out, notes = diversify_slide_briefs(DIVERSE)
    assert notes == [] and out == DIVERSE


def test_monotone_carousel_keeps_one_connective_motif_and_rebriefs_the_rest() -> None:
    out, notes = diversify_slide_briefs(MONOTONE)
    assert out[0]["generation_brief"] == MONOTONE[0]["generation_brief"]
    assert [n["action"] for n in notes] == ["kept_as_connective_motif", *["rebriefed_from_own_beat"] * 3]
    for new, old in zip(out[1:], MONOTONE[1:]):
        assert new["generation_brief"] != old["generation_brief"]
        assert old["slide_copy"] in new["generation_brief"]  # re-briefed from the slide's OWN copy
        assert "disc" in new["generation_brief"]  # told not to repeat the neighbours' object


def test_slide_prompt_never_carries_the_carousel_wide_object_metaphor() -> None:
    plan = {"main_idea": "Линейка как физическая иерархия блоков", "visual_treatment": "Unbranded geometric blocks photographed like objects"}
    scene = slide_scene_plan(plan, DIVERSE, 1)
    assert "блоков" not in scene["main_idea"] and "geometric" not in scene["visual_treatment"]
    prompt = compile_instagram_generation_prompt(plan=scene, opportunity_summary="story", evidence=["fact"], content_format="carousel", slide=DIVERSE[1])
    assert "Линейка как физическая иерархия блоков" not in prompt and "geometric blocks" not in prompt
    assert "A dark glass slab" in prompt and "sunlight" in prompt  # its own scene
    assert "already show" in prompt  # what the other pictures depict is named so it is not repeated


def test_visual_safety_text_is_unchanged_by_the_scene_plan() -> None:
    plan = {"main_idea": "x", "visual_treatment": "y"}
    base = compile_instagram_generation_prompt(plan=plan, opportunity_summary="s", evidence=["e"], content_format="carousel", slide=DIVERSE[0])
    new = compile_instagram_generation_prompt(plan=slide_scene_plan(plan, DIVERSE, 0), opportunity_summary="s", evidence=["e"],
                                              content_format="carousel", slide=DIVERSE[0])
    tail = lambda p: p[p.index("NEGATIVE CONSTRAINTS"):]  # noqa: E731
    assert tail(base) == tail(new)


def test_short_or_non_generated_carousels_keep_the_plan_as_is() -> None:
    plan = {"main_idea": "m", "visual_treatment": "v"}
    assert slide_scene_plan(plan, MONOTONE[:2], 0) == plan
    mixed = [_slide("a", "x", "source"), *MONOTONE[:2]]
    assert slide_scene_plan(plan, mixed, 0) == plan
    assert diversify_slide_briefs(MONOTONE[:2])[1] == []


import pytest  # noqa: E402

from services import instagram_creative_media as media  # noqa: E402


class _Creative:
    def __init__(self, slides: list[dict], plan: dict) -> None:
        self.slides = slides
        self.creative_execution_plan = type("P", (), {"model_dump": lambda self_: plan})()


@pytest.mark.asyncio
async def test_execution_path_gives_each_slide_its_own_scene_prompt_without_calling_a_provider(monkeypatch) -> None:
    monkeypatch.setattr(media, "OpenAIImageAdapter", lambda **kwargs: pytest.fail("paid adapter constructed"))
    plan = {"media_strategy": "generated_media", "main_idea": "Диски как мотив", "visual_treatment": "Brushed metal discs"}
    result = await media.execute_instagram_creative_media(
        creative=_Creative(MONOTONE, plan), source_image=None, source_ref=None, opportunity_summary="story", evidence=["fact"],
        content_format="carousel", creative_id="c", opportunity_id="o", mode="off",
    )
    prompts = [a.prompt for a in result.assets]
    assert len(prompts) == 4 and all("Диски как мотив" not in p and "Brushed metal discs" not in p for p in prompts)
    assert "Образ для мысли «s1»" in prompts[1] and "Образ для мысли" not in prompts[0]  # slide 0 keeps its own motif brief
