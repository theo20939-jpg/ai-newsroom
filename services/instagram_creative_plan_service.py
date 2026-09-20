"""INSTAGRAM-GROWTH-3, item 6: CreativePlan/CreativeDraft persistence. AI creative output is a
PROPOSAL, never a business fact - `status` never auto-flips to APPROVED anywhere in this module;
`approve_draft()` is the one explicit, human-triggered call that does it (and, in turn, marks the
owning plan APPROVED - a plan is approved once ONE of its drafts is).

Phase B.4.1 section 10/11 additions (`fetch_recent_carousel_fingerprints`/
`build_carousel_fatigue_note`): closes the previously-PARTIAL cross-post repetition gap by reading
a bounded recent window of already-persisted `InstagramCreativeDraft` rows - no DB migration
(`payload` is already a JSON blob), no second fatigue implementation (feeds
`services/instagram_content_brain.py`'s existing `evaluate_fatigue_state`), no new persistence
model. Recent DRAFTS (proposals) inform repetition history only - never treated as evidence of what
performed well; that requires real publication/performance data this repository does not yet
have."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_creative_plan import (
    CreativeDraftStatus,
    CreativePlanStatus,
    InstagramCreativeDraft,
    InstagramCreativePlan,
)
from services.instagram_content_brain import FatigueState, evaluate_fatigue_state


async def create_creative_plan(
    session: AsyncSession, *, content_opportunity_id: str, objective: str, format: str,
    campaign_id: UUID | None = None, product_id: UUID | None = None, series_id: UUID | None = None,
    hook_family: str | None = None, business_context_version: str | None = None,
    campaign_state_snapshot: str | None = None,
) -> InstagramCreativePlan:
    plan = InstagramCreativePlan(
        content_opportunity_id=content_opportunity_id, objective=objective, format=format, campaign_id=campaign_id,
        product_id=product_id, series_id=series_id, hook_family=hook_family,
        business_context_version=business_context_version, campaign_state_snapshot=campaign_state_snapshot,
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def get_creative_plan(session: AsyncSession, plan_id: UUID) -> InstagramCreativePlan | None:
    return await session.get(InstagramCreativePlan, plan_id)


async def create_creative_draft(
    session: AsyncSession, *, creative_plan_id: UUID, format: str, payload: dict, generated_at: datetime,
    approved_claims: list[str] | None = None, restricted_claims: list[str] | None = None,
    evidence_used: list[str] | None = None, ai_model: str | None = None, ai_capability: str | None = None,
    ai_cost_usd: float | None = None,
) -> InstagramCreativeDraft:
    draft = InstagramCreativeDraft(
        creative_plan_id=creative_plan_id, format=format, payload=payload, generated_at=generated_at,
        approved_claims=approved_claims or [], restricted_claims=restricted_claims or [],
        evidence_used=evidence_used or [], ai_model=ai_model, ai_capability=ai_capability, ai_cost_usd=ai_cost_usd,
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    return draft


async def list_drafts_for_plan(session: AsyncSession, creative_plan_id: UUID) -> list[InstagramCreativeDraft]:
    stmt = select(InstagramCreativeDraft).where(InstagramCreativeDraft.creative_plan_id == creative_plan_id)
    return list((await session.execute(stmt)).scalars().all())


async def approve_draft(session: AsyncSession, draft_id: UUID) -> InstagramCreativeDraft:
    draft = await session.get(InstagramCreativeDraft, draft_id)
    if draft is None:
        raise ValueError(f"no InstagramCreativeDraft with id={draft_id}")
    draft.status = CreativeDraftStatus.APPROVED

    plan = await session.get(InstagramCreativePlan, draft.creative_plan_id)
    if plan is not None:
        plan.status = CreativePlanStatus.APPROVED

    await session.commit()
    await session.refresh(draft)
    return draft


async def reject_draft(session: AsyncSession, draft_id: UUID, *, reason: str) -> InstagramCreativeDraft:
    draft = await session.get(InstagramCreativeDraft, draft_id)
    if draft is None:
        raise ValueError(f"no InstagramCreativeDraft with id={draft_id}")
    draft.status = CreativeDraftStatus.REJECTED
    draft.rejection_reason = reason
    await session.commit()
    await session.refresh(draft)
    return draft


@dataclass(frozen=True)
class RecentCarouselFingerprint:
    """One draft's validated structured signature, extracted from its own persisted `payload` -
    never fabricated for a draft whose payload predates Phase B.4's structured fields."""

    draft_id: UUID
    generated_at: datetime
    content_archetype: str | None
    compositions: tuple[str, ...]  # DISTINCT composition families this ONE post used (post-level, not per slide)


def _fingerprint_from_draft(draft: InstagramCreativeDraft) -> RecentCarouselFingerprint | None:
    payload = draft.payload
    if not isinstance(payload, dict):
        return None
    slides = payload.get("slides")
    if not isinstance(slides, list) or not slides:
        return None
    # A legacy pre-Phase-B.4 draft's slide dicts never carry the `composition` KEY at all - that
    # absence (not merely a null value) is what marks it as unvalidated for this purpose. Never
    # infer/guess a value for it.
    if not any(isinstance(slide, dict) and "composition" in slide for slide in slides):
        return None
    # Fatigue unit is the POST: one post contributes at most one hit per composition family, no
    # matter how many of its slides used it. (Legacy `overlay_mode` keys in old payloads are
    # ignored - overlays no longer exist in the visual system.)
    compositions = tuple(sorted({
        slide["composition"] for slide in slides
        if isinstance(slide, dict) and slide.get("composition")
    }))
    archetype = payload.get("content_archetype")
    return RecentCarouselFingerprint(
        draft_id=draft.id, generated_at=draft.generated_at,
        content_archetype=archetype if isinstance(archetype, str) else None,
        compositions=compositions,
    )


async def fetch_recent_carousel_fingerprints(
    session: AsyncSession, *, window_days: int = 14, limit: int = 50,
) -> list[RecentCarouselFingerprint]:
    """Phase B.4.1 section 10/11: the one real read of recent persisted carousel drafts this
    codebase performs for cross-post repetition context, across ALL plans (not scoped to a single
    `creative_plan_id` the way `list_drafts_for_plan` is - repetition has to be judged against
    everything recently proposed, not one campaign's own history). Bounded by both a recency
    window and a hard row limit; never used as performance evidence, only as a repetition signal
    (see module docstring)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    stmt = (
        select(InstagramCreativeDraft)
        .where(InstagramCreativeDraft.format == "carousel", InstagramCreativeDraft.generated_at >= cutoff)
        .order_by(InstagramCreativeDraft.generated_at.desc(), InstagramCreativeDraft.id.desc())
        .limit(limit)
    )
    drafts = list((await session.execute(stmt)).scalars().all())
    fingerprints = (_fingerprint_from_draft(draft) for draft in drafts)
    return [fp for fp in fingerprints if fp is not None]


_FATIGUE_NOTEWORTHY_STATES = (FatigueState.REPEATED, FatigueState.FATIGUED, FatigueState.OVERUSED)


def build_carousel_fatigue_note(fingerprints: list[RecentCarouselFingerprint], *, window_days: int = 14) -> str:
    """Turns the read-only fingerprints above into the exact free-text line the REAL carousel
    Creative Director prompt already reads via `CreativeDirectorInput.fatigue_note` (services/
    instagram_creative_director.py::_build_user_text) - reuses `services/instagram_content_brain.py
    ::evaluate_fatigue_state` for the actual judgment, no second fatigue implementation. Advisory
    only: the prompt's own rules (v6.yaml) already state content fit wins and a fatigue note never
    forces a mechanical rotation - this only supplies the count, the model still decides."""
    if not fingerprints:
        return ""
    composition_counts: dict[str, int] = {}
    archetype_counts: dict[str, int] = {}
    for fp in fingerprints:
        for comp in fp.compositions:
            composition_counts[comp] = composition_counts.get(comp, 0) + 1
        if fp.content_archetype:
            archetype_counts[fp.content_archetype] = archetype_counts.get(fp.content_archetype, 0) + 1

    lines: list[str] = []
    for comp, count in sorted(composition_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        state = evaluate_fatigue_state(dimension="composition", repetition_count=count, window_days=window_days)
        if state in _FATIGUE_NOTEWORTHY_STATES:
            lines.append(f"composition '{comp}' appeared in {count} of the last {window_days}d posts ({state.value}) - avoid unless this content genuinely calls for it")
    for archetype, count in sorted(archetype_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        state = evaluate_fatigue_state(dimension="content_archetype", repetition_count=count, window_days=window_days)
        if state in _FATIGUE_NOTEWORTHY_STATES:
            lines.append(f"content_archetype '{archetype}' appeared in {count} of the last {window_days}d posts ({state.value})")
    return "\n".join(lines)


async def record_creative_draft(
    session: AsyncSession, *, content_opportunity_id: str, objective: str, format: str, payload: dict,
    hook_family: str | None = None, ai_model: str | None = None, ai_capability: str | None = None,
    evidence_used: list[str] | None = None,
) -> InstagramCreativeDraft:
    """Phase B.4.2: the live trigger's writer for repetition history. Adds the plan + PROPOSED draft
    with flush() only - the caller's own transaction owns the commit, so a later failure in the
    same cycle rolls this back with everything else (unlike the create_* helpers above, which
    commit immediately)."""
    plan = InstagramCreativePlan(
        content_opportunity_id=content_opportunity_id, objective=objective, format=format, hook_family=hook_family,
    )
    session.add(plan)
    await session.flush()
    draft = InstagramCreativeDraft(
        creative_plan_id=plan.id, format=format, payload=payload, generated_at=datetime.now(timezone.utc),
        evidence_used=evidence_used or [], ai_model=ai_model, ai_capability=ai_capability,
    )
    session.add(draft)
    await session.flush()
    return draft
