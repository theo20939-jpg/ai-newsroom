"""INSTAGRAM-GROWTH-3, item 6/19: CreativePlan/CreativeDraft persistence tests - AI output is a
proposal, never auto-approved."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_creative_plan import CreativeDraftStatus, CreativePlanStatus
from services.instagram_creative_plan_service import (
    approve_draft,
    build_carousel_fatigue_note,
    create_creative_draft,
    create_creative_plan,
    fetch_recent_carousel_fingerprints,
    list_drafts_for_plan,
    reject_draft,
)


@pytest.mark.asyncio
async def test_creative_plan_starts_proposed(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(
        db_session, content_opportunity_id="opp-1", objective="reach", format="reel",
    )
    assert plan.status == CreativePlanStatus.PROPOSED


@pytest.mark.asyncio
async def test_creative_draft_never_auto_approves(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-2", objective="reach", format="single")
    draft = await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="single", payload={"creative_angle": "a"},
        generated_at=datetime.now(timezone.utc), evidence_used=["fact 1"],
    )
    assert draft.status == CreativeDraftStatus.PROPOSED
    refreshed_plan = await create_creative_plan(db_session, content_opportunity_id="opp-3", objective="reach", format="single")
    assert refreshed_plan.status == CreativePlanStatus.PROPOSED  # unrelated plan untouched


@pytest.mark.asyncio
async def test_approving_a_draft_also_approves_its_plan(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-4", objective="saves", format="carousel")
    draft = await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="carousel", payload={"slides": []},
        generated_at=datetime.now(timezone.utc),
    )
    approved = await approve_draft(db_session, draft.id)
    assert approved.status == CreativeDraftStatus.APPROVED

    from services.instagram_creative_plan_service import get_creative_plan
    refreshed = await get_creative_plan(db_session, plan.id)
    assert refreshed is not None
    assert refreshed.status == CreativePlanStatus.APPROVED


@pytest.mark.asyncio
async def test_rejecting_a_draft_records_reason(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-5", objective="reach", format="reel")
    draft = await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="reel", payload={"hook": "h"},
        generated_at=datetime.now(timezone.utc),
    )
    rejected = await reject_draft(db_session, draft.id, reason="restricted claim leaked")
    assert rejected.status == CreativeDraftStatus.REJECTED
    assert rejected.rejection_reason == "restricted claim leaked"


@pytest.mark.asyncio
async def test_multiple_drafts_can_be_listed_per_plan(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-6", objective="reach", format="reel")
    await create_creative_draft(db_session, creative_plan_id=plan.id, format="reel", payload={"v": 1}, generated_at=datetime.now(timezone.utc))
    await create_creative_draft(db_session, creative_plan_id=plan.id, format="reel", payload={"v": 2}, generated_at=datetime.now(timezone.utc))
    drafts = await list_drafts_for_plan(db_session, plan.id)
    assert len(drafts) == 2


def _b4_carousel_payload(*, composition: str | None, archetype: str | None = "news_insight") -> dict:
    return {
        "slides": [
            {"role": "hook", "slide_copy": "h", "visual_direction": "v", "composition": None, "overlay_mode": None},
            {"role": "takeaway", "slide_copy": "t", "visual_direction": "v", "composition": composition, "overlay_mode": "subtle" if composition else None},
        ],
        "content_archetype": archetype,
    }


def _legacy_carousel_payload() -> dict:
    """Pre-Phase-B.4 shape: slide dicts exist but never had a `composition` key at all."""
    return {"slides": [{"role": "hook", "slide_copy": "h", "visual_direction": "v"}]}


@pytest.mark.asyncio
async def test_fatigue_history_wiring_flags_repeated_composition(db_session: AsyncSession) -> None:
    """Test J: real persisted drafts -> fetch_recent_carousel_fingerprints() -> the EXISTING
    services/instagram_content_brain.py::evaluate_fatigue_state() -> an advisory fatigue_note line,
    with no second fatigue implementation and no fabricated data."""
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-fatigue", objective="saves", format="carousel")
    for _ in range(6):
        await create_creative_draft(
            db_session, creative_plan_id=plan.id, format="carousel",
            payload=_b4_carousel_payload(composition="contained_media"), generated_at=datetime.now(timezone.utc),
        )

    fingerprints = await fetch_recent_carousel_fingerprints(db_session, window_days=14)
    assert len(fingerprints) == 6
    assert all(fp.compositions == ("contained_media",) for fp in fingerprints)

    note = build_carousel_fatigue_note(fingerprints, window_days=14)
    assert "contained_media" in note
    assert "6x" in note
    assert "fatigued" in note.lower()


@pytest.mark.asyncio
async def test_legacy_drafts_never_fabricate_a_structured_fingerprint(db_session: AsyncSession) -> None:
    """Test K: a pre-Phase-B.4 draft (no `composition` key on any slide) must be silently skipped,
    never assigned a guessed composition/archetype - only drafts that actually carry the validated
    structured fields contribute to the fatigue signal."""
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-legacy", objective="saves", format="carousel")
    await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="carousel",
        payload=_legacy_carousel_payload(), generated_at=datetime.now(timezone.utc),
    )
    await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="carousel",
        payload=_b4_carousel_payload(composition="split_compare"), generated_at=datetime.now(timezone.utc),
    )

    fingerprints = await fetch_recent_carousel_fingerprints(db_session, window_days=14)
    assert len(fingerprints) == 1
    assert fingerprints[0].compositions == ("split_compare",)

    # A single occurrence is FRESH - no noteworthy line, and no crash/fabrication for the legacy row.
    note = build_carousel_fatigue_note(fingerprints, window_days=14)
    assert note == ""


@pytest.mark.asyncio
async def test_no_recent_drafts_produces_empty_advisory_note(db_session: AsyncSession) -> None:
    note = build_carousel_fatigue_note([], window_days=14)
    assert note == ""
