"""Phase V2.1 - bake-off harness dry-run behavior tests (Stage 17/18). No real network call
anywhere in this file - default (no --live) execution must remain a pure, local, zero-cost
operation, which is the exact thing these tests verify."""
from __future__ import annotations

import pytest

from scripts.nnj_visual_recomposition_bakeoff import (
    BAKE_OFF_MODELS,
    _parse_args,
    _run,
    build_matrix,
    build_recomposition_prompt,
    credential_audit,
    estimate_max_cost_usd,
    load_bake_off_cases,
)


def test_exactly_three_authoritative_models_no_fourth_provider() -> None:
    assert BAKE_OFF_MODELS == (
        ("gemini", "gemini-3.1-flash-image"),
        ("gemini", "gemini-3-pro-image"),
        ("openai", "gpt-image-2"),
    )


def test_load_bake_off_cases_returns_exactly_three_verified_cases() -> None:
    cases = load_bake_off_cases()
    assert len(cases) == 3
    assert {c.case_id for c in cases} == {
        "case1_hero_product_iphone", "case2_gadget_geometry_detail", "case3_bright_promotional_scene",
    }
    for case in cases:
        assert case.width > 0 and case.height > 0
        assert case.mime_type == "image/jpeg"


def test_build_matrix_produces_exactly_nine_planned_runs() -> None:
    cases = load_bake_off_cases()
    runs = build_matrix(cases)
    assert len(runs) == 9
    assert all(r.planned is True and r.executed is False for r in runs)
    assert {(r.case_id, r.provider, r.model_id) for r in runs} == {
        (case.case_id, provider, model_id) for case in cases for provider, model_id in BAKE_OFF_MODELS
    }


def test_canonical_prompt_is_identical_across_calls_never_tuned_per_model() -> None:
    """The exact same string every time - "one canonical provider-neutral prompt... do not tune
    per-model" (Stage 8)."""
    assert build_recomposition_prompt() == build_recomposition_prompt()
    prompt = build_recomposition_prompt()
    assert "NNJ" in prompt
    assert "FORBIDDEN" in prompt
    assert "OUTPUT" in prompt


def test_credential_audit_reports_presence_only_never_a_secret_value() -> None:
    audit = credential_audit()
    assert set(audit.keys()) == {"OPENAI_API_KEY", "GEMINI_API_KEY"}
    assert audit["OPENAI_API_KEY"] in ("PRESENT", "ABSENT")
    assert audit["GEMINI_API_KEY"] in ("PRESENT", "ABSENT")


def test_estimate_max_cost_usd_is_a_positive_disclosed_ceiling() -> None:
    cases = load_bake_off_cases()
    runs = build_matrix(cases)
    estimate = estimate_max_cost_usd(runs)
    assert estimate > 0
    assert estimate == round(sum(r.estimated_cost_usd or 0.0 for r in runs), 4)


# ---------------------------------------------------------------------------
# Dry-run execution - the critical zero-network-call proof
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_produces_manifest_with_zero_calls_and_zero_cost(tmp_path) -> None:
    args = _parse_args(["--output-dir", str(tmp_path)])
    assert args.live is False  # dry run is the default - no flag needed

    manifest = await _run(args)

    assert manifest["mode"] == "dry_run"
    assert manifest["planned_runs"] == 9
    assert manifest["network_image_generation_calls"] == 0
    assert manifest["successful_paid_generations"] == 0
    assert manifest["actual_cost_usd"] == 0
    assert all(r["executed"] is False for r in manifest["runs"])
    assert all(r["output_path"] is None for r in manifest["runs"])


@pytest.mark.asyncio
async def test_dry_run_writes_manifest_json_to_output_dir(tmp_path) -> None:
    args = _parse_args(["--output-dir", str(tmp_path)])

    await _run(args)

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()


def test_default_max_successful_generations_is_nine_the_full_matrix() -> None:
    args = _parse_args([])
    assert args.max_successful_generations == 9
    assert args.max_cost_usd is None
    assert args.live is False
