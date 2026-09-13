"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S9/S17/S21/S35: composition precedence + quality gate."""
from datetime import datetime, timezone
from uuid import uuid4

from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaSelectionResult,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.editorial_pipeline.composition import build_composition_plan, decide_data_composition_strategy
from services.editorial_pipeline.contracts import (
    DataCompositionStrategy,
    Platform,
    PresentationFormat,
    QualityGateVerdict,
    StructuredDataContent,
)
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.quality import run_quality_gate

_DATA_CONTENT_WITH_SERIES = StructuredDataContent(
    metric_value="290", metric_unit="тыс. юаней", metric_label="Стартовая цена Maxus 9",
    subject="Maxus 9", context_sentence="fact", comparison=None, delta=None, delta_context=None,
    series=(1.0, 2.0, 3.0), source_claim_id="claim-1", source_fact="fact",
)
_DATA_CONTENT_NO_SERIES = StructuredDataContent(
    metric_value="290", metric_unit="тыс. юаней", metric_label="Стартовая цена Maxus 9",
    subject="Maxus 9", context_sentence="fact", comparison=None, delta=None, delta_context=None,
    series=(), source_claim_id="claim-1", source_fact="fact",
)


def _candidate(subject_match: SubjectMatchClassification) -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id="c1",
        provenance=MediaProvenance(
            origin_url="https://example.com", asset_url="https://example.com/x.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
        subject_match=SubjectMatchValidation(
            depicted_subject_description="x", subject_match=subject_match, must_not_imply_violated=False, reason="test",
        ),
    )


def _selection(candidate: ResolvedMediaCandidate | None) -> MediaSelectionResult:
    return MediaSelectionResult(
        intent_primary_entity="Maxus 9", selected=candidate, exact_subject_media_not_found=candidate is None,
        fallback_used=False, candidates_considered=1 if candidate else 0,
    )


# --- composition precedence (S9) ---


def test_real_series_wins_data_with_graph() -> None:
    strategy = decide_data_composition_strategy(structured_data=_DATA_CONTENT_WITH_SERIES, media_selection=None)
    assert strategy == DataCompositionStrategy.DATA_WITH_GRAPH


def test_no_series_but_a_good_source_image_wins_data_with_source_image() -> None:
    selection = _selection(_candidate(SubjectMatchClassification.EXACT_SUBJECT))
    strategy = decide_data_composition_strategy(structured_data=_DATA_CONTENT_NO_SERIES, media_selection=selection)
    assert strategy == DataCompositionStrategy.DATA_WITH_SOURCE_IMAGE


def test_a_mismatched_image_never_counts_as_suitable_falls_to_typographic() -> None:
    selection = _selection(_candidate(SubjectMatchClassification.MISMATCH))
    strategy = decide_data_composition_strategy(structured_data=_DATA_CONTENT_NO_SERIES, media_selection=selection)
    assert strategy == DataCompositionStrategy.DATA_TYPOGRAPHIC


def test_neither_series_nor_image_falls_to_typographic_never_fabricates_a_graph() -> None:
    strategy = decide_data_composition_strategy(structured_data=_DATA_CONTENT_NO_SERIES, media_selection=_selection(None))
    assert strategy == DataCompositionStrategy.DATA_TYPOGRAPHIC


def test_build_composition_plan_sets_data_strategy_only_for_data() -> None:
    plan = build_composition_plan(
        presentation_format=PresentationFormat.NEWS, structured_data=None, media_selection=None,
    )
    assert plan.data_strategy is None
    data_plan = build_composition_plan(
        presentation_format=PresentationFormat.DATA, structured_data=_DATA_CONTENT_WITH_SERIES, media_selection=None,
    )
    assert data_plan.data_strategy == DataCompositionStrategy.DATA_WITH_GRAPH


# --- quality gate (S21) ---


def test_quality_gate_ready_for_clean_content() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=["fact"])
    content = StructuredDataContent(
        metric_value="290", metric_unit="тыс. юаней", metric_label="Стартовая цена Maxus 9", subject="Maxus 9",
        context_sentence="fact", comparison=None, delta=None, delta_context=None, series=(),
        source_claim_id=evidence.claims[0].claim_id, source_fact="fact",
    )
    result = run_quality_gate(
        content=content, evidence=evidence, media_selection=None,
        caption_or_copy="Стартовая цена Maxus 9 составляет 290 тыс. юаней.", platform=Platform.TELEGRAM,
    )
    assert result.verdict == QualityGateVerdict.READY
    assert result.failed_checks == ()


def test_quality_gate_holds_on_the_real_maxus_defect_text() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=["fact"])
    content = StructuredDataContent(
        metric_value="290", metric_unit="тыс. юаней", metric_label="x", subject="x", context_sentence="fact",
        comparison=None, delta=None, delta_context=None, series=(), source_claim_id=evidence.claims[0].claim_id,
        source_fact="fact",
    )
    result = run_quality_gate(
        content=content, evidence=evidence, media_selection=None,
        caption_or_copy="Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн рублей).",
        platform=Platform.TELEGRAM,
    )
    assert result.verdict == QualityGateVerdict.HOLD


def test_quality_gate_blocks_on_visual_mismatch_never_downgraded_to_hold() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=["fact"])
    selection = _selection(_candidate(SubjectMatchClassification.MISMATCH))
    result = run_quality_gate(
        content=None, evidence=evidence, media_selection=selection, caption_or_copy="text", platform=Platform.TELEGRAM,
    )
    assert result.verdict == QualityGateVerdict.BLOCK


def test_quality_gate_untraceable_claim_never_passes() -> None:
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=["real fact"])
    content = StructuredDataContent(
        metric_value="1", metric_unit="x", metric_label="x", subject="x", context_sentence="x", comparison=None,
        delta=None, delta_context=None, series=(), source_claim_id="claim-does-not-exist", source_fact="x",
    )
    result = run_quality_gate(
        content=content, evidence=evidence, media_selection=None, caption_or_copy="Цена x.", platform=Platform.TELEGRAM,
    )
    assert result.verdict != QualityGateVerdict.READY
