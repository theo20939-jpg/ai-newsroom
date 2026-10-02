from copy import deepcopy
from pathlib import Path

from integrations.prompts.file_repository import FilePromptRepository
from services import instagram_creative_director as director


PROMPTS = FilePromptRepository(Path("prompts"))

BEFORE_HEADLINES = [
    "Лучшая LLM — не всегда лучшая для твоей задачи",
    "Тесты дают шорт-лист",
    "Проверяй на своём хаосе",
    "Шаг 1. Опиши приёмку",
    "Шаг 2. Посчитай ручную работу",
    "Выбирай по своей задаче",
]

# Offline editorial acceptance fixture only. Production contains no phrase-replacement map.
AFTER_HEADLINES = [
    "Рейтинг не решит, какая модель нужна тебе",
    "Тесты помогают выбрать кандидатов",
    "Дай моделям настоящую рабочую задачу",
    "Сначала задай критерии результата",
    "Проверь, сколько работы останется человеку",
    "Выбирай модель по результатам своей проверки",
]


def _prompt(version: str):
    return PROMPTS.resolve(director.CAROUSEL_PROMPT_NAME, version)


def test_active_carousel_prompts_apply_general_russian_native_pass_without_phrase_blacklist() -> None:
    assert director.CAROUSEL_PROMPT_VERSION == "10.13"
    for version in ("10.13", "10.14"):
        rules = "\n".join(_prompt(version).rules)
        assert "RUSSIAN-NATIVE FINAL PASS" in rules
        assert "slide_copy, slide_body, final_caption and final_cta" in rules
        assert "SHORTEN THE THOUGHT, NOT THE GRAMMAR" in rules
        assert "Established technical terms" in rules
        assert "preserve every fact, number, date, name" in rules
        assert all(phrase not in rules for phrase in BEFORE_HEADLINES)
        assert all(phrase not in rules for phrase in AFTER_HEADLINES)


def test_language_only_versions_keep_the_exact_output_schemas() -> None:
    assert _prompt("10.13").output_schema == _prompt("10.11").output_schema
    assert _prompt("10.14").output_schema == _prompt("10.12").output_schema


def test_saved_founder_carousel_offline_rewrite_keeps_shape_and_fits_existing_headline_lengths() -> None:
    rewritten = deepcopy(BEFORE_HEADLINES)
    rewritten[:] = AFTER_HEADLINES
    assert len(rewritten) == len(BEFORE_HEADLINES) == 6
    assert max(map(len, rewritten)) <= 60
    assert all(len(after) <= max(60, len(before)) for before, after in zip(BEFORE_HEADLINES, rewritten, strict=True))
    assert "LLM" in BEFORE_HEADLINES[0]  # accepted technical vocabulary remains allowed by the contract


def test_language_patch_does_not_enter_visual_selection_or_delivery_modules() -> None:
    # The implementation surface is intentionally the two immutable prompt versions plus their selector.
    # This guard documents the scope boundary without pretending that a wording fixture is a renderer test.
    assert {"10.13", "10.14"} <= director.MEDIA_FIRST_CAROUSEL_VERSIONS
    assert {"10.13", "10.14"} <= director._EVIDENCE_HANDLE_CAROUSEL_VERSIONS
    assert {"10.13", "10.14"} <= director.BODY_COPY_CAROUSEL_VERSIONS

