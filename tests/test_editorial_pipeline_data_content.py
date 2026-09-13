"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S9/S28-C: the real Maxus 9 DATA replay.

The fact text below is the REAL sentence from the real article (iXBT, 2026-09-12,
https://www.ixbt.com/news/2026/09/12/435361-...saic-maxus-9-2027.html), independently fetched
during this phase's own investigation - not fabricated, not paraphrased. Running the OLD
`services.presentation_director._find_data_candidate()` extractor directly against it (before any
of this phase's own code existed) reproduced the exact defect class the phase brief named:

    label='Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн рублей).'

- the number "290 тыс." silently vanished from the middle of the sentence, leaving a dangling
"начинается с юаней" ("starts with yuan", no number) - confirmed via a direct, one-off repro script
run against this exact fact string before `build_structured_data_content()` was written.
"""
from uuid import uuid4

from services.editorial_pipeline.content import build_structured_data_content
from services.editorial_pipeline.evidence import build_evidence_pack

# The real, independently-fetched fact - verbatim.
_MAXUS_FACT = "Рекомендованная цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)."
_MAXUS_TITLE = "Представлен минивэн SAIC Maxus 9 2027 с заменой батареи за 90 секунд"
_MAXUS_BODY = (
    "SAIC представила минивэн Maxus 9 2027 года. Стартовая цена модели составляет "
    "290 тыс. юаней, что соответствует примерно 3,8 млн рублей. Полностью разряженный "
    "аккумулятор можно заменить на заряженный примерно за 90 секунд."
)


def test_old_extractor_reproduces_the_real_defect() -> None:
    """Pins down the OLD behavior as a documented regression baseline - if this ever stops
    reproducing the bug (e.g. because someone patches the old function directly instead of going
    through the new structured-content path), this test will fail loudly rather than silently
    losing its own justification for existing."""
    from services.presentation_director import _find_data_candidate

    old = _find_data_candidate(_MAXUS_TITLE, _MAXUS_BODY, [_MAXUS_FACT])
    assert old is not None
    assert "юаней" in old.label
    assert "290" not in old.label  # the defect: the number is gone from the label
    assert "с юаней" in old.label  # the dangling-preposition artifact the phase brief named


def test_maxus_9_structured_data_content_never_produces_the_defect() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None,
        source_url="https://www.ixbt.com/news/2026/09/12/435361-...saic-maxus-9-2027.html",
        research_facts=[_MAXUS_FACT],
    )

    content = build_structured_data_content(title=_MAXUS_TITLE, main_body=_MAXUS_BODY, evidence=evidence)

    assert content is not None
    assert content.metric_value == "290"
    assert "тыс" in content.metric_unit and "юан" in content.metric_unit  # unit stays whole
    assert "290" not in content.metric_label  # label never re-embeds the raw number
    assert "юаней" not in content.metric_label  # or the unit - it is a clean, constructed label
    assert content.subject == "Maxus 9"
    assert content.metric_label == "Стартовая цена Maxus 9"
    assert content.context_sentence == _MAXUS_FACT
    assert content.source_fact == _MAXUS_FACT
    assert evidence.claim_by_id(content.source_claim_id) is not None


def test_data_content_never_fabricates_when_nothing_grounds() -> None:
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None,
        research_facts=["Компания объявила о запуске нового продукта без указания цены."],
    )
    content = build_structured_data_content(
        title="Компания объявила о запуске нового продукта", main_body=None, evidence=evidence,
    )
    assert content is None


def test_data_content_claim_traceability() -> None:
    """Every StructuredDataContent's source_claim_id must resolve to a real claim whose
    raw_fact_text is the exact fact the metric came from - S7's own claim-traceability
    requirement, S35's own required test class."""
    evidence = build_evidence_pack(
        news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[_MAXUS_FACT],
    )
    content = build_structured_data_content(title=_MAXUS_TITLE, main_body=_MAXUS_BODY, evidence=evidence)
    assert content is not None
    claim = evidence.claim_by_id(content.source_claim_id)
    assert claim is not None
    assert claim.raw_fact_text == _MAXUS_FACT
