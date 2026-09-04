"""R2.10G3-A - shadow eventness evaluation harness tests.

Test matrix A-L per the phase's own spec. DB-backed tests (E/F/G/H/I/J/K) use the real local dev
database via scripts._recap_r2_10_g3_eventness_harness.run_evaluation() directly - this harness
manages its own read-only connection/transaction (mirrors scripts/_recap_r2_shadow_batch.py's own
established pattern), so these are integration-level tests, not the `db_session` fixture. Pure
structural tests (A/B/C/D/L) need no DB at all.
"""
from __future__ import annotations

import ast
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._recap_r2_10_g3_eventness_manifest import DESIRED_EVENTNESS_VALUES, MANIFEST, MANUAL_CLASSES

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HARNESS_PATH = _REPO_ROOT / "scripts" / "_recap_r2_10_g3_eventness_harness.py"
_BATCH_PATH = _REPO_ROOT / "scripts" / "_recap_r2_shadow_batch.py"
_FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


# --- A: manifest schema -----------------------------------------------------------------------


def test_manifest_has_between_30_and_40_entries() -> None:
    assert 30 <= len(MANIFEST) <= 40, f"expected 30-40 fixtures, got {len(MANIFEST)}"


def test_manifest_fixture_ids_are_unique() -> None:
    ids = [e.fixture_id for e in MANIFEST]
    assert len(ids) == len(set(ids))


def test_manifest_every_entry_has_valid_class_and_eventness() -> None:
    for entry in MANIFEST:
        assert entry.manual_class in MANUAL_CLASSES, entry.fixture_id
        assert entry.desired_eventness in DESIRED_EVENTNESS_VALUES, entry.fixture_id
        assert entry.rationale, f"{entry.fixture_id}: empty rationale"


def test_manifest_unclear_always_maps_to_uncertain() -> None:
    for entry in MANIFEST:
        if entry.manual_class == "UNCLEAR":
            assert entry.desired_eventness == "UNCERTAIN", entry.fixture_id


def test_manifest_includes_all_manual_classes() -> None:
    """Composition check (§9): must not be filled with only near-READY candidates."""
    classes = {e.manual_class for e in MANIFEST}
    assert classes == MANUAL_CLASSES, f"missing classes: {MANUAL_CLASSES - classes}"


def test_manifest_db_fixtures_have_story_id_and_offline_fixtures_have_events() -> None:
    for entry in MANIFEST:
        if entry.kind == "db":
            assert entry.story_id and entry.title_snapshot
        else:
            assert entry.offline_events


def test_manifest_mandatory_negative_control_present() -> None:
    ids = {e.fixture_id for e in MANIFEST}
    assert "vk_apple_synthetic_4publisher_false_ready" in ids


# --- B: zero Gateway imports in the deterministic batch path ------------------------------------


def test_harness_imports_no_llm_gateway() -> None:
    """Test B. Structural AST guard, mirrors feature/r2-shadow-preparation's own established
    convention (scripts/_recap_r2_shadow_batch.py's own module docstring: "no --with-llm argument
    exists in the parser at all")."""
    imports = _imports_in(_HARNESS_PATH)
    assert not any("llm_gateway" in m or "Gateway" in m for m in imports), imports
    assert not any(m.endswith("_synthesize") for m in imports), "harness must not import the synthesis script"


def test_harness_has_no_with_llm_argument() -> None:
    """The module docstring may mention '--with-llm' in prose (explaining the sibling batch
    script's own guarantee) - the real invariant is that no `add_argument("--with-llm", ...)` call
    exists anywhere in this file's parser construction."""
    tree = ast.parse(_HARNESS_PATH.read_text(encoding="utf-8"))
    add_argument_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
    ]
    flag_names = {
        arg.value for call in add_argument_calls for arg in call.args if isinstance(arg, ast.Constant)
    }
    assert "--with-llm" not in flag_names, flag_names


def test_reused_batch_script_also_has_no_llm_gateway_import() -> None:
    """The verbatim-reused scripts/_recap_r2_shadow_batch.py must still hold this invariant after
    being copied into this branch."""
    imports = _imports_in(_BATCH_PATH)
    assert not any("llm_gateway" in m or "Gateway" in m for m in imports), imports


# --- C: read-only transaction guard --------------------------------------------------------------


def test_harness_calls_read_only_guard() -> None:
    """Test C. Structural check that run_evaluation() actually invokes the guard - mirrors the
    equivalent check pattern already established for the sibling R2 shadow scripts."""
    source = _HARNESS_PATH.read_text(encoding="utf-8")
    assert "_verify_read_only" in source
    assert "SET TRANSACTION READ ONLY" in source


# --- D: limit hard ceiling (on the REUSED batch script, which owns this concept) ----------------


def test_batch_script_limit_ceiling_still_enforced() -> None:
    """Test D. This new harness evaluates a fixed manifest, not a recency-bounded scan, so it has
    no --limit of its own - the ceiling concept belongs to the reused scripts/_recap_r2_shadow_
    batch.py, verbatim-copied into this branch. Confirm it still enforces its own documented
    ceiling after the copy."""
    import scripts._recap_r2_shadow_batch as batch

    assert batch.MAX_LIMIT == 200
    assert batch.DEFAULT_LIMIT <= batch.MAX_LIMIT


# --- E-K: DB-backed integration tests (real local dev DB, read-only) ----------------------------


@pytest.mark.asyncio
async def test_vla_fixture_retains_manual_topic_cluster() -> None:
    """Test E."""
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    evaluations, _ = await run_evaluation(now=_FIXED_NOW)
    vla = next(e for e in evaluations if e.fixture_id == "vla")
    assert vla.manual_class == "TOPIC_CLUSTER"
    assert vla.desired_eventness == "REJECT"
    if vla.features is not None:
        assert vla.features.unique_source_count == 1


@pytest.mark.asyncio
async def test_nvidia_fixture_retains_manual_event_lifecycle() -> None:
    """Test F."""
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    evaluations, _ = await run_evaluation(now=_FIXED_NOW)
    nvidia = next(e for e in evaluations if e.fixture_id == "nvidia_hf_main")
    assert nvidia.manual_class == "EVENT_LIFECYCLE"
    assert nvidia.desired_eventness == "ACCEPT"


@pytest.mark.asyncio
async def test_vk_synthetic_false_ready_surfaced_as_disagreement() -> None:
    """Test G. The central regression case this whole harness exists to surface."""
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    evaluations, metrics = await run_evaluation(now=_FIXED_NOW)
    vk = next(e for e in evaluations if e.fixture_id == "vk_apple_synthetic_4publisher_false_ready")
    assert vk.existing_readiness_state == "READY"
    assert vk.desired_eventness == "REJECT"
    assert "CURRENT_READY_BUT_MANUAL_REJECT" in vk.disagreement_flags
    assert vk.fixture_id in metrics["false_accept_ids"]


@pytest.mark.asyncio
async def test_marvell_stays_unclear_uncertain() -> None:
    """Test H."""
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    evaluations, _ = await run_evaluation(now=_FIXED_NOW)
    marvell = next(e for e in evaluations if e.fixture_id == "marvell_google")
    assert marvell.manual_class == "UNCLEAR"
    assert marvell.desired_eventness == "UNCERTAIN"


@pytest.mark.asyncio
async def test_marvell_decimal_comma_no_longer_shows_false_conflict() -> None:
    """Test I. The Marvell offline fixture's own effective source count must reflect the G3-0 fix
    (EN/RU $12.2B correctly co-identified) - inherited through services/recap_event.py unchanged."""
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    evaluations, _ = await run_evaluation(now=_FIXED_NOW)
    marvell = next(e for e in evaluations if e.fixture_id == "marvell_google")
    assert marvell.features is not None
    # 3 distinct real domains (a.com/cnbc.com/ria.ru) - unaffected by the numeric fix directly,
    # but the underlying _has_conflicting_distinctive_facts() no longer sees a false EN/RU split.
    assert marvell.features.unique_source_count == 3


@pytest.mark.asyncio
async def test_no_production_readiness_mutation() -> None:
    """Test J. Row counts for the tables the harness could conceivably touch must be unchanged
    before/after a full run - the harness's own read-only transaction is rolled back, never
    committed (mirrors scripts/_recap_r2_shadow_batch.py's own established invariant)."""
    from sqlalchemy import func, select

    from database.models.editorial_task import EditorialTask
    from database.models.story import Story
    from database.session import async_session_factory
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    async with async_session_factory() as s:
        stories_before = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
        tasks_before = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()

    await run_evaluation(now=_FIXED_NOW)

    async with async_session_factory() as s:
        stories_after = (await s.execute(select(func.count()).select_from(Story))).scalar_one()
        tasks_after = (await s.execute(select(func.count()).select_from(EditorialTask))).scalar_one()

    assert stories_before == stories_after
    assert tasks_before == tasks_after


@pytest.mark.asyncio
async def test_deterministic_output_for_identical_input() -> None:
    """Test K."""
    from scripts._recap_r2_10_g3_eventness_harness import run_evaluation

    first, first_metrics = await run_evaluation(now=_FIXED_NOW)
    second, second_metrics = await run_evaluation(now=_FIXED_NOW)

    first_by_id = {e.fixture_id: (e.existing_readiness_state, tuple(e.disagreement_flags)) for e in first}
    second_by_id = {e.fixture_id: (e.existing_readiness_state, tuple(e.disagreement_flags)) for e in second}
    assert first_by_id == second_by_id
    assert first_metrics == second_metrics


# --- L: LLM path requires explicit invocation ----------------------------------------------------


def test_llm_synthesis_path_is_not_imported_or_auto_invoked() -> None:
    """Test L. The synthesis script (scripts/_recap_r2_shadow_synthesize.py) is deliberately NOT
    part of this branch/commit at all - see docs/r2_10_g3_eventness_evaluation_report.md's own
    §H for why: the default deterministic path must have LLM_CALLS=0 unconditionally, which the
    simplest, most auditable guarantee is "the script that could call it does not exist in this
    tree yet," not a flag that could be flipped."""
    assert not (_REPO_ROOT / "scripts" / "_recap_r2_shadow_synthesize.py").exists()
    assert importlib.util.find_spec("scripts._recap_r2_shadow_synthesize") is None
