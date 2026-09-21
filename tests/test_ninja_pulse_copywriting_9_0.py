from pathlib import Path

import yaml

from integrations.prompts.file_repository import FilePromptRepository
from services.editorial_treatment import BRIEF
from services.news_telegram_presentation import (
    _OPTIONAL_REDUNDANCY_THRESHOLD,
    build_v81_news_body,
    diagnose_v81_ending,
)


def _rules() -> str:
    parsed = yaml.safe_load(Path("prompts/copywriting/v9.0.yaml").read_text(encoding="utf-8"))
    return "\n".join(parsed["rules"])


def test_copywriting_9_0_is_immutable_schema_compatible_successor_to_8_9() -> None:
    repository = FilePromptRepository(Path("prompts"))
    prompt_89 = repository.resolve("copywriting", "8.9")
    prompt_90 = repository.resolve("copywriting", "9.0")
    assert prompt_90.version == "9.0"
    assert prompt_90.output_schema == prompt_89.output_schema
    assert 'version: "8.9"' in Path("prompts/copywriting/v8.9.yaml").read_text(encoding="utf-8")


def test_ending_is_selective_and_requires_distinct_semantic_beat() -> None:
    parsed = yaml.safe_load(Path("prompts/copywriting/v9.0.yaml").read_text(encoding="utf-8"))
    rules = "\n".join(parsed["rules"])
    assert "EDITORIAL ENDING (V9.0, SELECTIVE)" in rules
    assert "DISTINCT-BEAT TEST (V9.0)" in rules
    assert "one short editorial ending only when it adds a distinct editorial beat" in parsed["system"]
    assert "it is never mandatory" in rules
    assert "A lively metaphor for the same conclusion is still repetition" in rules
    assert "A post with no ending is better than a repetitive ending" in rules
    assert "for a normal non-sensitive Pulse story, write exactly" not in rules


def test_missing_methodology_or_confirmation_cannot_be_promoted_from_context_gap() -> None:
    rules = _rules()
    assert "ABSENCE-OF-CONTEXT SAFETY (V9.0, HARD RULE FOR ALL FIELDS)" in rules
    assert "HEADLINE, MAIN_BODY, and ENDING" in rules
    assert "A Research GAPS item is not such a FACT" in rules
    assert "'методика не указана'" in rules
    assert "'подтверждение не представлено'" in rules
    assert "omit the claim entirely" in rules


def test_financial_recipient_cannot_change_for_style() -> None:
    rules = _rules()
    assert "FINANCIAL RECIPIENT PRECISION (V9.0)" in rules
    for term in ("tax", "revenue", "payment", "fine", "investment", "fee", "funding", "sale proceeds"):
        assert term in rules
    assert "tax collected by a state must not become" in rules


def test_existing_caveat_or_consequence_must_not_be_repeated_in_ending() -> None:
    rules = _rules()
    assert "If main_body already states an evidence" in rules
    assert "At most one caveat across the entire post" in rules
    assert "metaphorically rephrase" in rules
    assert "set ending to null" in rules


def test_earned_irony_and_generic_cta_contract_are_preserved() -> None:
    rules = _rules()
    assert "IRONY (V9.0, PRESERVE WHEN EARNED)" in rules
    assert "FACT A + FACT B contrast" in rules
    for forbidden in ("Что думаете?", "Как вам?", "Согласны?", "Пишите в комментариях", "CTA"):
        assert forbidden in rules


def test_audience_and_default_caveat_formulas_are_not_defaults() -> None:
    rules = _rules()
    assert "ENDING FORMULA CONTROL (V9.0)" in rules
    assert "Для разработчиков" in rules
    assert "Для бизнеса" in rules
    assert "Для специалистов" in rules
    assert "X впечатляет/интересно/многообещающе, но" in rules


def test_presentation_behavior_and_redundancy_threshold_remain_unchanged() -> None:
    ending = "У этой гонки технологий теперь появился вполне бытовой финиш."
    output = {"title": "Заголовок", "main_body": "М" * 340, "ending": ending, "quote": None}
    rendered = build_v81_news_body(output, treatment=BRIEF)
    assert ending in rendered
    assert diagnose_v81_ending(output)["ending_drop_reason"] == "none"
    assert _OPTIONAL_REDUNDANCY_THRESHOLD == 0.3


def test_capability_accepts_9_0_context_without_new_workflow() -> None:
    source = Path("capabilities/copywriting_capability.py").read_text(encoding="utf-8")
    config = Path("core/config.py").read_text(encoding="utf-8")
    assert '"8.9", "9.0"' in source
    assert '"8.9", "9.0"]' in config
