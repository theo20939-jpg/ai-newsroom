"""Phase 18.6 - Meme Opportunity Human Calibration tests (docs/
phase18_6_meme_calibration_report.md).

Pure, DB-free unit tests - neither `services/meme_calibration.py` nor the analysis script touches
the database; only `scripts/phase18_6_generate_calibration_packet.py` does, via a read-only
SELECT, not exercised here (mirrors `tests/test_phase18_5_shadow_analytics.py`'s own established
split).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from schemas.meme_calibration import (
    MemeCalibrationDataset,
    MemeCalibrationHumanDecision,
    MemeCalibrationReason,
    MemeCalibrationRecord,
    MemeCalibrationSafetyOpinion,
    MemeReviewGroup,
)
from schemas.meme_shadow_analytics import MemeOpportunityLabel, MemeShadowRecord
from services.meme_calibration import (
    build_calibration_record,
    build_dataset,
    category_analysis,
    opportunity_classifier_metrics,
    render_markdown_packet,
    safety_analysis,
    score_correlation,
    select_diverse_by_category,
    select_random,
)

_NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _shadow_record(
    event_id: str,
    category: str = "AI",
    label: MemeOpportunityLabel = MemeOpportunityLabel.MEDIUM,
    composite_score: int = 40,
    sensitivity_categories: list[str] | None = None,
    evidence_patterns: list[str] | None = None,
) -> MemeShadowRecord:
    decision_by_label = {
        MemeOpportunityLabel.HIGH: "MEME_READY",
        MemeOpportunityLabel.MEDIUM: "REVIEW",
        MemeOpportunityLabel.LOW: "NOT_SUITABLE",
        MemeOpportunityLabel.BLOCKED: "SENSITIVE_BLOCK",
    }
    return MemeShadowRecord(
        event_id=event_id,
        category=category,
        source_name="Test Source",
        opportunity_decision=decision_by_label[label],
        opportunity_label=label,
        composite_score=composite_score,
        reason_codes=[],
        sensitivity_categories=sensitivity_categories or [],
        evidence_patterns=evidence_patterns or [],
        source_sufficiency="sufficient",
        collected_at=_NOW,
    )


def _calibration_record(
    event_id: str = "evt-1",
    group: MemeReviewGroup = MemeReviewGroup.MEDIUM_CANDIDATE,
    category: str = "AI",
    algorithm_score: int = 40,
    human_score: int | None = None,
    human_decision: MemeCalibrationHumanDecision | None = None,
    safety_review: MemeCalibrationSafetyOpinion | None = None,
) -> MemeCalibrationRecord:
    return MemeCalibrationRecord(
        event_id=event_id,
        group=group,
        title="Some headline",
        category=category,
        source_name="Test Source",
        published_at=_NOW,
        content_excerpt="Some excerpt.",
        algorithm_score=algorithm_score,
        algorithm_level="MEDIUM",
        triggered_signals=["contrast_connector"],
        safety_result=[],
        human_score=human_score,
        human_decision=human_decision,
        safety_review=safety_review,
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_calibration_record_defaults_are_genuinely_blank() -> None:
    record = MemeCalibrationRecord(
        event_id="evt-1", group=MemeReviewGroup.MEDIUM_CANDIDATE, title="T", category="AI",
        source_name=None, published_at=None, content_excerpt="", algorithm_score=40,
        algorithm_level="MEDIUM",
    )
    assert record.human_score is None
    assert record.human_decision is None
    assert record.reasons == []
    assert record.safety_review is None
    assert record.notes is None
    assert record.is_reviewed is False


def test_calibration_record_is_reviewed_true_once_decision_set() -> None:
    record = _calibration_record(human_decision=MemeCalibrationHumanDecision.ACCEPT)
    assert record.is_reviewed is True


def test_calibration_record_human_score_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        MemeCalibrationRecord(
            event_id="evt-1", group=MemeReviewGroup.MEDIUM_CANDIDATE, title="T", category="AI",
            source_name=None, published_at=None, content_excerpt="", algorithm_score=40,
            algorithm_level="MEDIUM", human_score=6,
        )


def test_calibration_record_human_score_negative_rejected() -> None:
    with pytest.raises(ValueError):
        MemeCalibrationRecord(
            event_id="evt-1", group=MemeReviewGroup.MEDIUM_CANDIDATE, title="T", category="AI",
            source_name=None, published_at=None, content_excerpt="", algorithm_score=40,
            algorithm_level="MEDIUM", human_score=-1,
        )


def test_calibration_record_forbids_unknown_fields() -> None:
    with pytest.raises(ValueError):
        MemeCalibrationRecord.model_validate({
            "event_id": "evt-1", "group": "MEDIUM_CANDIDATE", "title": "T", "category": "AI",
            "source_name": None, "published_at": None, "content_excerpt": "", "algorithm_score": 40,
            "algorithm_level": "MEDIUM", "unexpected_field": "nope",
        })


def test_calibration_record_algorithm_score_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        MemeCalibrationRecord(
            event_id="evt-1", group=MemeReviewGroup.MEDIUM_CANDIDATE, title="T", category="AI",
            source_name=None, published_at=None, content_excerpt="", algorithm_score=101,
            algorithm_level="MEDIUM",
        )


def test_completed_annotation_round_trips_through_json() -> None:
    """Parses a "completed human JSON" (every human_* field filled in) exactly the way
    `scripts/phase18_6_calibration_analysis.py` expects to receive it."""
    record = _calibration_record(
        human_score=4,
        human_decision=MemeCalibrationHumanDecision.ACCEPT,
        safety_review=MemeCalibrationSafetyOpinion.SAFE,
    )
    record = record.model_copy(update={"reasons": [MemeCalibrationReason.IRONY, MemeCalibrationReason.AI_HYPE], "notes": "Great candidate"})
    dataset = build_dataset([record])
    raw = dataset.model_dump_json()
    reloaded = MemeCalibrationDataset.model_validate_json(raw)
    assert reloaded.records[0].human_score == 4
    assert reloaded.records[0].human_decision == MemeCalibrationHumanDecision.ACCEPT
    assert reloaded.records[0].reasons == [MemeCalibrationReason.IRONY, MemeCalibrationReason.AI_HYPE]
    assert reloaded.records[0].notes == "Great candidate"


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------


def test_select_diverse_by_category_respects_count() -> None:
    records = [_shadow_record(f"evt-{i}", category="AI") for i in range(30)]
    selected = select_diverse_by_category(records, 20, seed=18.6)
    assert len(selected) == 20


def test_select_diverse_by_category_returns_all_when_pool_smaller_than_count() -> None:
    records = [_shadow_record(f"evt-{i}", category="AI") for i in range(5)]
    selected = select_diverse_by_category(records, 20, seed=18.6)
    assert len(selected) == 5


def test_select_diverse_by_category_empty_pool_returns_empty() -> None:
    assert select_diverse_by_category([], 20, seed=18.6) == []


def test_select_diverse_by_category_zero_count_returns_empty() -> None:
    records = [_shadow_record("evt-1")]
    assert select_diverse_by_category(records, 0, seed=18.6) == []


def test_select_diverse_by_category_covers_every_available_category() -> None:
    records = (
        [_shadow_record(f"ai-{i}", category="AI") for i in range(10)]
        + [_shadow_record(f"su-{i}", category="STARTUPS") for i in range(2)]
        + [_shadow_record(f"sw-{i}", category="SOFTWARE") for i in range(1)]
    )
    selected = select_diverse_by_category(records, 6, seed=18.6)
    categories = {r.category for r in selected}
    assert categories == {"AI", "STARTUPS", "SOFTWARE"}


def test_select_diverse_by_category_no_duplicates() -> None:
    records = [_shadow_record(f"evt-{i}", category="AI") for i in range(30)]
    selected = select_diverse_by_category(records, 20, seed=18.6)
    ids = [r.event_id for r in selected]
    assert len(ids) == len(set(ids))


def test_select_diverse_by_category_is_deterministic() -> None:
    records = (
        [_shadow_record(f"ai-{i}", category="AI") for i in range(10)]
        + [_shadow_record(f"su-{i}", category="STARTUPS") for i in range(4)]
    )
    first = [r.event_id for r in select_diverse_by_category(records, 8, seed=18.6)]
    second = [r.event_id for r in select_diverse_by_category(records, 8, seed=18.6)]
    assert first == second


def test_select_random_respects_count() -> None:
    records = [_shadow_record(f"evt-{i}", label=MemeOpportunityLabel.LOW) for i in range(50)]
    selected = select_random(records, 20, seed=18.6)
    assert len(selected) == 20


def test_select_random_no_duplicates() -> None:
    records = [_shadow_record(f"evt-{i}", label=MemeOpportunityLabel.LOW) for i in range(50)]
    selected = select_random(records, 20, seed=18.6)
    ids = [r.event_id for r in selected]
    assert len(ids) == len(set(ids))


def test_select_random_returns_all_when_pool_smaller_than_count() -> None:
    records = [_shadow_record(f"evt-{i}") for i in range(3)]
    assert len(select_random(records, 20, seed=18.6)) == 3


def test_select_random_empty_pool_returns_empty() -> None:
    assert select_random([], 20, seed=18.6) == []


def test_select_random_is_deterministic() -> None:
    records = [_shadow_record(f"evt-{i}") for i in range(50)]
    first = [r.event_id for r in select_random(records, 20, seed=18.6)]
    second = [r.event_id for r in select_random(records, 20, seed=18.6)]
    assert first == second


# ---------------------------------------------------------------------------
# Record building / group separation
# ---------------------------------------------------------------------------


def test_build_calibration_record_maps_medium_to_group_a() -> None:
    shadow = _shadow_record("evt-1", label=MemeOpportunityLabel.MEDIUM)
    record = build_calibration_record(shadow, title="Title", content="Content", published_at=_NOW)
    assert record.group == MemeReviewGroup.MEDIUM_CANDIDATE


def test_build_calibration_record_maps_low_to_group_b() -> None:
    shadow = _shadow_record("evt-1", label=MemeOpportunityLabel.LOW)
    record = build_calibration_record(shadow, title="Title", content="Content", published_at=_NOW)
    assert record.group == MemeReviewGroup.LOW_RANDOM


def test_build_calibration_record_maps_blocked_to_group_c() -> None:
    shadow = _shadow_record("evt-1", label=MemeOpportunityLabel.BLOCKED, sensitivity_categories=["war"])
    record = build_calibration_record(shadow, title="Title", content="Content", published_at=_NOW)
    assert record.group == MemeReviewGroup.SAFETY_BLOCKED
    assert record.safety_result == ["war"]


def test_build_calibration_record_rejects_high_label() -> None:
    """HIGH has no calibration group defined (the brief's own three groups are A/B/C only) -
    should fail loudly rather than silently mis-bucket."""
    shadow = _shadow_record("evt-1", label=MemeOpportunityLabel.HIGH)
    with pytest.raises(ValueError):
        build_calibration_record(shadow, title="Title", content="Content", published_at=_NOW)


def test_build_calibration_record_carries_algorithm_fields_through_unchanged() -> None:
    shadow = _shadow_record("evt-1", composite_score=42, evidence_patterns=["contrast_connector"])
    record = build_calibration_record(shadow, title="Title", content="Content", published_at=_NOW)
    assert record.algorithm_score == 42
    assert record.algorithm_level == "MEDIUM"
    assert record.triggered_signals == ["contrast_connector"]


def test_build_calibration_record_excerpt_truncated_to_280_chars() -> None:
    shadow = _shadow_record("evt-1")
    long_content = "x" * 1000
    record = build_calibration_record(shadow, title="Title", content=long_content, published_at=_NOW)
    assert len(record.content_excerpt) == 280


def test_build_calibration_record_handles_none_content() -> None:
    shadow = _shadow_record("evt-1")
    record = build_calibration_record(shadow, title="Title", content=None, published_at=_NOW)
    assert record.content_excerpt == ""


def test_build_calibration_record_human_fields_left_blank() -> None:
    shadow = _shadow_record("evt-1")
    record = build_calibration_record(shadow, title="Title", content="c", published_at=_NOW)
    assert record.human_score is None
    assert record.human_decision is None
    assert record.reasons == []
    assert record.safety_review is None
    assert record.notes is None


def test_build_dataset_computes_group_counts() -> None:
    records = [
        _calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE),
        _calibration_record("a-2", group=MemeReviewGroup.MEDIUM_CANDIDATE),
        _calibration_record("b-1", group=MemeReviewGroup.LOW_RANDOM),
        _calibration_record("c-1", group=MemeReviewGroup.SAFETY_BLOCKED),
    ]
    dataset = build_dataset(records)
    assert dataset.group_a_count == 2
    assert dataset.group_b_count == 1
    assert dataset.group_c_count == 1
    assert len(dataset.records) == 4


def test_build_dataset_empty_records_gives_zero_counts() -> None:
    dataset = build_dataset([])
    assert dataset.group_a_count == 0
    assert dataset.group_b_count == 0
    assert dataset.group_c_count == 0


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_render_markdown_packet_every_human_field_is_placeholder() -> None:
    records = [
        _calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE),
        _calibration_record("b-1", group=MemeReviewGroup.LOW_RANDOM),
        _calibration_record("c-1", group=MemeReviewGroup.SAFETY_BLOCKED),
    ]
    markdown = render_markdown_packet(build_dataset(records))
    assert markdown.count("_[ not yet reviewed ]_") == 15  # 5 human fields x 3 records
    for real_value in ("ACCEPT", "WEAK", "REJECT"):
        assert f"**Decision** (`ACCEPT` / `WEAK` / `REJECT`): {real_value}" not in markdown


def test_render_markdown_packet_includes_group_headers_and_counts() -> None:
    records = [_calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE)]
    markdown = render_markdown_packet(build_dataset(records))
    assert "Group A — Current MEDIUM candidates (1 items)" in markdown
    assert "Group B — Random LOW score examples (0 items)" in markdown
    assert "Group C — Safety-blocked examples (0 items)" in markdown


def test_render_markdown_packet_empty_group_shows_no_events_message() -> None:
    records = [_calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE)]
    markdown = render_markdown_packet(build_dataset(records))
    assert "_No real events were selected into this group._" in markdown


def test_render_markdown_packet_numbers_items_sequentially_across_groups() -> None:
    records = [
        _calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE),
        _calibration_record("b-1", group=MemeReviewGroup.LOW_RANDOM),
    ]
    markdown = render_markdown_packet(build_dataset(records))
    assert "### 1." in markdown
    assert "### 2." in markdown


# ---------------------------------------------------------------------------
# Metric calculation
# ---------------------------------------------------------------------------


def test_opportunity_classifier_metrics_empty_records_returns_none_metrics() -> None:
    metrics = opportunity_classifier_metrics([])
    assert metrics["precision_strict"] is None
    assert metrics["false_negative_rate"] is None
    assert metrics["recall"] is None
    assert metrics["false_negative_examples"] == []


def test_opportunity_classifier_metrics_precision_strict_and_lenient() -> None:
    records = [
        _calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE, human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("a-2", group=MemeReviewGroup.MEDIUM_CANDIDATE, human_decision=MemeCalibrationHumanDecision.WEAK),
        _calibration_record("a-3", group=MemeReviewGroup.MEDIUM_CANDIDATE, human_decision=MemeCalibrationHumanDecision.REJECT),
        _calibration_record("a-4", group=MemeReviewGroup.MEDIUM_CANDIDATE, human_decision=MemeCalibrationHumanDecision.REJECT),
    ]
    metrics = opportunity_classifier_metrics(records)
    assert metrics["precision_strict"] == pytest.approx(0.25)
    assert metrics["precision_lenient"] == pytest.approx(0.5)
    assert metrics["false_positive_rate"] == pytest.approx(0.5)
    assert metrics["group_a_reviewed"] == 4


def test_opportunity_classifier_metrics_ignores_unreviewed_group_a_records() -> None:
    records = [
        _calibration_record("a-1", group=MemeReviewGroup.MEDIUM_CANDIDATE, human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("a-2", group=MemeReviewGroup.MEDIUM_CANDIDATE, human_decision=None),
    ]
    metrics = opportunity_classifier_metrics(records)
    assert metrics["group_a_reviewed"] == 1
    assert metrics["precision_strict"] == pytest.approx(1.0)


def test_opportunity_classifier_metrics_false_negative_rate_and_examples() -> None:
    records = [
        _calibration_record("b-1", group=MemeReviewGroup.LOW_RANDOM, human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("b-2", group=MemeReviewGroup.LOW_RANDOM, human_decision=MemeCalibrationHumanDecision.REJECT),
        _calibration_record("b-3", group=MemeReviewGroup.LOW_RANDOM, human_decision=MemeCalibrationHumanDecision.WEAK),
    ]
    metrics = opportunity_classifier_metrics(records)
    assert metrics["false_negative_rate"] == pytest.approx(2 / 3)
    examples = metrics["false_negative_examples"]
    assert isinstance(examples, list)
    assert set(examples) == {"b-1", "b-3"}


def test_opportunity_classifier_metrics_recall_always_none_with_note() -> None:
    records = [_calibration_record("a-1", human_decision=MemeCalibrationHumanDecision.ACCEPT)]
    metrics = opportunity_classifier_metrics(records)
    assert metrics["recall"] is None
    assert "recall_note" in metrics and isinstance(metrics["recall_note"], str)


def test_score_correlation_perfect_positive() -> None:
    records = [
        _calibration_record("a-1", algorithm_score=10, human_score=1, human_decision=MemeCalibrationHumanDecision.REJECT),
        _calibration_record("a-2", algorithm_score=40, human_score=2, human_decision=MemeCalibrationHumanDecision.WEAK),
        _calibration_record("a-3", algorithm_score=70, human_score=4, human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("a-4", algorithm_score=90, human_score=5, human_decision=MemeCalibrationHumanDecision.ACCEPT),
    ]
    result = score_correlation(records)
    assert result["correlation"] == pytest.approx(1.0, abs=0.01)
    assert result["n"] == 4


def test_score_correlation_fewer_than_two_points_returns_none() -> None:
    records = [_calibration_record("a-1", human_score=3, human_decision=MemeCalibrationHumanDecision.ACCEPT)]
    result = score_correlation(records)
    assert result["correlation"] is None
    assert result["n"] == 1


def test_score_correlation_no_variance_returns_none() -> None:
    records = [
        _calibration_record("a-1", algorithm_score=40, human_score=3, human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("a-2", algorithm_score=40, human_score=3, human_decision=MemeCalibrationHumanDecision.ACCEPT),
    ]
    result = score_correlation(records)
    assert result["correlation"] is None


def test_score_correlation_ignores_records_without_human_score() -> None:
    records = [
        _calibration_record("a-1", algorithm_score=10, human_score=1, human_decision=MemeCalibrationHumanDecision.REJECT),
        _calibration_record("a-2", algorithm_score=90, human_score=None, human_decision=MemeCalibrationHumanDecision.ACCEPT),
    ]
    result = score_correlation(records)
    assert result["n"] == 1
    assert result["correlation"] is None


def test_category_analysis_averages_and_sorts_descending() -> None:
    records = [
        _calibration_record("a-1", category="AI", human_score=5, human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("a-2", category="AI", human_score=3, human_decision=MemeCalibrationHumanDecision.WEAK),
        _calibration_record("a-3", category="STARTUPS", human_score=1, human_decision=MemeCalibrationHumanDecision.REJECT),
    ]
    result = category_analysis(records)
    categories = list(result.keys())
    assert categories[0] == "AI"
    assert result["AI"]["average_human_score"] == pytest.approx(4.0)
    assert result["AI"]["reviewed_count"] == 2
    assert result["STARTUPS"]["average_human_score"] == pytest.approx(1.0)


def test_category_analysis_ignores_unreviewed_records() -> None:
    records = [_calibration_record("a-1", category="AI", human_score=None, human_decision=None)]
    result = category_analysis(records)
    assert result == {}


def test_safety_analysis_correct_and_false_blocks() -> None:
    records = [
        _calibration_record("c-1", group=MemeReviewGroup.SAFETY_BLOCKED, human_decision=MemeCalibrationHumanDecision.REJECT, safety_review=MemeCalibrationSafetyOpinion.SHOULD_BLOCK),
        _calibration_record("c-2", group=MemeReviewGroup.SAFETY_BLOCKED, human_decision=MemeCalibrationHumanDecision.ACCEPT, safety_review=MemeCalibrationSafetyOpinion.SAFE),
        _calibration_record("c-3", group=MemeReviewGroup.SAFETY_BLOCKED, human_decision=MemeCalibrationHumanDecision.WEAK, safety_review=MemeCalibrationSafetyOpinion.QUESTIONABLE),
    ]
    result = safety_analysis(records)
    assert result["group_c_reviewed"] == 3
    assert result["correct_blocks"] == 1
    assert result["false_blocks"] == 1
    assert result["false_block_examples"] == ["c-2"]
    assert result["questionable_blocks"] == 1


def test_safety_analysis_empty_group_c_returns_zeros() -> None:
    result = safety_analysis([])
    assert result["group_c_reviewed"] == 0
    assert result["correct_blocks"] == 0
    assert result["false_blocks"] == 0


# ---------------------------------------------------------------------------
# Analysis script's own honesty gate
# ---------------------------------------------------------------------------


def test_analyze_reports_pending_when_nothing_reviewed() -> None:
    from scripts.phase18_6_calibration_analysis import analyze

    dataset = build_dataset([_calibration_record("a-1")])
    report = analyze(dataset)
    assert report["status"] == "pending"
    assert report["message"] == "Calibration dataset prepared, human review pending."
    assert "opportunity_classifier_metrics" not in report


def test_analyze_reports_partial_when_some_reviewed() -> None:
    from scripts.phase18_6_calibration_analysis import analyze

    dataset = build_dataset([
        _calibration_record("a-1", human_decision=MemeCalibrationHumanDecision.ACCEPT),
        _calibration_record("a-2", human_decision=None),
    ])
    report = analyze(dataset)
    assert report["status"] == "partial"
    assert report["reviewed_records"] == 1
    assert "opportunity_classifier_metrics" in report


def test_analyze_reports_complete_when_all_reviewed() -> None:
    from scripts.phase18_6_calibration_analysis import analyze

    dataset = build_dataset([_calibration_record("a-1", human_decision=MemeCalibrationHumanDecision.ACCEPT)])
    report = analyze(dataset)
    assert report["status"] == "complete"


# ---------------------------------------------------------------------------
# Committed-artifact regression guards (real files, not just generator intent)
# ---------------------------------------------------------------------------


def test_committed_dataset_file_has_expected_group_sizes() -> None:
    from pathlib import Path

    path = Path("scripts/phase18_6_calibration_dataset.json")
    dataset = MemeCalibrationDataset.model_validate_json(path.read_text(encoding="utf-8"))
    assert dataset.group_a_count == 20
    assert dataset.group_b_count == 20
    assert dataset.group_c_count == 10
    assert len(dataset.records) == 50


def test_committed_dataset_file_every_human_field_is_blank() -> None:
    from pathlib import Path

    path = Path("scripts/phase18_6_calibration_dataset.json")
    dataset = MemeCalibrationDataset.model_validate_json(path.read_text(encoding="utf-8"))
    for record in dataset.records:
        assert record.human_score is None
        assert record.human_decision is None
        assert record.reasons == []
        assert record.safety_review is None
        assert record.notes is None


def test_committed_human_review_packet_has_at_least_50_items_and_every_decision_field_is_blank() -> None:
    """Regression guard for the brief's own "Leave EMPTY. Human must fill manually" requirement -
    checks the actual, committed docs/phase18_6_human_review_packet.md file, not merely the
    generator script's intent (mirrors Phase 18.5 M3's own established precedent)."""
    from pathlib import Path

    text = Path("docs/phase18_6_human_review_packet.md").read_text(encoding="utf-8")
    decision_lines = [line for line in text.splitlines() if line.strip().startswith("- **Decision** (`")]
    assert len(decision_lines) >= 50
    for line in decision_lines:
        assert "_[ not yet reviewed ]_" in line
        for real_value in ("ACCEPT", "WEAK", "REJECT"):
            assert not line.strip().endswith(real_value)


# ---------------------------------------------------------------------------
# Import-boundary / no-production-mutation checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", [
    "services/meme_calibration.py",
    "scripts/phase18_6_generate_calibration_packet.py",
    "scripts/phase18_6_calibration_analysis.py",
])
def test_no_forbidden_imports(module_path: str) -> None:
    import ast
    from pathlib import Path

    source = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_substrings = (
        "capabilities.executor", "workflows.runner", "bot.", "llm_gateway", "meme_image_generation",
        "meme_preview_notifier", "meme_candidate_service",
    )
    for module in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in module, f"{module_path} must never import {module!r}"


def test_no_insert_update_delete_statements_in_generation_script() -> None:
    from pathlib import Path

    source = Path("scripts/phase18_6_generate_calibration_packet.py").read_text(encoding="utf-8").lower()
    for forbidden in ("session.add(", "session.commit(", "insert(", "update(", "delete(", ".execute(text("):
        assert forbidden not in source, f"generation script must never contain {forbidden!r}"


def test_no_insert_update_delete_statements_in_analysis_script() -> None:
    from pathlib import Path

    source = Path("scripts/phase18_6_calibration_analysis.py").read_text(encoding="utf-8").lower()
    for forbidden in ("session.add(", "session.commit(", "insert(", "update(", "delete(", ".execute("):
        assert forbidden not in source, f"analysis script must never contain {forbidden!r}"


def test_analysis_script_has_no_database_imports_at_all() -> None:
    """Stronger than the shared import-boundary check - the analysis script must not import
    `database.session` or any SQLAlchemy machinery, since it only ever reads a local JSON file."""
    from pathlib import Path

    source = Path("scripts/phase18_6_calibration_analysis.py").read_text(encoding="utf-8")
    assert "database.session" not in source
    assert "sqlalchemy" not in source.lower()
