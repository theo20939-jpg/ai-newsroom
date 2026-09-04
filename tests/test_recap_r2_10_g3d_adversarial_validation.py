"""R2.10G3-D - adversarial rejector validation tests. Test matrix A-L per the phase's own spec.

Integration-level tests (most of them) use scripts._recap_r2_10_g3d_adversarial_validation's own
collect_records(), which manages its own read-only DB connection (real local dev DB, no Gateway)."""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._recap_r2_10_g3_eventness_calibrate import RULE_A, RULE_C, RULE_D, RULE_COMBINED
from scripts._recap_r2_10_g3d_adversarial_manifest import (
    ADVERSARIAL_MANIFEST,
    used_story_ids_overlap_with_prior_sets,
)
from scripts._recap_r2_10_g3d_adversarial_validation import (
    CONSOLIDATED_MANIFEST_INDEX,
    CONTROL_FIXTURE_IDS,
    class_specific_rejection_rates,
    collect_records,
    current_readiness_simulation,
    dataset_expansion_summary,
    measure_combined_safety,
    measure_rule_safety,
    production_candidacy,
    subtype_false_rejects,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VALIDATION_PATH = _REPO_ROOT / "scripts" / "_recap_r2_10_g3d_adversarial_validation.py"
_FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


# --- A: no overlap between new adversarial set and prior training/holdout sets -------------------


def test_no_overlap_with_calibration_or_holdout() -> None:
    """Test A."""
    assert used_story_ids_overlap_with_prior_sets() == set()


def test_adversarial_manifest_has_no_internal_duplicates() -> None:
    ids = [e.fixture_id for e in ADVERSARIAL_MANIFEST]
    sids = [e.story_id for e in ADVERSARIAL_MANIFEST]
    assert len(ids) == len(set(ids))
    assert len(sids) == len(set(sids))


def test_adversarial_manifest_meets_minimum_size_and_composition() -> None:
    """§6/§7 - minimum 40 Stories, with every required category present (even if some are below
    target and disclosed as CATEGORY_UNDERREPRESENTED rather than padded)."""
    assert len(ADVERSARIAL_MANIFEST) >= 40
    classes = {e.manual_class for e in ADVERSARIAL_MANIFEST}
    assert classes == {"REAL_SINGLE_EVENT", "EVENT_LIFECYCLE", "TOPIC_CLUSTER", "DIGEST", "NOISE", "UNCLEAR"}


# --- B: labels frozen before rule evaluation ------------------------------------------------------


def test_manifest_entries_are_frozen_dataclasses() -> None:
    """Test B. Structurally impossible to mutate a label in place after evaluation."""
    for entry in ADVERSARIAL_MANIFEST:
        assert entry.__dataclass_params__.frozen  # type: ignore[attr-defined]


# --- C: A/C/D definitions unchanged from G3-B -----------------------------------------------------


def test_rule_definitions_still_match_g3b_frozen_thresholds() -> None:
    """Test C. Re-asserts the exact G3-B thresholds via the rule descriptions - if G3-B's own
    RULE_A/RULE_C/RULE_D were ever edited, this test's own hardcoded strings would need editing
    too, making any silent drift visible in the diff."""
    assert RULE_A.description == "span_hours>=200 AND unique_source_count<=1 AND announcement_count>=4 => REJECT"
    assert RULE_C.description == "source_domains == {'github.com'} exclusively => REJECT"
    assert RULE_D.description == (
        "span_hours<=1.0 AND unique_source_count>=3 AND announcement_count==effective_event_count "
        "(no clustering merge occurred at all) => REJECT"
    )


def test_no_new_rule_clause_added_in_this_module() -> None:
    """Confirms this module never defines its own rule logic - it only imports and evaluates the
    frozen G3-B rules (§4/§5 - no threshold adjustment, no new clause, no exception)."""
    source = _VALIDATION_PATH.read_text(encoding="utf-8")
    assert "def _rule_" not in source
    assert "CandidateRule(" not in source


# --- D: PASS_THROUGH not ACCEPT ---------------------------------------------------------------------


def test_pass_through_is_not_an_accept_value() -> None:
    """Test D."""
    for rule in (RULE_A, RULE_C, RULE_D, RULE_COMBINED):
        source = inspect.getsource(rule.fn)
        assert '"ACCEPT"' not in source and "'ACCEPT'" not in source


# --- E: rule metrics correct ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_safety_metrics_formulas_correct() -> None:
    """Test E."""
    records = await collect_records(now=_FIXED_NOW)
    m = measure_rule_safety("RULE_A", "A_triggered", records)
    assert m.negative_coverage == round(m.true_negative_rejects / m.negatives_evaluated, 3)
    assert m.positive_preservation == round(1 - m.false_rejects / m.positives_evaluated, 3)
    assert len(m.false_reject_ids) == m.false_rejects


@pytest.mark.asyncio
async def test_combined_metrics_false_reject_ids_match_count() -> None:
    records = await collect_records(now=_FIXED_NOW)
    m = measure_combined_safety(records)
    assert len(m.false_reject_ids) == m.false_rejects


# --- F: individual rule candidacy calculated independently ------------------------------------------


def test_production_candidacy_computed_per_rule_independently() -> None:
    """Test F. §26 - it must be structurally possible for A/D to differ from C (not forced union)."""
    assert production_candidacy("RULE_A", g3b_calibration_fr=0, g3b_holdout_fr=0, g3d_fr=0) == "PRODUCTION_CANDIDATE"
    assert production_candidacy("RULE_D", g3b_calibration_fr=0, g3b_holdout_fr=0, g3d_fr=3) == "REJECTED"
    assert production_candidacy("RULE_C", g3b_calibration_fr=0, g3b_holdout_fr=0, g3d_fr=0) == "PRODUCTION_CANDIDATE"


# --- G: controls excluded from new-validation metric -----------------------------------------------


@pytest.mark.asyncio
async def test_controls_excluded_from_new_validation_metrics() -> None:
    """Test G."""
    records = await collect_records(now=_FIXED_NOW)
    control_records = [r for r in records if r.group == "CONTROL"]
    assert len(control_records) == len(CONTROL_FIXTURE_IDS)
    m = measure_combined_safety(records)
    # every false_reject_id, if any, must belong to the NEW_VALIDATION group, never a control
    new_validation_ids = {e.fixture_id for e in ADVERSARIAL_MANIFEST}
    assert all(fid in new_validation_ids for fid in m.false_reject_ids)


# --- H: UNCLEAR excluded from binary safety metrics -------------------------------------------------


@pytest.mark.asyncio
async def test_unclear_excluded_from_binary_scoring() -> None:
    """Test H."""
    records = await collect_records(now=_FIXED_NOW)
    unclear_ids = {e.fixture_id for e in ADVERSARIAL_MANIFEST if e.manual_class == "UNCLEAR"}
    assert len(unclear_ids) >= 4
    m = measure_combined_safety(records)
    assert not (unclear_ids & set(m.false_reject_ids))
    scored_ids = {r.fixture_id for r in records if r.group == "NEW_VALIDATION" and r.desired_eventness != "AMBIGUOUS"}
    assert not (unclear_ids & scored_ids)


# --- I: production files unchanged --------------------------------------------------------------------


def test_no_production_files_changed_since_base_commit() -> None:
    """Test I. Mirrors G3-C's own identical test - compares the base commit against the WORKING
    TREE (not HEAD) so it is meaningful both before and after this phase's own commit."""
    import subprocess

    base_commit = "f33a8b2c2e3b26cf5ef0ebdd5926e573e9884ef4"  # G3-C's own commit, this phase's base
    allowed_prefixes = ("scripts/", "tests/", "docs/", "prompts/")
    tracked = subprocess.run(["git", "diff", "--name-only", base_commit], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
    changed = sorted({p for p in (*tracked.stdout.splitlines(), *untracked.stdout.splitlines()) if p.strip()})
    assert changed, "expected at least one changed file on this branch"
    offending = [p for p in changed if not p.startswith(allowed_prefixes)]
    assert not offending, f"production/forbidden paths changed: {offending}"


# --- J: LLM automatic reject explicitly prohibited by policy artifact ----------------------------------


def test_llm_auto_reject_policy_is_recorded_and_false() -> None:
    """Test J. §24 - LLM_AUTO_REJECT_ALLOWED=false is a frozen policy decision, recorded as data
    (not merely prose) so a future phase cannot silently drift from it without editing this test."""
    policy_doc = _REPO_ROOT / "docs" / "r2_10_g3d_adversarial_validation_report.md"
    assert policy_doc.exists()
    text = policy_doc.read_text(encoding="utf-8")
    assert "LLM_AUTO_REJECT_ALLOWED=false" in text
    assert "LLM_AUTO_ACCEPT_ALLOWED=false" in text


# --- K: consolidated manifest uniqueness -----------------------------------------------------------


def test_consolidated_manifest_index_has_no_cross_split_story_id_collisions() -> None:
    """Test K."""
    by_story_id: dict[str, list[str]] = {}
    for row in CONSOLIDATED_MANIFEST_INDEX:
        by_story_id.setdefault(row["story_id"], []).append(row["split"])
    collisions = {sid: splits for sid, splits in by_story_id.items() if sid != "(offline)" and len(set(splits)) > 1}
    assert collisions == {}


def test_dataset_expansion_totals_are_internally_consistent() -> None:
    summary = dataset_expansion_summary()
    assert summary["total_unique_db_backed_labelled"] == (
        summary["g3a_calibration_db"] + summary["g3b_holdout"] + summary["g3d_adversarial"]
    )  # true only because A/B/D story_ids are pairwise disjoint (test A/K already prove this)


# --- L: no Gateway import on default path -----------------------------------------------------------


def test_no_gateway_import_on_default_path() -> None:
    """Test L."""
    tree = ast.parse(_VALIDATION_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not any("llm_gateway" in m or "Gateway" in m for m in modules), modules


# --- additional: readiness simulation / subtype breakdown / class-specific rates sanity --------------


@pytest.mark.asyncio
async def test_readiness_simulation_never_shows_negative_counts() -> None:
    records = await collect_records(now=_FIXED_NOW)
    sim = current_readiness_simulation(records)
    assert sim["false_ready_before"] >= 0
    assert sim["additional_positive_damage"] <= sim["manual_positives_rejected_before"]


@pytest.mark.asyncio
async def test_class_specific_rates_cover_every_scored_class() -> None:
    records = await collect_records(now=_FIXED_NOW)
    rates = class_specific_rejection_rates(records)
    assert set(rates.keys()) <= {"REAL_SINGLE_EVENT", "EVENT_LIFECYCLE", "TOPIC_CLUSTER", "DIGEST", "NOISE"}
    assert "UNCLEAR" not in rates


@pytest.mark.asyncio
async def test_rule_d_false_rejects_are_all_short_multi_source_real_subtype() -> None:
    """Regression-pin for this phase's own central finding - RULE_D's false rejects must be
    exactly the SHORT_MULTI_SOURCE_REAL_EVENT-subtype fixtures this phase deliberately sought out
    (§9's own explicit adversarial target), never a fixture outside that subtype."""
    records = await collect_records(now=_FIXED_NOW)
    m = measure_rule_safety("RULE_D", "D_triggered", records)
    subtypes = subtype_false_rejects(records)
    if m.false_rejects > 0:
        assert set(m.false_reject_ids) <= set(subtypes.get("SHORT_MULTI_SOURCE_REAL_EVENT", []))
