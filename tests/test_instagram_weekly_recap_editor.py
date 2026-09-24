"""KAGE weekly recap editor (services/instagram_weekly_recap_editor.py): the deterministic candidate set the ONE editor call reads,
the strict validator that checks every answer against that set, the single-call runner, and the planner/worker wiring with its
deterministic fallback. No provider: a fake gateway. Headlines are real items from the 5-11 Aug 2026 window."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import services.instagram_feed_planner as planner
import services.instagram_weekly_recap_editor as ed
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.instagram_weekly_recap import RecapStory, consolidate
from tests.fakes.fake_gateway import FakeLLMGateway

T0 = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)
PROMPTS = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")

SPEAKER = [
    ("Sources: OpenAI's new device, slated for 2027, is a hockey puck-sized smart speaker with moving parts", "Techmeme"),
    ("Jony Ive's first OpenAI gadget is reportedly a hockey puck-sized smart speaker", "The Verge AI"),
    ("OpenAI's ring-shaped smart speaker will reportedly cost between $300 and $400", "Engadget"),
    ("OpenAI's new AI smart speaker will reportedly sell for between $300-$400", "TechCrunch AI"),
    ("Details Leak on OpenAI's Doughnut-Shaped Smart Speaker", "CNET"),
]


def _story(sid: str, title: str, sources=("Engadget",), days: float = 0.0, category: str = "AI") -> RecapStory:
    return RecapStory(story_id=sid, titles=(title,), sources=frozenset(sources), first_seen=T0 + timedelta(days=days), category=category)


def _week(extra=()):
    stories = [
        _story("telegram", "Telegram briefly pulled from the App Store over child sexual abuse material availability",
               ("9to5Mac", "Engadget", "Rozetked", "CNET", "vc.ru", "3DNews")),
        _story("assistant", "Google Assistant will vanish from Android phones and connected devices in September",
               ("9to5Google", "Engadget", "ZDNET", "The Verge AI"), category="GADGETS"),
        _story("gta", "Netflix bags an exclusive GTA VI trailer... for all of six hours", ("Engadget", "PC Gamer", "Rozetked"), category="OTHER"),
        _story("gta-solo", "The GTA 3D trilogy fanpatch has its biggest update, with over 100 new fixes", ("PC Gamer",), category="OTHER"),
        _story("aggregator-only", "Samsung confirms Galaxy Z Fold 8 record-breaking sales numbers", (), category="GADGETS"),
        _story("lonely", "A small note about a niche Rust crate release for embedded AI boards", ("Lobsters",)),
        *[_story(f"speaker-{i}", title, (outlet,), days=0.1 * i) for i, (title, outlet) in enumerate(SPEAKER)],
        *extra,
    ]
    return consolidate(stories)


def _ids(candidates, needle: str) -> list[str]:
    return [c.candidate_id for c in candidates if needle.lower() in " ".join(c.item.titles).lower()]


# --- the deterministic candidate set --------------------------------------------------------------------------------------------

def test_candidates_keep_widely_carried_stories_and_one_outlet_fragments_of_an_echoed_story():
    candidates = ed.build_editor_candidates(_week())
    headlines = [c.headline for c in candidates]
    assert _ids(candidates, "Telegram briefly pulled") and _ids(candidates, "Google Assistant")
    # the speaker leak is six one-outlet fragments in production; its echo (the same headline words across outlets) lists it, capped
    assert 1 <= len(_ids(candidates, "smart speaker")) <= ed.ECHO_LINES_MAX + 1
    # one outlet and no echo: listed only while the budget lasts, after every echoed story
    assert headlines.index(next(h for h in headlines if "niche Rust crate" in h)) > max(
        headlines.index(h) for h in headlines if "smart speaker" in h)
    assert not any("Fold 8" in h for h in headlines)  # only aggregators carried it: not an outlet
    assert [c.candidate_id for c in candidates] == [f"C{i:03d}" for i in range(1, len(candidates) + 1)]


def test_a_widely_carried_story_outside_the_daily_feeds_world_is_offered_as_culture_a_niche_one_is_not():
    candidates = ed.build_editor_candidates(_week())
    gta = [c for c in candidates if "Netflix" in c.headline]
    assert gta and gta[0].category_hint == "CULTURE"
    assert not any("fanpatch" in c.headline for c in candidates)


def test_the_candidate_set_is_deterministic_and_bounded_by_its_budget():
    week = _week()
    assert [c.headline for c in ed.build_editor_candidates(week)] == [c.headline for c in ed.build_editor_candidates(week)]
    small = ed.build_editor_candidates(week, char_budget=400)
    assert 1 <= len(small) < len(ed.build_editor_candidates(week))
    assert sum(len(ed.render_candidate(c)) for c in small) <= 400


def test_the_exact_daily_premise_is_attached_to_the_story_that_was_a_daily_post():
    candidates = ed.build_editor_candidates(_week(), daily_premise_by_story={"telegram": "Telegram vanished from the App Store overnight"})
    telegram = next(c for c in candidates if "Telegram" in c.headline)
    assert telegram.daily_premise == "Telegram vanished from the App Store overnight"
    assert "DAILY=YES: Telegram vanished" in ed.render_candidate(telegram)
    assert all(c.daily_premise is None for c in candidates if c is not telegram)


def test_evidence_is_the_headlines_own_story_text_and_off_topic_bodies_are_never_attached():
    candidates = ed.build_editor_candidates(_week())
    enriched = ed.attach_evidence(candidates, {
        "telegram": "<p>Apple removed <b>Telegram</b> from the App Store for several hours; https://x.example/a CSAM material was cited.</p>",
        "assistant": "Our favourite air fryers of the year, tested by our expert cooks.",  # a polluted membership: another event's text
    })
    telegram = next(c for c in enriched if "Telegram" in c.headline)
    assert telegram.evidence and "<" not in telegram.evidence and "https://" not in telegram.evidence
    assert next(c for c in enriched if "Google Assistant" in c.headline).evidence is None


# --- the validator --------------------------------------------------------------------------------------------------------------

def _entry(rank, primary, merged=None, *, premise="Telegram was briefly removed from Apple's App Store.", category="VIRAL", overlap="NONE"):
    return {"rank": rank, "primary_candidate_id": primary, "merged_candidate_ids": merged or [primary], "weekly_premise": premise,
            "category": category, "why_this_made_the_week": "Six outlets in two languages.", "why_now": "It happened on Tuesday.",
            "daily_overlap": overlap}


def _candidates():
    return ed.build_editor_candidates(_week(), daily_premise_by_story={"assistant": "Google Assistant is going away"})


def test_a_valid_answer_with_an_editorial_merge_is_accepted_and_ranks_are_renumbered():
    candidates = _candidates()
    tg = _ids(candidates, "Telegram")[0]
    speakers = _ids(candidates, "smart speaker")
    result = ed.validate_editor_output({"items": [
        _entry(3, speakers[0], speakers, premise="OpenAI's first device is reportedly a hockey puck-sized smart speaker.", category="AI"),
        _entry(1, tg),
    ], "daily_overlap_exclusions": []}, candidates)
    assert [p.rank for p in result.picks] == [1, 2]
    assert result.picks[0].primary.candidate_id == tg
    assert [c.candidate_id for c in result.picks[1].merged] == speakers
    assert result.dropped == ()


@pytest.mark.parametrize("mutate, reason", [
    (lambda c: _entry(1, "C999"), "unknown candidate id"),
    (lambda c: _entry(1, _ids(c, "Telegram")[0], overlap="REPEAT"), "exact repeat"),
    (lambda c: _entry(1, _ids(c, "Google Assistant")[0], premise="Google Assistant leaves Android.", category="GADGET"),
     "claims no daily overlap"),
    (lambda c: _entry(1, _ids(c, "Telegram")[0], premise="Telegram was removed from the App Store for 12 hours."), "premise number"),
    (lambda c: _entry(1, _ids(c, "Telegram")[0], category="BUSINESS"), "outside the contract"),
    (lambda c: _entry(1, _ids(c, "Telegram")[0], premise=" "), "empty premise"),
])
def test_an_item_outside_the_contract_is_dropped_with_its_reason(mutate, reason):
    candidates = _candidates()
    result = ed.validate_editor_output({"items": [mutate(candidates)], "daily_overlap_exclusions": []}, candidates)
    assert result.picks == ()
    assert len(result.dropped) == 1 and reason in result.dropped[0]


def test_a_candidate_id_is_used_by_one_item_only_and_a_broader_daily_story_may_stay_as_a_different_angle():
    candidates = _candidates()
    tg, assistant = _ids(candidates, "Telegram")[0], _ids(candidates, "Google Assistant")[0]
    result = ed.validate_editor_output({"items": [
        _entry(1, tg), _entry(2, tg, [tg], premise="Again Telegram."),
        _entry(3, assistant, premise="Google Assistant will vanish from Android phones in September.", category="GADGET",
               overlap="DIFFERENT_ANGLE"),
    ], "daily_overlap_exclusions": [{"candidate_ids": [assistant], "reason": "same premise as D1"}]}, candidates)
    assert [p.primary.candidate_id for p in result.picks] == [tg, assistant]
    assert "already used" in result.dropped[0]
    assert result.daily_exclusions == (((assistant,), "same premise as D1"),)


def test_a_malformed_or_oversized_answer_raises():
    candidates = _candidates()
    with pytest.raises(ed.WeeklyRecapEditorError):
        ed.validate_editor_output({"picks": []}, candidates)
    with pytest.raises(ed.WeeklyRecapEditorError):
        ed.validate_editor_output({"items": [_entry(i, "C001") for i in range(1, 10)]}, candidates)


def test_an_empty_answer_is_respected_no_filler():
    assert ed.validate_editor_output({"items": [], "daily_overlap_exclusions": []}, _candidates()).picks == ()


# --- the single call -------------------------------------------------------------------------------------------------------------

def _response(output, finish="stop"):
    return GenerateResponse(text=None, structured_output=output, finish_reason=finish, model_used="fake",
                            usage=CapabilityUsage(input_tokens=100, output_tokens=100))


@pytest.mark.asyncio
async def test_the_editor_makes_exactly_one_bounded_call_with_the_real_prompt_contract():
    candidates = _candidates()
    tg = _ids(candidates, "Telegram")[0]
    gateway = FakeLLMGateway(generate_response=_response({"items": [_entry(1, tg)], "daily_overlap_exclusions": []}))
    result, _call = await ed.run_weekly_recap_editor(gateway, PROMPTS, candidates=candidates, daily_premises=["Google Assistant is going away"],
                                                     week_label="5-11 August 2026")
    assert len(gateway.received_requests) == 1
    request = gateway.received_requests[0]
    assert request.max_tokens == ed.EDITOR_MAX_TOKENS and request.response_mode == "json_schema"
    assert request.response_schema["properties"]["items"]["maxItems"] == ed.EDITOR_MAX_ITEMS
    # editorial judgment: the strongest configured model that fits the weekly cap, with real reasoning - not the lowest-cost route
    assert request.preferred_model == ed.EDITOR_PREFERRED_MODEL == "gpt-5.6-terra" and request.reasoning_effort == "medium"
    assert "strongest_alternative_beaten" in request.response_schema["properties"]["items"]["items"]["required"]
    user = request.messages[1].content[0].text
    assert "D1: Google Assistant is going away" in user and f"\n{tg} " in user and "Telegram briefly pulled" in user
    assert [p.primary.candidate_id for p in result.picks] == [tg]


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway", [
    FakeLLMGateway(generate_error=RuntimeError("provider down")),
    FakeLLMGateway(generate_response=_response({"items": []}, finish="length")),
    FakeLLMGateway(generate_response=_response(None)),
])
async def test_any_call_failure_raises_the_editor_error_and_never_retries(gateway):
    with pytest.raises(ed.WeeklyRecapEditorError):
        await ed.run_weekly_recap_editor(gateway, PROMPTS, candidates=_candidates(), daily_premises=[], week_label="w")
    assert len(gateway.received_requests) == 1


@pytest.mark.asyncio
async def test_a_truncated_answer_is_reported_as_truncation_and_keeps_the_paid_call_for_accounting():
    """The first calibrated live call (terra, medium reasoning) came back truncated with no structured output: the error must say
    so (finish_reason is checked before the missing output) and carry the provider call, so its spend is recorded."""
    gateway = FakeLLMGateway(generate_response=_response(None, finish="length"))
    with pytest.raises(ed.WeeklyRecapEditorError, match="truncated") as info:
        await ed.run_weekly_recap_editor(gateway, PROMPTS, candidates=_candidates(), daily_premises=[], week_label="w")
    assert info.value.call is not None and info.value.call.usage.output_tokens == 100


# --- planner + worker wiring ----------------------------------------------------------------------------------------------------

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _session_with_week():
    rows = []
    specs = [("Telegram briefly pulled from the App Store over child sexual abuse material availability", s)
             for s in ("9to5Mac", "Engadget", "Rozetked", "CNET", "vc.ru", "3DNews")]
    specs += [("Google Assistant will vanish from Android phones and connected devices in September", s)
              for s in ("9to5Google", "Engadget", "ZDNET", "The Verge AI")]
    specs += [("Samsung confirms Galaxy Z Fold 8 record-breaking pre-order numbers", s)
              for s in ("9to5Google", "CNET", "ZDNET", "Engadget")]
    stories = {}
    for title, source in specs:
        story = stories.setdefault(title, SimpleNamespace(id=uuid4(), first_event_id=None))
        event = SimpleNamespace(id=uuid4(), title=title, url=f"https://{source.lower().replace(' ', '')}.example/a", category=None,
                                collected_at=T0)
        story.first_event_id = story.first_event_id or event.id
        link = SimpleNamespace(match_type="supporting_source")
        rows.append((link, event, SimpleNamespace(name=source, url=f"https://{source}.example"), story))
    return SimpleNamespace(execute=AsyncMock(return_value=_Rows(rows)))


@pytest.mark.asyncio
async def test_planner_uses_the_editor_picks_when_the_call_succeeds(monkeypatch):
    monkeypatch.setattr(planner, "load_feed_evidence", AsyncMock(return_value={}))

    async def one_pick(gateway, repo, *, candidates, daily_premises, week_label):
        tg = next(c for c in candidates if "Telegram" in c.headline)
        return ed.EditorResult(picks=(ed.EditorPick(1, tg, (tg,), "Telegram left the App Store briefly.", "VIRAL", "why", "now", "NONE"),),
                               dropped=(), daily_exclusions=()), None

    monkeypatch.setattr(ed, "run_weekly_recap_editor", one_pick)
    out = await planner.select_weekly_recap_candidates(_session_with_week(), now=T0 + timedelta(days=1), used_story_ids=set(),
                                                       editor_gateway=object(), editor_prompt_repository=object())
    assert len(out) == 1 and out[0].relevance_tier == "INSTAGRAM_WEEKLY_VIRAL"
    assert out[0].reason.startswith("Telegram left the App Store briefly.")


@pytest.mark.asyncio
async def test_planner_falls_back_to_the_deterministic_recap_when_the_editor_fails(monkeypatch):
    monkeypatch.setattr(planner, "load_feed_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(ed, "run_weekly_recap_editor", AsyncMock(side_effect=ed.WeeklyRecapEditorError("provider down")))
    session = _session_with_week()
    with_editor = await planner.select_weekly_recap_candidates(session, now=T0 + timedelta(days=1), used_story_ids=set(),
                                                               editor_gateway=object(), editor_prompt_repository=object())
    without = await planner.select_weekly_recap_candidates(session, now=T0 + timedelta(days=1), used_story_ids=set())
    assert [c.story_id for c in with_editor] == [c.story_id for c in without]
    assert len(without) >= 3


@pytest.mark.asyncio
async def test_worker_hands_the_recap_gateway_and_daily_premises_to_the_selector(monkeypatch):
    import worker.content_cycle as cc
    from core.config import settings

    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", True)
    monkeypatch.setattr(settings, "instagram_weekly_recap_enabled", True)
    usage = planner.FeedUsage(daily_titles_this_week=["gym"], daily_premise_by_story={"s1": "gym"})
    monkeypatch.setattr(cc, "load_feed_usage", AsyncMock(return_value=usage))
    select = AsyncMock(return_value=[])
    monkeypatch.setattr(cc, "select_weekly_recap_candidates", select)
    monkeypatch.setattr(cc, "build_instagram_recap_bundle", AsyncMock(return_value=None))

    @asynccontextmanager
    async def session_factory():
        yield object()

    gateway, repo = object(), object()
    assert await cc._run_instagram_weekly_recap(session_factory, AsyncMock(), gate_gateway=gateway, gate_prompt_repository=repo) is None
    kwargs = select.await_args.kwargs
    assert kwargs["editor_gateway"] is gateway and kwargs["editor_prompt_repository"] is repo
    assert kwargs["daily_premise_by_story"] == {"s1": "gym"} and kwargs["daily_titles"] == ["gym"]


def test_the_weekly_recap_stays_off_by_default():
    from core.config import settings

    assert settings.instagram_weekly_recap_enabled is False
