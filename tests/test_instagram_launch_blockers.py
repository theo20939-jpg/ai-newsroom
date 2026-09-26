"""The six blockers of the 2026-09-26 KAGE launch canary, each reproduced from the real failure and fixed without weakening grounding:
1. Phase A retyped a quote with one word changed ('бесперспективная' -> 'бесперспективна'): v3 cites evidence by HANDLE, resolved to the
   exact source text - a quote the model still types itself meets the unchanged strict check;
2. daily evidence glued byline + category + date + headline onto the article sentence (vc.ru gym story);
3. an unsuitable / missing photo turned a slide into fact cells or a stray numeral card: it becomes a designed editorial beat;
4. an AI_HACK carousel without a photo repeated one three-cell card on 6 of 7 slides: diagrams stay only for real UI paths / data;
5. the Russian-copy check missed 'chairman.' and 'open-weight';
6. the live prompts still introduced the Instagram system as NINJA.
No provider, no network, no DB."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

import services.instagram_creative_director as cd
import services.instagram_evidence_package as ep
from integrations.prompts.file_repository import FilePromptRepository
from tests.test_instagram_downstream_blockers import _PhaseAOnly
from tests.test_instagram_format_contract import _decision
from tests.test_instagram_recap_visual_first import _photo, _plan

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = FilePromptRepository(ROOT / "prompts")
CANARY = ROOT / "artifacts/instagram_feed_product/launch_canary_20260926"

# --- 1. exact quotes --------------------------------------------------------------------------------------------------------------------

SOURCE = ("Все остальное сделала нейросеть: нашла в интернете подходящие мишени, оценила их, скачала готовый код для атаки, попробовала его "
          "применить, ничего не добилась, самостоятельно решила, что цель бесперспективная, и ушла искать другую.")
DRIFTED = SOURCE.replace("бесперспективная", "бесперспективна")  # the real single-canary Phase A output


def _input() -> cd.InstagramEditorialDecisionInput:
    return cd.InstagramEditorialDecisionInput(source_type="news", source_summary="s", allowed_evidence=["Заголовок истории", SOURCE],
                                              planned_format="TREND")


@pytest.mark.asyncio
async def test_phase_a_cites_evidence_by_handle_and_gets_the_exact_source_text():
    fake = _PhaseAOnly({**_decision(), "evidence_used": ["E2"]})
    decision, _ = await cd.generate_editorial_decision(fake, PROMPTS, decision_input=_input())
    assert decision.evidence_used == [SOURCE]  # the handle resolved to the exact, unretyped source span
    user = fake.requests[0].messages[1].content[0].text
    assert "E1: Заголовок истории" in user and f"E2: {SOURCE}" in user  # handles are what the model sees
    assert "by their HANDLES ONLY" in fake.requests[0].messages[0].content[0].text


@pytest.mark.asyncio
async def test_a_quote_the_model_still_retypes_with_one_word_changed_is_still_rejected():
    with pytest.raises(cd.UngroundedEvidenceError):
        await cd.generate_editorial_decision(_PhaseAOnly({**_decision(), "evidence_used": [DRIFTED]}), PROMPTS, decision_input=_input())
    with pytest.raises(cd.UngroundedEvidenceError):  # an invented handle is not evidence either
        await cd.generate_editorial_decision(_PhaseAOnly({**_decision(), "evidence_used": ["E9"]}), PROMPTS, decision_input=_input())


# --- 2. daily evidence glue ------------------------------------------------------------------------------------------------------------

VC_RU = ("Приёмная\nДеньги\nАртур Томилко\nAI\n10 авг\n"
         "Австралиец попросил ИИ-агента записать его в спортзал — тот взломал систему фитнес-клуба, чтобы обойти ограничения на частоту "
         "бронирований, и удалил из листа ожидания другого\nклиента\nИсправить свои действия агент не смог.\n"
         "Житель Австралии решил воспользоваться ИИ-агентом OpenClaw на базе Claude для записи в спортзал,\nпишет\nABC.\n")


def test_daily_items_never_start_with_a_glued_byline_or_date_and_keep_the_headline_apart():
    items = [i.text for i in ep.extract_items(ep.EvidenceSource(url="https://vc.ru/ai/3070742", source_type=ep.LINKED_ARTICLE, text=VC_RU),
                                              premise="Австралиец попросил ИИ-агента записать его в спортзал", how_to=False)]
    assert not any(t.startswith(("Артур", "AI ", "10 авг")) or "10 авг Австралиец" in t for t in items)
    assert "Житель Австралии решил воспользоваться ИИ-агентом OpenClaw на базе Claude для записи в спортзал, пишет ABC." in items
    assert not any("клиента Исправить" in t for t in items)  # the headline is not glued to the next sentence


def test_the_real_canary_linked_article_is_cut_cleanly():
    package = json.loads((CANARY / "daily/2026-08-10_2_meme_trend/evidence_package.json").read_text(encoding="utf-8"))
    source = next(s for s in package["sources"] if s["source_type"] == "LINKED_ARTICLE")
    items = ep.extract_items(ep.EvidenceSource(url=source["url"], source_type=source["source_type"], text=source["text"]),
                             premise=package["premise"], how_to=False)
    assert items and not any(i.text.startswith("Артур Томилко") for i in items)


def test_daily_stored_html_is_cut_along_its_paragraphs():
    body = "<p>Институт говорит о новом типе риска</p><p>Модели OpenAI и Anthropic вышли из-под контроля во время теста, сообщил институт.</p>"
    assert ep.recap_paragraphs(body) == ["Институт говорит о новом типе риска",
                                         "Модели OpenAI и Anthropic вышли из-под контроля во время теста, сообщил институт."]


# --- 3/4. no-photo and weak-diagram slides ----------------------------------------------------------------------------------------------

def _diagram(steps, media=()):
    plan = _plan(list(media))
    plan["regions"].append({"kind": "graphic", "x": 0.07, "y": 0.6, "w": 0.86, "h": 0.25, "z": 3, "graphic_type": "flow_diagram",
                            "flow_steps": list(steps)})
    return plan


def test_topic_cells_and_real_ui_paths_all_become_editorial_beats():
    from services.instagram_recap_frames import editorial_fallback_layout

    weak = ["70+ ИНСТРУМЕНТОВ", "ОДИН ДИАЛОГ", "ТВОЯ ЗАДАЧА"]  # the real Adobe hook: one number does not make three facts
    assert editorial_fallback_layout(_diagram(weak), role="hook", slide_text="70+ инструментов Adobe", headline="70+ инструментов Adobe",
                                     photo="source", ui_paths=True)[1] == "ambient"
    step = editorial_fallback_layout(_diagram(["ВОЙТИ В ADOBE", "ГЕНЕРАЦИЯ", "СОХРАНЕНИЕ"]), role="step", slide_text="Шаг 3. Войди в Adobe",
                                     headline="Шаг 3. Войди в Adobe", photo="source", ui_paths=True)
    assert step[1] == "step_numeral" and any(r.get("content_ref") == "number" for r in step[0]["regions"])
    statement = editorial_fallback_layout(_diagram(["ДОСТУПНО СЕГОДНЯ", "ВЕБ + ПРИЛОЖЕНИЕ", "ЕСТЬ ЛИМИТЫ"]), role="takeaway",
                                          slide_text="Начать можно сегодня", headline="Начать можно сегодня", photo=None, ui_paths=True)
    assert statement[1] == "statement" and not any(r.get("graphic_type") for r in statement[0]["regions"])
    # founder decision 2026-09-26: even a real UI path is not kept as 01/02/03 rectangles - its path stays in the slide's own copy
    path = _diagram(["ОТКРОЙ CHATGPT", "ПЕРЕЙДИ В «PLUGINS»", "ДОБАВЬ ADOBE"])
    beat = editorial_fallback_layout(path, role="step", slide_text="Шаг 1", headline="Шаг 1. Добавь плагин", photo=None, ui_paths=True)
    assert beat[1] == "step_numeral" and not any(r.get("graphic_type") for r in beat[0]["regions"])


def test_a_recap_story_whose_photo_was_judged_unsuitable_uses_it_as_a_quiet_layer_even_without_a_photo_region():
    from services.instagram_recap_frames import editorial_fallback_layout

    layout, variant = editorial_fallback_layout(_diagram(["Тестирование", "Поведение моделей", "Риск выявлен"]), role="story",
                                                slide_text="Тесты показали неприятный риск", headline="Тесты показали неприятный риск",
                                                photo="story_4")
    photo = next(r for r in layout["regions"] if r["kind"] == "media")
    assert variant == "ambient" and photo["content_ref"] == "story_4" and photo["tone"] == "muted"


@pytest.mark.parametrize("headline,photo,expected", [
    ("Тесты показали неприятный риск", "story_4", "ambient"),  # the real recap slide that became a '4' numeral card
    ("Начать можно сегодня. Но есть лимит.", None, "statement"),
    ("Шаг 3. Войди в Adobe", None, "step_numeral"),
])
def test_every_editorial_beat_renders_as_planned_and_counts_as_a_visual(headline, photo, expected):
    from services.instagram_carousel_layouts import render_carousel_slide
    from services.instagram_media_first import slide_has_visual
    from services.instagram_platform_renderer import InstagramRenderProfile, profile_spec

    assets = {"story_4": (Image.open(io.BytesIO(_photo(4))), "id4")} if photo else {}
    result = render_carousel_slide(spec=profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE), role="story" if photo else "takeaway",
                                   index=5, total=9, slide_copy=headline, slide_body="Короткое пояснение в одну строку для читателя.",
                                   source_evidence=None, package_identity="p", media_mode="SOURCE" if photo else "GRAPHIC",
                                   layout_plan=_diagram(["Тестирование", "Поведение моделей", "Риск выявлен"]), subject_assets=assets,
                                   media_subject=photo, editorial_fallback=True, ui_paths=not photo)
    assert result.notes["editorial_variant"] == expected and result.notes.get("layout_plan_applied")
    assert slide_has_visual(notes=result.notes, planned_slide=None)


def test_a_plain_text_card_is_still_not_a_visual():
    from services.instagram_media_first import slide_has_visual

    assert not slide_has_visual(notes={"layout_plan_applied": True}, planned_slide={"layout": {"regions": [{"kind": "text"}]}})
    assert not slide_has_visual(notes={"designed_typographic": False}, planned_slide=None)


# --- 5. language ------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,leaks", [
    ("Demis Hassabis становится его chairman.", ["chairman"]),
    ("Meta ставит на open-weight AI", ["open-weight"]),
    ("модели показали deceptive behavior и harmful activity.", ["deceptive", "behavior", "harmful", "activity"]),
    ("OpenAI, Anthropic, ChatGPT, Gemini, Adobe и GTA VI", []),
    ("Открой «Plugins» и введи «@Adobe»", []),
    ("Подробности на chatgpt.com, AI-агент и GPT-5.6", []),
])
def test_ordinary_english_is_caught_through_punctuation_and_hyphens(text, leaks):
    assert cd.english_descriptive_leaks(text) == leaks


# --- 6. KAGE identity -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,version", [
    (cd.EDITORIAL_DECISION_PROMPT_NAME, cd._EDITORIAL_DECISION_PLANNED_PROMPT_VERSION), (cd.SINGLE_PROMPT_NAME, cd._SINGLE_PROMPT_VERSION),
    (cd.CAROUSEL_PROMPT_NAME, cd._CAROUSEL_PROMPT_VERSION), (cd.CAROUSEL_PROMPT_NAME, cd._RECAP_CAROUSEL_PROMPT_VERSION),
    (cd.REEL_PROMPT_NAME, cd._REEL_PROMPT_VERSION),
])
def test_the_live_instagram_prompts_speak_as_kage(name, version):
    prompt = PROMPTS.resolve(name, version)
    text = json.dumps({"system": prompt.system, "rules": prompt.rules, "schema": prompt.output_schema}, ensure_ascii=False)
    for legacy in ("NINJA's Instagram", "NINJA PULSE", "NINJA red", "published by NINJA", "NINJA adaptation"):
        assert legacy not in text, (name, version, legacy)
    assert "KAGE" in text
