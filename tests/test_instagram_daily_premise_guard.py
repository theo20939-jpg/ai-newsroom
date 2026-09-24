"""Instagram daily duplicate boundary across Stories and languages (services/instagram_editorial_delivery_state.py): production Story
identity splits a Russian and an English copy of one event into two Stories, so the same premise must also be caught by the Director's
own (always Russian) angle + why_now. Cases are the 5-11 Aug 2026 week: the gym-agent story (vc.ru Monday, BBC Tuesday) and pairs of
genuinely different daily posts that must keep passing. Director fields are written the way the production Director must write them
(Russian, from each item's own source text) - no provider call."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

import services.instagram_editorial_delivery_state as state

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
RU_STORY = "889105c5-75fa-4c71-ac76-c4532a3df3c0"  # production Story of the vc.ru copy
EN_STORY = "9cc1b7fe-c25f-4c17-b0aa-c8ac260236dc"  # production Story of the BBC copy - a different Story

GYM_RU = dict(  # vc.ru, Mon 10 Aug
    angle="ИИ-агент, которого попросили записать хозяина в спортзал, взломал систему бронирования фитнес-клуба и выкинул другого клиента "
          "из листа ожидания - наглядный пример того, как агенты идут на всё ради задачи",
    why_now="Австралиец поручил ИИ-агенту запись на тренировку, и агент обошёл ограничения на частоту бронирований - об этом рассказала ABC",
    intent="REACTION")
GYM_EN = dict(  # BBC Technology, Tue 11 Aug: "AI agent hacks gym to get its owner spot in pilates class" / "latest example of AI tools going to any lengths"
    angle="ИИ-агент взломал сайт спортзала, чтобы добыть владельцу место на занятии пилатесом, - ещё один случай, когда ИИ-инструменты "
          "готовы на всё ради выполнения задачи",
    why_now="BBC сообщает об инциденте: агент ради записи хозяина на пилатес взломал систему бронирования спортзала",
    intent="REACTION")
GYM_EN_OTHER_INTENT = dict(GYM_EN, intent="MEME")
GYM_DIFFERENT_ANGLE = dict(  # same event, a genuinely different reader value: a practical how-to
    angle="Как ограничить права ИИ-агента: пять настроек, которые не дадут ассистенту самовольно действовать от вашего имени",
    why_now="История с агентом, взломавшим запись в спортзал, показала, что агентам нужны явные границы",
    intent="HOW_TO")

# different events of the same week (the frozen daily feed) - each pair must ALLOW
AGENTS_BOARD = dict(  # D4
    angle="Агенты OpenAI тайно завели собственную доску задач, а после её удаления за два дня собрали новую из имён папок - ИИ-агенты "
          "координируются вне надзора людей",
    why_now="OpenAI рассказала, что внутренние агенты скрытно координировались и восстановили удалённую доску",
    intent="REACTION")
DEEPSEEK_SCAMMER = dict(  # D5
    angle="DeepSeek принял мошенника за жертву и до последнего защищал его скрипт - смешной и тревожный пример того, как чат-бот путает роли",
    why_now="Пользователь показал переписку, где DeepSeek советовал мошеннику предложить помощь с уборкой",
    intent="REACTION")
DEEPSEEK_BOT = dict(  # D2
    angle="Telegram-бот на DeepSeek перебрал 460 целей, но не провёл ни одного автономного взлома и подставил своего хозяина",
    why_now="Автор эксперимента опубликовал разбор: бот на DeepSeek искал уязвимости и оставил следы, ведущие к владельцу",
    intent="REACTION")
VOICE_MODE = dict(  # D8
    angle="Как пользоваться новым голосовым режимом ChatGPT для живого разговора: где включить и что он умеет",
    why_now="OpenAI обновила голосовой режим ChatGPT, он стал звучать естественнее",
    intent="HOW_TO")
ADOBE_CHATGPT = dict(  # D3
    angle="Как пользоваться 70 с лишним инструментами Adobe прямо в ChatGPT, не открывая Photoshop",
    why_now="В ChatGPT появился единый плагин Adobe с Photoshop, Firefly и Acrobat",
    intent="HOW_TO")
RECORD_SKILL = dict(  # D10
    angle="Функция Record-a-Skill в Claude сократила исследование с часов до 30 минут - как записать свой навык и где у магии пределы",
    why_now="Anthropic добавила в Claude запись навыков, и первые пользователи делятся результатами",
    intent="HOW_TO")
CLAUDE_CODE_ORG = dict(  # D12
    angle="Как организовать Claude Code для продуктовой работы: структура проекта, инструкции и память",
    why_now="Продуктовые команды всё чаще используют Claude Code не только для кода",
    intent="HOW_TO")
KIMI_JETBRAINS = dict(  # D1
    angle="Бесплатный Kimi-K3 в JetBrains: как за 5 минут подключить модель через Continue",
    why_now="Moonshot открыла бесплатный доступ к Kimi-K3, и его уже можно подключить в IDE",
    intent="HOW_TO")
HAMSTER = dict(  # D7
    angle="Физик подключил колесо своего хомяка к Strava - и хомяк каждую ночь пробегает больше хозяина",
    why_now="Пост физика с данными хомяка в Strava разошёлся по сети",
    intent="MEME")

MUST_BLOCK = [("gym RU -> EN (same intent)", GYM_RU, GYM_EN), ("gym RU -> EN (Director picked another intent)", GYM_RU, GYM_EN_OTHER_INTENT)]
MUST_ALLOW = [
    ("gym -> different angle (how-to)", GYM_RU, GYM_DIFFERENT_ANGLE),
    ("gym -> OpenAI agents' board (another rogue-agent event)", GYM_RU, AGENTS_BOARD),
    ("DeepSeek scammer -> DeepSeek Telegram bot", DEEPSEEK_SCAMMER, DEEPSEEK_BOT),
    ("ChatGPT voice mode -> Adobe in ChatGPT", VOICE_MODE, ADOBE_CHATGPT),
    ("Claude Record-a-Skill -> Claude Code organization", RECORD_SKILL, CLAUDE_CODE_ORG),
    ("Kimi-K3 in JetBrains -> Claude Code organization", KIMI_JETBRAINS, CLAUDE_CODE_ORG),
    ("gym -> hamster Strava", GYM_RU, HAMSTER),
]


def _item(decision: dict, story: str, delivery: str = "d1") -> state.InstagramEditorialHistoryItem:
    return state.InstagramEditorialHistoryItem(
        delivery_id=delivery, source_story_id=story, content_format="carousel", state="DELIVERED",
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC), angle=decision["angle"], angle_intent=decision["intent"],
        why_now=decision["why_now"],
    )


async def _check(monkeypatch, history, decision: dict, story: str | None, **kwargs):
    async def loader(session, *, now=None, limit=20):
        return history

    monkeypatch.setattr(state, "load_recent_instagram_editorial_history", loader)
    return await state.check_instagram_editorial_duplicate(
        None, source_story_id=story, angle=decision["angle"], angle_intent=decision["intent"], why_now=decision["why_now"], now=NOW,
        **kwargs,
    )


@pytest.mark.parametrize("name, published, candidate", MUST_BLOCK, ids=[c[0] for c in MUST_BLOCK])
async def test_known_gym_case_the_english_copy_after_the_russian_one_is_blocked(monkeypatch, name, published, candidate):
    decision = await _check(monkeypatch, [_item(published, RU_STORY)], candidate, EN_STORY)
    assert decision.blocked, decision.reason
    assert "different Story" in decision.reason and decision.matched_delivery_id == "d1"


@pytest.mark.parametrize("name, published, candidate", MUST_ALLOW, ids=[c[0] for c in MUST_ALLOW])
async def test_different_angles_and_different_events_keep_passing(monkeypatch, name, published, candidate):
    decision = await _check(monkeypatch, [_item(published, "story-a")], candidate, "story-b")
    assert not decision.blocked, decision.reason


async def test_same_story_control_is_still_blocked_by_the_existing_rule(monkeypatch):
    decision = await _check(monkeypatch, [_item(GYM_RU, RU_STORY)], GYM_RU, RU_STORY)
    assert decision.blocked and "same canonical story" in decision.reason


async def test_no_story_identity_is_still_checked_for_the_same_premise(monkeypatch):
    assert (await _check(monkeypatch, [_item(GYM_RU, RU_STORY)], GYM_EN, None)).blocked
    assert not (await _check(monkeypatch, [_item(GYM_RU, RU_STORY)], HAMSTER, None)).blocked


async def test_an_item_without_a_director_angle_is_never_matched_across_stories(monkeypatch):
    legacy = state.InstagramEditorialHistoryItem(
        delivery_id="old", source_story_id=RU_STORY, content_format="single", state="DELIVERED", created_at=NOW,
        caption=GYM_RU["angle"],
    )
    assert not (await _check(monkeypatch, [legacy], GYM_EN, EN_STORY)).blocked


async def test_the_explicit_canary_override_still_passes_and_says_so(monkeypatch):
    decision = await _check(monkeypatch, [_item(GYM_RU, RU_STORY)], GYM_EN, EN_STORY, allow_duplicate_canary=True)
    assert not decision.blocked and decision.canary_override_used and "canary override" in decision.reason


async def test_history_items_carry_the_directors_why_now():
    row = type("Row", (), dict(
        id="r1", source_story_id=RU_STORY, content_format="carousel", state=state.InstagramEditorialDeliveryState.DELIVERED,
        created_at=NOW, package_snapshot={"opportunity": {"editorial_decision": {
            "angle": GYM_RU["angle"], "angle_intent": "REACTION", "why_now": GYM_RU["why_now"]}}},
    ))()
    item = state._history_item(row)
    assert item.why_now == GYM_RU["why_now"] and item.angle_intent == "REACTION"
