"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S22/S35: bounded Russian language QA.

Confirms this module catches the REAL Maxus-defect artifact - which the existing, currently-
deployed `services.presentation_director._ORPHANED_LABEL_RE` does NOT catch, for two independent,
concrete reasons this phase found: (1) it never listed `с` among its guarded prepositions, and
(2) `_CURRENCY_WORD` never recognized "юань" as a currency at all. Both gaps are demonstrated
directly against the production constants, then shown fixed by this module's own extended patterns.
"""
from services.editorial_pipeline.language_qa import check_language_quality, correct_duplicated_sentences

_DEFECT_TEXT = "Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн рублей)."
_CLEAN_TEXT = "Стартовая цена Maxus 9 составляет 290 тыс. юаней."


def test_the_existing_production_regex_does_not_catch_the_real_defect() -> None:
    """Pins down the gap this module fixes - see language_qa.py's own module docstring."""
    from services.presentation_director import _CURRENCY_WORD, _ORPHANED_LABEL_RE

    assert _ORPHANED_LABEL_RE.search(_DEFECT_TEXT) is None  # "с" is not a guarded preposition
    assert "юан" not in _CURRENCY_WORD.lower()  # yuan was never a recognized currency word


def test_catches_the_real_maxus_defect_artifact() -> None:
    result = check_language_quality(_DEFECT_TEXT)
    assert result.passed is False
    assert "юан" in result.reason.lower()


def test_the_fixed_metric_label_passes() -> None:
    result = check_language_quality(_CLEAN_TEXT)
    assert result.passed is True


def test_catches_a_trailing_bare_preposition() -> None:
    result = check_language_quality("Автомобиль можно было купить за.")
    assert result.passed is False


def test_catches_duplicated_sentences() -> None:
    result = check_language_quality("Цена высокая. Цена высокая.")
    assert result.passed is False
    assert "duplicat" in result.reason.lower()


def test_does_not_flag_genuinely_distinct_sentences() -> None:
    result = check_language_quality("Цена высокая. Продажи начинаются в этом месяце.")
    assert result.passed is True


def test_correct_duplicated_sentences_is_a_single_bounded_mechanical_pass() -> None:
    """Only collapses an EXACT duplicate - never rewrites wording, never touches distinct
    sentences (S22's own "at most one bounded correction pass for objective failures")."""
    corrected = correct_duplicated_sentences("Цена высокая. Цена высокая. Продажи начинаются в этом месяце.")
    assert corrected == "Цена высокая. Продажи начинаются в этом месяце."
    # idempotent - re-running the same bounded pass never changes already-clean text further
    assert correct_duplicated_sentences(corrected) == corrected
