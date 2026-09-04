"""R2.10G3-C - shadow LLM eventness judge tests. Test matrix A-P per the phase's own spec.

None of these tests make a real Gateway call (no cost incurred on every `pytest` run) - the §20
hard cap of <=30 physical calls applies to the ONE real evaluation run
(`python scripts/_recap_r2_10_g3_eventness_llm_judge.py`), whose output artifacts this phase's own
report cites directly. Tests that need real Story evidence use
`scripts._recap_r2_10_g3_eventness_llm_judge.collect_all_evidence()` - the read-only DB pass only,
fully isolated from the Gateway (see that function's own docstring) - against the real local dev DB,
mirroring G3-A/G3-B's own established test-against-real-DB precedent."""
from __future__ import annotations

import ast
import inspect
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._recap_r2_10_g3_eventness_calibrate import RULE_COMBINED
from scripts._recap_r2_10_g3_eventness_llm_judge import (
    HARD_MIDDLE_FIXTURE_IDS,
    NEGATIVE_CONTROL_FIXTURE_IDS,
    POSITIVE_CONTROL_FIXTURE_IDS,
    PROMPT_NAME,
    PROMPT_VERSION,
    JudgeRecord,
    LLMJudgeOutputError,
    _offline_event_rows,
    build_evidence_bundle_text,
    build_target_set,
    cascade_simulation,
    collect_all_evidence,
    compute_metrics,
    evaluate_offline_fixture,
    ground_truth_eventness,
    parse_judge_output,
    run_llm_judge,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_JUDGE_PATH = _REPO_ROOT / "scripts" / "_recap_r2_10_g3_eventness_llm_judge.py"
_BASE_COMMIT = "76c46aeb9e561cfc560000d4785a2ad2bd7b7354"  # G3-B's own commit, this phase's base
_ALLOWED_PATH_PREFIXES = ("scripts/", "tests/", "docs/", "prompts/")
_FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def _make_record(**overrides: object) -> JudgeRecord:
    base = dict(
        fixture_id="x", group="HARD_MIDDLE", also_satisfies=None, manual_class="TOPIC_CLUSTER",
        desired_eventness="REJECT", ground_truth_eventness="REJECT", deterministic_rule_result="PASS_THROUGH",
        current_readiness_state=None, llm_opinion="REJECT", reason_codes=["TOPIC_COLLECTION"], confidence="MEDIUM",
        short_reason="test", recommendation_language_detected=False, is_correct=True, error_type=None,
        overconfident_wrong=False, prompt_version=PROMPT_VERSION, model_used="gpt-5.6-luna",
        input_tokens=100, output_tokens=50, physical_provider_attempts=1, parse_error=None, skipped_reason=None,
    )
    base.update(overrides)
    return JudgeRecord(**base)  # type: ignore[arg-type]


# --- A: no production code changed ------------------------------------------------------------------


def test_no_production_files_changed_since_base_commit() -> None:
    """Test A. Every path changed on this branch relative to G3-B's own commit must live under an
    allowed prefix (scripts/, tests/, docs/, prompts/) - never services/, worker/, database/,
    migrations/, bot/, or anything Docker/DATA/Telegram/publication-related. Compares the base
    commit against the WORKING TREE (not HEAD) so this test is meaningful both before and after
    this phase's own commit - `git diff <base>...HEAD` alone would see nothing until committed."""
    tracked = subprocess.run(
        ["git", "diff", "--name-only", _BASE_COMMIT],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    changed = sorted({p for p in (*tracked.stdout.splitlines(), *untracked.stdout.splitlines()) if p.strip()})
    assert changed, "expected at least one changed file on this branch"
    offending = [p for p in changed if not p.startswith(_ALLOWED_PATH_PREFIXES)]
    assert not offending, f"production/forbidden paths changed: {offending}"


# --- B: manual label absent from Gateway payload ------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_label_absent_from_gateway_payload() -> None:
    """Test B. For every target fixture, the built evidence bundle text never contains its own
    manual_class or desired_eventness value. (fixture_id is checked separately, per-fixture, in
    test M/test_vk_false_ready_mandatory_negative_ground_truth_and_no_leakage - not blanket-checked
    here, since several fixture_ids (e.g. "vlm") are also real content acronyms that legitimately
    appear in a Story's own title/keywords; a bare substring check on those would be a false
    positive, not an actual label leak.)"""
    targets = build_target_set()
    evidence = await collect_all_evidence(targets, now=_FIXED_NOW)
    checked = 0
    for target in targets:
        entry = target.entry
        _evaluation, text = evidence[entry.fixture_id]
        if not text:
            continue  # skipped (missing db row) - nothing to check
        assert entry.manual_class not in text, f"{entry.fixture_id}: manual_class leaked into payload"
        assert entry.desired_eventness not in text, f"{entry.fixture_id}: desired_eventness leaked into payload"
        checked += 1
    assert checked >= 15  # sanity: most of the 21 targets actually resolved in this DB


# --- C: one Story => at most one physical evaluation call ---------------------------------------------


def test_one_physical_call_per_target_fixture() -> None:
    """Test C. `run_llm_judge()`'s own source calls `_call(` exactly twice textually - once for the
    §22 prompt-freeze sanity fixture, once inside the per-target loop (so exactly one call per
    target at runtime, never a retry-on-disagreement loop)."""
    source = inspect.getsource(run_llm_judge)
    assert source.count("await _call(") == 2


def test_target_set_has_no_duplicate_fixtures_and_respects_hard_cap() -> None:
    targets = build_target_set()
    ids = [t.entry.fixture_id for t in targets]
    assert len(ids) == len(set(ids))
    assert len(targets) + 1 <= 30  # +1 prompt-freeze sanity call, §20


# --- D: strict output parser ---------------------------------------------------------------------------


def test_parse_judge_output_accepts_well_formed_output() -> None:
    opinion = parse_judge_output({
        "eventness_opinion": "REJECT", "reason_codes": ["TOPIC_COLLECTION"],
        "short_reason": "Shared research topic, not one event.", "confidence": "MEDIUM",
    })
    assert opinion.eventness_opinion == "REJECT"
    assert opinion.reason_codes == ["TOPIC_COLLECTION"]


@pytest.mark.parametrize("bad_output", [
    None,
    {},
    {"eventness_opinion": "MAYBE", "reason_codes": ["OTHER"], "short_reason": "x", "confidence": "LOW"},
    {"eventness_opinion": "ACCEPT", "reason_codes": [], "short_reason": "x", "confidence": "LOW"},
    {"eventness_opinion": "ACCEPT", "reason_codes": ["OTHER"], "short_reason": "", "confidence": "LOW"},
    {"eventness_opinion": "ACCEPT", "reason_codes": ["OTHER"], "short_reason": "x", "confidence": "SUPER_SURE"},
])
def test_parse_judge_output_rejects_malformed_output(bad_output: dict | None) -> None:
    """Test D."""
    with pytest.raises(LLMJudgeOutputError):
        parse_judge_output(bad_output)


# --- E: unknown reason code rejected -------------------------------------------------------------------


def test_unknown_reason_code_rejected() -> None:
    """Test E."""
    with pytest.raises(LLMJudgeOutputError):
        parse_judge_output({
            "eventness_opinion": "REJECT", "reason_codes": ["MADE_UP_CODE"],
            "short_reason": "x", "confidence": "LOW",
        })


# --- F: PASS_THROUGH != ACCEPT -------------------------------------------------------------------------


def test_deterministic_combined_rule_never_returns_accept() -> None:
    """Test F."""
    source = inspect.getsource(RULE_COMBINED.fn)
    assert '"ACCEPT"' not in source and "'ACCEPT'" not in source


# --- G: deterministic REJECT cannot be overridden in cascade simulation ---------------------------------


def test_cascade_never_lets_llm_override_a_deterministic_reject() -> None:
    """Test G. §29 - a fixture the deterministic layer already REJECTed must never appear in
    `hard_middle_sent_to_llm` or `additional_negatives_caught_by_llm`, even if the LLM's own
    opinion (sent for diagnostic purposes only) was ACCEPT."""
    records = [
        _make_record(
            fixture_id="already_rejected_by_rule", ground_truth_eventness="REJECT",
            deterministic_rule_result="REJECT", llm_opinion="ACCEPT", is_correct=False,
            error_type="ACCEPT_ON_MANUAL_NEGATIVE",
        ),
    ]
    cascade = cascade_simulation(records)
    assert cascade["deterministic_negatives_filtered_ids"] == ["already_rejected_by_rule"]
    assert "already_rejected_by_rule" not in cascade["hard_middle_sent_to_llm_ids"]  # type: ignore[operator]
    assert "already_rejected_by_rule" not in cascade["additional_negatives_caught_by_llm_ids"]  # type: ignore[operator]


# --- H: LLM path cannot write DB -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_path_cannot_write_db() -> None:
    """Test H. `collect_all_evidence()` is the exact code path `run_llm_judge()` uses before it
    ever imports the Gateway - proving this path never mutates the DB proves the LLM path (which
    runs strictly after it) starts from, and can only add to, an unmodified database."""
    from sqlalchemy import func, select

    from database.models.editorial_task import EditorialTask
    from database.models.story import Story
    from database.session import async_session_factory

    async with async_session_factory() as s:
        stories_before = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
        tasks_before = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()

    await collect_all_evidence(build_target_set(), now=_FIXED_NOW)

    async with async_session_factory() as s:
        stories_after = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
        tasks_after = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()

    assert stories_before == stories_after
    assert tasks_before == tasks_after


# --- I: LLM path cannot send Telegram --------------------------------------------------------------------


def test_no_telegram_import_anywhere_in_module() -> None:
    """Test I."""
    tree = ast.parse(_JUDGE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not any("telegram" in m.lower() or m.startswith("bot.") or m == "bot" for m in modules), modules


# --- J: LLM path cannot publish --------------------------------------------------------------------------


def test_no_publication_related_import_anywhere_in_module() -> None:
    """Test J. This module never even imports services.event_recap (the module that owns
    publishable/synthesize_event_recap) - it builds its own bounded GenerateRequest directly."""
    tree = ast.parse(_JUDGE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert "services.event_recap" not in modules
    assert not any("publish" in m.lower() for m in modules), modules


def test_module_never_calls_session_commit_or_add() -> None:
    source = _JUDGE_PATH.read_text(encoding="utf-8")
    assert ".commit(" not in source
    assert "session.add(" not in source


# --- K/L/M: mandatory fixtures represented correctly, without label leakage -----------------------------


def test_vla_mandatory_negative_in_target_set() -> None:
    """Test K."""
    assert "vla" in NEGATIVE_CONTROL_FIXTURE_IDS
    targets = build_target_set()
    vla = next(t for t in targets if t.entry.fixture_id == "vla")
    assert vla.entry.manual_class == "TOPIC_CLUSTER"
    assert ground_truth_eventness(vla.entry) == "REJECT"


@pytest.mark.asyncio
async def test_nvidia_hf_positive_fixture_no_label_leakage() -> None:
    """Test L."""
    assert "nvidia_hf_main" in POSITIVE_CONTROL_FIXTURE_IDS
    targets = build_target_set()
    target = next(t for t in targets if t.entry.fixture_id == "nvidia_hf_main")
    assert ground_truth_eventness(target.entry) == "ACCEPT"
    evidence = await collect_all_evidence((target,), now=_FIXED_NOW)
    _evaluation, text = evidence["nvidia_hf_main"]
    assert "EVENT_LIFECYCLE" not in text
    assert "ACCEPT" not in text
    assert "nvidia_hf_main" not in text


def test_vk_false_ready_mandatory_negative_ground_truth_and_no_leakage() -> None:
    """Test M. Offline fixture - no DB round trip needed to build its evidence text."""
    assert "vk_apple_synthetic_4publisher_false_ready" in NEGATIVE_CONTROL_FIXTURE_IDS
    targets = build_target_set()
    target = next(t for t in targets if t.entry.fixture_id == "vk_apple_synthetic_4publisher_false_ready")
    assert ground_truth_eventness(target.entry) == "REJECT"
    evaluation = evaluate_offline_fixture(target.entry, now=_FIXED_NOW)
    assert evaluation.features is not None
    text = build_evidence_bundle_text(target.entry, _offline_event_rows(target.entry), evaluation.features)
    assert "REJECT" not in text
    assert "mandatory negative control" not in text.lower()
    assert "false_ready" not in text.lower()
    assert target.entry.fixture_id not in text


# --- N: Marvell UNCLEAR scoring semantics -------------------------------------------------------------


def test_marvell_ground_truth_is_uncertain_and_excluded_from_binary_scoring() -> None:
    """Test N."""
    targets = build_target_set()
    marvell = next(t for t in targets if t.entry.fixture_id == "marvell_google")
    assert marvell.entry.manual_class == "UNCLEAR"
    assert ground_truth_eventness(marvell.entry) == "UNCERTAIN"

    correct_record = _make_record(
        fixture_id="marvell_google", ground_truth_eventness="UNCERTAIN", llm_opinion="UNCERTAIN",
        is_correct=None, error_type=None,
    )
    metrics = compute_metrics([correct_record])
    assert metrics["scored_count"] == 0
    assert "marvell_google" in metrics["correct_uncertain_ids"]  # type: ignore[operator]

    overclaim_record = _make_record(
        fixture_id="marvell_google", ground_truth_eventness="UNCERTAIN", llm_opinion="ACCEPT",
        is_correct=None, error_type=None,
    )
    overclaim_metrics = compute_metrics([overclaim_record])
    assert "marvell_google" in overclaim_metrics["ambiguous_control_overclaim_ids"]  # type: ignore[operator]


# --- O: metrics correct -------------------------------------------------------------------------------


def test_compute_metrics_false_accept_and_false_reject_counted_correctly() -> None:
    """Test O."""
    records = [
        _make_record(fixture_id="neg1", group="HARD_MIDDLE", ground_truth_eventness="REJECT", llm_opinion="ACCEPT", is_correct=False, error_type="ACCEPT_ON_MANUAL_NEGATIVE"),
        _make_record(fixture_id="pos1", group="POSITIVE_CONTROL", ground_truth_eventness="ACCEPT", llm_opinion="REJECT", is_correct=False, error_type="REJECT_ON_MANUAL_POSITIVE"),
        _make_record(fixture_id="pos2", group="POSITIVE_CONTROL", ground_truth_eventness="ACCEPT", llm_opinion="ACCEPT", is_correct=True, error_type=None),
        _make_record(fixture_id="neg2", group="NEGATIVE_CONTROL", ground_truth_eventness="REJECT", llm_opinion="REJECT", is_correct=True, error_type=None),
    ]
    metrics = compute_metrics(records)
    assert metrics["scored_count"] == 4
    assert metrics["false_accept_ids_overall"] == ["neg1"]
    assert metrics["false_reject_ids_overall"] == ["pos1"]
    assert metrics["correct_accepts"] == 1
    assert metrics["correct_rejects"] == 1
    assert metrics["positive_control_false_rejects"] == ["pos1"]
    assert metrics["negative_control_false_accepts"] == []  # neg1 is HARD_MIDDLE, not NEGATIVE_CONTROL


def test_compute_metrics_skipped_and_parse_error_excluded_from_scoring() -> None:
    records = [
        _make_record(fixture_id="missing", skipped_reason="story_id not found in this database", is_correct=None, error_type="SKIPPED_MISSING_STORY"),
        _make_record(fixture_id="unparseable", is_correct=None, error_type="PARSE_ERROR", llm_opinion=None),
    ]
    metrics = compute_metrics(records)
    assert metrics["scored_count"] == 0
    assert metrics["skipped_count"] == 1
    assert metrics["parse_error_count"] == 1


# --- P: prompt version/hash stored in artifact --------------------------------------------------------


def test_prompt_version_resolves_and_matches_module_constant() -> None:
    """Test P."""
    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(_REPO_ROOT / "prompts")
    prompt = repo.resolve(PROMPT_NAME, PROMPT_VERSION)
    assert prompt.name == PROMPT_NAME
    assert prompt.version == PROMPT_VERSION
    assert prompt.output_schema["required"] == ["eventness_opinion", "reason_codes", "short_reason", "confidence"]


def test_every_record_field_carries_prompt_version() -> None:
    record = _make_record()
    assert record.prompt_version == PROMPT_VERSION


# --- structural: fixed target set matches G3-B's own §8 hard-middle list exactly ------------------------


def test_hard_middle_fixture_ids_match_g3b_report_exactly() -> None:
    expected = {
        "vlm", "vk_apple_real_3publisher", "marvell_google", "new_york_times_digest",
        "optimizatsiya_koda", "llm_agents_cluster", "robotic_welding_cluster",
        "multimodal_medical_cluster", "object_detection_cluster", "us_futures_wire_noise",
        "holdout_when_predictor_cluster",
    }
    assert set(HARD_MIDDLE_FIXTURE_IDS) == expected
    assert len(HARD_MIDDLE_FIXTURE_IDS) == 11
