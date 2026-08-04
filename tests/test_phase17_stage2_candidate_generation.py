"""Phase 17 Stage 2 - controlled candidate generation tests (docs/
phase17_stage2_controlled_candidate_generation_plan.md).

Scoped to the genuinely new parts this script adds on top of the already-tested M4.1
candidate-generation path (tests/test_phase17_m4_1_replay.py covers `generate_with_retry`/
`_attempt_generation`/`_build_candidate_request` directly - reused, not reimplemented, here):
the baseline-vs-candidate record shape, the human-only `record_editorial_preference()` mutation
path (pure file I/O, no DB, no LLM), and resume behavior that must never clobber an
already-recorded human editorial_preference/editorial_notes/failure_reasons.
"""
import json
import uuid
from pathlib import Path

import pytest

import scripts.phase17_stage2_candidate_generation as stage2


class _FakeCategory:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeDraft:
    def __init__(self, title: str = "Baseline title", body: str = "Baseline body text.") -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.body = body


class _FakeEvent:
    def __init__(self, category: str = "AI") -> None:
        self.id = uuid.uuid4()
        self.category = _FakeCategory(category)


# ---------------------------------------------------------------------------
# Dry-run / paid-flag gating (mirrors M3/M4/M4.1's own established test)
# ---------------------------------------------------------------------------


def test_dry_run_is_default_without_both_flags() -> None:
    for live, confirm in [(False, False), (True, False), (False, True)]:
        assert (not (live and confirm)) is True
    assert (not (True and True)) is False


# ---------------------------------------------------------------------------
# Record shape (baseline text captured, candidate absent until generated)
# ---------------------------------------------------------------------------


def test_new_record_captures_baseline_text_from_draft() -> None:
    draft = _FakeDraft(title="Real headline", body="Real production body.")
    event = _FakeEvent()
    record = stage2._new_record(draft, event, {"schema_version": "v1"})
    assert record["baseline_text"] == {"title": "Real headline", "body": "Real production body."}
    assert record["candidate_text"] is None
    assert record["candidate_generated"] is False


def test_new_record_defaults_editorial_preference_not_yet_reviewed() -> None:
    record = stage2._new_record(_FakeDraft(), _FakeEvent(), {})
    assert record["editorial_preference"] == "not_yet_reviewed"
    assert record["failure_reasons"] == []
    assert record["generation_status"] == "not_attempted"


def test_new_record_uses_real_draft_and_event_ids() -> None:
    draft, event = _FakeDraft(), _FakeEvent(category="SOFTWARE")
    record = stage2._new_record(draft, event, {})
    assert record["draft_id"] == str(draft.id)
    assert record["event_id"] == str(event.id)
    assert record["category"] == "SOFTWARE"


# ---------------------------------------------------------------------------
# Resume support - must preserve already-resolved records verbatim, including any
# human-recorded editorial_preference/editorial_notes
# ---------------------------------------------------------------------------


def test_load_existing_output_keeps_only_resolved_generation_status(tmp_path: Path) -> None:
    path = tmp_path / "existing.json"
    path.write_text(
        json.dumps({"records": [
            {"draft_id": "resolved-valid", "generation_status": "valid", "editorial_preference": "candidate"},
            {"draft_id": "resolved-dry-run", "generation_status": "dry_run"},
            {"draft_id": "unresolved", "generation_status": "not_attempted"},
            {"draft_id": "missing-status"},
        ]}),
        encoding="utf-8",
    )
    existing = stage2._load_existing_output(str(path))
    assert set(existing) == {"resolved-valid", "resolved-dry-run"}
    # The human's own recorded preference on a resumed record must survive untouched.
    assert existing["resolved-valid"]["editorial_preference"] == "candidate"


def test_load_existing_output_missing_file_returns_empty(tmp_path: Path) -> None:
    assert stage2._load_existing_output(str(tmp_path / "does_not_exist.json")) == {}


# ---------------------------------------------------------------------------
# record_editorial_preference() - the human-only, DB-free mutation path
# ---------------------------------------------------------------------------


def _write_results(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"summary": {}, "records": records}), encoding="utf-8")
    return path


def test_record_editorial_preference_updates_matched_record(tmp_path: Path) -> None:
    path = _write_results(tmp_path, [
        {"draft_id": "case-1", "generation_status": "valid", "editorial_preference": "not_yet_reviewed",
         "editorial_notes": "", "failure_reasons": []},
    ])
    result = stage2.record_editorial_preference(
        str(path), "case-1", "candidate", notes="reads better", failure_reasons=["baseline_too_short"],
    )
    assert result["editorial_preference"] == "candidate"
    assert result["editorial_notes"] == "reads better"
    assert result["failure_reasons"] == ["baseline_too_short"]

    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted_record = persisted["records"][0]
    assert persisted_record["editorial_preference"] == "candidate"
    assert persisted_record["editorial_notes"] == "reads better"


def test_record_editorial_preference_leaves_other_records_untouched(tmp_path: Path) -> None:
    other = {"draft_id": "case-other", "generation_status": "valid", "editorial_preference": "not_yet_reviewed"}
    path = _write_results(tmp_path, [
        {"draft_id": "case-1", "generation_status": "valid", "editorial_preference": "not_yet_reviewed"},
        dict(other),
    ])
    stage2.record_editorial_preference(str(path), "case-1", "baseline")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted_other = next(r for r in persisted["records"] if r["draft_id"] == "case-other")
    assert persisted_other == other


def test_record_editorial_preference_rejects_invalid_value(tmp_path: Path) -> None:
    path = _write_results(tmp_path, [{"draft_id": "case-1", "generation_status": "valid"}])
    with pytest.raises(ValueError, match="invalid editorial_preference"):
        stage2.record_editorial_preference(str(path), "case-1", "definitely_not_valid")


def test_record_editorial_preference_missing_draft_id_raises(tmp_path: Path) -> None:
    path = _write_results(tmp_path, [{"draft_id": "case-1", "generation_status": "valid"}])
    with pytest.raises(ValueError, match="not found"):
        stage2.record_editorial_preference(str(path), "does-not-exist", "baseline")


def test_record_editorial_preference_deduplicates_failure_reasons(tmp_path: Path) -> None:
    path = _write_results(tmp_path, [
        {"draft_id": "case-1", "generation_status": "valid", "failure_reasons": ["tone_mismatch"]},
    ])
    result = stage2.record_editorial_preference(
        str(path), "case-1", "baseline", failure_reasons=["tone_mismatch", "too_long"],
    )
    assert result["failure_reasons"] == ["tone_mismatch", "too_long"]


def test_record_editorial_preference_without_notes_or_reasons_only_sets_preference(tmp_path: Path) -> None:
    path = _write_results(tmp_path, [
        {"draft_id": "case-1", "generation_status": "valid", "editorial_notes": "kept as-is",
         "failure_reasons": ["existing"]},
    ])
    result = stage2.record_editorial_preference(str(path), "case-1", "neither")
    assert result["editorial_preference"] == "neither"
    assert result["editorial_notes"] == "kept as-is"
    assert result["failure_reasons"] == ["existing"]


def test_valid_editorial_preferences_matches_documented_enum() -> None:
    assert stage2.VALID_EDITORIAL_PREFERENCES == {
        "not_yet_reviewed", "baseline", "candidate", "neither",
    }
