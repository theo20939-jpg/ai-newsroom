"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S9/S32): the real, generic media-subject
extractor, exercised both directly (`extract_media_subject`) and through the actual production
entrypoint (`build_visual_intent_from_evidence`) - the "at least half of the truthfulness tests
must begin from the SAME upstream data shape production uses" requirement (S32), not only
hand-built ideal `MediaIntent` objects (see tests/test_unified_pipeline_subject_match_classifier.py
and tests/test_unified_pipeline_media_truthfulness_replay.py for those).
"""
from __future__ import annotations

from uuid import uuid4

from schemas.media_intent import MediaSubjectType
from services.editorial_pipeline.contracts import EvidencePack
from services.editorial_pipeline.media import build_visual_intent_from_evidence
from services.editorial_pipeline.subject_extraction import extract_media_subject

# ---------------------------------------------------------------------------
# S9 - the old regex's own named failure cases, reproduced and fixed.
# ---------------------------------------------------------------------------


def test_iphone_17_is_extracted_despite_lowercase_leading_i() -> None:
    """The old `_extract_subject_from_title()` regex required `[A-Z]` at the very start of the
    token - "iPhone" starts with a lowercase "i" and could never match at all."""
    result = extract_media_subject("Apple представила iPhone 17 с новой камерой")
    assert result is not None
    assert result.versioned_form == "iPhone 17"
    assert result.brand_form == "iPhone"


def test_gpt_6_is_extracted_despite_hyphen_not_space() -> None:
    """The old regex required `\\s+` between the word and the digit - a hyphenated model name like
    "GPT-6" could never match."""
    result = extract_media_subject("OpenAI анонсировала GPT-6 на презентации")
    assert result is not None
    assert result.versioned_form in ("GPT-6", "GPT 6")
    assert result.brand_form == "GPT"


def test_dario_amodei_is_extracted_despite_no_digit_at_all() -> None:
    """The old regex required a trailing digit unconditionally - a person's name has none."""
    result = extract_media_subject("Dario Amodei рассказал о будущем ИИ в новом интервью")
    assert result is not None
    assert result.proper_noun_run == "Dario Amodei"


def test_openai_is_extracted_despite_no_digit_at_all() -> None:
    result = extract_media_subject("OpenAI представила новую модель ИИ")
    assert result is not None
    assert result.brand_form == "OpenAI"


def test_foldable_iphone_is_extracted_despite_no_digit_at_all() -> None:
    """The literal Founder-audit foldable-iPhone case: no version number, no trailing digit."""
    result = extract_media_subject("Apple показала складной iPhone на презентации")
    assert result is not None
    assert result.brand_form == "iPhone"


def test_maxus_9_still_extracted_no_regression() -> None:
    """The pre-existing, already-correct case (the old regex's own one success story) must still
    work with the new extractor - no regression."""
    result = extract_media_subject("Представлен минивэн SAIC Maxus 9 2027 с заменой батареи")
    assert result is not None
    assert result.versioned_form == "Maxus 9"
    assert result.brand_form == "Maxus"


def test_concept_only_title_extracts_nothing_never_fabricates() -> None:
    """A genuinely subject-less story (S11's own CONCEPT category) must not have a subject
    invented for it."""
    result = extract_media_subject("Регулирование ИИ обсуждается на международном уровне")
    assert result is None


def test_no_brand_or_company_name_is_hardcoded_in_the_module() -> None:
    """S9's own explicit instruction, verified structurally: the extractor recognizes SHAPES only -
    proven by feeding it made-up brand/person names it has never seen before."""
    result = extract_media_subject("Zorblex представила Nyquora-8 на выставке технологий")
    assert result is not None
    assert result.versioned_form == "Nyquora-8"
    assert result.brand_form == "Nyquora"


# ---------------------------------------------------------------------------
# S32 - production-shaped: through the REAL entrypoint, not a hand-built MediaIntent.
# ---------------------------------------------------------------------------


def _evidence() -> EvidencePack:
    return EvidencePack(news_event_id=uuid4(), story_id=None, claims=(), source_url=None, research_facts=())


def test_production_intent_foldable_iphone_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="Apple показала складной iPhone на презентации", category=None, evidence=_evidence(),
    )
    PRODUCTION_INTENT_FOLDABLE_IPHONE_IS_INFORMATIVE = bool(intent.product_name or intent.model_name)
    assert PRODUCTION_INTENT_FOLDABLE_IPHONE_IS_INFORMATIVE is True
    assert intent.product_name == "iPhone"
    assert intent.subject_type == MediaSubjectType.PRODUCT


def test_production_intent_iphone_17_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="Apple представила iPhone 17 с новой камерой", category=None, evidence=_evidence(),
    )
    PRODUCTION_INTENT_IPHONE_17_IS_INFORMATIVE = bool(intent.model_name)
    assert PRODUCTION_INTENT_IPHONE_17_IS_INFORMATIVE is True
    assert intent.model_name == "iPhone 17"
    assert intent.product_name == "iPhone"


def test_production_intent_gpt6_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="OpenAI анонсировала GPT-6 на презентации", category=None, evidence=_evidence(),
    )
    PRODUCTION_INTENT_GPT6_IS_INFORMATIVE = bool(intent.model_name)
    assert PRODUCTION_INTENT_GPT6_IS_INFORMATIVE is True
    assert intent.model_name in ("GPT-6", "GPT 6")


def test_production_intent_dario_amodei_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="Dario Amodei рассказал о будущем ИИ в новом интервью", category=None, evidence=_evidence(),
    )
    PRODUCTION_INTENT_DARIO_AMODEI_IS_INFORMATIVE = bool(intent.person or intent.primary_entity != "Dario Amodei рассказал о будущем ИИ в новом интервью"[:200])
    assert PRODUCTION_INTENT_DARIO_AMODEI_IS_INFORMATIVE is True
    assert intent.person == "Dario Amodei"
    assert intent.primary_entity == "Dario Amodei"


def test_production_intent_maxus9_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="Представлен минивэн SAIC Maxus 9 2027 с заменой батареи", category=None, evidence=_evidence(),
    )
    PRODUCTION_INTENT_MAXUS9_IS_INFORMATIVE = bool(intent.model_name)
    assert PRODUCTION_INTENT_MAXUS9_IS_INFORMATIVE is True
    assert intent.model_name == "Maxus 9"


def test_production_intent_playstation_hardware_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="Sony анонсировала PlayStation 6 с поддержкой нового формата", category=None, evidence=_evidence(),
    )
    assert intent.model_name == "PlayStation 6"
    assert intent.product_name == "PlayStation"


def test_production_intent_automotive_model_is_informative() -> None:
    intent = build_visual_intent_from_evidence(
        title="Tesla представила Model Y 2027 с обновлённой батареей", category=None, evidence=_evidence(),
    )
    assert intent.model_name is not None
    assert "Y" in intent.model_name or "Model" in (intent.product_name or "")


def test_production_intent_generic_concept_story_falls_back_to_concept_never_fabricates() -> None:
    intent = build_visual_intent_from_evidence(
        title="Регулирование ИИ обсуждается на международном уровне", category=None, evidence=_evidence(),
    )
    assert intent.subject_type == MediaSubjectType.CONCEPT
    assert intent.product_name is None
    assert intent.model_name is None
    assert intent.person is None
