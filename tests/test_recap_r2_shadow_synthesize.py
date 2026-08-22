"""NINJA PULSE RECAP - R2 Shadow second canary test suite.

Covers: the Gateway wrapper's own model_copy(max_tokens/reasoning_effort) interception (in
isolation, no real routing/provider), the Human Review Protocol precondition/reprint, max_chars
flagging, causal-connective detection (flag-only, never a rewrite), evaluation_status mapping, the
readiness_state/publishable passthrough invariant, output-artifact structure, and every structural
safety guard (no --limit, no bot/worker/Gateway import at module level).

Reuses tests/test_event_recap.py's own established FakeLLMGateway/FakePromptRepository fixtures
and helpers directly (this codebase's own established cross-test-file reuse convention).

NO production DB beyond the shared `db_session` fixture (SAVEPOINT-rolled-back local test DB), NO
real LLM, NO real Gateway, NO network, NO writes anywhere in this file.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys as _sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, GenerateResponse, Message
from schemas.capability import CapabilityUsage
from scripts._recap_r2_shadow_synthesize import (
    MAX_CHARS,
    MAX_TOKENS,
    REASONING_EFFORT,
    ShadowSynthesisMetadata,
    ShadowSynthesisReport,
    _SingleAttemptGateway,
    _check_max_chars_note,
    _compute_synthesis_evaluation_status,
    _compute_synthesis_quality_notes,
    _detect_unevidenced_causal_claims,
    _print_human_review_protocol_reprint,
    _write_synthesis_report,
)
from scripts._recap_r2_10_readiness_candidate_scanner import CandidateScanRow
from services.event_recap import build_event_recap_candidate, synthesize_event_recap
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.test_event_recap import _PROMPT, _make_story, _prompt_repository, _runtime  # noqa: F401 (_PROMPT used transitively by _prompt_repository)

_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

_SCRIPT_PATH = Path("scripts/_recap_r2_shadow_synthesize.py")


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
# Gateway wrapper - the one piece of new logic beyond the base _SingleAttemptGateway pattern
# ---------------------------------------------------------------------------


class _FakeRoutingEngine:
    async def route(self, criteria: object, observability: object) -> list[str]:
        return ["fake-candidate"]


class _FakeFallbackPolicy:
    def __init__(self, response: GenerateResponse) -> None:
        self.received_requests: list[GenerateRequest] = []
        self._response = response

    async def dispatch(self, request: GenerateRequest, ranked_candidates: object, criteria: object, observability: object) -> GenerateResponse:
        self.received_requests.append(request)
        return self._response


@pytest.mark.asyncio
async def test_gateway_wrapper_applies_max_tokens_and_reasoning_effort() -> None:
    """The core cost-safety mechanism (contract section 4a) - proven in isolation, no real routing
    engine or provider involved, so this is fast and has zero network dependency."""
    fake_response = GenerateResponse(
        text=None, structured_output={"ok": True}, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=1, output_tokens=1),
    )
    fake_policy = _FakeFallbackPolicy(fake_response)
    gateway = _SingleAttemptGateway(
        routing_engine=_FakeRoutingEngine(), fallback_policy=fake_policy,
        max_tokens=MAX_TOKENS, reasoning_effort=REASONING_EFFORT,
    )
    original_request = GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])])
    assert original_request.max_tokens is None  # sanity: unbounded before the wrapper touches it

    response = await gateway.generate(original_request)

    assert len(fake_policy.received_requests) == 1
    forwarded = fake_policy.received_requests[0]
    assert forwarded.max_tokens == MAX_TOKENS
    assert forwarded.reasoning_effort == REASONING_EFFORT
    assert original_request.max_tokens is None, "the original request object must never be mutated (frozen pydantic model)"
    assert response.model_used == "fake-model-v1"
    assert gateway.last_model_used == "fake-model-v1"


# ---------------------------------------------------------------------------
# Human Review Protocol
# ---------------------------------------------------------------------------


def test_shadow_synthesize_requires_prior_shadow_run_output(tmp_path: Path) -> None:
    story_id = uuid4()
    result = subprocess.run(
        [_sys.executable, str(_SCRIPT_PATH), "--story-id", str(story_id), "--from-shadow-run", str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "No prior R2 Shadow v1 observation found" in result.stderr
    assert str(story_id) in result.stderr


def test_human_review_protocol_reprint_shows_key_fields(capsys: pytest.CaptureFixture[str]) -> None:
    prior_report = {
        "story_id": str(uuid4()), "title": "VK vs Apple",
        "candidate": {"readiness_state": "COOLING", "announcement_count": 3},
        "evaluation": {"evaluation_status": "NEEDS_REVIEW", "quality_notes": [
            "announcement_count reflects raw report-level clusters, not confirmed distinct developments",
        ]},
    }
    _print_human_review_protocol_reprint(prior_report)
    captured = capsys.readouterr()
    assert "evaluation_status=NEEDS_REVIEW" in captured.out
    assert "readiness_state=COOLING" in captured.out
    assert "announcement_count=3" in captured.out
    assert "raw report-level clusters" in captured.out
    assert "real, paid LLM call" in captured.out


def test_human_review_protocol_reprint_handles_rejected_prior_story(capsys: pytest.CaptureFixture[str]) -> None:
    prior_report = {
        "story_id": str(uuid4()), "title": "incoherent story", "candidate": None,
        "evaluation": {"evaluation_status": "REJECTED", "quality_notes": []},
    }
    _print_human_review_protocol_reprint(prior_report)
    captured = capsys.readouterr()
    assert "candidate=None" in captured.out
    assert "quality_notes: (none)" in captured.out


# ---------------------------------------------------------------------------
# max_chars (flag-only) and causal-connective detection (flag-only)
# ---------------------------------------------------------------------------


def test_max_chars_under_limit_returns_none() -> None:
    assert _check_max_chars_note("short text") is None


def test_max_chars_over_limit_returns_flag_note() -> None:
    long_text = "x" * (MAX_CHARS + 1)
    note = _check_max_chars_note(long_text)
    assert note is not None
    assert str(MAX_CHARS) in note
    assert "flag only" in note


def test_causal_connective_flagged_when_absent_from_evidence() -> None:
    flagged = _detect_unevidenced_causal_claims(
        "Marvell deal announced", "The stock rose because investors were optimistic.",
        [], [], evidence_bundle_text="Marvell and Google announced a chip deal.",
    )
    assert "because" in flagged


def test_causal_connective_not_flagged_when_present_in_evidence() -> None:
    flagged = _detect_unevidenced_causal_claims(
        "Marvell deal announced", "The stock rose because investors were optimistic.",
        [], [], evidence_bundle_text="Analysts said the stock rose because of investor optimism.",
    )
    assert "because" not in flagged


def test_causal_connective_detection_never_modifies_input_text() -> None:
    """Flag-only metadata (contract section 4c owner-confirmed scope) - this test exists purely to
    document/pin that the function returns flags only, never a modified string."""
    text = "The deal collapsed because regulators objected."
    result = _detect_unevidenced_causal_claims(text, "", [], [], evidence_bundle_text="")
    assert text == "The deal collapsed because regulators objected."  # untouched
    assert "because" in result


# ---------------------------------------------------------------------------
# evaluation_status mapping
# ---------------------------------------------------------------------------


def test_evaluation_status_rejected_when_row_rejected() -> None:
    row = _row(readiness_state="REJECTED")
    assert _compute_synthesis_evaluation_status(row, [], []) == "REJECTED"


def test_evaluation_status_needs_review_via_manual_review_flag() -> None:
    row = _row(readiness_state="COOLING", recommended_for_manual_review=True)
    assert _compute_synthesis_evaluation_status(row, [], []) == "NEEDS_REVIEW"


def test_evaluation_status_needs_review_via_quality_notes() -> None:
    row = _row(readiness_state="ACTIVE")
    assert _compute_synthesis_evaluation_status(row, ["some flag"], []) == "NEEDS_REVIEW"


def test_evaluation_status_needs_review_via_synthesized_quality_flags() -> None:
    """fact_verification_review / internal_vocabulary_leak_detected already reach here via
    EventRecapCandidate.quality_flags (unmodified) - proves they fall through the same rule."""
    row = _row(readiness_state="ACTIVE")
    assert _compute_synthesis_evaluation_status(row, [], ["fact_verification_review"]) == "NEEDS_REVIEW"


def test_evaluation_status_observed_when_clean() -> None:
    row = _row(readiness_state="ACTIVE")
    assert _compute_synthesis_evaluation_status(row, [], []) == "OBSERVED"


# ---------------------------------------------------------------------------
# DB-backed: real candidate + FakeLLMGateway synthesis + output structure + invariants
# ---------------------------------------------------------------------------


async def _candidate_for_synthesis(db_session: AsyncSession):
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    result = await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert result.candidate is not None
    return result.candidate


@pytest.mark.asyncio
async def test_readiness_state_and_publishable_carried_through_unchanged(db_session: AsyncSession) -> None:
    """Direct implementation-level proof of contract section 7a - even a fact-verification-flagged
    synthesis cannot change readiness_state or publishable."""
    candidate = await _candidate_for_synthesis(db_session)
    original_readiness_state = candidate.readiness_state
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["The dividend program is now confirmed to cost $999999999 in total."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    synthesized = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())
    assert synthesized.readiness_state == original_readiness_state
    assert synthesized.publishable is False
    assert synthesized.fact_verification.status != "pass"  # sanity: this fixture is meant to flag


@pytest.mark.asyncio
async def test_write_synthesis_report_produces_valid_json_and_txt(db_session: AsyncSession, tmp_path: Path) -> None:
    candidate = await _candidate_for_synthesis(db_session)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "recap_title": "Taiwan AI dividend approved",
            "recap_summary": "Taiwan approved a $314 AI dividend for every citizen.",
            "key_takeaways": ["Taiwan approved a $314 AI dividend for every citizen."],
            "uncertainty_notes": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    ))
    synthesized = await synthesize_event_recap(candidate, gateway, _prompt_repository(), runtime=_runtime())

    row = _row(readiness_state=synthesized.readiness_state, recommended_for_manual_review=False)
    report = ShadowSynthesisReport(
        story_id=candidate.story_id, title=candidate.story_title, candidate=synthesized,
        quality_notes=[], evaluation_status=_compute_synthesis_evaluation_status(row, [], synthesized.quality_flags),
        synthesis=ShadowSynthesisMetadata(
            physical_provider_attempts=1, fallback_attempts=0, same_candidate_retries=0,
            model_used="fake-model-v1", max_tokens_sent=MAX_TOKENS, reasoning_effort_sent=REASONING_EFFORT,
        ),
    )
    json_path, txt_path = _write_synthesis_report(tmp_path, report, "rendered preview text")

    assert json_path == tmp_path / f"story_{candidate.story_id}_synthesis.json"
    assert txt_path == tmp_path / f"story_{candidate.story_id}_synthesis.txt"
    assert json_path.exists()
    assert txt_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["story_id"] == str(candidate.story_id)
    assert payload["candidate"]["recap_title"] == "Taiwan AI dividend approved"
    assert payload["candidate"]["publishable"] is False
    assert payload["synthesis"]["max_tokens_sent"] == MAX_TOKENS
    assert payload["synthesis"]["reasoning_effort_sent"] == REASONING_EFFORT
    assert txt_path.read_text(encoding="utf-8") == "rendered preview text"


@pytest.mark.asyncio
async def test_write_synthesis_report_never_touches_base_shadow_v1_artifact(db_session: AsyncSession, tmp_path: Path) -> None:
    """A pre-existing R2 Shadow v1 story_<id>.json in the same directory must be byte-for-byte
    unchanged after the synthesis artifacts are written alongside it (contract section 7)."""
    candidate = await _candidate_for_synthesis(db_session)
    base_json_path = tmp_path / f"story_{candidate.story_id}.json"
    original_content = '{"story_id": "fake", "title": "original shadow v1 observation"}'
    base_json_path.write_text(original_content, encoding="utf-8")

    report = ShadowSynthesisReport(
        story_id=candidate.story_id, title=candidate.story_title, candidate=candidate,
        quality_notes=[], evaluation_status="OBSERVED",
        synthesis=ShadowSynthesisMetadata(
            physical_provider_attempts=1, fallback_attempts=0, same_candidate_retries=0,
            model_used="fake-model-v1", max_tokens_sent=MAX_TOKENS, reasoning_effort_sent=REASONING_EFFORT,
        ),
    )
    _write_synthesis_report(tmp_path, report, "preview")

    assert base_json_path.read_text(encoding="utf-8") == original_content


@pytest.mark.asyncio
async def test_compute_synthesis_quality_notes_flags_announcement_count_and_max_chars(db_session: AsyncSession) -> None:
    candidate = await _candidate_for_synthesis(db_session)
    assert candidate.announcement_count > 1  # Taiwan fixture's own two distinct-enough titles
    notes = _compute_synthesis_quality_notes(
        candidate, rendered_preview_text="x" * (MAX_CHARS + 1), evidence_bundle_text="",
        recap_title="t", recap_summary="s", key_takeaways=[], uncertainty_notes=[],
    )
    assert any("r2_11_announcement_identity_findings" in n for n in notes)
    assert any(str(MAX_CHARS) in n for n in notes)


@pytest.mark.asyncio
async def test_shadow_synthesize_deterministic_phase_makes_zero_db_writes(db_session: AsyncSession) -> None:
    story, _events = await _make_story(db_session, [
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
    ])
    session_new_before = set(db_session.new)
    session_dirty_before = set(db_session.dirty)
    await build_event_recap_candidate(db_session, story, force_shadow=True, now=_NOW)
    assert set(db_session.new) == session_new_before
    assert set(db_session.dirty) == session_dirty_before


# ---------------------------------------------------------------------------
# Structural safety checks
# ---------------------------------------------------------------------------


def test_shadow_synthesize_has_no_limit_argument() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    add_argument_flags: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument" and node.args
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
        ):
            add_argument_flags.add(node.args[0].value)
    assert "--limit" not in add_argument_flags
    assert add_argument_flags == {"--story-id", "--from-shadow-run", "--output-dir"}


def test_shadow_synthesize_has_no_bot_worker_or_gateway_import_at_module_level() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.add(node.module)
        elif isinstance(node, ast.Import):
            module_level_imports.update(alias.name for alias in node.names)
    for forbidden_prefix in ("bot", "worker", "integrations.llm_gateway"):
        assert not any(
            m == forbidden_prefix or m.startswith(forbidden_prefix + ".") for m in module_level_imports
        ), f"unexpected import with prefix {forbidden_prefix!r} in module_level_imports={module_level_imports}"


def test_shadow_synthesize_does_not_import_or_reference_event_recap_module_internals() -> None:
    """Contract section 4a / implementation plan: services/event_recap.py is not modified, and this
    script must not reach into its private (_-prefixed) internals - only the real, public, unmodified
    functions it already exports."""
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "services.event_recap":
            for alias in node.names:
                assert not alias.name.startswith("_"), f"imports a private event_recap symbol: {alias.name}"


def test_shadow_synthesize_cli_help_works() -> None:
    result = subprocess.run(
        [_sys.executable, str(_SCRIPT_PATH), "--help"], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "--story-id" in result.stdout
    assert "--from-shadow-run" in result.stdout
    assert "--output-dir" in result.stdout
