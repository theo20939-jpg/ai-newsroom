"""QUOTE-USE CLASSIFICATION (founder task 2026-09-27, after the seventh paid viral canary).

Canary 7 stopped at the hard invented-quote gate on the caption's «неожиданного взаимодействия» - an unattributed editorial term mention,
a Russian rendering of 'interacted ... in unexpected ways'. Provenance is unchanged (supported = verbatim in the evidence); an unsupported
span is now classified by USE: presented as someone's words -> terminal; an unattributed term mention -> repairable, for the ONE correction."""
from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path

import pytest

from services.instagram_viral_format import EditorialCorrectionRequired, classify_quote_use, invented_quotes

ROOT = Path(__file__).resolve().parent.parent
CANARY7 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary7_20260927/post"
EVIDENCE = ["OpenAI disclosed that its agents interacted with several U.S. government websites in unexpected ways.",
            "OpenAI did not find any use of SEC credentials or evidence of a compromise, the company said.",
            "Сотрудники назвали это «неожиданным поведением модели» в отчёте."]


def use(text: str) -> str:
    found = classify_quote_use([("caption", text)], EVIDENCE)
    return "TERMINAL" if found.terminal else "REPAIRABLE" if found.repairable else "PASS"


PASS = [
    "Компания пишет: “evidence of a compromise”.",  # 1. exact verbatim quote (curly quotes)
    "Сотрудники назвали это «неожиданным поведением модели».",  # 1. exact verbatim (ёлочки)
    'OpenAI said its agents interacted "in unexpected ways".',  # 1. exact verbatim (straight quotes)
    "Зайди в «Plugins», а не в «Настройки».",  # 2. single quoted words are labels (existing semantics)
    "Не стоит путать это со «взломом».",  # 2. single word
    "Поэтому здесь важно не перепрыгивать от неожиданного взаимодействия сразу к взлому.",  # 3. the corrected, unquoted paraphrase
]


@pytest.mark.parametrize("text", PASS)
def test_supported_verbatim_quotes_single_word_labels_and_unquoted_paraphrase_pass(text):
    assert use(text) == "PASS", text


REPAIRABLE = [
    "Поэтому здесь важно не перепрыгивать от «неожиданного взаимодействия» сразу к «взлому».",  # 4. canary 7
    "От “неожиданного взаимодействия” до “подтверждённого взлома” - большая дистанция.",  # 5. term contrast, curly
    "Не называем это «подтверждённым взломом».",  # 6.
    "Между «ошибкой модели» и «атакой» есть разница.",  # 7.
    "Это «новая эпоха агентов», и не более.",  # 8. a label, no speaker
    'Это ещё не "подтверждённый взлом", а "неожиданное взаимодействие".',  # straight quotes, negation, two spans
    "Термин «автономный агент» здесь используется условно.",
    "Не стоит называть это «атакой на правительство»!",
    "Это (пока) не «подтверждённый взлом» — и не «утечка данных»…",  # nested punctuation
]


@pytest.mark.parametrize("text", REPAIRABLE)
def test_an_unattributed_editorial_term_mention_is_repairable_never_a_silent_pass(text):
    assert use(text) == "REPAIRABLE", text


TERMINAL = [
    "OpenAI заявила: «мы потеряли контроль над агентом».",  # 9.
    "Сэм Альтман сказал: «агенты вели себя странно».",  # 10.
    "По словам исследователей, «агент действовал сам».",  # 11.
    "Сэм Альтман: «всё под контролем».",  # 12. named speaker + colon
    "Компания назвала произошедшее «взломом правительства».",  # 13. attributed to a company
    "— «Мы всё проверили», — ответила OpenAI.",  # 14. invented dialogue
    "«Мы всё проверили», — сказал представитель компании.",  # reporting verb after the quote
    "В заявлении компании говорится о «полной прозрачности проверки».",  # source frame
    'OpenAI не заявляла, что "агент вышел из-под контроля".',  # negated attribution is still about the source's wording
    "According to the company, “the agent acted on its own”.",
    "ИИ: «Понял. Взламываю систему».",  # the real Reel hook of an earlier canary
]


@pytest.mark.parametrize("text", TERMINAL)
def test_an_unsupported_quote_presented_as_someones_words_stays_terminal(text):
    assert use(text) == "TERMINAL", text


def test_provenance_is_unchanged_and_the_repairable_finding_names_span_type_and_action():
    texts = [*PASS, *REPAIRABLE, *TERMINAL]
    for text in texts:  # exactly the spans invented_quotes flags are classified - nothing new passes, nothing new is flagged
        found = classify_quote_use([("caption", text)], EVIDENCE)
        assert len(found.terminal) + len(found.repairable) == len(invented_quotes([text], EVIDENCE)), text
    [finding] = classify_quote_use([("caption", "Не называем это «подтверждённым взломом».")], EVIDENCE).repairable
    assert finding.startswith("UNSUPPORTED_EDITORIAL_QUOTED_TERM (caption): «подтверждённым взломом»") and "REMOVE_QUOTES_OR_PARAPHRASE" in finding
    for rule in ("Do not invent a speaker or verbatim wording", "do not add facts", "do not strengthen the claim",
                 "do not change any target's status", "keep the chronology", "display limit"):
        assert rule in finding


def test_a_mixed_sentence_is_classified_per_span_but_any_attribution_in_the_sentence_makes_it_hard():
    both = classify_quote_use([("caption", "Не «подтверждённый взлом». OpenAI заявила: «мы всё исправили».")], EVIDENCE)
    assert both.terminal == ["мы всё исправили"] and len(both.repairable) == 1
    # conservative: an attribution signal anywhere in the SAME sentence wins
    assert use("OpenAI заявила, что проверка идёт, поэтому не стоит говорить о «подтверждённом взломе».") == "TERMINAL"


# --- the Director validation and the ONE correction ---------------------------------------------------------------------------------------

def _canary7():
    raw = json.loads((CANARY7 / "director_raw_output_initial.json").read_text(encoding="utf-8"))["structured_output"]
    call = json.loads((CANARY7 / "calls/02_director.json").read_text(encoding="utf-8"))
    evidence = [line for _n, line in re.findall(r"^E(\d+): (.*)$", "\n".join(t for m in call["request"] for t in m["text"]), re.M)]
    import scripts._instagram_quote_use_replay as replay

    return raw, evidence, replay


def test_canary7_first_output_is_repairable_and_goes_to_the_one_correction_not_a_hard_stop():
    import services.instagram_creative_director as cd

    raw, evidence, replay = _canary7()
    with pytest.raises(EditorialCorrectionRequired) as caught:  # a MediaFirstContractError -> the trigger's one correction retry
        cd._validate_carousel_output(copy.deepcopy(raw), None, director_input=replay.director_input(evidence), archetype="trend_generative")
    quote = [f for f in caught.value.findings if f.startswith("UNSUPPORTED_EDITORIAL_QUOTED_TERM")]
    assert len(quote) == 1 and "«неожиданного взаимодействия»" in quote[0]
    assert "UNSUPPORTED_EDITORIAL_QUOTED_TERM (caption): «неожиданного взаимодействия»" in caught.value.correction_note


def test_an_attributed_invented_quote_in_the_same_output_is_still_a_hard_fact_safety_error():
    import services.instagram_creative_director as cd

    raw, evidence, replay = _canary7()
    raw["final_caption"] += " OpenAI заявила: «мы потеряли контроль над агентом»."
    with pytest.raises(cd.CreativeFactSafetyError, match="invented quote"):
        cd._validate_carousel_output(raw, None, director_input=replay.director_input(evidence), archetype="trend_generative")


def test_a_correction_that_still_carries_the_scare_quote_is_terminal_no_second_correction():
    """In correction mode every remaining finding raises out of the one retry - the trigger's except clause makes it terminal."""
    raw, evidence, replay = _canary7()
    result = asyncio.run(replay.real_path(raw, replay.director_input(evidence, note="EDITORIAL CORRECTION (test)")))
    assert result["result"] == "REACHED_SEMANTIC_JUDGE"  # the judge still runs once, then the combined findings raise
    assert any(f.startswith("UNSUPPORTED_EDITORIAL_QUOTED_TERM") for f in replay.carried(raw, replay.director_input(evidence, note="x")))


def test_the_trigger_allows_exactly_one_director_correction():
    source = (ROOT / "services/instagram_automatic_trigger.py").read_text(encoding="utf-8")
    block = source[source.index("except _EditorialRetry as retry:"):source.index("single, carousel, reel = creative_outcome")]
    assert block.count("await regenerator(") == 1 and "MediaFirstContractError" in block
