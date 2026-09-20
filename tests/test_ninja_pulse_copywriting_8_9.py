from pathlib import Path

import yaml

from integrations.prompts.file_repository import FilePromptRepository
from services.editorial_treatment import BRIEF, STANDARD
from services.news_telegram_presentation import (
    _OPTIONAL_REDUNDANCY_THRESHOLD,
    build_v81_news_body,
    diagnose_v81_ending,
    render_v81_news_card_html,
)


def _output(*, main_body: str, ending: str | None) -> dict[str, object]:
    return {"title": "Заголовок", "main_body": main_body, "ending": ending, "quote": None}


def test_copywriting_8_9_is_immutable_schema_compatible_successor_to_8_8() -> None:
    repository = FilePromptRepository(Path("prompts"))
    prompt_88 = repository.resolve("copywriting", "8.8")
    prompt_89 = repository.resolve("copywriting", "8.9")

    assert prompt_89.version == "8.9"
    assert prompt_89.output_schema == prompt_88.output_schema
    assert "ending_strategy" not in prompt_89.output_schema.get("properties", {})


def test_copywriting_8_9_reverses_default_without_weakening_fact_safety() -> None:
    parsed = yaml.safe_load(Path("prompts/copywriting/v8.9.yaml").read_text(encoding="utf-8"))
    rules = "\n".join(parsed["rules"])

    assert "EDITORIAL ENDING (V8.9, DEFAULT)" in rules
    assert "normally one short" in parsed["system"]
    assert "40-160 characters" in rules
    assert "IRONY (V8.9, FIRST-CLASS OPTION)" in rules
    assert "SENSITIVE STORIES AND VALID NULLS (V8.9)" in rules
    assert "FINAL-SENTENCE FACT SCOPE (V8.8)" in rules
    assert "ABSENCE IS NOT EVIDENCE (V8.8)" in rules
    assert "FINAL SENTENCE MUST BE NEW (V8.8)" in rules
    assert "Most posts should simply end" not in rules


def test_copywriting_8_9_forbids_generic_cta_and_internal_labels() -> None:
    raw = Path("prompts/copywriting/v8.9.yaml").read_text(encoding="utf-8")
    for forbidden in (
        "Что думаете?", "Как вам?", "Согласны?", "Будете пользоваться?",
        "Кто бы попробовал?", "Пишите в комментариях", "CTA", "REACTION BAIT",
    ):
        assert forbidden in raw


def test_valid_distinct_ending_survives_old_brief_treatment_ceiling() -> None:
    main_body = "М" * 340
    ending = "У этой гонки технологий теперь появился вполне бытовой финиш."
    output = _output(main_body=main_body, ending=ending)

    rendered_body = build_v81_news_body(output, treatment=BRIEF)

    assert ending in rendered_body
    assert len(rendered_body) > 350


def test_quality_filters_still_drop_filler_redundancy_and_duplicate_hedge() -> None:
    filler = _output(main_body="Компания выпустила новый гаджет.", ending="Время покажет, что будет дальше.")
    assert diagnose_v81_ending(filler)["ending_drop_reason"] == "filler"

    duplicate = _output(
        main_body="Компания выпустила новый гаджет для дома.",
        ending="Компания выпустила новый гаджет для дома.",
    )
    assert diagnose_v81_ending(duplicate)["ending_drop_reason"] == "redundant"

    hedge = _output(
        main_body="Сделка пока не подтверждена компанией.",
        ending="Инвестор называет статус проекта неподтвержденным.",
    )
    assert diagnose_v81_ending(hedge)["ending_drop_reason"] == "duplicate_hedge"


def test_diagnostic_reports_null_model_and_successful_render() -> None:
    null_output = _output(main_body="Факт.", ending=None)
    assert diagnose_v81_ending(null_output) == {
        "ending_generated": "no",
        "ending_rendered": "no",
        "ending_drop_reason": "null_from_model",
    }

    output = _output(
        main_body="Робот научился складывать футболки без помощи человека.",
        ending="Домашняя автоматизация наконец добралась до самой бесконечной части стирки.",
    )
    html = render_v81_news_card_html(output, treatment=STANDARD)
    assert diagnose_v81_ending(output, rendered_html=html) == {
        "ending_generated": "yes",
        "ending_rendered": "yes",
        "ending_drop_reason": "none",
    }


def test_actual_telegram_hard_limit_drops_whole_ending_without_truncation() -> None:
    ending = "Финальная редакционная мысль остаётся целой и никогда не обрезается."
    output = _output(main_body="М" * 4020, ending=ending)

    html = render_v81_news_card_html(output, treatment=STANDARD)
    diagnostic = diagnose_v81_ending(output, rendered_html=html)

    assert ending not in html
    assert diagnostic["ending_drop_reason"] == "telegram_hard_limit"
    assert diagnostic["ending_generated"] == "yes"
    assert diagnostic["ending_rendered"] == "no"


def test_redundancy_threshold_remains_unchanged() -> None:
    assert _OPTIONAL_REDUNDANCY_THRESHOLD == 0.3


def test_v8_8_stays_frozen_and_capability_accepts_v8_9_context() -> None:
    raw_88 = Path("prompts/copywriting/v8.8.yaml").read_text(encoding="utf-8")
    source = Path("capabilities/copywriting_capability.py").read_text(encoding="utf-8")
    assert 'version: "8.8"' in raw_88
    assert "EDITORIAL ENDING (V8.9, DEFAULT)" not in raw_88
    assert '"8.8", "8.9"' in source


def test_hard_limit_base_card_without_ending_never_recurses() -> None:
    output = _output(main_body="М" * 4200, ending=None)
    html = render_v81_news_card_html(output, treatment=STANDARD)
    assert "М" * 4200 in html
    assert diagnose_v81_ending(output, rendered_html=html)["ending_drop_reason"] == "null_from_model"
