"""KAGE Instagram feed product (founder brief, 2026-09-24): up to 2 posts a day - AI_HACK first, MEME_TREND selective, ordinary news
never a daily post, news bundled into a weekly recap, no filler. Headlines below are real items from the 5-11 Aug 2026 window
(local candidate history); the old news-first lane rated the business ones MAJOR and would have posted each of them."""
from __future__ import annotations

import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import services.instagram_automatic_trigger as trigger
from schemas.instagram_creative import InstagramEditorialDecision
from services.editorial_treatment import BRIEF, MAJOR, SKIP, EditorialTreatmentDecision
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_creative_director import derive_content_archetype
from services.instagram_feed_planner import FeedUsage, _archetype, mark_tried, open_slots, weekly_recap_identity
from services.instagram_feed_product import (
    ARCHETYPE_BY_FORMAT,
    DAILY_MAX_POSTS,
    FeedCandidate,
    FeedFormat,
    format_from_editorial_decision,
    plan_daily_slots,
    read_candidate,
    select_weekly_recap,
)


def _read(title: str, source: str = "Engadget", source_type: str = "RSS", summary: str = "", coverage: int = 1):
    return read_candidate(FeedCandidate(id=str(uuid4()), title=title, summary=summary, source_name=source, source_type=source_type,
                                        coverage=coverage))


@pytest.mark.parametrize("title", [
    "eBay reports Q2 revenue up 15% YoY to $3.13B, vs. $3.02B est., GMV up 15% to $22.4B",
    "Etsy says it will cut ~220 employees, or ~12% of its workforce, mostly in product and engineering",
    "Sandisk reports Q4 revenue up 372% YoY to $8.97B, vs. $8.48B est.",
    "Big shake-up in Google’s AI team as DeepMind chief executive steps down",
    "General Catalyst leads $1.1B round into 2-month-old River AI",
    "Video game maker EA bought by Saudi-led group for $55bn",
    "One of China’s Most Powerful AI Models Has Also Escaped Containment",  # a lab safety incident is AI news, not a meme
    "OpenAI and Anthropic models went on a hacking spree when tested by the UK's AI research institute",
    "‘Zoomsday’ hack uncovered using fewer than 20 AI prompts",
])
def test_ordinary_news_never_gets_a_daily_slot(title):
    read = _read(title)
    assert read.format in (FeedFormat.WEEKLY_NEWS, FeedFormat.REJECT) and not read.strong


@pytest.mark.parametrize(("title", "source"), [
    ("ciflow/trunk/192514: [UPDATE] Update", "PyTorch Releases"),
    ("v0.32.6", "Ollama Releases"),
    ("openai/codex: 0.147.0-alpha.6", "OpenAI GitHub"),
    ("Deals: M5 MacBook Air up to $300 off, AirPods Max 2 $100 off", "9to5Mac"),
    ("3 Genius Artificial Intelligence (AI) Stocks to Buy Right Now - The Motley Fool", "Google News: Artificial Intelligence"),
    ("Existing machine-learning weather forecasting models rely on predetermined and fixed autoregressive timesteps.", "arXiv cs.LG"),
    ("300+ нейросетей в одном окне, российской картой и без сложных настроек", "Rozetked"),
])
def test_tags_papers_deals_and_promos_are_rejected(title, source):
    assert _read(title, source=source).format is FeedFormat.REJECT


def test_a_telegram_teaser_headline_is_not_a_story():
    assert _read("**🤩**** Бесплатно без лимитов**", source="Код Дурова", source_type="TELEGRAM").format is FeedFormat.REJECT


@pytest.mark.parametrize("title", [
    "«Скопируй промпт дважды и получишь +76%». Я решил проверить",
    "How to Disable Gemini in Gmail and Google Docs",
    "Claude's Record-a-Skill cut my research from hours to 30 minutes - but the magic has limits",
    "You can use 70+ Adobe tools without leaving ChatGPT now - here's how",
    "Почему нейросети съедают токены: что происходит с длинными чатами и как снизить расход",
])
def test_a_method_the_reader_can_try_now_is_an_ai_hack(title):
    read = _read(title, source="Habr: Artificial Intelligence")
    assert read.format is FeedFormat.AI_HACK and read.strong


@pytest.mark.parametrize("title", [
    "Я собрал 33 ИИ-агента на одном движке. Показываю, как устроены пять из них",  # a maker's diary, not a method for the reader
    "Как мы научились не тратить деньги на ненужные ИИ-проекты: 4 ошибки и 1 система",
    "Приручить цифровых чертей: как я собрал тренажёр по софт-скиллам на LLM",
    "A New Trick Reveals AI Models’ Inner Thoughts",
])
def test_a_makers_diary_or_research_is_not_a_hack(title):
    read = _read(title, source="Habr: Artificial Intelligence")
    assert not (read.format is FeedFormat.AI_HACK and read.strong)


@pytest.mark.parametrize(("title", "source"), [
    ("Австралиец попросил ИИ-агента записать его в спортзал — тот взломал систему фитнес-клуба", "vc.ru"),
    ("ИИ в поиске Google убедил людей, что дорожные камеры набиты золотом — началась волна вандализма", "3DNews"),
    ("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night", "Hacker News Front Page"),
    ("$580M undersea cable rerouted to avoid the grave of Dobby the House Elf", "Hacker News Front Page"),
    ("'Wait for me, my Czech friend': Japanese dev adds Czech localization just for the one Steam user who wishlisted his game",
     "PC Gamer"),
])
def test_a_premise_people_send_is_a_meme_trend(title, source):
    read = _read(title, source=source)
    assert read.format is FeedFormat.MEME_TREND and read.strong


@pytest.mark.parametrize(("title", "not_kind"), [
    ("Сайт ВТБ и его веб-приложение перестали открываться в зарубежных браузерах", "oddity"),  # "иностранных" contains "странн"
    ("Бразильское агентство и датская студия разработали бесплатный шрифт", "ai_tool"),  # "агентство" is not an agent
    ("Реакции пользователей на обновление оказались неожиданными", "business"),  # "реакции" contains "акци"
])
def test_russian_stems_match_whole_words_only(title, not_kind):
    assert not_kind not in _read(title, source="vc.ru").kinds


def _pair(title: str, source: str = "Engadget", coverage: int = 1):
    candidate = FeedCandidate(id=str(uuid4()), title=title, source_name=source, coverage=coverage)
    return candidate, read_candidate(candidate)


_HACKS = [_pair("How to Disable Gemini in Gmail and Google Docs"), _pair("How to use Claude's voice mode"),
          _pair("How to use ChatGPT's new, more natural Voice Mode for conversations"), _pair("Here's how to set up Copilot prompts")]
_TRENDS = [_pair("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night"),
           _pair("$580M undersea cable rerouted to avoid the grave of Dobby the House Elf")]
_NEWS = [_pair("eBay reports Q2 revenue up 15% YoY to $3.13B"), _pair("Google Assistant will vanish from Android phones in September")]


def test_a_day_never_exceeds_two_posts_and_ai_hack_comes_first():
    plans = plan_daily_slots(_NEWS + _TRENDS + _HACKS)
    assert [p.format for p in plans] == [FeedFormat.AI_HACK, FeedFormat.MEME_TREND]
    assert len(plans) <= DAILY_MAX_POSTS
    assert all(0 < len(p.shortlist) <= 3 for p in plans)


def test_no_filler_a_day_of_news_has_no_daily_post():
    assert plan_daily_slots(_NEWS) == []


def test_published_posts_close_their_slots():
    assert [p.format for p in plan_daily_slots(_HACKS + _TRENDS, published_today={FeedFormat.AI_HACK: 1})] == [FeedFormat.MEME_TREND]
    assert plan_daily_slots(_HACKS + _TRENDS, published_today={FeedFormat.AI_HACK: 1, FeedFormat.MEME_TREND: 1}) == []


def test_news_insight_is_at_most_one_a_week():
    insight = _pair("5 ошибок, которые делают при работе с нейросетями")
    assert insight[1].format is FeedFormat.NEWS_INSIGHT
    assert [p.format for p in plan_daily_slots([insight])] == [FeedFormat.NEWS_INSIGHT]
    assert plan_daily_slots([insight], news_insight_this_week=1) == []


def test_tried_candidates_are_not_retried_the_same_day():
    candidate, read = _HACKS[0]
    usage = FeedUsage()
    day = f"test-{uuid4()}"
    mark_tried(day, candidate.id)
    _, plans = open_slots([candidate], usage, day_key=day)
    assert plans == []


def test_a_post_of_unknown_format_still_counts_towards_the_daily_maximum():
    usage = FeedUsage(today_total=2)
    _, plans = open_slots([c for c, _ in _HACKS + _TRENDS], usage, day_key=f"test-{uuid4()}")
    assert plans == []


@pytest.mark.parametrize(("kind", "intent", "origin"), list(itertools.product(
    ("NEWS", "NEWS_X_TREND", "PRODUCT_X_TREND", "CULTURE", "PRODUCT", "EVERGREEN"),
    ("BREAKING", "EXPLAINER", "IMPACT", "REACTION", "DEBATE", "COMPARISON", "HOW_TO", "MEME", "PRODUCT_USE_CASE", "EVERGREEN_VALUE"),
    ("NEWS", "TREND", "PRODUCT", "CULTURE", "EVERGREEN"),
)))
def test_the_planned_format_is_the_archetype_the_creative_director_generates(kind, intent, origin):
    decision = {"opportunity_type": kind, "angle_intent": intent, "origin": origin}
    fmt = format_from_editorial_decision(decision)
    parsed = SimpleNamespace(**decision)
    archetype = derive_content_archetype(parsed)
    if fmt is FeedFormat.WEEKLY_NEWS:
        assert archetype == "news_insight"  # a plain news angle: the Director would have made a news post - the product refuses it
    else:
        assert ARCHETYPE_BY_FORMAT[fmt] == archetype


def test_the_weekly_recap_is_broad_skips_daily_stories_and_small_stories():
    daily = _pair("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night", coverage=9)
    pool = [
        _pair("Demis Hassabis drops DeepMind CEO role to become Chair and focus on AGI", coverage=12),
        _pair("OpenAI is giving ChatGPT free users unlimited text chats", coverage=8),
        _pair("Samsung confirms Galaxy Z Fold 8’s record-breaking sales numbers", coverage=7),
        _pair("Telegram CEO says extortionist planted illegal content that triggered App Store removal", coverage=6),
        _pair("Some tiny AI model update nobody covered", coverage=1),
        _pair("eBay reports Q2 revenue up 15% YoY to $3.13B", coverage=4),  # business needs twice the coverage
        _pair("Anthropic AI created fake profiles and impersonated people in attempted hack", coverage=5),
        _pair("Meta claims its own AI also hacked into a third-party service during testing", coverage=5),
        daily,
    ]
    picked = select_weekly_recap(pool, used_daily_ids={daily[0].id})
    titles = [c.title for c, _, _ in picked]
    categories = {cat for _, _, cat in picked}
    assert {"AI", "GADGET"} <= categories
    assert daily[0].title not in titles and "Some tiny AI model update nobody covered" not in titles
    assert not any("eBay" in t for t in titles)
    assert sum("hack" in t for t in titles) <= 1  # a wave of AI incidents is one story of the week


def test_a_weekly_recap_needs_a_real_set():
    assert select_weekly_recap([_pair("OpenAI is giving ChatGPT free users unlimited text chats", coverage=8)]) == []


def test_one_recap_identity_per_iso_week():
    from datetime import datetime, timezone

    monday = datetime(2026, 8, 10, 9, tzinfo=timezone.utc)
    sunday = datetime(2026, 8, 16, 22, tzinfo=timezone.utc)
    assert weekly_recap_identity(monday) == weekly_recap_identity(sunday) != weekly_recap_identity(datetime(2026, 8, 17, tzinfo=timezone.utc))


def test_today_counts_read_the_archetype_recorded_in_the_package_snapshot():
    assert _archetype({"director_input": {"content_archetype": "ai_hack"}}) == "ai_hack"
    assert _archetype({"package": {"media_plan": {"content_archetype": "trend_generative"}}}) == "trend_generative"
    assert _archetype({}) is None


# --- the live trigger: the feed path ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("treatment", "accepted_to_opportunity"), [
    (EditorialTreatmentDecision(MAJOR, human_review_required=False, reason="high significance"), True),
    (EditorialTreatmentDecision(BRIEF, human_review_required=True, reason="no Intelligence significance available"), True),
    (EditorialTreatmentDecision(SKIP, human_review_required=False, reason="very low significance (1) - not worth a post"), True),
    (EditorialTreatmentDecision(SKIP, human_review_required=False, reason="very low significance (1) + weak evidence (x)"), False),
])
async def test_the_feed_path_skips_the_news_significance_gate_but_not_weak_evidence(monkeypatch, treatment, accepted_to_opportunity):
    calls = []

    async def fake_opportunity(*args, **kwargs):
        calls.append(kwargs)
        return trigger.InstagramTriggerCandidateOutcome(event_id="e", accepted=True, reason="submitted")

    monkeypatch.setattr(trigger, "evaluate_and_submit_instagram_opportunity", fake_opportunity)
    outcome = await trigger.evaluate_and_submit_instagram_candidate(
        AsyncMock(), AsyncMock(), event_id=str(uuid4()), event_title="t", treatment=treatment, research_facts=["t"],
        gateway=object(), prompt_repository=object(), feed_format=FeedFormat.AI_HACK,
    )
    assert bool(calls) is accepted_to_opportunity
    if calls:
        assert calls[0]["required_feed_format"] is FeedFormat.AI_HACK
    else:
        assert outcome.reason == "treatment=SKIP:weak_evidence"


@pytest.mark.asyncio
async def test_the_news_lane_without_a_feed_format_keeps_the_major_gate(monkeypatch):
    monkeypatch.setattr(trigger, "evaluate_and_submit_instagram_opportunity", AsyncMock())
    outcome = await trigger.evaluate_and_submit_instagram_candidate(
        AsyncMock(), AsyncMock(), event_id="e", event_title="t",
        treatment=EditorialTreatmentDecision(BRIEF, human_review_required=True, reason="r"), research_facts=["t"],
        gateway=object(), prompt_repository=object(),
    )
    assert outcome.accepted is False and outcome.reason == "treatment=BRIEF"


class _NoCreativeDirector:
    async def generate(self, *args, **kwargs):  # pragma: no cover - reaching it is the failure
        raise AssertionError("a mismatched format must never reach the Creative Director")


@pytest.mark.asyncio
@pytest.mark.parametrize(("decision_intent", "planned", "rejected"), [
    ("BREAKING", FeedFormat.AI_HACK, True),   # the Director reads plain news: the hack slot stays empty
    ("HOW_TO", FeedFormat.MEME_TREND, True),  # another format: not this slot
])
async def test_a_director_decision_that_disagrees_leaves_the_slot_empty_before_generation(monkeypatch, decision_intent, planned, rejected):
    decision = InstagramEditorialDecision(
        source_summary="s", opportunity_type="NEWS", why_now="w", audience_value="a", angle="a", angle_intent=decision_intent,
        topic="t", purpose="VALUE", origin="NEWS", recommended_format="carousel", format_reason="f", creative_direction="c",
    )
    opportunity = ContentOpportunity(
        id=f"opp-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()), news_value=1.0, audience_relevance=0.5,
        product_mention_allowed=False, evidence=["fact"], confidence=0.5,
    )
    decided = trigger.replace(opportunity, editorial_decision=decision.model_dump())

    async def fake_plan(session, **kwargs):
        rec = trigger.recommend_objective(opportunity=decided, has_multi_step_narrative=False)
        return trigger._PhaseAEditorialPlan(
            opportunity=decided,
            format_decision=trigger.evaluate_format_shadow(
                objective=rec.primary_objective, has_video_asset=False, has_multi_step_narrative=False,
            ),
            duplicate=trigger.InstagramEditorialDuplicateDecision(False, "none"), brand_context="", account_context="",
            product_context="", recent_content_context="",
        )

    monkeypatch.setattr(trigger, "_build_phase_a_editorial_plan", fake_plan)
    monkeypatch.setattr(trigger, "get_video_candidates_for_event", AsyncMock(return_value=[]))
    outcome = await trigger.evaluate_and_submit_instagram_opportunity(
        AsyncMock(), AsyncMock(), opportunity=opportunity, opportunity_summary="s", gateway=_NoCreativeDirector(),
        prompt_repository=object(), phase_a_enabled=True, required_feed_format=planned,
    )
    assert outcome.accepted is False and outcome.reason.startswith("feed_format_mismatch:")
