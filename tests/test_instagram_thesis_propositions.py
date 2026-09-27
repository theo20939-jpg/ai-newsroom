"""PROPOSITION-AWARE THESIS UNIQUENESS (founder task 2026-09-27, after the canary-7 offline continuation).

Canary 7's slides 3 ('Взаимодействие нашли во время проверки') and 4 ('По SEC признаков компрометации не нашли') were called the same point
because the 4-letter prefix stems made 'Компания' / 'компрометации' one token ('комп') and 'нашли' / 'не нашли' one token ('нашл'). The thesis
layer now compares propositions: conservative stems, polarity, a few predicate concepts and the slide's editorial role."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.instagram_editorial_critic import content_stems
from services.instagram_viral_format import proposition_role, ru_stem, thesis_tokens, viral_copy_findings

ROOT = Path(__file__).resolve().parent.parent
CANARY7 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary7_20260927/post"


def S(head: str, body: str = "") -> dict:
    return {"role": "story", "slide_copy": head, "slide_body": body}


def pair_findings(a: dict, b: dict) -> list[str]:
    return [f for f in viral_copy_findings([a, b], [], include_quotes=False) if f.startswith("slides 1 and 2")]


DISTINCT = {
    "1 discovery vs SEC no-compromise": (S("Взаимодействие нашли во время проверки"), S("По SEC признаков компрометации не нашли")),
    "2 summer vs disclosed 25 Sept": (S("Событие произошло летом"), S("OpenAI раскрыла детали 25 сентября")),
    "3 SEC no-compromise vs ongoing": (S("SEC: признаков компрометации не нашли"), S("Проверка продолжается")),
    "4 darknet vs 97% discount": (S("Google обнаружила предложения на даркнете"), S("Скидки доходят до 97%")),
    "5 statement vs reader consequence": (S("OpenAI заявила, что проверка продолжается"), S("Пользователям стоит проверить настройки агентов")),
    "6 same entity, other proposition": (S("OpenAI раскрыла странное поведение агентов"), S("OpenAI поддерживает замедление разработки ИИ")),
    "7 positive vs negated": (S("SEC: компрометацию нашли"), S("SEC: компрометацию не нашли")),
    "8 компания vs компрометация": (S("Компания выпустила обновление"), S("Компрометацию данных не подтвердили")),
}


@pytest.mark.parametrize("name", DISTINCT)
def test_different_propositions_are_distinct_whatever_words_they_share(name):
    a, b = DISTINCT[name]
    assert pair_findings(a, b) == [], name


DUPLICATE = {
    "9 same disclosure date, paraphrased": (S("OpenAI раскрыла детали 25 сентября"), S("Компания рассказала об этом 25 сентября")),
    "10 same SEC no-compromise, paraphrased": (S("По SEC компрометации не нашли"), S("OpenAI не обнаружила признаков компрометации SEC")),
    "11 same event-action, synonyms": (S("Агент взаимодействовал с сайтом SEC"), S("ИИ обращался к сайту SEC")),
    "12 same thesis, reordered": (S("OpenAI раскрыла 25 сентября детали"), S("25 сентября детали раскрыла OpenAI")),
    "13 same claim plus filler": (S("OpenAI раскрыла детали 25 сентября"), S("И вот что важно: OpenAI раскрыла детали именно 25 сентября")),
}


@pytest.mark.parametrize("name", DUPLICATE)
def test_true_duplicates_in_other_words_are_still_blocked(name):
    a, b = DUPLICATE[name]
    assert pair_findings(a, b), name


def test_the_prefix_collision_is_gone_and_polarity_is_its_own_token():
    assert "комп" in content_stems("Компания") & content_stems("компрометации")  # the old 4-letter collision, documented
    assert ru_stem("Компания") != ru_stem("компрометации")
    assert ru_stem("столкновение") == ru_stem("столкновением") and ru_stem("песня") == ru_stem("песней")
    assert thesis_tokens("компрометацию нашли") & thesis_tokens("компрометацию не нашли") == {"компрометац"}
    assert "¬FIND" in thesis_tokens("не нашли") and "FIND" in thesis_tokens("нашли")
    assert ru_stem("подтвердил") == ru_stem("подтвердили") == ru_stem("подтвердила")
    assert thesis_tokens("не подтвердили") == {"¬" + ru_stem("подтвердили")} and thesis_tokens("подтвердили") == {ru_stem("подтвердили")}
    assert thesis_tokens("не для всех нашли") == {"¬FIND"}  # a stopword does not end the negation's reach


def test_canary7_slides_3_and_4_are_distinct_roles_and_the_carousel_has_no_thesis_finding():
    raw = json.loads((CANARY7 / "director_raw_output_initial.json").read_text(encoding="utf-8"))["structured_output"]
    slides = raw["slides"]
    assert (proposition_role(slides[2]), proposition_role(slides[3])) == ("DISCOVERY_MECHANISM", "TARGET_STATUS")
    assert not [f for f in viral_copy_findings(slides, [], include_quotes=False) if f.startswith("slides ")]
