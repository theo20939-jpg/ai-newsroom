"""Phase B.6: MEDIA-FIRST Instagram generation + shared KAGE voice + no empty text-only slides. Zero cost: no provider, no network."""
from __future__ import annotations

import copy
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageDraw
from pydantic import SecretStr

import services.instagram_creative_media as media
from core.config import settings
from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramCarouselCreative
from services import instagram_creative_director as cd
from services.budgeted_image_execution import BudgetedImageResult
from services.instagram_art_validator import validate_instagram_art
from services.instagram_asset_profile import profile_asset, render_profile_lines
from services.instagram_automatic_trigger import _carousel_media_note, _carousel_media_subjects
from services.instagram_b4_observability import build_b4_observability
from services.instagram_creative_director import CreativeDirectorInput, generate_carousel_creative
from services.instagram_media_first import (
    MAX_GENERATED_SLIDES_PER_POST,
    MediaFirstContractError,
    UnsupportedClickbaitError,
    assert_hook_is_short,
    assert_media_first,
    assert_no_unsupported_clickbait,
    find_unsupported_clickbait,
    weak_hook_patterns,
)
from services.instagram_platform_renderer import render_instagram_carousel
from services.kage_voice import KAGE_VOICE_RELATIVE_PATH, load_kage_voice
from tests.test_instagram_phase_b5_visual_dna_declarative import _EVIDENCE, _carousel_output_with_layouts, _layout, _package_for, _r

_ROOT = Path(__file__).resolve().parent.parent
_PROMPTS = _ROOT / "prompts"
_NAME = "instagram_creative_director_carousel"


# ------------------------------------------------------------------------------------------ prompt v10 / v9.1


def _load(version: str) -> dict:
    return yaml.safe_load((_PROMPTS / _NAME / f"v{version}.yaml").read_text(encoding="utf-8"))


def test_v10_makes_generated_media_first_class_and_v91_is_untouched() -> None:
    v91, v10 = _load("9.1"), _load("10")
    assert v91["version"] == "9.1" and any("generated_media is not available" in r for r in v91["rules"])  # history preserved
    text = " ".join(v10["rules"])
    assert v10["version"] == "10" and "generated_media is not available" not in text
    assert "GENERATED media is FIRST-CLASS" in text and "There is no typographic-only slide" in text
    assert "generation_brief" in text and "content_ref is `generated`" in text
    assert cd.CAROUSEL_PROMPT_VERSION == "10.4" and "10" in cd.MEDIA_FIRST_CAROUSEL_VERSIONS and "10.1" in cd.MEDIA_FIRST_CAROUSEL_VERSIONS and "10.1" in cd._EVIDENCE_HANDLE_CAROUSEL_VERSIONS


def test_v10_schema_requires_a_visual_source_on_every_slide_and_never_typographic() -> None:
    v10 = _load("10")
    slide = v10["output_schema"]["properties"]["slides"]["items"]
    assert slide["properties"]["media_source"]["enum"] == ["source", "generated", "graphic"]
    assert "media_source" in slide["required"] and "generation_brief" in slide["required"]
    assert v10["output_schema"]["properties"]["creative_execution_plan"]["properties"]["media_strategy"]["enum"] == ["source_media", "generated_media", "graphic"]
    assert "typographic" not in " ".join(v10["output_schema"]["properties"]["creative_execution_plan"]["properties"]["media_strategy"]["enum"])


def test_v10_carries_the_hook_policy_bold_but_honest_and_no_kage_voice_copy() -> None:
    v10 = _load("10")
    text = " ".join(v10["rules"])
    for reaction in ("surprise", "curiosity", "humour", "disbelief", "tension", "desire", "relatable frustration", "that is useful", "what the hell"):
        assert reaction in text
    for opener in ("Компания X представила", "Главные новости недели", "Вот что произошло"):
        assert opener in text  # named as openers to AVOID
    assert "BOLD, NOT DISHONEST" in text and "REACTION:" in text and "one strong line" in text
    voice = load_kage_voice().text
    for line in [ln.strip() for ln in voice.splitlines() if len(ln.strip()) > 40]:
        assert line not in text and line not in v10["system"]  # the voice lives in ONE file; the prompt only adapts it


def test_v10_is_v91_plus_the_media_first_and_voice_contract() -> None:
    v91, v10 = _load("9.1"), _load("10")
    keep = [i for i in range(len(v91["rules"])) if i not in (13, 17, 21, 27, 28, 30)]
    assert all(v91["rules"][i] == v10["rules"][i] for i in keep)  # every other rule (evidence, layout, families, calm zone, collage, no overlay) is inherited verbatim
    assert "NO overlay, scrim, dimming" in " ".join(v10["rules"]) and "content_ref is `generated`" in " ".join(v10["rules"])


# ------------------------------------------------------------------------------------------ shared KAGE voice


def test_kage_voice_is_one_shared_document_that_reaches_the_creative_director() -> None:
    voice = load_kage_voice()
    assert voice.path == KAGE_VOICE_RELATIVE_PATH == "docs/brand/kage_voice_v1.md" and (_ROOT / voice.path).exists()
    for trait in ("smart", "internet-native", "bold", "conversational", "emotionally sharp", "dryly funny", "slightly provocative", "corporate", "fake youth slang", "clickbait"):
        assert trait in voice.text.lower()
    director_input = CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=["e"], locale="ru",
                                           kage_voice_context=voice.render_context())
    user_text = cd._build_user_text(director_input, evidence_handles=True)
    assert voice.text in user_text and voice.sha256[:12] in user_text and "docs/brand/kage_voice_v1.md" in user_text
    assert "KAGE VOICE" not in cd._build_user_text(CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", locale="ru"))  # older prompts unchanged


def test_the_trigger_injects_the_shared_voice_only_for_media_first_versions() -> None:
    import inspect

    import services.instagram_automatic_trigger as trigger

    source = inspect.getsource(trigger.evaluate_and_submit_instagram_opportunity)
    assert "load_kage_voice().render_context() if media_first" in source and "media_first=media_first" in source
    assert "CAROUSEL_PROMPT_VERSION in MEDIA_FIRST_CAROUSEL_VERSIONS" in source


# ------------------------------------------------------------------------------------------ media mode mapping


def _slide_obj(**kw):
    from types import SimpleNamespace

    base = dict(media_source=None, media_need=None, must_match_story=False, media_subject=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("need", ["минимально, текст", "minimal typographic", "typograph text only", "типографика", None])
def test_a_media_first_slide_never_resolves_to_typographic_whatever_media_need_says(need) -> None:
    for declared, expected in (("source", media.InstagramMediaMode.SOURCE), ("generated", media.InstagramMediaMode.GENERATED), ("graphic", media.InstagramMediaMode.GRAPHIC)):
        mode = media._mode_for_item(strategy="typographic", slide=_slide_obj(media_source=declared, media_need=need), index=1)
        assert mode is expected and mode is not media.InstagramMediaMode.TYPOGRAPHIC


def test_legacy_slides_without_media_source_keep_the_old_mapping_typographic_stays_in_code() -> None:
    assert media._mode_for_item(strategy="typographic", slide=_slide_obj(media_need="минимально"), index=1) is media.InstagramMediaMode.TYPOGRAPHIC
    assert media.InstagramMediaMode.TYPOGRAPHIC.value == "TYPOGRAPHIC"


# ------------------------------------------------------------------------------------------ source suitability (no OCR, no provider)


def _article_card() -> Image.Image:
    """A flat Habr-style card: a slate ground, a highlighted headline band and white text lines - a handful of flat colours."""
    img = Image.new("RGB", (1200, 630), (55, 74, 90))
    d = ImageDraw.Draw(img)
    d.rectangle([50, 175, 1000, 240], fill=(152, 210, 240))
    d.rectangle([50, 300, 800, 360], fill=(152, 210, 240))
    d.text((60, 190), "AliceAI Foundation", fill=(30, 40, 50))
    return img


def _photo() -> Image.Image:
    import random

    rng = random.Random(7)
    img = Image.new("RGB", (1200, 900))
    px = img.load()
    for x in range(1200):
        for y in range(900):
            base = (x * 255 // 1200, y * 255 // 900, (x + y) * 255 // 2100)
            px[x, y] = tuple(min(255, max(0, c + rng.randint(-18, 18))) for c in base)
    return img


def test_a_flat_article_card_is_not_suitable_as_a_final_visual_but_a_photo_is() -> None:
    assert profile_asset(_article_card(), subject_key="source").suitable_for_final_visual is False
    assert profile_asset(_photo(), subject_key="source").suitable_for_final_visual is True


def test_the_media_note_tells_the_model_source_available_vs_suitable_and_offers_generated() -> None:
    card_note = _carousel_media_note(source_image=_article_card(), recap_bundle=None, media_first=True)
    assert "SOURCE_AVAILABLE: yes" in card_note and "SOURCE_SUITABLE_FOR_FINAL_VISUAL: NO" in card_note and "GENERATED" in card_note
    assert "immersive_image_field: full-canvas" not in card_note  # an unsuitable card is never offered as an immersive field
    photo_note = _carousel_media_note(source_image=_photo(), recap_bundle=None, media_first=True)
    assert "SOURCE_SUITABLE_FOR_FINAL_VISUAL: yes" in photo_note and "GENERATED media is a first-class option" in photo_note
    none_note = _carousel_media_note(source_image=None, recap_bundle=None, media_first=True)
    assert "SOURCE_AVAILABLE: no" in none_note and "media-free families" not in none_note and "GENERATED" in none_note
    assert "media-free families" in _carousel_media_note(source_image=None, recap_bundle=None)  # v9.x note unchanged
    assert _carousel_media_subjects(source_image=_article_card(), recap_bundle=None) == (("source",), ("source",))
    assert _carousel_media_subjects(source_image=_photo(), recap_bundle=None) == (("source",), ())


# ------------------------------------------------------------------------------------------ the media-first contract


def _media(ref, x=0.0, y=0.0, w=1.0, h=1.0, **kw):
    return _r("media", x, y, w, h, content_ref=ref, crop_mode="cover", **kw)


def _text(x=0.08, y=0.62, w=0.6, h=0.22):
    return _r("text", x, y, w, h, content_ref="copy", scale_token="HEADLINE_L", align="left", valign="top", max_lines=3)


def _slide_dict(role, copy_text, source, regions, *, brief=None, family="light_utility_editorial", subject=None, **kw):
    layout = {**_layout(regions, background="ink", density="MEDIUM"), "arrangement": kw.pop("arrangement", "standard")}
    generated = source == "generated"
    base = {"role": role, "slide_copy": copy_text, "source_evidence": "E1", "slide_purpose": role, "media_need": None,
            "visual_direction": DIRECTION if generated else "v",
            "media_subject": subject, "media_function": "hero" if source != "graphic" else "none", "must_match_story": False, "layout": layout,
            "visual_family": family, "visual_family_reason": "fit", "media_source": source, "generation_brief": brief,
            "hook_emotion": "tension" if role == "hook" else None, "hook_mechanic": "contradiction" if role == "hook" else None,
            "story_anchor": ANCHOR if generated else None}
    base.update(kw)
    return base


DIRECTION = ("A small cheap server board quietly finishes a simple task in the foreground while an oversized server rack idles behind it; the pair shows a modest machine "
             "matched to a simple job, which supports the slide's claim that not every task needs the flagship model.")
ANCHOR = "маленькая плата тянет простую задачу, пока огромная стойка простаивает"
BRIEF = "Две станции: маленький дешёвый сервер справляет простую задачу, пока огромный кластер простаивает рядом, холодный свет, вид сверху"


def _ok_slides():
    return [
        _slide_dict("hook", "Ты платишь за мощность, которая простаивает", "generated", [_media("generated", 0.0, 0.0, 1.0, 0.55), _text(y=0.62)], brief=BRIEF),
        _slide_dict("evidence", "Простые задачи не требуют флагмана", "graphic", [
            _r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="flow_diagram", tone="accent", flow_steps=["ВВОД", "ДЕЙСТВИЕ", "РЕЗУЛЬТАТ"]), _text(y=0.56)]),
        _slide_dict("takeaway", "Выбирай модель под задачу", "source", [_media("source", 0.5, 0.1, 0.42, 0.4, frame="paper"), _text(0.08, 0.55, 0.8, 0.24)], subject="source"),
    ]


def test_every_slide_with_a_real_visual_idea_passes() -> None:
    slides = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": _ok_slides()}).slides
    assert_media_first(list(slides), available_subjects={"source"}, unsuitable_subjects=set())


def _fails(slides, **kw) -> str:
    slides = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides
    with pytest.raises(MediaFirstContractError) as info:
        assert_media_first(list(slides), available_subjects=kw.get("available", {"source"}), unsuitable_subjects=kw.get("unsuitable", set()))
    return str(info.value)


def test_a_typographic_only_slide_is_rejected() -> None:
    bare = _slide_dict("evidence", "Только текст на пустом фоне", "graphic", [_r("accent", 0.08, 0.5, 0.2, 0.01, accent_type="rule_h"), _text(y=0.56)])
    slides = _ok_slides()
    slides[1] = bare
    assert "substantive graphic" in _fails(slides)  # a rule + headline is not GRAPHIC
    slides = _ok_slides()
    slides[1] = {**bare, "media_source": None}
    assert "media_source must be" in _fails(slides)
    slides[1] = _slide_dict("evidence", "Гигантская цифра", "graphic", [_r("text", 0.08, 0.3, 0.6, 0.3, content_ref="number", scale_token="NUMERAL"), _text(y=0.7)])
    assert "substantive graphic" in _fails(slides)


def test_graphic_needs_ui_flow_or_poll_and_a_generated_slide_needs_brief_and_region() -> None:
    for kind in ("ui_frame", "flow_diagram", "poll_cards"):
        slides = _ok_slides()
        region_kw = {"flow_steps": ["ВВОД", "ДЕЙСТВИЕ", "РЕЗУЛЬТАТ"]} if kind == "flow_diagram" else {}
        slides[1] = _slide_dict("evidence", "Выбор: A? Да | Нет" if kind == "poll_cards" else "Шаги", "graphic", [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type=kind, tone="accent", **region_kw), _text(y=0.56)])
        assert_media_first(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides), available_subjects={"source"}, unsuitable_subjects=set())
    slides = _ok_slides()
    slides[0] = {**slides[0], "generation_brief": "коротко"}
    assert "concrete generation_brief" in _fails(slides)
    slides = _ok_slides()
    slides[0] = _slide_dict("hook", "Ты платишь за мощность", "generated", [_media("source", 0.0, 0.0, 1.0, 0.55), _text()], brief=BRIEF)
    assert "content_ref 'generated'" in _fails(slides)


def test_a_flat_article_card_cannot_be_the_hero_but_may_be_a_small_collage_fragment() -> None:
    slides = _ok_slides()
    slides[2] = _slide_dict("takeaway", "Выбирай модель под задачу", "source", [_media("source", 0.05, 0.1, 0.9, 0.5), _text(0.08, 0.7, 0.8, 0.2)], subject="source")
    assert "not suitable as a final visual" in _fails(slides, unsuitable={"source"})
    fragment = _slide_dict("takeaway", "Выбирай модель под задачу", "source", [
        _media("generated", 0.05, 0.08, 0.62, 0.5, z=1), _media("source", 0.7, 0.6, 0.2, 0.15, z=2, frame="torn", tilt_deg=4), _text(0.08, 0.7, 0.55, 0.2)],
        subject="source", brief=BRIEF, arrangement="collage")
    fragment["media_source"] = "source"
    slides = _ok_slides()
    slides[2] = fragment
    assert_media_first(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides), available_subjects={"source"}, unsuitable_subjects={"source"})


def test_the_number_of_generated_slides_is_bounded() -> None:
    assert MAX_GENERATED_SLIDES_PER_POST == 6
    slides = [_slide_dict("hook" if i == 0 else "evidence", f"Слайд номер {i + 1}", "generated", [_media("generated", 0.0, 0.0, 1.0, 0.5), _text(y=0.6)], brief=BRIEF) for i in range(7)]
    slides[-1]["role"] = "takeaway"
    with pytest.raises(MediaFirstContractError, match="exceed the per-post bound"):
        assert_media_first(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides), available_subjects=set(), unsuitable_subjects=set())


# ------------------------------------------------------------------------------------------ hook / voice guards


def test_hook_policy_bold_but_supported() -> None:
    assert weak_hook_patterns("Компания OpenAI представила новую модель") and weak_hook_patterns("Главные истории недели в ИИ") and weak_hook_patterns("Вот что произошло сегодня")
    assert not weak_hook_patterns("Ты переплачиваешь за AI, который тебе не нужен")
    assert_hook_is_short("Ты переплачиваешь за AI, который тебе не нужен")
    with pytest.raises(MediaFirstContractError):
        assert_hook_is_short("х" * 130)
    assert find_unsupported_clickbait({"slide_0_copy": "Интернет умер, и все делают неправильно"}, ["Вышла новая модель"])
    assert not find_unsupported_clickbait({"slide_0_copy": "Интернет умер"}, ["Автор пишет: интернет умер для рассылок"])  # literal support allows it
    with pytest.raises(UnsupportedClickbaitError):
        assert_no_unsupported_clickbait({"final_caption": "Это уничтожит всё"}, ["Вышло обновление"])


# ------------------------------------------------------------------------------------------ the generation prompt


def test_the_generation_prompt_depicts_the_story_and_never_asks_for_headline_or_logo() -> None:
    slide = {"generation_brief": BRIEF, "visual_family": "immersive_image_field", "media_function": "hero", "slide_purpose": "hook", "slide_copy": "Ты платишь за мощность, которая простаивает",
             "media_subject": "story_2"}
    prompt = media.compile_instagram_generation_prompt(
        plan={"main_idea": "выбор мощности под задачу"}, opportunity_summary="Дешёвая модель для простых задач",
        evidence=["[story_2] Модель сравнивает стоимость задачи"], content_format="carousel", slide=slide)
    assert BRIEF in prompt and "Дешёвая модель для простых задач" in prompt and "[story_2] Модель сравнивает стоимость задачи" in prompt
    assert "calm, low-detail area" in prompt and "SPECIFICITY" in prompt and "generic AI brain" in prompt
    assert "NO LOGOS" in prompt and "NO READABLE TEXT" in prompt and "Do not bake any headline" in prompt
    assert slide["slide_copy"] not in prompt  # the exact Russian copy is the renderer's job, never the image's
    hero = media.compile_instagram_generation_prompt(plan={}, opportunity_summary="s", evidence=[], content_format="carousel", slide={**slide, "visual_family": "hero_object_stage"})
    assert "plain uniform studio ground" in hero
    legacy = media.compile_instagram_generation_prompt(plan={}, opportunity_summary="s", evidence=[], content_format="carousel", slide={"slide_purpose": "x"})
    assert "SPECIFIC SCENE" not in legacy and "VISUAL PROFILE VERSION" in legacy  # no brief: the old prompt is unchanged


def test_a_recap_story_image_is_generated_from_that_storys_evidence_only() -> None:
    evidence = ["[story_1] Факт про Claude", "[story_2] Факт про Яндекс", "[story_2] Ещё про Яндекс"]
    assert media._evidence_for_slide(evidence, {"media_subject": "story_2"}) == ["[story_2] Факт про Яндекс", "[story_2] Ещё про Яндекс"]
    assert media._evidence_for_slide(evidence, {"media_subject": None}) == evidence


# ------------------------------------------------------------------------------------------ execution: generated media reaches the renderer, text-only is refused


def _png(color=(35, 72, 145)) -> bytes:
    image = Image.new("RGB", (1024, 1536), color)
    ImageDraw.Draw(image).ellipse((110, 180, 820, 890), fill=(240, 167, 60))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class _Executor:
    def __init__(self, calls, colors=None):
        self.calls, self.colors = calls, colors or [(35, 72, 145), (140, 60, 90), (30, 120, 90)]

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return BudgetedImageResult(
            status="generated",
            response=ImageGenerationResponse(image_bytes=_png(self.colors[(len(self.calls) - 1) % len(self.colors)]), provider="openai", model_used="gpt-image-2",
                                             usage=CapabilityUsage(input_tokens=140, output_tokens=2733, units=1, unit_type="image"), request_id=f"req-{len(self.calls)}"),
            accounted_cost_usd=Decimal("0.04310"), cost_semantics="configured_token_estimate", attempt=1)


def _generated_carousel():
    slides = [
        _slide_dict("hook", "Ты платишь за мощность, которая простаивает", "generated", [_media("generated", 0.08, 0.06, 0.84, 0.5, frame="paper"), _text(y=0.62)], brief=BRIEF),
        _slide_dict("evidence", "Простым задачам не нужен флагман", "generated", [_media("generated", 0.5, 0.08, 0.42, 0.4, frame="paper"), _text(0.08, 0.1, 0.36, 0.3)],
                    brief="Крупный план маленькой платы, которая тянет простую задачу, рядом выключенная стойка"),
        _slide_dict("takeaway", "Выбирай модель под задачу", "graphic", [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="flow_diagram", tone="accent", flow_steps=["ВВОД", "ДЕЙСТВИЕ", "РЕЗУЛЬТАТ"]), _text(y=0.56)]),
    ]
    slides[2]["visual_direction"] = "«Задача → Модель → Результат»"
    return InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides})


@pytest.mark.asyncio
async def test_generated_slides_are_generated_per_slide_rendered_and_recorded(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: _Executor(calls))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    carousel = _generated_carousel()
    result = await media.execute_instagram_creative_media(
        creative=carousel, source_image=None, source_ref=None, opportunity_summary="Дешёвая модель для простых задач", evidence=[_EVIDENCE],
        content_format="carousel", creative_id="b6", opportunity_id="opp", mode="live", slide_assets={})
    assert len(calls) == 2 and all(c["max_attempts"] == 1 for c in calls)  # exactly the generated slides, no retries, graphic slide generates nothing
    assets = {a.asset_key: a for a in result.assets}
    assert assets["0"].media_mode.value == "GENERATED" and assets["1"].media_mode.value == "GENERATED" and assets["2"].media_mode.value == "GRAPHIC"
    assert assets["0"].prompt_sha256 != assets["1"].prompt_sha256 and BRIEF in assets["0"].prompt and "флагман" not in assets["0"].prompt
    assert assets["0"].asset_identity != assets["1"].asset_identity  # per-slide images, never one hero reused blindly
    assert Decimal(assets["0"].accounted_cost_usd) == Decimal("0.04310")

    package = _package_for(carousel)
    from dataclasses import replace as dc_replace

    package = dc_replace(package, media_plan={**package.media_plan, "media_execution": result.execution_metadata()})
    assert package.media_plan["media_first"] is True
    renders = render_instagram_carousel(
        package, slide_images=result.slide_images(), asset_identities=result.slide_asset_identities(),
        slide_subject_assets={int(a.asset_key): {"generated": (a.image, a.asset_identity)} for a in result.assets if a.image is not None})
    assert all(r.evidence.notes["layout_plan_applied"] for r in renders)
    ids = [{m["identity"] for m in r.evidence.notes["media_regions"]} for r in renders]
    assert ids[0] == {assets["0"].asset_identity} and ids[1] == {assets["1"].asset_identity} and ids[2] == set()  # each slide consumes only its own image
    art = validate_instagram_art(package, renders)
    assert not any("slide_without_meaningful_visual" in b for b in art.blocking_issues), art.blocking_issues
    obs = build_b4_observability(carousel=carousel, prompt_version="10", renders=renders, art=art, slide_identities=result.slide_asset_identities())
    assert obs["text_only_slides"] == [] and obs["typographic_final_media_slides"] == []
    assert [s["media_source"] for s in obs["slides"]] == ["generated", "generated", "graphic"]


@pytest.mark.asyncio
async def test_a_slide_whose_generation_did_not_produce_an_image_is_blocked_never_shipped_text_only(monkeypatch) -> None:
    carousel = _generated_carousel()
    result = await media.execute_instagram_creative_media(
        creative=carousel, source_image=None, source_ref=None, opportunity_summary="s", evidence=[_EVIDENCE], content_format="carousel", creative_id="b6", opportunity_id="opp",
        mode="off", slide_assets={})
    assert result.status == "generation_off"  # the trigger stops here: nothing is rendered or delivered without its visual
    package = _package_for(carousel)
    renders = render_instagram_carousel(package)  # if it were rendered anyway, the slides have no image
    art = validate_instagram_art(package, renders)
    assert any("slide_without_meaningful_visual: slide_index=0" in b for b in art.blocking_issues)
    assert any("slide_without_meaningful_visual: slide_index=1" in b for b in art.blocking_issues)
    assert not any("slide_index=2" in b and "meaningful_visual" in b for b in art.blocking_issues)  # the flow_diagram slide is a real graphic
    obs = build_b4_observability(carousel=carousel, prompt_version="10", renders=renders, art=art, slide_identities={})
    assert obs["text_only_slides"] == [0, 1]


def test_the_art_gate_only_enforces_media_first_on_media_first_plans() -> None:
    legacy = _package_for(InstagramCarouselCreative.model_validate(_carousel_output_with_layouts()))
    assert legacy.media_plan["media_first"] is False
    art = validate_instagram_art(legacy, render_instagram_carousel(legacy))
    assert not any("meaningful_visual" in b for b in art.blocking_issues)


# ------------------------------------------------------------------------------------------ the real generation path with the v10 contract


class _Gateway:
    def __init__(self, output):
        self.output, self.requests = output, []

    async def generate(self, request):
        self.requests.append(request)
        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


def _v10_output(slides):
    out = _carousel_output_with_layouts()
    out["slides"] = slides
    out["evidence_used"] = ["E1"]
    return out


def _v10_input(**kw) -> CreativeDirectorInput:
    base = dict(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=[_EVIDENCE], locale="ru", media_first=True,
                kage_voice_context=load_kage_voice().render_context(), available_media_subjects=("source",), unsuitable_media_subjects=())
    base.update(kw)
    return CreativeDirectorInput(**base)


@pytest.mark.asyncio
async def test_v10_generation_accepts_a_media_first_plan_and_sends_voice_handles_and_media_note() -> None:
    gateway = _Gateway(_v10_output(_ok_slides()))
    outcome = await generate_carousel_creative(gateway, FilePromptRepository(_PROMPTS), director_input=_v10_input(media_note="SOURCE_AVAILABLE: yes"))
    text = gateway.requests[0].messages[1].content[0].text
    assert "KAGE VOICE" in text and "E1: " in text and "SOURCE_AVAILABLE" in text
    assert outcome.carousel.slides[0].role == "hook" and [s.media_source for s in outcome.carousel.slides] == ["generated", "graphic", "source"]
    assert outcome.carousel.evidence_used == [_EVIDENCE] and outcome.weak_hook_patterns == ()
    assert gateway.requests[0].max_tokens == 16_000


@pytest.mark.asyncio
async def test_v10_generation_rejects_typographic_only_unsuitable_source_and_unsupported_clickbait() -> None:
    repo = FilePromptRepository(_PROMPTS)
    bad = _ok_slides()
    bad[1] = _slide_dict("evidence", "Пустая карточка", "graphic", [_r("accent", 0.08, 0.5, 0.2, 0.01, accent_type="rule_h"), _text(y=0.56)])
    with pytest.raises(MediaFirstContractError):
        await generate_carousel_creative(_Gateway(_v10_output(bad)), repo, director_input=_v10_input())
    with pytest.raises(MediaFirstContractError, match="not suitable"):
        card = _ok_slides()
        card[2] = _slide_dict("takeaway", "Выбирай модель", "source", [_media("source", 0.05, 0.1, 0.9, 0.5), _text(0.08, 0.7, 0.8, 0.2)], subject="source")
        await generate_carousel_creative(_Gateway(_v10_output(card)), repo, director_input=_v10_input(unsuitable_media_subjects=("source",)))
    with pytest.raises(UnsupportedClickbaitError):
        loud = _ok_slides()
        loud[0]["slide_copy"] = "Интернет умер, все делают неправильно"
        await generate_carousel_creative(_Gateway(_v10_output(loud)), repo, director_input=_v10_input())
    with pytest.raises(MediaFirstContractError, match="hook copy"):
        long_hook = _ok_slides()
        long_hook[0]["slide_copy"] = "Это очень длинный заголовок, " * 6
        await generate_carousel_creative(_Gateway(_v10_output(long_hook)), repo, director_input=_v10_input())


@pytest.mark.asyncio
async def test_the_media_first_contract_is_off_unless_the_caller_asks_and_fact_safety_is_unchanged() -> None:
    # a v9-shaped plan (no media_source) still passes when the caller does not run the media-first contract
    outcome = await generate_carousel_creative(_Gateway(_carousel_output_with_layouts()), FilePromptRepository(_PROMPTS),
                                               director_input=CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=[_EVIDENCE], locale="ru"))
    assert outcome.carousel is not None
    from services.instagram_creative_director import UngroundedEvidenceError

    tampered = _v10_output(_ok_slides())
    tampered["evidence_used"] = ["E9"]
    with pytest.raises(UngroundedEvidenceError):
        await generate_carousel_creative(_Gateway(tampered), FilePromptRepository(_PROMPTS), director_input=_v10_input())
    assert copy.deepcopy(_ok_slides())[0]["role"] == "hook"


# ------------------------------------------------------------------------------------------ the live trigger, end to end (DB session)


def _live_slides():
    slides = [
        _slide_dict("hook", "Ты платишь за мощность, которая простаивает", "generated", [_media("generated", 0.08, 0.06, 0.84, 0.5, frame="paper"), _text(y=0.62)], brief=BRIEF),
        _slide_dict("evidence", "Простые задачи не требуют флагмана", "graphic", [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="flow_diagram", tone="accent", flow_steps=["ВВОД", "ДЕЙСТВИЕ", "РЕЗУЛЬТАТ"]), _text(y=0.56)]),
        _slide_dict("takeaway", "Выбирай модель под задачу", "source", [_media("source", 0.5, 0.1, 0.42, 0.4, frame="paper"), _text(0.08, 0.55, 0.8, 0.24)], subject="source"),
    ]
    slides[1]["visual_direction"] = "«Задача → Модель → Результат»"
    for slide in slides:
        slide["source_evidence"] = "E1"
    return slides


def _live_output():
    out = _v10_output(_live_slides())
    out["content_archetype"] = "news_insight"
    out["creative_execution_plan"]["media_strategy"] = "generated_media"
    return out


@pytest.mark.asyncio
async def test_live_trigger_runs_the_media_first_pipeline_end_to_end(db_session, monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import services.instagram_automatic_trigger as trigger
    from tests.test_instagram_phase_b42_orchestration import RoutingFakeGateway, _news_opportunity, _patch_delivery

    calls: list[dict] = []
    monkeypatch.setattr(media, "build_budgeted_image_executor", lambda: _Executor(calls))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "live")
    photo = _photo()

    async def fake_source(session, story_id):
        return photo, SimpleNamespace(id=uuid4(), candidate_id="cand-b6"), 1, 100

    monkeypatch.setattr(trigger, "_resolve_single_source_image", fake_source)
    captured = _patch_delivery(monkeypatch)
    gateway = RoutingFakeGateway(_live_output())
    outcome = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, AsyncMock(), opportunity=_news_opportunity(), opportunity_summary="Дешёвая модель для простых задач", gateway=gateway,
        prompt_repository=FilePromptRepository(_PROMPTS), phase_a_enabled=True)
    assert outcome.accepted is True and outcome.reason == "submitted", outcome.reason
    request_text = gateway.carousel_request().messages[1].content[0].text
    assert "KAGE VOICE (shared brand voice, source of truth docs/brand/kage_voice_v1.md" in request_text
    assert "SOURCE_SUITABLE_FOR_FINAL_VISUAL: yes" in request_text and "GENERATED media is a first-class option" in request_text
    assert len(calls) == 1 and calls[0]["max_attempts"] == 1  # exactly the ONE generated slide; no retries
    obs = captured["package"].media_plan["b4_observability"]
    assert obs["prompt_version"] == "10.4" and obs["text_only_slides"] == [] and obs["typographic_final_media_slides"] == []
    assert [s["media_source"] for s in obs["slides"]] == ["generated", "graphic", "source"]
    assert obs["overlay_operations_executed_total"] == 0 and obs["art_validation_passed"] is True, obs["art_blocking_issues"]
    plan = captured["package"].media_plan
    assert plan["media_first"] is True and plan["media_execution"]["assets"][0]["media_mode"] == "GENERATED"
    assert plan["media_execution"]["assets"][0]["generation_prompt_sha256"] and plan["media_execution"]["assets"][0]["accounted_cost_usd"] == "0.04310"


@pytest.mark.asyncio
async def test_live_trigger_never_ships_a_generated_slide_without_its_image_or_a_typographic_only_plan(db_session, monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import services.instagram_automatic_trigger as trigger
    from tests.test_instagram_phase_b42_orchestration import RoutingFakeGateway, _news_opportunity, _patch_delivery

    photo = _photo()

    async def fake_source(session, story_id):
        return photo, SimpleNamespace(id=uuid4(), candidate_id="cand-b6"), 1, 100

    monkeypatch.setattr(trigger, "_resolve_single_source_image", fake_source)
    _patch_delivery(monkeypatch)
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "off")  # production default
    off = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, AsyncMock(), opportunity=_news_opportunity(), opportunity_summary="s", gateway=RoutingFakeGateway(_live_output()),
        prompt_repository=FilePromptRepository(_PROMPTS), phase_a_enabled=True)
    assert off.reason == "generation_off"  # fail closed: no render, no delivery
    bare = _live_output()
    bare["slides"][1] = _slide_dict("evidence", "Пустой слайд", "graphic", [_r("accent", 0.08, 0.5, 0.2, 0.01, accent_type="rule_h"), _text(y=0.56)])
    typographic = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, AsyncMock(), opportunity=_news_opportunity(), opportunity_summary="s", gateway=RoutingFakeGateway(bare),
        prompt_repository=FilePromptRepository(_PROMPTS), phase_a_enabled=True)
    assert typographic.reason == "creative_director_failed:MediaFirstContractError"
