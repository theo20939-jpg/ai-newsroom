"""KAGE downstream evidence package (services/instagram_evidence_package.py): verbatim, provenance-tagged STEP / FACT / LIMITATION lines
for an already-selected post, AI_HACK step readiness, Telegram outbound-link follow, official-doc enrichment, recap body sanitation,
source-media readiness, the worker gate, the Phase A token bound and selection immutability. Text fragments are real extractions from
the 5-11 Aug 2026 week. No network, no provider."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import services.instagram_evidence_package as ep

WIRED = """How to Disable Gemini in Gmail and Google Docs | WIRED
Skip to main content
SECURITY
POLITICS
How to Disable Gemini in Gmail and Google Docs
New AI toolbars and prompts are showing up in Google Docs and Gmail. If you don't want Gemini's help in writing documents and emails, here's how to turn that stuff off.
If you're one of the users who sees this feature and you don't want it on your screen, good news: The giant bar is easy enough to hide.
Click
Gemini
in the menu bar, then hover over
Bottom bar preferences
and select
Turn off
.
Courtesy of Justin Pot
Open your Gmail account, then click the gear in the top right corner.
Next, click See all settings.
Then, in the General tab, scroll down until you see the Smart features option.
Save on industry-leading noise-canceling audio, and pro-level Alpha cameras.
"""
ENGADGET = """How to use ChatGPT's new, more natural Voice Mode for conversations
Latest
News
How to use ChatGPT's new, more natural Voice Mode for conversations
Talking to ChatGPT just got a lot less awkward, and this is a long enough lede line to count as the start of the real article body here.
To get started, simply tap the ChatGPT Voice icon, which is represented by a waveform symbol, at the far right of the text box.
If you tap on the settings icon at the top-right corner, you can change the intelligence of the voice model.
This customization is not available on the GPT-Live-1 mini model, so currently requires a paid plan.
"""
HABR = """Бесплатный Kimi-k3 в JetBrains: настройка Continue за 5 минут
Привет, Хабр! Расскажу, как подключить Kimi-k3-free в вашу JetBrains IDE через плагин Continue — и всё это абсолютно бесплатно, с ограничениями.
1. Регистрируемся на TokenRouter
Идём на tokenrouter.com
Создаём API-ключ (кнопка "Create API Key")
2. Устанавливаем Continue
File → Settings → Plugins → ищем Continue → устанавливаем → перезапускаем.
{ "model": "moonshotai/kimi-k3-free", "apiBase": "https://api.tokenrouter.com/v1" }
И я предложил этому человеку проверить его слова в деле — только взять не «змейку» и «тетрис», а наш продукт.
"""


def _src(text, kind=ep.ORIGINAL_ARTICLE, url="https://www.wired.com/story/x"):
    return ep.EvidenceSource(url=url, source_type=kind, text=text)


def _pkg(fmt, title, *sources):
    return ep.assemble_package(post_id="p", fmt=fmt, premise=title, sources=list(sources), media=ep.SourceMedia(status=ep.NOT_AVAILABLE))


# --- AI_HACK step readiness ------------------------------------------------------------------------------------------------------------

def test_a_ui_name_split_out_by_an_inline_link_stays_inside_its_step_and_ads_are_not_steps():
    package = _pkg("ai_hack", "How to Disable Gemini in Gmail and Google Docs", _src(WIRED))
    texts = [s.text for s in package.steps]
    assert "Click Gemini in the menu bar, then hover over Bottom bar preferences and select Turn off." in texts
    assert "Next, click See all settings." in texts
    assert not any("noise-canceling" in t for t in texts)
    assert package.quality == ep.STRONG


def test_a_how_to_written_as_prose_is_recognised_and_its_caveat_is_a_limitation():
    package = _pkg("ai_hack", "How to use ChatGPT's new, more natural Voice Mode for conversations", _src(ENGADGET))
    assert any(s.text.startswith("To get started, simply tap the ChatGPT Voice icon") for s in package.steps)
    assert any("requires a paid plan" in item.text for item in package.limitations)
    assert package.quality == ep.SUFFICIENT


def test_russian_tutorial_steps_paths_and_config_are_steps_but_quoted_words_are_not_a_path():
    package = _pkg("ai_hack", "Бесплатный Kimi-k3 в JetBrains: настройка Continue за 5 минут", _src(HABR, url="https://habr.com/ru/articles/1"))
    texts = " || ".join(s.text for s in package.steps)
    assert "Регистрируемся на TokenRouter" in texts and "File → Settings → Plugins" in texts and '"apiBase"' in texts
    assert "змейку" not in texts
    assert package.quality == ep.STRONG


def test_an_rss_teaser_with_no_step_is_blocking_the_workflow_is_never_invented():
    teaser = ep.EvidenceSource(url=None, source_type=ep.STORED_BODY, text="Adobe's new plugin works both in Work and Codex, and is available today in ChatGPT.")
    package = _pkg("ai_hack", "You can use 70+ Adobe tools without leaving ChatGPT now - here's how", teaser)
    assert package.quality == ep.BLOCKING and package.steps == ()
    assert "invent" in package.why


def test_every_line_keeps_its_provenance_and_different_sources_are_not_silently_merged():
    doc = _src("Start a new chat, then type @Adobe and select Adobe from the menu.", kind=ep.OFFICIAL_DOC, url="https://blog.adobe.com/a")
    article = _src("Adobe tools in ChatGPT\nAdobe tools in ChatGPT: a long lede sentence that is clearly more than one hundred and twenty characters long, so the span starts here.\n"
                   "Open ChatGPT, go to Plugins, and add the Adobe plugin.", url="https://www.zdnet.com/a")
    package = _pkg("ai_hack", "Adobe tools in ChatGPT", article, doc)
    by_url = {s.source_url for s in package.steps}
    assert by_url == {"https://blog.adobe.com/a", "https://www.zdnet.com/a"}
    assert all(s.grounding == "verbatim_source_text" and s.source_type for s in package.steps)
    assert package.steps[0].source_type == ep.OFFICIAL_DOC  # the source hierarchy: official documentation first


# --- TREND facts ----------------------------------------------------------------------------------------------------------------------

def test_a_story_that_mentions_a_restriction_states_a_fact_not_a_how_to_caveat():
    post = ep.EvidenceSource(url="https://t.me/vcnews/1", source_type=ep.TELEGRAM_POST, text=(
        "Австралиец попросил ИИ-агента записать его в спортзал — тот взломал систему фитнес-клуба, чтобы обойти ограничения на частоту "
        "бронирований, и удалил из листа ожидания другого клиента, рассказало ABC."))
    package = _pkg("meme_trend", "Австралиец попросил ИИ-агента записать его в спортзал — тот взломал систему фитнес-клуба", post)
    assert package.limitations == () and len(package.facts) == 1


def test_the_posts_own_article_lines_are_facts_without_repeating_the_headline():
    article = _src("DeepSeek перепутал скамера с жертвой\nDeepSeek перепутал скамера с жертвой — это вступление статьи, которое длиннее ста двадцати символов, чтобы здесь начиналось само тело.\n"
                   "Alyona: Ой нет, у меня сегодня дел много, работа, уборка по дому, так что никак не получится.", url="https://habr.com/ru/articles/2")
    package = _pkg("meme_trend", "DeepSeek перепутал скамера с жертвой", article)
    assert any("уборка по дому" in f.text for f in package.facts)


# --- links ---------------------------------------------------------------------------------------------------------------------------

def test_official_doc_links_are_allow_listed_and_must_name_the_premises_product():
    html = ('<a href="https://blog.adobe.com/en/publish/2026/08/06/introducing-adobe-plugin-chatgpt">x</a>'
            '<a href="https://support.claude.com/en">help centre</a><a href="https://example.com/adobe-chatgpt">other</a>'
            '<a href="https://www.zdnet.com/adobe">own site</a>')
    links = ep.official_doc_links(html, base_url="https://www.zdnet.com/article/a", premise="Adobe plugin for ChatGPT - here's how")
    assert links == ["https://blog.adobe.com/en/publish/2026/08/06/introducing-adobe-plugin-chatgpt"]


def test_a_telegram_post_follows_its_explicit_article_link_never_another_telegram_link():
    assert ep.telegram_outbound_link("см. t.me/other/1 и подробности vc.ru/ai/3070742") == "https://vc.ru/ai/3070742"
    assert ep.telegram_outbound_link("[Объясняем](https://habr.com/ru/articles/3/)") == "https://habr.com/ru/articles/3/"
    assert ep.telegram_outbound_link("только текст") is None


def test_stored_html_bodies_become_plain_text():
    assert ep.plain_text('<img src="x.png" /><p>Привет, <b>Хабр</b>! [ссылка](https://h.com/a)</p>') == "Привет, Хабр ! [ссылка]"


# --- weekly recap sanitation ---------------------------------------------------------------------------------------------------------

PREMISE = "UK AI research testing found OpenAI and Anthropic models went on a hacking spree in tests."
HEADLINES = ["OpenAI and Anthropic models went on a hacking spree when tested by the UK's AI research institute",
             "AI models shock UK testers by going on a hacking spree"]


def test_a_polluted_body_never_reaches_the_recap_even_with_the_same_story_id():
    bodies = [("event:1:body", "They're perfect for time-poor cooks, but which deserves your counter space? From combi models to smart designs."),
              ("event:2:body", "It is the latest development in the ongoing dispute between Apple and the Home Office over data privacy."),
              ("event:3:article", "OpenAI and Anthropic models went on a hacking spree when the UK AI Security Institute tested them in a sandbox.")]
    kept, excluded = ep.sanitize_recap_bodies(PREMISE, HEADLINES, bodies)
    assert [ref for ref, _ in kept] == ["event:3:article"]
    assert excluded == ["event:1:body", "event:2:body"]


@pytest.mark.asyncio
async def test_the_recap_story_package_cites_only_relevant_bodies():
    package = await ep.build_recap_story_package(post_id="s4", premise=PREMISE, headlines=HEADLINES, bodies=[
        ("event:1:body", "<p>They're perfect for time-poor cooks, but which deserves your counter space?</p>"),
        ("event:3:article", "OpenAI and Anthropic models went on a hacking spree when the UK AI Security Institute tested them in a sandbox.")])
    assert package.excluded_bodies == ("event:1:body",)
    assert all("cooks" not in f.text for f in package.facts)


# --- source media ---------------------------------------------------------------------------------------------------------------------

def _candidate(status, width, height, quality="accepted"):
    return SimpleNamespace(status=SimpleNamespace(value=status), quality_validation=SimpleNamespace(status=SimpleNamespace(value=quality)),
                           technical_validation=SimpleNamespace(width=width, height=height, observed_mime="image/jpeg"),
                           declared_width=None, declared_height=None, declared_mime_type=None, remote_url="https://img/x.jpg",
                           discovery_method=SimpleNamespace(value="og_image"))


def test_source_media_readiness_from_the_existing_image_intelligence_result():
    available = ep.media_from_image_intelligence(SimpleNamespace(candidates=[_candidate("validated", 1200, 630)]))
    assert (available.status, available.width, available.height, available.mime_type) == (ep.AVAILABLE, 1200, 630, "image/jpeg")
    assert ep.media_from_image_intelligence(SimpleNamespace(candidates=[_candidate("validated", 100, 100)])).status == ep.INVALID
    assert ep.media_from_image_intelligence(SimpleNamespace(candidates=[], article_fetch_error="http_error")).status == ep.NOT_AVAILABLE


def test_without_source_media_the_director_is_told_so():
    package = _pkg("ai_hack", "How to Disable Gemini in Gmail and Google Docs", _src(WIRED))
    assert package.director_evidence()[-1].startswith("SOURCE MEDIA: NONE")


# --- the async builder (existing acquisition / image paths, stubbed) ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_telegram_post_uses_its_linked_article_and_acquisition_off_leaves_only_the_stored_body(monkeypatch):
    fetched = []

    async def fake_fetch(url, *, event_id):
        fetched.append(url)
        return ("Австралиец попросил ИИ-агента записать его в спортзал\nЖитель Австралии решил воспользоваться ИИ-агентом OpenClaw на базе "
                "Claude для записи в спортзал, пишет ABC, и это длинная строка статьи, чтобы началось тело.", "FULL_TEXT", url)

    monkeypatch.setattr(ep, "_fetch_article", fake_fetch)
    monkeypatch.setattr("services.image_intelligence.run_shadow_discovery", AsyncMock(return_value=SimpleNamespace(candidates=[])))
    common = dict(post_id="p", fmt="meme_trend", title="Австралиец попросил ИИ-агента записать его в спортзал", url="https://t.me/vcnews/1",
                  source_type="TELEGRAM", source_name="vc.ru", stored_body="Австралиец попросил ИИ-агента... vc.ru/ai/3070742", event_id=uuid4())
    package = await ep.build_daily_evidence_package(**common)
    assert fetched == ["https://vc.ru/ai/3070742"]
    assert [s.source_type for s in package.sources] == [ep.TELEGRAM_POST, ep.LINKED_ARTICLE]
    assert package.media.status == ep.NOT_AVAILABLE
    off = await ep.build_daily_evidence_package(**{**common, "fmt": "ai_hack"}, acquisition_enabled=False, media_mode="off")
    assert [s.source_type for s in off.sources] == [ep.TELEGRAM_POST] and off.quality == ep.BLOCKING
    assert fetched == ["https://vc.ru/ai/3070742"]  # acquisition off: no fetch at all


# --- worker gate ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_blocking_package_never_reaches_the_director(monkeypatch):
    import worker.content_cycle as cc
    from tests.test_instagram_automatic_trigger_worker_wiring import _FakeEventRow, _feed_pool, _session_factory_for

    monkeypatch.setattr(cc.settings, "instagram_automatic_generation_enabled", True)
    director = AsyncMock()
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_candidate", director)
    monkeypatch.setattr(cc, "_classify_event_for_router_treatment", AsyncMock(return_value=SimpleNamespace(treatment="SKIP", reason="x")))
    ids = [uuid4()]
    _feed_pool(monkeypatch, ids, ["How to use Claude voice mode"])
    monkeypatch.setattr(cc, "build_daily_evidence_package", AsyncMock(return_value=SimpleNamespace(
        quality=ep.BLOCKING, why="no step", director_evidence=lambda: [])))
    report = await cc._run_instagram_automatic_trigger(_session_factory_for(_FakeEventRow()), AsyncMock(), ids,
                                                       gate_gateway=object(), gate_prompt_repository=object())
    director.assert_not_awaited()
    assert report.stories_evaluated == 0


# --- cost bound, budget isolation, selection immutability ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_phase_a_decision_call_is_bounded_and_a_truncation_is_reported_as_such():
    import services.instagram_creative_director as cd
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from tests.fakes.fake_gateway import FakeLLMGateway

    gateway = FakeLLMGateway(generate_response=GenerateResponse(text=None, structured_output=None, finish_reason="length", model_used="m",
                                                                usage=CapabilityUsage(input_tokens=1, output_tokens=8000)))
    with pytest.raises(cd.CreativeDirectorUnavailableError, match="truncated at max_tokens=8000"):
        await cd.generate_editorial_decision(gateway, FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts"),
                                             decision_input=cd.InstagramEditorialDecisionInput(source_type="news", source_summary="s"))
    assert gateway.received_requests[0].max_tokens == cd._EDITORIAL_DECISION_MAX_TOKENS == 8000


def test_no_other_provider_budget_moved():
    import services.instagram_creative_director as cd
    import services.instagram_source_suitability as suit
    import services.instagram_weekly_recap_editor as editor

    assert cd._CREATIVE_DIRECTOR_MAX_TOKENS == 16_000 and editor.EDITOR_MAX_TOKENS == 8000
    assert "max_tokens=400" in Path(suit.__file__).read_text(encoding="utf-8")


def test_selection_modules_never_read_the_downstream_package():
    root = Path(__file__).resolve().parent.parent / "services"
    for module in ("instagram_feed_product.py", "instagram_feed_planner.py", "instagram_weekly_recap.py", "instagram_weekly_recap_editor.py"):
        assert "instagram_evidence_package" not in (root / module).read_text(encoding="utf-8"), module


def test_every_line_the_director_receives_survives_the_real_grounding_check_when_quoted_verbatim():
    """E2E 2026-09-25: provenance glued onto the text ('STEP (host): ...') made the Director's verbatim quotes fail
    assert_evidence_grounded on every post. The Director gets the exact source text; provenance stays in the package."""
    from services.instagram_creative_director import assert_evidence_grounded

    package = _pkg("ai_hack", "How to Disable Gemini in Gmail and Google Docs", _src(WIRED))
    evidence = package.director_evidence()
    quoted = [s.text for s in package.steps] + [f.text for f in package.facts]
    assert quoted and all(q in evidence for q in quoted)
    assert_evidence_grounded(quoted, evidence)  # raises on any mismatch
    assert package.steps[0].source_url == "https://www.wired.com/story/x"  # provenance kept in the package
