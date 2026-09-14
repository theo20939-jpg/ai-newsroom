"""TELEGRAM-DATA-SEMANTIC-PARSER-V2-1: the real NASA/IBM DATA-card production defect.

A real Telegram DATA card (built by the OLD, pre-ASML-hotfix production code - the ASML hotfix,
`feature/telegram-data-semantic-overflow-hotfix-1` @ 45de6d4, was never deployed to production, so
this is a SECOND, independently-discovered instance of the same defect CLASS, not a regression from
that hotfix) escaped with: value "20" correct, but the unit slot absorbed a whole comparison clause
("% точнее специализированных моделей..."), and the label became a stripped sentence fragment
("Показатель Модель способна выявлять..."). Reproduced directly against the actual pre-hotfix
`services/editorial_pipeline/content.py` (loaded from git commit 39f764b) below - see
`test_nasa_pre_asml_hotfix_reproduces_the_defect`.

Against the CURRENT (post-ASML-hotfix, pre-this-phase) code, this exact NASA fact ALREADY does not
overflow the unit (the ASML fix's own change-unit passthrough already returns "%" unchanged) - but
the comparison ("точнее") was simply discarded, and the label fell back to the fully generic
"Показатель" with no metric-kind signal at all. This phase's own job is the GENERALIZATION the ASML
hotfix's brief explicitly disclaimed doing: a bounded comparator vocabulary (never entering `unit`),
comparator-driven metric-kind derivation, and two independent, final safety validators
(`_is_unit_safe`/`_is_label_safe`) that gate `build_structured_data_content()`'s own return value -
defense-in-depth, not merely correct-by-construction.

See docs/telegram_data_semantic_parser_v2_1_report.md for the full root-cause writeup.
"""
from __future__ import annotations

import io
from uuid import uuid4

import pytest
from PIL import Image

from services.brand_renderer import render_data_hero_card
from services.data_source_classification import DataPresentationMode
from services.editorial_pipeline.content import (
    _classify_metric_kind,
    _extract_comparator,
    _is_label_safe,
    _is_unit_safe,
    build_structured_data_content,
)
from services.editorial_pipeline.evidence import build_evidence_pack
from services.presentation_director import DataCandidate
from services.render_evidence import derive_data_render_evidence

# ---------------------------------------------------------------------------------------------
# A. The real NASA/IBM defect, reproduced through the actual production structured-content entrypoint
# ---------------------------------------------------------------------------------------------

_NASA_TITLE = "NASA и IBM представили открытую ИИ-модель для поиска льда на Луне"
_NASA_FACT = (
    "Модель способна выявлять водяной лёд более чем на 20% точнее специализированных моделей, "
    "обученных на меньшем объёме данных."
)
_NASA_BODY = (
    "NASA и IBM представили открытую ИИ-модель для поиска льда на Луне. "
    "Модель способна выявлять водяной лёд более чем на 20% точнее специализированных моделей, "
    "обученных на меньшем объёме данных."
)


def _nasa_content():
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[_NASA_FACT],
    )
    return build_structured_data_content(title=_NASA_TITLE, main_body=_NASA_BODY, evidence=evidence)


def test_nasa_real_replay_unit_stays_bounded() -> None:
    content = _nasa_content()
    assert content is not None
    assert content.metric_value == "20"
    assert content.metric_unit == "%"
    assert "точнее" not in content.metric_unit
    assert "специализированных" not in content.metric_unit
    assert "моделей" not in content.metric_unit


def test_nasa_real_replay_comparator_captured_separately() -> None:
    content = _nasa_content()
    assert content is not None
    assert content.comparison == "точнее"


def test_nasa_real_replay_label_is_concise_and_never_malformed() -> None:
    content = _nasa_content()
    assert content is not None
    assert len(content.metric_label) <= 40
    lowered = content.metric_label.lower()
    assert "способна выявлять" not in lowered
    assert "точнее специализированных" not in lowered
    # the acceptable, evidence-grounded, non-hardcoded outcome (§10 of the parser-v2 brief)
    assert content.metric_label == "Точность"
    assert content.subject == ""  # no safe concise subject exists (NASA/IBM never appear in the fact)


def test_nasa_real_replay_hero_text_fits_within_safe_bounds() -> None:
    content = _nasa_content()
    assert content is not None
    cand = DataCandidate(
        value=content.metric_value, unit=content.metric_unit, label=content.metric_label,
        evidence_fact=content.source_fact, series=content.series, delta=content.delta,
    )
    assert render_data_hero_card(cand)  # no exception - genuinely fits


# The OLD (pre-ASML-hotfix, actually-deployed-to-production at the time this NASA card was
# generated) reproduction is documented in docs/telegram_data_semantic_parser_v2_1_report.md §B,
# generated via a one-off script loading `services/editorial_pipeline/content.py` directly from
# git commit 39f764b (the same pattern already used for `BEFORE_ASML.jpg` in the prior hotfix) -
# not a committed test dependency, matching that same precedent rather than shipping a stray
# duplicate/deleted-code snapshot module in this repository.


# ---------------------------------------------------------------------------------------------
# B. ASML replay - MUST STAY FIXED (already covered by
#    tests/test_telegram_data_semantic_overflow_hotfix_1.py; re-asserted here as part of this
#    phase's own required regression matrix).
# ---------------------------------------------------------------------------------------------

_ASML_TITLE = "Все EUV-сканеры ASML расписаны до конца 2027 года"
_ASML_FACT = (
    "ASML контролирует примерно 94% рынка литографических сканеров, необходимых для "
    "производства полупроводников."
)
_ASML_BODY = (
    "Все EUV-сканеры ASML расписаны до конца 2027 года. ASML контролирует примерно 94% рынка "
    "литографических сканеров, необходимых для производства полупроводников."
)


def test_asml_no_regression_after_parser_v2() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[_ASML_FACT],
    )
    content = build_structured_data_content(title=_ASML_TITLE, main_body=_ASML_BODY, evidence=evidence)
    assert content is not None
    assert content.metric_value == "94"
    assert content.metric_unit == "%"
    assert content.metric_label == "Доля рынка ASML"
    assert content.subject == "ASML"
    assert content.comparison is None  # no comparator vocabulary anywhere in the ASML fact


# ---------------------------------------------------------------------------------------------
# C. Maxus replay - MUST STAY FIXED, zero diff
# ---------------------------------------------------------------------------------------------

_MAXUS_FACT = "Рекомендованная цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)."
_MAXUS_TITLE = "Представлен минивэн SAIC Maxus 9 2027 с заменой батареи за 90 секунд"
_MAXUS_BODY = (
    "SAIC представила минивэн Maxus 9 2027 года. Стартовая цена модели составляет "
    "290 тыс. юаней, что соответствует примерно 3,8 млн рублей. Полностью разряженный "
    "аккумулятор можно заменить на заряженный примерно за 90 секунд."
)


def test_maxus_zero_diff_after_parser_v2() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[_MAXUS_FACT],
    )
    content = build_structured_data_content(title=_MAXUS_TITLE, main_body=_MAXUS_BODY, evidence=evidence)
    assert content is not None
    assert content.metric_value == "290"
    assert "тыс" in content.metric_unit and "юан" in content.metric_unit
    assert content.metric_label == "Стартовая цена Maxus 9"
    assert content.subject == "Maxus 9"
    assert content.comparison is None


# ---------------------------------------------------------------------------------------------
# D. Generic percent - unchanged
# ---------------------------------------------------------------------------------------------


def test_generic_percent_unit_never_absorbs_trailing_prose() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["По данным опроса, 42% пользователей приложения используют новую функцию каждый день."],
    )
    content = build_structured_data_content(
        title="Новое приложение для заметок набирает популярность",
        main_body="Опрос показал, что 42% пользователей приложения используют новую функцию каждый день.",
        evidence=evidence,
    )
    assert content is not None
    assert content.metric_value == "42"
    assert content.metric_unit == "%"
    assert content.metric_unit != "% пользователей"


# ---------------------------------------------------------------------------------------------
# E / F / G. Comparative constructions - bounded comparator, never in unit
# ---------------------------------------------------------------------------------------------


def test_comparative_faster_never_leaks_into_unit() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["Модель работает на 40% быстрее предыдущей версии в реальных задачах."],
    )
    content = build_structured_data_content(
        title="Новая модель обработки данных представлена разработчиками",
        main_body="Новая модель обработки данных представлена разработчиками. Модель работает на 40% быстрее предыдущей версии в реальных задачах.",
        evidence=evidence,
    )
    assert content is not None
    assert content.metric_value == "40"
    assert content.metric_unit == "%"
    assert content.comparison == "быстрее"
    assert "быстрее" not in content.metric_unit


def test_comparative_lower_never_leaks_into_unit() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["Затраты компании снизились на 15% ниже прошлого года."],
    )
    content = build_structured_data_content(
        title="Компания отчиталась о снижении затрат в новом квартале",
        main_body="Компания отчиталась о снижении затрат в новом квартале. Затраты компании снизились на 15% ниже прошлого года.",
        evidence=evidence,
    )
    assert content is not None
    assert content.metric_value == "15"
    assert content.metric_unit == "%"
    assert content.comparison == "ниже"
    assert "ниже" not in content.metric_unit


def test_comparative_more_efficient_never_leaks_into_unit() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["Двигатель работает на 30% эффективнее предыдущей модели."],
    )
    content = build_structured_data_content(
        title="Новый двигатель показал улучшенные характеристики на тестах",
        main_body="Новый двигатель показал улучшенные характеристики на тестах. Двигатель работает на 30% эффективнее предыдущей модели.",
        evidence=evidence,
    )
    assert content is not None
    assert content.metric_value == "30"
    assert content.metric_unit == "%"
    assert content.comparison == "эффективнее"
    assert content.metric_label == "Эффективность"


# ---------------------------------------------------------------------------------------------
# H. Currency magnitude
# ---------------------------------------------------------------------------------------------


def test_currency_magnitude_dollars_bounded() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["Инвесторы вложили 3,2 млрд долларов в развитие компании."],
    )
    content = build_structured_data_content(
        title="Стартап привлек новый раунд финансирования",
        main_body="Стартап привлек новый раунд финансирования. Инвесторы вложили 3,2 млрд долларов в развитие компании.",
        evidence=evidence,
    )
    assert content is not None
    assert "млрд" in content.metric_unit and "доллар" in content.metric_unit
    assert _is_unit_safe(content.metric_unit)


# ---------------------------------------------------------------------------------------------
# I. Pathological trailing prose - direct validator + integration-level fail-closed proof
# ---------------------------------------------------------------------------------------------


def test_unit_safety_validator_rejects_trailing_prose() -> None:
    assert _is_unit_safe("%") is True
    assert _is_unit_safe("тыс юаней") is True
    assert _is_unit_safe("млрд долларов") is True
    assert _is_unit_safe("") is True
    assert _is_unit_safe("раза") is True
    assert _is_unit_safe("% рынка литографических сканеров") is False
    assert _is_unit_safe("точнее специализированных моделей") is False
    assert _is_unit_safe("тыс. юаней рекомендованная цена автомобиля") is False


def test_build_structured_data_content_fails_closed_when_legacy_grounding_is_corrupted(monkeypatch) -> None:
    """A direct integration-level proof of §13's fail-closed gate: even if the legacy grounding
    step (`_find_data_candidate`) were to regress in the future and return an already-corrupted
    unit (the exact shape this validator exists to catch), `build_structured_data_content()` must
    return `None` - never propagate the unsafe string into a `StructuredDataContent`."""
    import services.editorial_pipeline.content as content_module
    from services.presentation_director import DataCandidate as _DC

    corrupted = _DC(
        value="20", unit="% точнее специализированных моделей, обученных на меньшем объёме данных",
        label="20% точнее специализированных моделей", evidence_fact=_NASA_FACT,
    )
    monkeypatch.setattr(content_module, "_find_data_candidate", lambda *a, **k: corrupted)

    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[_NASA_FACT],
    )
    result = build_structured_data_content(title=_NASA_TITLE, main_body=_NASA_BODY, evidence=evidence)
    assert result is None


# ---------------------------------------------------------------------------------------------
# J. Sentence-label attack
# ---------------------------------------------------------------------------------------------


def test_label_safety_validator_rejects_a_whole_sentence() -> None:
    sentence = (
        "Модель способна выявлять водяной лёд более чем на 20 процентов точнее "
        "специализированных моделей."
    )
    assert _is_label_safe(sentence) is False
    assert _is_label_safe("Показатель") is True
    assert _is_label_safe("Доля рынка ASML") is True
    assert _is_label_safe("Точность") is True


def test_build_structured_data_content_never_reads_legacy_label() -> None:
    """Structural proof: `build_structured_data_content()`'s own CODE (comments excluded - one
    explains, in prose, exactly why `legacy.label` is deliberately never read) never references
    `legacy.label` at all - the whole-sentence fallback class of defect is architecturally
    impossible, not merely avoided by the validator."""
    import inspect

    from services.editorial_pipeline import content as content_module

    src = inspect.getsource(content_module.build_structured_data_content)
    code_lines = [line for line in src.splitlines() if not line.strip().startswith("#")]
    assert "legacy.label" not in "\n".join(code_lines)


# ---------------------------------------------------------------------------------------------
# K. Unknown unit - never captured as arbitrary text; no candidate at all
# ---------------------------------------------------------------------------------------------


def test_unknown_unit_never_produces_a_data_candidate() -> None:
    """A number followed by a genuinely unrecognized unit word ("очков", "points") is never
    captured as a (value, unit) pair by the legacy grounding step at all (`_NUMBER_UNIT_RE` only
    recognizes the bounded change/magnitude vocabulary) - so no DATA candidate is produced, and
    the caller falls through to QUOTE/NEWS, never inventing a unit from arbitrary text."""
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["Игрок набрал 20 очков в решающем матче сезона."],
    )
    content = build_structured_data_content(
        title="Звезда лиги установила новый рекорд результативности",
        main_body="Звезда лиги установила новый рекорд результативности. Игрок набрал 20 очков в решающем матче сезона.",
        evidence=evidence,
    )
    assert content is None


# ---------------------------------------------------------------------------------------------
# L. RenderEvidence - semantically safe but geometrically impossible content still fails closed
# ---------------------------------------------------------------------------------------------


def test_semantically_safe_but_geometrically_impossible_still_fails_closed() -> None:
    """Both defense layers must hold independently (§14 of the parser-v2 brief): a unit/label that
    pass every semantic validator can still be geometrically impossible (an absurdly long VALUE),
    and the renderer's own pre-existing fail-closed guard (TELEGRAM-DATA-SEMANTIC-OVERFLOW-
    HOTFIX-1) must still catch it."""
    cand = DataCandidate(
        value="999999999999999999", unit="%", label="Точность", evidence_fact="x",
    )
    assert _is_unit_safe(cand.unit)
    assert _is_label_safe(cand.label)
    with pytest.raises(ValueError, match="does not fit"):
        render_data_hero_card(cand)

    buf = io.BytesIO()
    Image.new("RGB", (1280, 720)).save(buf, format="JPEG")
    ev = derive_data_render_evidence(
        buf.getvalue(), cand, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    assert ev.text_clipped is True  # RenderEvidence stays truthful even for semantically-safe input


# ---------------------------------------------------------------------------------------------
# Metric-kind classifier unit coverage - comparator branch is checked LAST, never overrides a
# more specific evidence-word signal (§9/§10)
# ---------------------------------------------------------------------------------------------


def test_comparator_kind_never_overrides_a_more_specific_signal() -> None:
    # a price-word fact containing a comparator too: price wins (checked first)
    fact_lower = "цена автомобиля стала на 10% дороже прошлогодней модели"
    assert _classify_metric_kind(fact_lower, "%", "дороже") == "Цена"


def test_comparator_extraction_is_bounded_and_deterministic() -> None:
    assert _extract_comparator("модель работает на 40% быстрее прошлой версии") == "быстрее"
    assert _extract_comparator("ничего особенного не изменилось") is None
