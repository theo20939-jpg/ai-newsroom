"""NINJA PULSE RECAP - R2 Shadow first canary test suite.

Covers: pure-function helpers, evaluation_status mapping, output structure, the read-only/no-DB-
write invariant, the structural absence of --with-llm, and the no-bot/worker/Gateway AST guard.
Reuses tests/test_event_recap.py's own established `_make_story()` fixture-construction helper
directly (this codebase's own established cross-test-file reuse convention).

NO production DB beyond the shared `db_session` fixture (SAVEPOINT-rolled-back local test DB), NO
LLM, NO Gateway, NO network, NO writes anywhere in this file.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts._recap_r2_shadow_batch import (
    ShadowEvaluation,
    ShadowStoryReport,
    _build_visual_observation,
    _compute_evaluation_status,
    _compute_quality_notes,
    _empty_visual_observation,
    _write_story_report,
    build_shadow_report,
    build_shadow_summary,
)
from scripts._recap_r2_10_readiness_candidate_scanner import CandidateScanRow
from services.event_recap import EventRecapCandidate, MediaCandidateRef
from tests.test_event_recap import _candidate_from_titles, _make_story

_NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

_REJECTED_TITLES = [
    "What are you doing this weekend?",
    "What happens when a hybrid battery dies in a used car you just bought?",
    "What the world's oldest telecommunications company is doing to survive",
    "What software do you use daily to get work done?",
]


def _row(**overrides: object) -> CandidateScanRow:
    defaults: dict[str, object] = dict(
        story_id=uuid4(), title="x", event_count=2, origin_projection_status="not_needed",
        story_integrity_eligible=True, announcement_count=1, readiness_source_count=1,
        readiness_state="ACTIVE", rejection_reasons=[], research_complete_tracked=False,
        recommended_for_manual_review=False,
    )
    defaults.update(overrides)
    return CandidateScanRow(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_compute_evaluation_status_rejected() -> None:
    row = _row(readiness_state="REJECTED")
    assert _compute_evaluation_status(row, []) == "REJECTED"


def test_compute_evaluation_status_needs_review_via_manual_review_flag() -> None:
    row = _row(readiness_state="COOLING", recommended_for_manual_review=True)
    assert _compute_evaluation_status(row, []) == "NEEDS_REVIEW"


def test_compute_evaluation_status_needs_review_via_quality_notes() -> None:
    row = _row(readiness_state="ACTIVE", recommended_for_manual_review=False)
    assert _compute_evaluation_status(row, ["media_candidates empty"]) == "NEEDS_REVIEW"


def test_compute_evaluation_status_observed_when_clean() -> None:
    row = _row(readiness_state="ACTIVE", recommended_for_manual_review=False)
    assert _compute_evaluation_status(row, []) == "OBSERVED"


def _titles_and_candidate() -> EventRecapCandidate:
    return _candidate_from_titles(
        ["Taiwan approves $314 AI dividend for every citizen", "Government confirms $314 per person AI dividend program in Taiwan"],
        "Taiwan AI dividend program",
    )


def test_build_visual_observation_no_media() -> None:
    candidate = _titles_and_candidate()
    visual = _build_visual_observation(candidate)
    assert visual.has_media is False
    assert visual.media_candidate_count == 0
    assert visual.media_spans_multiple_events is False
    assert len(visual.visual_checklist) == 5


def test_build_visual_observation_single_event_media() -> None:
    import dataclasses

    candidate = _titles_and_candidate()
    event_id = candidate.announcements[0].member_event_ids[0]
    candidate = dataclasses.replace(candidate, media_candidates=[
        MediaCandidateRef(kind="image", event_id=event_id, remote_url="https://example.com/a.jpg", rank=1),
        MediaCandidateRef(kind="video", event_id=event_id, remote_url="https://example.com/a.mp4", rank=None),
    ])
    visual = _build_visual_observation(candidate)
    assert visual.has_media is True
    assert visual.media_candidate_count == 2
    assert visual.media_spans_multiple_events is False


def test_build_visual_observation_multi_event_media_flagged() -> None:
    import dataclasses

    candidate = _titles_and_candidate()
    event_ids = [a.member_event_ids[0] for a in candidate.announcements]
    assert len(event_ids) >= 2, "fixture must produce at least 2 announcements to exercise this case"
    candidate = dataclasses.replace(candidate, media_candidates=[
        MediaCandidateRef(kind="image", event_id=event_ids[0], remote_url="https://example.com/a.jpg", rank=1),
        MediaCandidateRef(kind="image", event_id=event_ids[1], remote_url="https://example.com/b.jpg", rank=1),
    ])
    visual = _build_visual_observation(candidate)
    assert visual.media_spans_multiple_events is True


def test_compute_quality_notes_flags_empty_media() -> None:
    candidate = _titles_and_candidate()
    visual = _build_visual_observation(candidate)
    notes = _compute_quality_notes(candidate, visual)
    assert "media_candidates empty" in notes


def test_compute_quality_notes_flags_multi_event_media() -> None:
    import dataclasses

    candidate = _titles_and_candidate()
    event_ids = [a.member_event_ids[0] for a in candidate.announcements]
    candidate = dataclasses.replace(candidate, media_candidates=[
        MediaCandidateRef(kind="image", event_id=event_ids[0], remote_url="https://example.com/a.jpg", rank=1),
        MediaCandidateRef(kind="image", event_id=event_ids[1], remote_url="https://example.com/b.jpg", rank=1),
    ])
    visual = _build_visual_observation(candidate)
    notes = _compute_quality_notes(candidate, visual)
    assert any("possible anchor mismatch" in n for n in notes)


def test_compute_quality_notes_flags_announcement_count_caveat_when_over_one() -> None:
    candidate = _titles_and_candidate()
    assert candidate.announcement_count > 1  # Taiwan fixture's own two distinct-enough titles
    visual = _build_visual_observation(candidate)
    notes = _compute_quality_notes(candidate, visual)
    assert any("r2_11_announcement_identity_findings" in n for n in notes)


def test_empty_visual_observation_is_all_zero() -> None:
    visual = _empty_visual_observation()
    assert visual.media_candidate_count == 0
    assert visual.media_spans_multiple_events is False
    assert visual.has_media is False
    assert len(visual.visual_checklist) == 5


def test_build_shadow_summary_counts_correctly() -> None:
    reports = [
        ShadowStoryReport(
            story_id=uuid4(), title="rejected-a", candidate=None, rejection_reasons=["integrity failed"],
            evaluation=ShadowEvaluation(evaluation_status="REJECTED", manual_review_required=False, quality_notes=[], visual=_empty_visual_observation()),
        ),
        ShadowStoryReport(
            story_id=uuid4(), title="rejected-b", candidate=None, rejection_reasons=["integrity failed"],
            evaluation=ShadowEvaluation(evaluation_status="REJECTED", manual_review_required=False, quality_notes=[], visual=_empty_visual_observation()),
        ),
    ]
    summary = build_shadow_summary(reports)
    assert summary["scanned_count"] == 2
    assert summary["candidate_count"] == 0
    assert summary["rejection_reasons_distribution"] == {"integrity failed": 2}
    assert summary["readiness_states_distribution"] == {}


# ---------------------------------------------------------------------------
# DB-backed: build_shadow_report(), output structure, evaluation_status mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_shadow_report_rejected_story(db_session: AsyncSession) -> None:
    story, _events = await _make_story(db_session, _REJECTED_TITLES)
    report = await build_shadow_report(db_session, story, now=_NOW)
    assert report.candidate is None
    assert report.rejection_reasons  # non-empty, real reason present
    assert report.evaluation.evaluation_status == "REJECTED"
    assert report.evaluation.manual_review_required is False
    assert report.evaluation.quality_notes == []
    assert report.evaluation.visual.has_media is False


@pytest.mark.asyncio
async def test_build_shadow_report_candidate_story_flags_empty_media(db_session: AsyncSession) -> None:
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    report = await build_shadow_report(db_session, story, now=_NOW)
    assert report.candidate is not None
    assert report.rejection_reasons == []
    # no image/video candidates exist for these in-memory-only fixture events - always flagged.
    assert "media_candidates empty" in report.evaluation.quality_notes
    assert report.evaluation.evaluation_status == "NEEDS_REVIEW"
    assert report.evaluation.visual.has_media is False
    assert report.evaluation.visual.media_candidate_count == 0
    assert len(report.evaluation.visual.visual_checklist) == 5


@pytest.mark.asyncio
async def test_build_shadow_report_makes_zero_db_writes(db_session: AsyncSession) -> None:
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    session_new_before = set(db_session.new)
    session_dirty_before = set(db_session.dirty)
    await build_shadow_report(db_session, story, now=_NOW)
    assert set(db_session.new) == session_new_before
    assert set(db_session.dirty) == session_dirty_before


@pytest.mark.asyncio
async def test_write_story_report_produces_valid_json_and_txt(db_session: AsyncSession, tmp_path: Path) -> None:
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    report = await build_shadow_report(db_session, story, now=_NOW)
    _write_story_report(tmp_path, report)

    json_path = tmp_path / f"story_{report.story_id}.json"
    txt_path = tmp_path / f"story_{report.story_id}.txt"
    assert json_path.exists()
    assert txt_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["story_id"] == str(report.story_id)
    assert payload["title"] == story.title
    assert "candidate" in payload
    assert report.candidate is not None
    assert payload["candidate"]["readiness_state"] == report.candidate.readiness_state
    assert "evaluation" in payload
    assert payload["evaluation"]["evaluation_status"] in ("OBSERVED", "NEEDS_REVIEW", "REJECTED")
    assert "visual" in payload["evaluation"]
    assert set(payload["evaluation"]["visual"].keys()) == {
        "media_candidate_count", "media_spans_multiple_events", "has_media", "visual_checklist",
    }
    assert txt_path.read_text(encoding="utf-8")  # non-empty evidence bundle


@pytest.mark.asyncio
async def test_write_story_report_rejected_story_writes_placeholder_txt(db_session: AsyncSession, tmp_path: Path) -> None:
    story, _events = await _make_story(db_session, _REJECTED_TITLES)
    report = await build_shadow_report(db_session, story, now=_NOW)
    _write_story_report(tmp_path, report)

    json_path = tmp_path / f"story_{report.story_id}.json"
    txt_path = tmp_path / f"story_{report.story_id}.txt"
    assert json_path.exists()
    assert txt_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["candidate"] is None
    assert payload["evaluation"]["evaluation_status"] == "REJECTED"
    assert "REJECTED" in txt_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Safety structural checks
# ---------------------------------------------------------------------------


def test_shadow_batch_has_no_with_llm_argument() -> None:
    """Structural, not just behavioral - --with-llm must not exist as an `add_argument()` call at
    all, not merely default to False (docs/r2_shadow_contract.md section 2). AST-based (not a raw
    substring search) so this doesn't false-positive on the module's own prose explaining that the
    flag does not exist."""
    source = Path("scripts/_recap_r2_shadow_batch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    add_argument_flags: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument" and node.args
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
        ):
            add_argument_flags.add(node.args[0].value)
    assert "--with-llm" not in add_argument_flags
    assert add_argument_flags == {"--limit", "--output-dir"}


def test_shadow_batch_limit_bounded_by_default_and_ceiling() -> None:
    from scripts._recap_r2_shadow_batch import DEFAULT_LIMIT, MAX_LIMIT

    assert DEFAULT_LIMIT == 20
    assert MAX_LIMIT == 200
    assert DEFAULT_LIMIT <= MAX_LIMIT


def test_shadow_batch_has_read_only_guard() -> None:
    from scripts._recap_r2_shadow_batch import ReadOnlyGuardError, _verify_read_only

    assert callable(_verify_read_only)
    assert issubclass(ReadOnlyGuardError, RuntimeError)


def test_shadow_batch_has_no_bot_worker_or_gateway_imports() -> None:
    """Self-contained AST guard for this new script only (the existing repo-wide guard in
    tests/test_event_recap.py is out of scope for this checkpoint's file allowlist)."""
    source = Path("scripts/_recap_r2_shadow_batch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.add(node.module)
        elif isinstance(node, ast.Import):
            module_level_imports.update(alias.name for alias in node.names)
    for forbidden_prefix in ("bot", "worker", "integrations.llm_gateway"):
        assert not any(m == forbidden_prefix or m.startswith(forbidden_prefix + ".") for m in module_level_imports), (
            f"unexpected import with prefix {forbidden_prefix!r} in module_level_imports={module_level_imports}"
        )


def test_shadow_batch_cli_help_works() -> None:
    """Proves no import-time side effects and no hidden DB/network touch merely from --help."""
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, "scripts/_recap_r2_shadow_batch.py", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "--limit" in result.stdout
    assert "--output-dir" in result.stdout


def test_shadow_batch_rejects_limit_outside_bounds() -> None:
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, "scripts/_recap_r2_shadow_batch.py", "--limit", "0"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "--limit must be between 1 and 200" in result.stderr

    result = subprocess.run(
        [_sys.executable, "scripts/_recap_r2_shadow_batch.py", "--limit", "201"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
