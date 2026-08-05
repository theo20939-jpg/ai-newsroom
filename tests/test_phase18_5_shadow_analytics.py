"""Phase 18.5 M1/M2 - Meme Shadow Analytics tests (docs/
phase18_5_meme_shadow_validation_discovery.md).

Pure, DB-free unit tests - `services/meme_shadow_analytics.py` never touches the database itself
(only `scripts/phase18_5_shadow_collection.py` does, via a read-only SELECT, not exercised here).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database.models.news_event import EventCategory
from schemas.meme_opportunity import (
    MemeOpportunityAssessment,
    MemeOpportunityDecision,
    MemeOpportunitySignals,
)
from schemas.meme_shadow_analytics import MemeOpportunityLabel, MemeShadowRecord
from services.meme_shadow_analytics import (
    LABEL_BY_DECISION,
    all_category_distribution,
    blocked_sensitivity_distribution,
    build_shadow_record,
    category_distribution,
    composite_score_histogram,
    decision_counts,
    evaluate_event_shadow,
    label_for_decision,
    opportunity_rate,
    pattern_performance,
    safety_block_rate,
    source_sufficiency_distribution,
)

_NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _assessment(
    decision: MemeOpportunityDecision, *, composite: int = 50, reason_codes=None,
    sensitivity=None, evidence=None, sufficiency: str = "sufficient",
) -> MemeOpportunityAssessment:
    signals = MemeOpportunitySignals(
        irony_contrast_score=composite, audience_relatability_score=composite,
        visual_potential_score=composite, topic_fit_score=composite, freshness_score=composite,
        composite_score=composite,
    )
    return MemeOpportunityAssessment(
        policy_version="v1", decision=decision, signals=signals,
        sensitivity_categories=sensitivity or [], source_sufficiency=sufficiency,
        reason_codes=reason_codes or [], evidence=evidence or [],
    )


# ---------------------------------------------------------------------------
# Label mapping
# ---------------------------------------------------------------------------


def test_every_decision_has_a_label() -> None:
    for decision in MemeOpportunityDecision:
        assert decision in LABEL_BY_DECISION


def test_meme_ready_maps_to_high() -> None:
    assert label_for_decision(MemeOpportunityDecision.MEME_READY) == MemeOpportunityLabel.HIGH


def test_review_maps_to_medium() -> None:
    assert label_for_decision(MemeOpportunityDecision.REVIEW) == MemeOpportunityLabel.MEDIUM


@pytest.mark.parametrize("decision", [MemeOpportunityDecision.NOT_SUITABLE, MemeOpportunityDecision.INSUFFICIENT_SOURCE])
def test_not_suitable_and_insufficient_source_map_to_low(decision: MemeOpportunityDecision) -> None:
    assert label_for_decision(decision) == MemeOpportunityLabel.LOW


def test_sensitive_block_maps_to_blocked() -> None:
    assert label_for_decision(MemeOpportunityDecision.SENSITIVE_BLOCK) == MemeOpportunityLabel.BLOCKED


# ---------------------------------------------------------------------------
# build_shadow_record - normalization
# ---------------------------------------------------------------------------


def test_build_shadow_record_normalizes_fields() -> None:
    event_id = uuid4()
    assessment = _assessment(
        MemeOpportunityDecision.MEME_READY, composite=72, reason_codes=["x"],
        evidence=["contrast_connector"],
    )
    record = build_shadow_record(event_id, EventCategory.AI, "Test Source", assessment, now=_NOW)

    assert record.event_id == str(event_id)
    assert record.category == "AI"
    assert record.source_name == "Test Source"
    assert record.opportunity_decision == "MEME_READY"
    assert record.opportunity_label == MemeOpportunityLabel.HIGH
    assert record.composite_score == 72
    assert record.reason_codes == ["x"]
    assert record.evidence_patterns == ["contrast_connector"]
    assert record.collected_at == _NOW


def test_build_shadow_record_never_contains_raw_title_or_content() -> None:
    """No field on MemeShadowRecord can hold the event's own title/content text - proven by
    schema inspection (the model literally has no such field), not merely by convention."""
    fields = set(MemeShadowRecord.model_fields)
    assert "title" not in fields
    assert "content" not in fields
    assert "text" not in fields


def test_build_shadow_record_is_json_serializable() -> None:
    assessment = _assessment(MemeOpportunityDecision.REVIEW)
    record = build_shadow_record(uuid4(), EventCategory.STARTUPS, None, assessment, now=_NOW)
    payload = record.model_dump_json()
    assert "MEDIUM" in payload


# ---------------------------------------------------------------------------
# evaluate_event_shadow - failure isolation
# ---------------------------------------------------------------------------


def test_evaluate_event_shadow_normal_case() -> None:
    record = evaluate_event_shadow(
        uuid4(), "Nvidia CEO insists AI is not destroying jobs",
        "The Nvidia chief executive publicly insists AI is not destroying jobs, addressing "
        "growing anxiety among workers during a keynote address.",
        EventCategory.AI, _NOW, "Test Source", now=_NOW,
    )
    assert record is not None
    assert record.opportunity_label in (MemeOpportunityLabel.HIGH, MemeOpportunityLabel.MEDIUM)


def test_evaluate_event_shadow_failure_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.meme_shadow_analytics.assess_meme_opportunity", _broken)
    record = evaluate_event_shadow(
        uuid4(), "Some title", "Some content.", EventCategory.AI, _NOW, "Source", now=_NOW,
    )
    assert record is None  # never raises past this function


def test_evaluate_event_shadow_handles_missing_content() -> None:
    record = evaluate_event_shadow(uuid4(), "Some title", None, EventCategory.UNKNOWN, None, None, now=_NOW)
    assert record is not None
    assert record.opportunity_label in list(MemeOpportunityLabel)


# ---------------------------------------------------------------------------
# M2 metrics
# ---------------------------------------------------------------------------


def _record(
    label: MemeOpportunityLabel, category: str = "AI", evidence=None, sensitivity=None,
    source_sufficiency: str = "sufficient", composite_score: int = 50,
) -> MemeShadowRecord:
    decision = next(d for d, lbl in LABEL_BY_DECISION.items() if lbl == label)
    return MemeShadowRecord(
        event_id=str(uuid4()), category=category, source_name="s",
        opportunity_decision=decision.value, opportunity_label=label, composite_score=composite_score,
        reason_codes=[], sensitivity_categories=sensitivity or [], evidence_patterns=evidence or [],
        source_sufficiency=source_sufficiency, collected_at=_NOW,
    )


def test_opportunity_rate_counts_high_and_medium_only() -> None:
    records = [
        _record(MemeOpportunityLabel.HIGH), _record(MemeOpportunityLabel.MEDIUM),
        _record(MemeOpportunityLabel.LOW), _record(MemeOpportunityLabel.BLOCKED),
    ]
    assert opportunity_rate(records) == pytest.approx(0.5)


def test_opportunity_rate_empty_is_zero() -> None:
    assert opportunity_rate([]) == 0.0


def test_category_distribution_only_counts_potential_memes() -> None:
    records = [
        _record(MemeOpportunityLabel.HIGH, category="AI"),
        _record(MemeOpportunityLabel.MEDIUM, category="AI"),
        _record(MemeOpportunityLabel.HIGH, category="STARTUPS"),
        _record(MemeOpportunityLabel.LOW, category="GADGETS"),  # excluded - not a potential meme
    ]
    dist = category_distribution(records)
    assert dist["AI"] == pytest.approx(2 / 3)
    assert dist["STARTUPS"] == pytest.approx(1 / 3)
    assert "GADGETS" not in dist


def test_category_distribution_empty_when_no_potential_memes() -> None:
    records = [_record(MemeOpportunityLabel.LOW), _record(MemeOpportunityLabel.BLOCKED)]
    assert category_distribution(records) == {}


def test_safety_block_rate() -> None:
    records = [
        _record(MemeOpportunityLabel.BLOCKED), _record(MemeOpportunityLabel.HIGH),
        _record(MemeOpportunityLabel.LOW), _record(MemeOpportunityLabel.LOW),
    ]
    assert safety_block_rate(records) == pytest.approx(0.25)


def test_pattern_performance_counts_named_patterns() -> None:
    records = [
        _record(MemeOpportunityLabel.HIGH, evidence=["contrast_connector"]),
        _record(MemeOpportunityLabel.MEDIUM, evidence=["self_referential_reassurance", "explicit_irony_marker"]),
        _record(MemeOpportunityLabel.LOW, evidence=["contrast_connector"]),  # excluded - not potential meme
    ]
    perf = pattern_performance(records)
    assert perf["contradiction"] == 1
    assert perf["irony"] == 2


def test_pattern_performance_empty_input() -> None:
    assert pattern_performance([]) == {}


def test_decision_counts_includes_every_label_even_if_zero() -> None:
    records = [_record(MemeOpportunityLabel.HIGH), _record(MemeOpportunityLabel.HIGH)]
    counts = decision_counts(records)
    assert counts["HIGH"] == 2
    assert counts["MEDIUM"] == 0
    assert counts["LOW"] == 0
    assert counts["BLOCKED"] == 0


def test_all_category_distribution_includes_every_record() -> None:
    records = [
        _record(MemeOpportunityLabel.LOW, category="AI"), _record(MemeOpportunityLabel.LOW, category="AI"),
        _record(MemeOpportunityLabel.BLOCKED, category="STARTUPS"),
    ]
    dist = all_category_distribution(records)
    assert dist["AI"] == pytest.approx(2 / 3)
    assert dist["STARTUPS"] == pytest.approx(1 / 3)


def test_all_category_distribution_empty_input() -> None:
    assert all_category_distribution([]) == {}


def test_blocked_sensitivity_distribution_counts_only_blocked() -> None:
    records = [
        _record(MemeOpportunityLabel.BLOCKED, sensitivity=["war", "disaster"]),
        _record(MemeOpportunityLabel.BLOCKED, sensitivity=["war"]),
        _record(MemeOpportunityLabel.HIGH, sensitivity=["war"]),  # excluded - not BLOCKED
    ]
    dist = blocked_sensitivity_distribution(records)
    assert dist["war"] == 2
    assert dist["disaster"] == 1


def test_source_sufficiency_distribution() -> None:
    records = [
        _record(MemeOpportunityLabel.LOW, source_sufficiency="headline_only"),
        _record(MemeOpportunityLabel.LOW, source_sufficiency="headline_only"),
        _record(MemeOpportunityLabel.HIGH, source_sufficiency="sufficient"),
    ]
    dist = source_sufficiency_distribution(records)
    assert dist["headline_only"] == pytest.approx(2 / 3)
    assert dist["sufficient"] == pytest.approx(1 / 3)


def test_composite_score_histogram_buckets_correctly() -> None:
    records = [
        _record(MemeOpportunityLabel.LOW, composite_score=12),
        _record(MemeOpportunityLabel.LOW, composite_score=15),
        _record(MemeOpportunityLabel.LOW, composite_score=27),
    ]
    hist = composite_score_histogram(records)
    assert hist["10-19"] == 2
    assert hist["20-29"] == 1


# ---------------------------------------------------------------------------
# Import-boundary check - this phase must be structurally incapable of an LLM/image/Telegram call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", ["services/meme_shadow_analytics.py", "scripts/phase18_5_shadow_collection.py"])
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


def test_no_insert_update_delete_statements_in_collection_script() -> None:
    """Textual guard (in addition to the import-boundary check) - the collection script must
    never construct a write statement of any kind."""
    from pathlib import Path

    source = Path("scripts/phase18_5_shadow_collection.py").read_text(encoding="utf-8").lower()
    for forbidden in ("session.add(", "session.commit(", "insert(", "update(", "delete(", ".execute(text("):
        assert forbidden not in source, f"collection script must never contain {forbidden!r}"
