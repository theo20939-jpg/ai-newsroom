"""Phase B.6.1: per-slide generated-image attempt identity, the emotional HOOK contract (hook_emotion) and story-specific generated visuals. Zero provider cost."""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr, ValidationError

import services.instagram_creative_media as media
from core.config import Settings, settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import HOOK_EMOTIONS, InstagramCarouselCreative
from services import instagram_creative_director as cd
from services.budget_guard import RedisBudgetGuard, image_attempt_key, image_execution_key
from services.budgeted_image_execution import BudgetedImageExecutor
from services.instagram_creative_director import generate_carousel_creative
from services.instagram_media_first import (
    GENERIC_AI_ART_TERMS,
    MediaFirstContractError,
    assert_hook_contract,
    assert_media_first,
    find_generic_ai_art,
    weak_hook_patterns,
)
from services.kage_voice import load_kage_voice
from tests.test_instagram_phase_b5_visual_dna_declarative import _EVIDENCE, _carousel_output_with_layouts, _package_for
from tests.test_instagram_phase_b6_media_first import (
    ANCHOR,
    BRIEF,
    DIRECTION,
    _Gateway,
    _generated_carousel,
    _load,
    _media,
    _ok_slides,
    _png,
    _slide_dict,
    _text,
    _v10_input,
    _v10_output,
)

_ROOT = Path(__file__).resolve().parent.parent
_PROMPTS = _ROOT / "prompts"


# ------------------------------------------------------------------------------------------ per-slide attempt identity (real Redis)


def _guard_settings() -> Settings:
    return Settings(_env_file=None, llm_budget_mode="enforce", llm_daily_budget_usd=10.0, llm_daily_warning_usd=5.0, redis_unavailable_policy="fail_closed")  # type: ignore[call-arg]


class _FakeImageAdapter:
    """Stands in for the OpenAI adapter: a provider execution is counted, never made."""

    executions: list[str] = []

    def __init__(self, **_kw) -> None:
        pass

    @property
    def CAPABILITIES(self):  # noqa: N802
        return SimpleNamespace(supports_text_to_image=True)

    async def generate_image(self, request):
        type(self).executions.append(request.metadata["asset_key"])
        return ImageGenerationResponse(image_bytes=_png(), provider="openai", model_used="gpt-image-2",
                                       usage=CapabilityUsage(input_tokens=140, output_tokens=2733, units=1, unit_type="image"), request_id="req")


def _four_generated_slides_carousel() -> InstagramCarouselCreative:
    slides = [
        _slide_dict("hook" if i == 0 else ("takeaway" if i == 3 else "evidence"), f"Слайд номер {i + 1} про выбор модели", "generated",
                    [_media("generated", 0.08, 0.06, 0.84, 0.5, frame="paper"), _text(y=0.62)], brief=BRIEF)
        for i in range(4)
    ]
    return InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides})


@pytest.mark.asyncio
async def test_each_generated_slide_of_one_post_gets_its_own_attempt(redis_client, monkeypatch, tmp_path) -> None:
    namespace = f"test-{uuid.uuid4()}"
    guard = RedisBudgetGuard(redis_client, _guard_settings(), ledger_namespace=namespace)
    _FakeImageAdapter.executions = []
    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: BudgetedImageExecutor(budget_guard=guard))
    monkeypatch.setattr(media, "OpenAIImageAdapter", _FakeImageAdapter)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    carousel = _four_generated_slides_carousel()
    kwargs = dict(creative=carousel, source_image=None, source_ref=None, opportunity_summary="Дешёвая модель для простых задач", evidence=[_EVIDENCE],
                  content_format="carousel", creative_id="one-post", opportunity_id="opp", mode="live", slide_assets={})
    try:
        first = await media.execute_instagram_creative_media(**kwargs)
        assert [a.status for a in first.assets] == ["generated_media"] * 4  # the B.6 bug: only slide 0 was allowed
        assert _FakeImageAdapter.executions == ["0", "1", "2", "3"]  # four provider executions, one per slide
        keys = {image_attempt_key(namespace, f"instagram:one-post:visual:{i}") for i in range(4)}
        assert len(keys) == 4
        for k in keys:
            assert await redis_client.get(k) == "1"  # four distinct attempt keys, each at attempt 1
        assert await redis_client.exists(image_attempt_key(namespace, "instagram:one-post")) == 0  # nothing is counted at the shared post level any more
        # the SAME slide identity a second time: still denied (duplicate protection is not weakened), and no new provider execution happens
        second = await media.execute_instagram_creative_media(**kwargs)
        assert [a.status for a in second.assets] == ["generation_duplicate"] * 4
        assert _FakeImageAdapter.executions == ["0", "1", "2", "3"]
        for k in keys:
            assert await redis_client.get(k) == "1"  # max_attempts stays 1
    finally:
        for i in range(4):
            await redis_client.delete(image_attempt_key(namespace, f"instagram:one-post:visual:{i}"), image_execution_key(namespace, f"instagram:one-post:visual:{i}:v2"))
        await redis_client.delete(f"phase7:cost_ledger:{namespace}")


def test_the_attempt_identity_is_derived_from_the_post_and_the_slide_key_only() -> None:
    import inspect

    source = inspect.getsource(media._execute_generated_asset)
    assert 'creative_id=f"instagram:{creative_id}:visual:{asset_key}"' in source and 'execution_id = f"instagram:{creative_id}:visual:{asset_key}:v2"' in source
    assert "max_attempts=1" in source and "uuid" not in source and "random" not in source


# ------------------------------------------------------------------------------------------ hook contract


def test_v101_is_v10_plus_only_the_hook_and_generated_contracts_and_v10_is_untouched() -> None:
    v10, v101 = _load("10"), _load("10.1")
    assert v10["version"] == "10" and v101["version"] == "10.1" and cd.CAROUSEL_PROMPT_VERSION == "10.7"
    changed = [i for i, (a, b) in enumerate(zip(v10["rules"], v101["rules"])) if a != b]
    assert len(v10["rules"]) == len(v101["rules"]) and len(changed) == 2
    assert v101["rules"][changed[0]].startswith("GENERATED slide contract") and v101["rules"][changed[1]].startswith("HOOK CONTRACT")
    assert v10["system"] == v101["system"]
    v10_props = v10["output_schema"]["properties"]["slides"]["items"]["properties"]
    v101_props = v101["output_schema"]["properties"]["slides"]["items"]["properties"]
    assert "hook_emotion" not in v10_props and "story_anchor" not in v10_props  # v10 is history: unchanged
    assert set(v101_props) - set(v10_props) == {"hook_emotion", "story_anchor"} and all(v10_props[k] == v101_props[k] for k in v10_props)
    assert set(v101_props["hook_emotion"]["enum"]) == set(HOOK_EMOTIONS) | {None}
    assert set(v101["output_schema"]["properties"]["slides"]["items"]["required"]) == set(v101_props)


def test_the_hook_contract_text_demands_emotion_not_description_and_forbids_exaggeration() -> None:
    text = " ".join(_load("10.1")["rules"])
    for needle in ("hook_emotion", "surprise", "absurdity", "relatable_frustration", "usefulness", "merely descriptive", "at least TWO", "contradiction", "personal relevance",
                   "unexpected consequence", "challenge an intuitive assumption", "sharp comparison", "weekly newspaper digest", "never invent impact, certainty, market consequences",
                   "user behaviour", "future dominance", "scarcity or urgency", "ai_hack", "news_recap", "trend_generative", "null on every other slide"):
        assert needle in text, needle


def test_hook_emotion_is_a_bounded_field_on_the_hook_slide_only() -> None:
    slides = _ok_slides()
    assert slides[0]["hook_emotion"] == "tension" and all(s["hook_emotion"] is None for s in slides[1:])
    carousel = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides})
    assert_hook_contract(list(carousel.slides))
    with pytest.raises(ValidationError):
        InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": [{**slides[0], "hook_emotion": "outrage"}, *slides[1:]]})
    for emotion in HOOK_EMOTIONS:
        ok = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": [{**slides[0], "hook_emotion": emotion}, *slides[1:]]})
        assert ok.slides[0].hook_emotion == emotion


def test_the_hook_contract_rejects_a_missing_emotion_a_non_hook_first_slide_and_emotion_elsewhere() -> None:
    slides = _ok_slides()

    def check(mutated):
        return assert_hook_contract(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": mutated}).slides))

    with pytest.raises(MediaFirstContractError, match="hook_emotion"):
        check([{**slides[0], "hook_emotion": None}, *slides[1:]])
    with pytest.raises(MediaFirstContractError, match="hook slide only"):
        check([slides[0], {**slides[1], "hook_emotion": "curiosity"}, slides[2]])
    with pytest.raises(MediaFirstContractError, match="hook copy|no copy"):
        assert_hook_contract([SimpleNamespace(role="hook", slide_copy="  ", hook_emotion="tension")])
    with pytest.raises(MediaFirstContractError, match="must be the hook"):
        assert_hook_contract([SimpleNamespace(role="context", slide_copy="x", hook_emotion="tension")])


def test_the_validation_is_a_contract_check_not_a_regex_that_claims_to_prove_emotion() -> None:
    import inspect

    import services.instagram_media_first as mf

    assert "re." not in inspect.getsource(mf.assert_hook_contract)  # the model states the emotion; the founder judges whether it lands
    assert weak_hook_patterns("Неделя, когда открытость снова стала главным сюжетом") and weak_hook_patterns("Эта неделя была громкой")  # advisory generic-newsroom flags stay advisory


@pytest.mark.asyncio
async def test_generation_requires_hook_emotion_and_persists_it() -> None:
    repo = FilePromptRepository(_PROMPTS)
    missing = _ok_slides()
    missing[0]["hook_emotion"] = None
    with pytest.raises(MediaFirstContractError, match="hook_emotion"):
        await generate_carousel_creative(_Gateway(_v10_output(missing)), repo, director_input=_v10_input())
    outcome = await generate_carousel_creative(_Gateway(_v10_output(_ok_slides())), repo, director_input=_v10_input())
    assert outcome.carousel.slides[0].hook_emotion == "tension" and all(s.hook_emotion is None for s in outcome.carousel.slides[1:])
    plan = _package_for(outcome.carousel).media_plan["slides"]
    assert plan[0]["hook_emotion"] == "tension" and plan[1]["hook_emotion"] is None and plan[0]["story_anchor"] == ANCHOR


@pytest.mark.asyncio
async def test_the_shared_kage_voice_is_still_injected_from_the_canonical_file() -> None:
    gateway = _Gateway(_v10_output(_ok_slides()))
    await generate_carousel_creative(gateway, FilePromptRepository(_PROMPTS), director_input=_v10_input())
    voice = load_kage_voice()
    assert voice.text in gateway.requests[0].messages[1].content[0].text and voice.path == "docs/brand/kage_voice_v1.md"
    system = gateway.requests[0].messages[0].content[0].text
    assert all(line.strip() not in system for line in voice.text.splitlines() if len(line.strip()) > 40)  # never duplicated into the prompt


# ------------------------------------------------------------------------------------------ story-specific generated visuals


def _generated_variants(**kw):
    slides = _ok_slides()
    slides[0] = {**slides[0], **kw}
    return list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides)


def _fails(**kw) -> str:
    with pytest.raises(MediaFirstContractError) as info:
        assert_media_first(_generated_variants(**kw), available_subjects={"source"}, unsuitable_subjects=set(), evidence=[_EVIDENCE])
    return str(info.value)


def test_a_generated_slide_needs_a_story_anchor_and_a_concrete_visual_direction() -> None:
    assert_media_first(_generated_variants(), available_subjects={"source"}, unsuitable_subjects=set(), evidence=[_EVIDENCE])
    assert "story_anchor" in _fails(story_anchor=None)
    assert "story_anchor" in _fails(story_anchor="ИИ")
    assert "visual_direction" in _fails(visual_direction="futuristic AI visual")
    assert "visual_direction" in _fails(visual_direction="v")


@pytest.mark.parametrize("bad", ["a glowing cube orbited by floating spheres", "an anonymous robot in a cyberpunk city", "an abstract monolith of dark blocks", "a hologram of a digital brain",
                                 "neon circuit board pattern", "абстрактный монолит на фоне"])
def test_generic_ai_art_defaults_are_rejected_unless_the_story_is_literally_about_them(bad: str) -> None:
    generic = " ".join([DIRECTION, bad])
    assert "generic AI-art default" in _fails(visual_direction=generic)
    assert find_generic_ai_art(generic, [_EVIDENCE])
    literal = find_generic_ai_art("a humanoid robot folds laundry", ["Компания показала robot для домашних задач"])
    assert literal == []  # the evidence itself is about a robot: allowed


def test_generic_ai_art_terms_list_is_unchanged_and_there_is_no_separate_unescaped_phrase_list() -> None:
    """Phase B.7: VAGUE_DIRECTION_PHRASES (no evidence escape hatch) is removed - it was redundant with MIN_VISUAL_DIRECTION_CHARS
    and produced a real false positive ("abstract AI model cores", a grounded B.6.2 plan). GENERIC_AI_ART_TERMS (evidence-aware)
    is the only remaining lexical guard; grounding itself is now the structural source_evidence requirement (see b62/b7 tests)."""
    import services.instagram_media_first as m

    assert not hasattr(m, "VAGUE_DIRECTION_PHRASES")
    assert len(GENERIC_AI_ART_TERMS) >= 15
    for phrase in ("abstract technology scene", "dynamic AI composition", "futuristic AI visual", "two abstract AI model cores"):
        assert find_generic_ai_art(phrase, []) == []  # no longer flagged - these were never generic OBJECTS, just prose


def test_the_generation_prompt_carries_the_anchor_direction_and_forbids_the_generic_defaults() -> None:
    slide = {"generation_brief": BRIEF, "story_anchor": ANCHOR, "visual_direction": DIRECTION, "visual_family": "immersive_image_field", "media_function": "hero", "slide_purpose": "hook"}
    prompt = media.compile_instagram_generation_prompt(plan={}, opportunity_summary="Дешёвая модель для простых задач", evidence=["e"], content_format="carousel", slide=slide)
    assert ANCHOR in prompt and DIRECTION in prompt and "STORY-SPECIFIC ANCHOR" in prompt and "WHAT MUST BE PHYSICALLY VISIBLE" in prompt
    for banned in ("glowing cube", "floating spheres", "abstract monolith", "anonymous robot", "neon circuitry", "reusable unchanged for ten unrelated AI posts"):
        assert banned in prompt  # named as things NOT to produce
    assert "NO LOGOS" in prompt and "NO READABLE TEXT" in prompt


def test_weak_source_cards_and_typographic_slides_stay_rejected_under_v101() -> None:
    slides = _ok_slides()
    slides[2] = _slide_dict("takeaway", "Выбирай модель", "source", [_media("source", 0.05, 0.1, 0.9, 0.5), _text(0.08, 0.7, 0.8, 0.2)], subject="source")
    with pytest.raises(MediaFirstContractError, match="not suitable"):
        assert_media_first(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides), available_subjects={"source"},
                           unsuitable_subjects={"source"}, evidence=[])
    bare = _ok_slides()
    bare[1] = {**bare[1], "media_source": None}
    with pytest.raises(MediaFirstContractError, match="media_source must be"):
        assert_media_first(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": bare}).slides), available_subjects={"source"}, unsuitable_subjects=set())
    assert Decimal("0") == Decimal("0.0")
