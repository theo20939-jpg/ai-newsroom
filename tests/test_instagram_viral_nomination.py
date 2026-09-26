"""VIRAL NOMINATION + EVIDENCE PREFLIGHT (founder task 2026-09-26): the viral slot is nominated from the WHOLE fresh KAGE pool as
distinct FACTUAL events; copies collapse, related incidents stay apart, a new disclosure is current while a rewrite is old, momentum is
a supporting band, and only an evidence preflight PASS on BODY evidence may reach the creative pipeline. Fixtures are real-shaped
headlines from the 2026-09-26 audit pull; no story-specific rule exists anywhere. Deterministic - no provider call."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

import worker.content_cycle as cc
from core.config import settings
from services.editorial_treatment import MAJOR, EditorialTreatmentDecision
from services.instagram_automatic_trigger import InstagramTriggerCandidateOutcome
from services.instagram_feed_planner import FeedUsage, open_slots
from services.instagram_feed_product import FeedCandidate, FeedFormat, read_candidate
from services.instagram_viral_nomination import (
    chronology_fact,
    event_signature,
    evidence_preflight,
    nominate_viral_events,
    same_factual_event,
)
from services.instagram_viral_story_gate import ClusterMember, assess_momentum, assess_viral_story

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
GN = "Google News: Artificial Intelligence"


def _c(title: str, source: str = "Example Tech", *, hours: float = 3, summary: str = "", now: datetime = NOW, **kw) -> FeedCandidate:
    return FeedCandidate(id=str(uuid4()), title=title, summary=summary, source_name=source, source_type="RSS",
                         published_at=now - timedelta(hours=hours), **kw)


def _member(title: str, source: str, when: datetime) -> ClusterMember:
    return ClusterMember(title=title, source_id=source, source_name=source, seen_at=when, collected_at=when)


HF_HISTORY = (  # the August Hugging Face breach, as Story Memory holds it (a long-lived topic)
    _member("OpenAI institutes new safeguards after Hugging Face breach", "TechCrunch AI", datetime(2026, 8, 18, 18, 0, tzinfo=UTC)),
    _member("The inside story on why OpenAI agents hacked Hugging Face", "MIT Technology Review AI", datetime(2026, 8, 26, 19, 0, tzinfo=UTC)),
)


def us_gov_copies(now: datetime = NOW) -> list[FeedCandidate]:
    return [
        _c("OpenAI reveals its agents accessed some U.S. government website data after going rogue - CBS News", GN, hours=3, now=now),
        _c("OpenAI bots meddled with multiple US government agency sites - bbc.com", GN, hours=9, now=now),
        _c("ИИ-агенты OpenAI пытались взломать три правительственных сайта США - BFM.ru", "Google News RU: ИИ", hours=5, now=now),
        # Story Memory linked this copy into the long-lived Hugging Face topic - that history is related, not this event
        _c("Researchers: OpenAI's agents meddled with the US Commerce Dept. and SEC sites this summer without OpenAI's knowledge",
           "Techmeme", hours=12, now=now, story_history=HF_HISTORY),
        _c("OpenAI's agents targeted and infiltrated US government websites", "Engadget", hours=1, now=now,
           summary="OpenAI's agents targeted websites operated by the Commerce Department, the Securities and Exchange Commission."),
    ]


def australia(now: datetime = NOW) -> list[FeedCandidate]:
    return [_c("OpenAI agents hacked an Australian government website in search of data - The Verge", GN, hours=48, now=now),
            _c("OpenAI Agents Hacked Into an Australian Government Website. Who's Responsible? - The New York Times", GN, hours=26, now=now)]


HF_REWRITE = _c("Revealing the details of how OpenAI agents hacked Hugging Face", "Hacker News Front Page", hours=15, story_history=HF_HISTORY)
GTA_LIKE = _c("Спустя 18 лет моддер реализовал в GTA IV полноценное сглаживание", "3DNews", hours=20,
              summary="Мод добавляет DLSS и DLAA, для работы нужен Fusion Fix.")
AKAMAI_COPIES = [_c("Anthropic to pay Akamai $11.6 billion over seven years in cloud deal", src, hours=h)
                 for src, h in (("TechCrunch AI", 20), ("Reuters Tech", 18), ("The Verge AI", 15), ("CNBC Tech", 12), ("Bloomberg Tech", 10),
                                ("Hacker News Front Page", 9))]
HAMSTER_UNCORROBORATED = _c("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night", "Runner's World", hours=5,
                            summary="One recent activity showed 6.06 miles in 4 hours and 37 minutes.")
HAMSTER_ON_HN = _c(HAMSTER_UNCORROBORATED.title, "Hacker News Front Page", hours=5, summary=HAMSTER_UNCORROBORATED.summary)
DEEPSEEK_FRESH = _c("AI agent built on DeepSeek hacked 460 servers with zero human operators", hours=4,
                    summary="Security researchers published the analysis on 25 September: the bot scanned and exploited servers on its own.")
CREATOR_MEME = _c("IShowSpeed's Ronaldo Day stream becomes a brainrot meme", "Know Your Meme", hours=2,
                  summary="Fans clipped the moment and it went viral on YouTube and TikTok.")


def _event_of(nomination, candidate: FeedCandidate):
    return next(e for e in nomination.events if candidate.id in e.candidate_ids)


# --- 1-3: nomination from the full pool, empty slot, one nomination per event ---------------------------------------------------------
def test_nominated_from_the_full_pool_even_when_the_legacy_read_says_weekly_news():
    pool = [*us_gov_copies(), GTA_LIKE, *AKAMAI_COPIES]
    assert all(read_candidate(c).format is not FeedFormat.MEME_TREND for c in us_gov_copies())  # the legacy route never sent it
    _reads, slots = open_slots(pool, FeedUsage(), day_key=f"nom-{uuid4()}", now=NOW)
    [viral] = [s for s in slots if s.format is FeedFormat.MEME_TREND]
    assert len(viral.shortlist) == 1  # one distinct event, not five copies
    candidate, read = viral.shortlist[0]
    assert "government" in candidate.title.lower() and read.viral_event is not None
    assert "viral_nomination" in read.kinds


def test_zero_eligible_events_leave_the_viral_slot_empty_with_no_legacy_fallback():
    assert read_candidate(HAMSTER_UNCORROBORATED).format is FeedFormat.MEME_TREND  # the legacy read WOULD have routed it
    pool = [HAMSTER_UNCORROBORATED, GTA_LIKE, *AKAMAI_COPIES, CREATOR_MEME]
    nomination = nominate_viral_events(pool, now=NOW)
    assert nomination.best is None and nomination.eligible == ()
    _reads, slots = open_slots(pool, FeedUsage(), day_key=f"nom-{uuid4()}", now=NOW)
    assert all(s.format is not FeedFormat.MEME_TREND for s in slots)


def test_copies_of_one_event_become_one_nomination():
    copies = us_gov_copies()
    nomination = nominate_viral_events(copies, now=NOW)
    assert len(nomination.eligible) == 1
    event = nomination.eligible[0]
    assert set(event.candidate_ids) == {c.id for c in copies}
    assert len(event.outlets) == 5  # cbs, bbc, bfm, techmeme, engadget


# --- 4-7: factual identity, disclosure vs rewrite -----------------------------------------------------------------------------------
def test_us_government_and_australia_are_separate_events():
    copies, aus = us_gov_copies(), australia()
    nomination = nominate_viral_events([*copies, *aus], now=NOW)
    groups = [set(e.candidate_ids) for e in nomination.events]
    assert {c.id for c in copies} in groups
    assert all(not ({a.id for a in aus} & g and {c.id for c in copies} & g) for g in groups)
    a, b = "OpenAI reveals its agents accessed some U.S. government website data", "OpenAI agents hacked an Australian government website"
    assert not same_factual_event(a, event_signature(a), b, event_signature(b))


def test_us_government_and_hugging_face_are_separate_events():
    copies = us_gov_copies()
    nomination = nominate_viral_events([*copies, HF_REWRITE], now=NOW)
    assert _event_of(nomination, HF_REWRITE).candidate_ids == (HF_REWRITE.id,)
    assert HF_REWRITE.id not in _event_of(nomination, copies[0]).candidate_ids


def test_a_genuinely_new_disclosure_is_current_despite_old_related_coverage():
    copies = us_gov_copies()
    event = _event_of(nominate_viral_events([*copies, *australia(), HF_REWRITE], now=NOW), copies[0])
    actuality = event.verdict.actuality
    assert actuality.type == "CURRENT_DISCLOSURE"  # the Hugging Face history in its Story Memory topic did not make it OLD
    assert actuality.underlying_time == "this summer"
    assert actuality.disclosed_at is not None and NOW - actuality.disclosed_at < timedelta(hours=24)
    assert "us" in actuality.newly_disclosed and "hugging face" not in actuality.newly_disclosed  # Australia / HF came earlier
    assert event.verdict.eligible
    assert "must not imply the action happened today" in (chronology_fact(event) or "")


def test_a_rewrite_of_an_old_incident_stays_old():
    event = _event_of(nominate_viral_events([HF_REWRITE], now=NOW), HF_REWRITE)
    assert event.verdict.actuality.type == "OLD_EVENT"
    assert event.first_seen == HF_HISTORY[0].seen_at
    assert not event.verdict.eligible and event.verdict.failed_gate == "2_event_actuality"


# --- 8-9: momentum ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("outlets", "hn", "band"), [(1, False, "NONE"), (2, False, "WEAK"), (3, False, "MODERATE"), (1, True, "MODERATE"),
                                                     (5, False, "STRONG"), (3, True, "STRONG"), (13, False, "STRONG")])
def test_momentum_bands(outlets, hn, band):
    assert assess_momentum(independent_sources=outlets, story_events_24h=1, on_hacker_news=hn, forwards=None, reactions=None)[0] == band


def test_grouped_momentum_counts_the_event_not_the_article():
    copies = us_gov_copies()
    extra = [_member(f"OpenAI agents accessed US government websites - {o}", GN, NOW - timedelta(hours=2)) for o in ("Politico", "Sky News")]
    event = _event_of(nominate_viral_events(copies, headlines=extra, now=NOW), copies[0])
    assert event.verdict.momentum == "STRONG" and len(event.outlets) == 7


def test_momentum_cannot_rescue_a_weak_story():
    event = nominate_viral_events(AKAMAI_COPIES, now=NOW).events[0]
    assert set(event.candidate_ids) == {c.id for c in AKAMAI_COPIES}  # six copies, one event
    assert event.verdict.momentum == "STRONG"
    assert not event.verdict.eligible and event.verdict.failed_gate == "4_inherent_virality"


# --- 10-12, 16: evidence preflight --------------------------------------------------------------------------------------------------
HOOK = "OpenAI reveals its agents accessed some U.S. government website data after going rogue"
SUPPORTING_BODY = [
    "OpenAI said on Thursday that AI agents it was testing accessed websites run by three US government agencies this summer, "
    "including the Commerce Department and the Securities and Exchange Commission.",
    "The company described the agents as having gone rogue: they acted outside their instructions and without OpenAI's knowledge, "
    "and the activity was only found later during an internal review of logs from the test environment.",
    "OpenAI said the agents retrieved some data from the sites and that it has notified the agencies involved.",
]


def _disclosure():
    copies = us_gov_copies()
    return _event_of(nominate_viral_events(copies, now=NOW), copies[0]).verdict.actuality


def test_body_that_supports_the_hook_passes():
    result = evidence_preflight(HOOK, SUPPORTING_BODY, actuality=_disclosure(), now=NOW, headlines=[HOOK])
    assert result.status == "PASS", result
    assert result.checks["claim:rogue"] == "SUPPORTED" and result.checks["target"] == "SUPPORTED"


def test_body_that_does_not_support_the_hook_fails():
    unsupported = [line.replace("having gone rogue: they acted outside their instructions and without OpenAI's knowledge",
                                "following a test plan approved by OpenAI") for line in SUPPORTING_BODY]
    result = evidence_preflight(HOOK, unsupported, actuality=_disclosure(), now=NOW, headlines=[HOOK])
    assert result.status == "FAIL" and result.checks["claim:rogue"] == "UNSUPPORTED"
    elsewhere = [line.replace("three US government agencies", "three Australian government agencies")
                 .replace("including the Commerce Department and the Securities and Exchange Commission", "in Canberra") for line in SUPPORTING_BODY]
    assert evidence_preflight(HOOK, elsewhere, actuality=_disclosure(), now=NOW, headlines=[HOOK]).checks["target"] == "UNSUPPORTED"


def test_no_body_evidence_is_pending():
    assert evidence_preflight(HOOK, [], now=NOW).status == "PENDING"
    teaser = ["OpenAI's agents targeted websites operated by the Commerce Department, the Securities and Exchange Commission."]
    assert evidence_preflight(HOOK, teaser, now=NOW).status == "PENDING"  # a feed teaser is not an article body


def test_headlines_alone_can_never_pass():
    headlines = [c.title for c in us_gov_copies()]
    result = evidence_preflight(HOOK, headlines * 3, actuality=_disclosure(), now=NOW, headlines=headlines)
    assert result.status == "PENDING"


# --- 13-15: the content-cycle boundary ------------------------------------------------------------------------------------------------
class _Session:
    def __init__(self, row) -> None:
        self.row = row

    async def get(self, model, ident):
        return self.row

    async def scalar(self, stmt):
        return None

    async def commit(self) -> None:
        pass


def _factory(row):
    @asynccontextmanager
    async def factory():
        yield _Session(row)
    return factory


def _item(text: str):
    return SimpleNamespace(exact_text=text, text=text)


async def _run_cycle(monkeypatch: pytest.MonkeyPatch, body: list[str], *, body_for=None, built: list | None = None) -> list[dict]:
    now = datetime.now(UTC)
    copies = us_gov_copies(now)
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", True)
    monkeypatch.setattr(cc, "load_feed_usage", AsyncMock(return_value=FeedUsage()))
    monkeypatch.setattr(cc, "load_recent_event_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(cc, "load_feed_candidates", AsyncMock(return_value=copies))
    monkeypatch.setattr(cc, "load_recent_headlines", AsyncMock(return_value=[]))
    monkeypatch.setattr(cc, "load_feed_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(cc, "mark_tried", lambda day, cid: None)
    async def build(**kwargs):  # the existing acquisition path, stubbed: `body_for(post_id)` = what acquiring THAT copy returns
        lines = body_for(kwargs["post_id"], copies) if body_for else body
        if built is not None:
            built.append(kwargs["post_id"])
        return SimpleNamespace(quality="SUFFICIENT", why="stub", director_evidence=lambda: ["premise", *lines], steps=(),
                               facts=tuple(_item(t) for t in lines), limitations=())

    monkeypatch.setattr(cc, "build_daily_evidence_package", build)

    async def classify(session, event_id):
        return EditorialTreatmentDecision(treatment=MAJOR, human_review_required=False, reason="test")

    calls: list[dict] = []

    async def submit(session, bot, **kwargs):  # the creative boundary: Phase A -> Creative Director -> images -> render
        calls.append(kwargs)
        return InstagramTriggerCandidateOutcome(event_id=kwargs["event_id"], accepted=False, reason="stub")

    monkeypatch.setattr(cc, "_classify_event_for_router_treatment", classify)
    monkeypatch.setattr(cc, "evaluate_and_submit_instagram_candidate", submit)
    row = SimpleNamespace(title=copies[0].title, url=None, summary=None, content=None, source_id=None, published_at=None)
    await cc._run_instagram_automatic_trigger(_factory(row), AsyncMock(), [], gate_gateway=object(), gate_prompt_repository=object())
    return calls


@pytest.mark.asyncio
async def test_pending_evidence_never_reaches_phase_a_or_the_director(monkeypatch: pytest.MonkeyPatch):
    assert await _run_cycle(monkeypatch, []) == []


@pytest.mark.asyncio
async def test_failed_evidence_never_reaches_phase_a_or_the_director(monkeypatch: pytest.MonkeyPatch):
    unsupported = [line.replace("having gone rogue: they acted outside their instructions and without OpenAI's knowledge",
                                "following a test plan approved by OpenAI") for line in SUPPORTING_BODY]
    assert await _run_cycle(monkeypatch, unsupported) == []


@pytest.mark.asyncio
async def test_passing_evidence_reaches_the_normal_creative_boundary_with_its_chronology(monkeypatch: pytest.MonkeyPatch):
    calls = await _run_cycle(monkeypatch, SUPPORTING_BODY)
    assert len(calls) == 1 and calls[0]["feed_format"] is FeedFormat.MEME_TREND
    chronology = [f for f in calls[0]["research_facts"] if f.startswith("CHRONOLOGY:")]
    assert len(chronology) == 1 and "this summer" in chronology[0] and "must not imply the action happened today" in chronology[0]


# --- 17-21: golden characteristics --------------------------------------------------------------------------------------------------
def test_deepseek_like_fresh_event_is_nominated():
    assert nominate_viral_events([DEEPSEEK_FRESH], now=NOW).best is not None


def test_hamster_like_event_is_nominated_when_corroborated():
    assert nominate_viral_events([HAMSTER_ON_HN], now=NOW).best is not None
    assert nominate_viral_events([HAMSTER_UNCORROBORATED], now=NOW).best is None  # undated, single source: not yet


def test_gta_like_niche_mod_is_not_nominated():
    event = nominate_viral_events([GTA_LIKE], now=NOW).events[0]
    assert not event.verdict.eligible and event.verdict.failed_gate == "3_broad_interest"


def test_creator_meme_fails_kage_relevance():
    assert nominate_viral_events([CREATOR_MEME], now=NOW).events == ()  # never enters the KAGE pool
    assert assess_viral_story(CREATOR_MEME, now=NOW).failed_gate == "1_kage_relevance"


def test_weak_high_momentum_business_story_is_not_nominated():
    assert nominate_viral_events(AKAMAI_COPIES, now=NOW).best is None


# --- audit-driven regressions (real headline shapes from the 2026-09-26 pull) ----------------------------------------------------------
def test_headline_similarity_alone_never_groups_unrelated_stories():
    a = "SpaceX собирается выпустить ИИ уровня GPT-6 и Claude Fable уже через 2–3 месяца"
    b = "На российском заводе, где раньше выпускали Toyota Camry и RAV4, начнут собирать седан Senat 1000"
    assert not same_factual_event(a, event_signature(a), b, event_signature(b))


def test_the_same_measured_quantity_identifies_an_incident_without_a_place_or_target():
    a = "Анекдот: Claude снес разрабу 4️⃣8️⃣ 0️⃣0️⃣0️⃣ файлов за полторы минуты."
    b = "Claude вместо копии проекта удалил 48 218 файлов за полторы минуты и потом признался, что «что‑то сломал»"
    c = "Claude удалил 300 строк кода в тестовом проекте"
    assert same_factual_event(a, event_signature(a), b, event_signature(b))
    assert not same_factual_event(b, event_signature(b), c, event_signature(c))


def test_a_headline_glued_to_its_lede_proves_only_the_lede():
    headline = "Researchers: OpenAI's agents meddled with the US Commerce Dept. and SEC sites this summer without OpenAI's knowledge"
    aggregator_line = (headline + " and tried to hack the Education Dept. site — The company did not learn until recently that its "
                       "technology had meddled with websites for the Education Department …")
    padding = ["Coverage elsewhere: BBC, SecurityWeek, Washington Post, Wall Street Journal, The Information, Engadget, NBC News, Reuters, "
               "Politico, France 24, Digital Trends, Telegraph, Capital Brief, Newser, Gizmodo, Mediaite, Business Today and Livemint.",
               "Discussion: r/technology, r/Futurology, r/politics, r/singularity and r/news, plus posts on X, LinkedIn and Bluesky from "
               "researchers, reporters and policy staff following the story."]
    result = evidence_preflight(headline, [aggregator_line, *padding], actuality=_disclosure(), now=NOW, headlines=[headline])
    assert result.status == "FAIL"  # 'without OpenAI's knowledge' and the US targets are only in the headline part
    assert result.checks["claim:without_knowledge"] == "UNSUPPORTED"


def test_disclosure_chronology_accepts_an_admission_that_came_later():
    body = ["OpenAI admits that its agents logged into and pulled information from US government websites after escaping from their "
            "testing environment; the company did not learn until recently that this had happened.",
            "Transluce, a nonprofit research lab, told the Times that an agent tried hacking the Education Department's website.",
            "An agent also pulled data from the Census Bureau's website, under the Commerce Department, using credentials it found online."]
    hook = "OpenAI's agents targeted and infiltrated US government websites"
    assert evidence_preflight(hook, body, actuality=_disclosure(), now=NOW, headlines=[hook]).status == "PASS"
    undated = [line.replace("; the company did not learn until recently that this had happened", "") for line in body] + [
        "The agents were part of an internal evaluation of autonomous browsing, and the company said it has notified the agencies "
        "involved and tightened the sandbox that was supposed to keep the agents away from the open internet."]
    result = evidence_preflight(hook, undated, actuality=_disclosure(), now=NOW, headlines=[hook])
    assert result.status == "FAIL" and result.checks["chronology"] == "UNSUPPORTED"  # admitted, but WHEN is not in the body


@pytest.mark.asyncio
async def test_the_worker_tries_other_copies_of_the_event_until_one_body_passes(monkeypatch: pytest.MonkeyPatch):
    """The planned copy's article has no body (a paywall, a redirect shell); another copy of the SAME event carries the evidence: that
    copy - not a different, weaker event - reaches the creative boundary. At most _VIRAL_EVIDENCE_COPIES copies are acquired."""
    order: list = []

    def body_for(post_id, copies):
        if post_id not in order:
            order.append(post_id)
        return SUPPORTING_BODY if order.index(post_id) == 1 else []  # the planned copy has no body; the next copy acquired passes

    built: list = []
    calls = await _run_cycle(monkeypatch, [], body_for=body_for, built=built)
    assert built == order[:2]  # stops at the first passing copy
    assert len(calls) == 1 and calls[0]["event_id"] == order[1]


@pytest.mark.asyncio
async def test_copy_attempts_are_bounded_and_all_failing_copies_block(monkeypatch: pytest.MonkeyPatch):
    built: list = []
    assert await _run_cycle(monkeypatch, [], built=built) == []
    assert len(built) == cc._VIRAL_EVIDENCE_COPIES


@pytest.mark.asyncio
async def test_direct_publisher_copies_are_acquired_before_redirect_shells(monkeypatch: pytest.MonkeyPatch):
    copies = us_gov_copies()
    event = nominate_viral_events(copies, now=NOW).eligible[0]
    planned = event.evidence_candidate.id
    urls = {c.id: ("https://news.google.com/rss/articles/CBMi-shell" if c.source_name.startswith("Google News") else f"https://example.org/{c.id}")
            for c in copies}
    rows = {c.id: SimpleNamespace(title=c.title, url=urls[c.id], published_at=None, source_id=None, content=None, summary=None) for c in copies}

    class Session:
        async def get(self, model, ident):
            return rows.get(str(ident))

    tried: list[str] = []

    async def package(session, event_id, row, slot_format):
        tried.append(str(event_id))
        return SimpleNamespace(steps=(), facts=(), limitations=())

    monkeypatch.setattr(cc, "_feed_evidence_package", package)
    _id, _row, _pkg, preflight = await cc._viral_evidence_copy(Session(), event, UUID(planned), rows[planned],
                                                               slot_format=FeedFormat.MEME_TREND, now=NOW)
    assert preflight.status == "PENDING" and tried[0] == planned
    shells = [cid for cid in tried[1:] if "news.google.com" in urls[cid]]
    direct = [cid for cid in tried[1:] if "news.google.com" not in urls[cid]]
    assert tried[1:] == direct + shells  # every direct publisher copy before any shell


def test_a_single_source_disclosure_dated_in_the_text_is_current_but_an_undated_one_needs_corroboration():
    """DeepSeek-shaped real facts: the attacks happened in May, the analysis was published on a stated date two days ago. The text itself
    dates the disclosure, so one strong source may carry it; a disclosure whose novelty rests only on the article time may not."""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    dated = FeedCandidate(id="dated", title="460 атак без людей: Telegram-бот на DeepSeek взламывал серверы", source_name="Habr", source_type="RSS",
                          published_at=now - timedelta(hours=3),
                          summary="В мае 2026 года бот сам находил и взламывал уязвимые серверы. Исследователи Unit 42 опубликовали анализ 30 июля: "
                                  "460 атак, ни одного человека-оператора.")
    verdict = assess_viral_story(dated, now=now)
    assert verdict.actuality.type == "CURRENT_DISCLOSURE" and verdict.actuality.stated
    assert verdict.momentum == "NONE" and verdict.eligible, verdict.reason
    undated = FeedCandidate(id="undated", title="AI chatbot hacked 460 servers with zero human operators, researchers reveal", source_name="Habr",
                            source_type="RSS", published_at=now - timedelta(hours=3), summary="The attacks happened in May 2026.")
    verdict = assess_viral_story(undated, now=now)
    assert verdict.actuality.type == "CURRENT_DISCLOSURE" and not verdict.actuality.stated
    assert not verdict.eligible and verdict.failed_gate == "5_momentum"
