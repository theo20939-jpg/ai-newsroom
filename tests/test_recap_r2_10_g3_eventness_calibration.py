"""R2.10G3-B - deterministic eventness rejector calibration tests. Test matrix A-N per the phase's
own spec. Integration-level tests (E onward) use scripts._recap_r2_10_g3_eventness_calibrate's own
collect_evaluations(), which manages its own read-only DB connection (real local dev DB)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts._recap_r2_10_g3_eventness_calibrate import (
    AMBIGUOUS_CLASSES,
    CANDIDATE_RULES,
    NEGATIVE_EVENT_CLASSES,
    POSITIVE_EVENT_CLASSES,
    RULE_A,
    RULE_COMBINED,
    RULE_D,
    class_distributions,
    collect_evaluations,
    loo_zero_false_reject_stable,
    manual_class_group_counts,
    measure_rule,
)
from scripts._recap_r2_10_g3_eventness_holdout import HOLDOUT, used_story_ids_overlap_with_calibration
from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CALIBRATE_PATH = _REPO_ROOT / "scripts" / "_recap_r2_10_g3_eventness_calibrate.py"


# --- A: calibration labels are immutable inputs --------------------------------------------------


def test_manifest_module_defines_no_mutation_api() -> None:
    """Test A. The manifest exposes MANIFEST as a plain tuple of frozen dataclasses - structurally
    impossible to mutate in place (no setter, no list, frozen=True on every entry)."""
    assert isinstance(MANIFEST, tuple)
    for entry in MANIFEST:
        assert entry.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_holdout_disjoint_from_calibration() -> None:
    assert used_story_ids_overlap_with_calibration() == set()


# --- B: UNCLEAR excluded from binary rule scoring -------------------------------------------------


@pytest.mark.asyncio
async def test_unclear_and_needs_review_excluded_from_binary_scoring() -> None:
    """Test B (and resolves the manual_class-vs-desired_eventness tension documented in
    measure_rule()'s own docstring): fixtures whose desired_eventness is NEEDS_REVIEW/UNCERTAIN -
    including UNCLEAR-class ones - never appear in either the negatives or positives measure_rule()
    scores against."""
    cal, _ = await collect_evaluations()
    m = measure_rule(RULE_A, cal)
    excluded = [e for e in cal if e.desired_eventness in ("NEEDS_REVIEW", "UNCERTAIN")]
    assert len(excluded) > 0  # sanity: the exclusion actually has something to exclude
    assert m.negatives_evaluated + m.positives_evaluated == len(cal) - len(excluded)


# --- C: PASS_THROUGH is never treated as ACCEPT --------------------------------------------------


def test_pass_through_is_not_an_accept_value() -> None:
    """Test C. Structural guard: no candidate rule's return type includes "ACCEPT" anywhere."""
    for rule in (*CANDIDATE_RULES, RULE_COMBINED):
        import inspect

        source = inspect.getsource(rule.fn)
        assert '"ACCEPT"' not in source and "'ACCEPT'" not in source


# --- D: zero production readiness mutation --------------------------------------------------------


@pytest.mark.asyncio
async def test_no_production_readiness_mutation() -> None:
    """Test D."""
    from sqlalchemy import func, select

    from database.models.editorial_task import EditorialTask
    from database.models.story import Story
    from database.session import async_session_factory

    async with async_session_factory() as s:
        stories_before = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
        tasks_before = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()

    await collect_evaluations()

    async with async_session_factory() as s:
        stories_after = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
        tasks_after = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()

    assert stories_before == stories_after
    assert tasks_before == tasks_after


# --- E: candidate rule output deterministic --------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_output_deterministic() -> None:
    """Test E."""
    cal, _ = await collect_evaluations()
    for rule in (*CANDIDATE_RULES, RULE_COMBINED):
        m1 = measure_rule(rule, cal)
        m2 = measure_rule(rule, cal)
        assert m1 == m2


# --- F: LLM/Gateway cannot be imported/called ------------------------------------------------------


def test_calibration_script_imports_no_llm_gateway() -> None:
    """Test F."""
    tree = ast.parse(_CALIBRATE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not any("llm_gateway" in m or "Gateway" in m or m.endswith("_synthesize") for m in modules), modules


# --- G: holdout labels loaded separately from calibration labels ------------------------------------


def test_holdout_loaded_from_a_separate_module() -> None:
    """Test G."""
    import scripts._recap_r2_10_g3_eventness_holdout as holdout_mod
    import scripts._recap_r2_10_g3_eventness_manifest as manifest_mod

    assert holdout_mod is not manifest_mod
    assert len(HOLDOUT) >= 10


# --- H: metrics calculated correctly -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_negative_coverage_and_positive_preservation_formulas() -> None:
    """Test H."""
    cal, _ = await collect_evaluations()
    m = measure_rule(RULE_A, cal)
    assert m.negative_coverage == round(m.true_negative_rejects / m.negatives_evaluated, 3)
    assert m.positive_preservation == round(1 - m.false_rejects / m.positives_evaluated, 3)


# --- I: false reject accounting correct ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_false_reject_ids_match_count() -> None:
    """Test I."""
    cal, _ = await collect_evaluations()
    for rule in (*CANDIDATE_RULES, RULE_COMBINED):
        m = measure_rule(rule, cal)
        assert len(m.false_reject_ids) == m.false_rejects


# --- J-M: mandatory fixtures --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vla_mandatory_negative() -> None:
    """Test J. VLA must be a TOPIC_CLUSTER negative in the manual_class grouping (rule coverage is
    not required for every individual negative - RULE_A catches it via long span/single source,
    verified here directly)."""
    cal, _ = await collect_evaluations()
    vla = next(e for e in cal if e.fixture_id == "vla")
    assert vla.manual_class in NEGATIVE_EVENT_CLASSES
    assert vla.features is not None
    assert RULE_A.fn(vla.features) == "REJECT"


@pytest.mark.asyncio
async def test_nvidia_hf_mandatory_positive_never_rejected() -> None:
    """Test K. Nvidia/HF must never be rejected by any candidate or combined rule."""
    cal, _ = await collect_evaluations()
    nvidia = next(e for e in cal if e.fixture_id == "nvidia_hf_main")
    assert nvidia.manual_class in POSITIVE_EVENT_CLASSES
    assert nvidia.features is not None
    for rule in (*CANDIDATE_RULES, RULE_COMBINED):
        assert rule.fn(nvidia.features) != "REJECT", f"{rule.rule_id} incorrectly rejects Nvidia/HF"


@pytest.mark.asyncio
async def test_vk_false_ready_mandatory_negative_caught() -> None:
    """Test L. The central product question (§27): RULE_D (and the combined rule) must reject the
    VK synthetic false-READY fixture."""
    cal, _ = await collect_evaluations()
    vk = next(e for e in cal if e.fixture_id == "vk_apple_synthetic_4publisher_false_ready")
    assert vk.desired_eventness == "REJECT"
    assert vk.features is not None
    assert RULE_D.fn(vk.features) == "REJECT"
    assert RULE_COMBINED.fn(vk.features) == "REJECT"


@pytest.mark.asyncio
async def test_marvell_remains_ambiguous_not_scored() -> None:
    """Test M. Marvell must never be counted as a true-negative-reject or false-reject - it is
    excluded from binary scoring entirely (UNCLEAR/UNCERTAIN)."""
    cal, _ = await collect_evaluations()
    marvell = next(e for e in cal if e.fixture_id == "marvell_google")
    assert marvell.manual_class in AMBIGUOUS_CLASSES
    assert marvell.desired_eventness == "UNCERTAIN"
    m = measure_rule(RULE_COMBINED, cal)
    assert "marvell_google" not in m.false_reject_ids


# --- N: decimal-comma behavior inherited correctly from G3-0 --------------------------------------------


@pytest.mark.asyncio
async def test_marvell_decimal_comma_fix_inherited() -> None:
    """Test N."""
    cal, _ = await collect_evaluations()
    marvell = next(e for e in cal if e.fixture_id == "marvell_google")
    assert marvell.features is not None
    assert marvell.features.unique_source_count == 3  # 3 real domains, EN/RU $12.2B no longer conflicts


# --- Additional: LOO stability, class distributions, combined rule sanity --------------------------------


@pytest.mark.asyncio
async def test_all_candidate_rules_loo_stable_on_calibration() -> None:
    cal, _ = await collect_evaluations()
    for rule in (*CANDIDATE_RULES, RULE_COMBINED):
        stable, breaking = loo_zero_false_reject_stable(rule, cal)
        assert stable, f"{rule.rule_id} is not LOO-stable: {breaking}"


@pytest.mark.asyncio
async def test_manual_class_group_counts_match_spec() -> None:
    """§6's own expected counts."""
    cal, _ = await collect_evaluations()
    counts = manual_class_group_counts(cal)
    assert counts == {"POSITIVE_EVENT": 12, "NEGATIVE_EVENT": 17, "AMBIGUOUS": 2}


@pytest.mark.asyncio
async def test_class_distributions_cover_all_six_classes() -> None:
    cal, _ = await collect_evaluations()
    dist = class_distributions(cal)
    assert set(dist.keys()) == {
        "REAL_SINGLE_EVENT", "EVENT_LIFECYCLE", "TOPIC_CLUSTER", "DIGEST", "NOISE", "UNCLEAR",
    }


@pytest.mark.asyncio
async def test_combined_rule_has_zero_false_rejects_on_calibration_and_holdout() -> None:
    cal, holdout = await collect_evaluations()
    assert measure_rule(RULE_COMBINED, cal).false_rejects == 0
    assert measure_rule(RULE_COMBINED, holdout).false_rejects == 0
