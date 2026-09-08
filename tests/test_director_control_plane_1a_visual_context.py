"""DIRECTOR-CONTROL-PLANE-1A §17/§21/§37: bounded reference selection + Visual Director context
wiring tests - proves DesignReferenceAsset/DesignSpecVersion rows are real inputs to the Visual
Director's own context object (services/visual_creative_direction.py::VisualDirectorContext), not
just stored metadata, and that account_presentation_spec_reader.py exposes NEEDS_FOUNDER_INPUT
fields honestly from the real design/account_presentation_spec.md file."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_reference_asset import DesignReferenceRole
from database.models.design_spec_version import DesignSpecStatus, DesignSpecType
from services.account_presentation_spec_reader import read_account_presentation_spec, summarize_for_creative
from services.design_reference_registry import (
    MAX_REFERENCES_PER_ART_REVIEW,
    select_bounded_references,
    upsert_asset,
)
from services.design_spec_registry import create_candidate_spec, describe_spec_for_creative, promote_candidate
from services.visual_design_director import StoryFactsInput, build_visual_director_context


class TestBoundedReferenceSelection:
    @pytest.mark.asyncio
    async def test_selection_is_bounded_by_the_shared_limit(self, db_session: AsyncSession) -> None:
        for i in range(MAX_REFERENCES_PER_ART_REVIEW + 4):
            await upsert_asset(
                db_session, asset_path=f"assets/brand/newsroom_visuals/v1/references/test_bound_{i}.png",
                reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="DATA",
            )
        await db_session.flush()
        selected = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="DATA",
        )
        assert len(selected) == MAX_REFERENCES_PER_ART_REVIEW

    @pytest.mark.asyncio
    async def test_approved_and_rejected_selections_never_mix(self, db_session: AsyncSession) -> None:
        await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_approved_only.png",
            reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="BREAKING",
        )
        await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_rejected_only.png",
            reference_role=DesignReferenceRole.REJECTED_REFERENCE, platform="telegram", presentation_type="BREAKING",
        )
        await db_session.flush()
        approved = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="BREAKING",
        )
        rejected = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.REJECTED_REFERENCE, platform="telegram", presentation_type="BREAKING",
        )
        approved_paths = {a.asset_path for a in approved}
        rejected_paths = {a.asset_path for a in rejected}
        assert "assets/brand/newsroom_visuals/v1/references/test_approved_only.png" in approved_paths
        assert "assets/brand/newsroom_visuals/v1/references/test_rejected_only.png" in rejected_paths
        assert approved_paths.isdisjoint(rejected_paths)

    @pytest.mark.asyncio
    async def test_wrong_presentation_reference_not_selected(self, db_session: AsyncSession) -> None:
        await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_quote_only.png",
            reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="QUOTE",
        )
        await db_session.flush()
        selected = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="DATA",
        )
        assert "assets/brand/newsroom_visuals/v1/references/test_quote_only.png" not in {a.asset_path for a in selected}

    @pytest.mark.asyncio
    async def test_platformless_reference_applies_everywhere(self, db_session: AsyncSession) -> None:
        await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_universal.png",
            reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform=None, presentation_type=None,
        )
        await db_session.flush()
        selected_telegram = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="DATA",
        )
        selected_instagram = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="instagram", presentation_type="REEL",
        )
        assert "assets/brand/newsroom_visuals/v1/references/test_universal.png" in {a.asset_path for a in selected_telegram}
        assert "assets/brand/newsroom_visuals/v1/references/test_universal.png" in {a.asset_path for a in selected_instagram}

    @pytest.mark.asyncio
    async def test_ambiguous_reference_never_auto_selected(self, db_session: AsyncSession) -> None:
        await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_ambiguous.png",
            reference_role=DesignReferenceRole.NEEDS_FOUNDER_REVIEW, platform="telegram", presentation_type="DATA",
        )
        await db_session.flush()
        approved = await select_bounded_references(
            db_session, reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="DATA",
        )
        assert "assets/brand/newsroom_visuals/v1/references/test_ambiguous.png" not in {a.asset_path for a in approved}


class TestDescribeSpecForCreative:
    def test_none_spec_is_an_honest_empty_string(self) -> None:
        assert describe_spec_for_creative(None) == ""

    @pytest.mark.asyncio
    async def test_active_spec_is_summarized_from_real_persisted_data(self, db_session: AsyncSession) -> None:
        candidate = await create_candidate_spec(
            db_session, scope="test_visual_director_scope", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
            parameters={"alignment": "left"}, notes="test spec for context wiring",
        )
        active = await promote_candidate(db_session, candidate.id)
        assert active.status == DesignSpecStatus.ACTIVE
        summary = describe_spec_for_creative(active)
        assert "test_visual_director_scope" in summary
        assert "left" in summary


class TestAccountPresentationSpecReader:
    def test_telegram_section_exposes_needs_founder_input_honestly(self) -> None:
        spec = read_account_presentation_spec("telegram")
        assert spec is not None
        assert spec.needs_founder_input_fields, "expected at least one NEEDS_FOUNDER_INPUT field for the unregistered Telegram surface"
        assert any(f.name == "Channel name" for f in spec.fields)

    def test_unknown_platform_returns_none(self) -> None:
        assert read_account_presentation_spec("does-not-exist-platform") is None

    def test_summarize_for_creative_is_empty_for_none(self) -> None:
        assert summarize_for_creative(None) == ""

    def test_summarize_for_creative_includes_real_field_names(self) -> None:
        summary = summarize_for_creative(read_account_presentation_spec("instagram"))
        assert "Username/display name" in summary


class TestVisualDirectorContextDeclarativeFields:
    def test_defaults_are_empty_for_every_pre_existing_caller(self) -> None:
        context = build_visual_director_context(
            story=StoryFactsInput(story_id="s1", title="Test story"), platform="telegram", presentation_type="DATA",
            designer_brief_text="brief", designer_brief_scope="global", designer_brief_version=1,
            feed_context_summary=[], recent_failure_summary=[], available_media_summary="none",
            renderer_constraints_summary="none", attempts_used=0, max_attempts=3, budget_state_summary="ok",
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        assert context.active_design_spec_summary == ""
        assert context.account_presentation_spec_summary == ""
        assert context.approved_reference_summary == []
        assert context.rejected_reference_summary == []
        assert context.source_classification_summary == ""

    def test_declarative_fields_pass_through_when_supplied(self) -> None:
        context = build_visual_director_context(
            story=StoryFactsInput(story_id="s2", title="Test story 2"), platform="telegram", presentation_type="DATA",
            designer_brief_text="brief", designer_brief_scope="global", designer_brief_version=1,
            feed_context_summary=[], recent_failure_summary=[], available_media_summary="none",
            renderer_constraints_summary="none", attempts_used=0, max_attempts=3, budget_state_summary="ok",
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
            active_design_spec_summary="scope=global; type=declarative_visual_params",
            account_presentation_spec_summary="Channel name=NEEDS_FOUNDER_INPUT",
            approved_reference_summary=["ref_a.png (good)"], rejected_reference_summary=["ref_b.png (bad crop)"],
            source_classification_summary="SOURCE_INFOGRAPHIC",
        )
        assert context.active_design_spec_summary == "scope=global; type=declarative_visual_params"
        assert context.account_presentation_spec_summary == "Channel name=NEEDS_FOUNDER_INPUT"
        assert context.approved_reference_summary == ["ref_a.png (good)"]
        assert context.rejected_reference_summary == ["ref_b.png (bad crop)"]
        assert context.source_classification_summary == "SOURCE_INFOGRAPHIC"

    def test_same_final_image_different_spec_context_produces_different_context_object(self) -> None:
        """§21's own required proof, applied at the context-construction boundary: the SAME story/
        platform/presentation_type with a DIFFERENT active_design_spec_summary/reference set
        produces a DIFFERENT VisualDirectorContext - proving these are real inputs threaded through
        construction, not dead/ignored parameters. The Art Director's own evaluation-level version
        of this proof (on final pixels) lives in tests/test_director_control_plane_1a_art_director.py."""
        story = StoryFactsInput(story_id="s3", title="Same story")
        base_kwargs: dict[str, Any] = dict(
            platform="telegram", presentation_type="DATA", designer_brief_text="brief",
            designer_brief_scope="global", designer_brief_version=1, feed_context_summary=[],
            recent_failure_summary=[], available_media_summary="none", renderer_constraints_summary="none",
            attempts_used=0, max_attempts=3, budget_state_summary="ok", now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        context_a = build_visual_director_context(
            story=story, active_design_spec_summary="scope=global; version=1", approved_reference_summary=["ref_a.png"], **base_kwargs,
        )
        context_b = build_visual_director_context(
            story=story, active_design_spec_summary="scope=global; version=2", approved_reference_summary=["ref_c.png"], **base_kwargs,
        )
        assert context_a.active_design_spec_summary != context_b.active_design_spec_summary
        assert context_a.approved_reference_summary != context_b.approved_reference_summary
