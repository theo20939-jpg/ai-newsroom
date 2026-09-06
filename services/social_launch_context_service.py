"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §3/§16: SocialLaunchContextService - the ONE place a
SocialLaunchContext row is ever created. Append-only versioning (see database/models/
social_launch_context.py's own docstring for why) - `get_current_context()` always returns the
highest `version` row for a platform; `create_next_version()` is the ONLY function that ever
INSERTs a new one, always called from services/social_launch_proposal_service.py::
confirm_proposal(), never from the parser directly (same "never let an LLM self-confirm its own
proposed mutation" discipline services/business_context_proposal_service.py already established)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchContext,
    SocialLaunchPlatform,
)


async def get_current_context(session: AsyncSession, platform: SocialLaunchPlatform) -> SocialLaunchContext | None:
    """The one function anything (directors, console, learning-boundary filter) should call for
    "what is the current launch context for this platform" - `None` when the founder has never
    run `/launch <platform> ...` for it yet (a truthful COLD_START/no-context state, never a
    fabricated default)."""
    stmt = (
        select(SocialLaunchContext)
        .where(SocialLaunchContext.platform == platform)
        .order_by(SocialLaunchContext.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def list_history(session: AsyncSession, platform: SocialLaunchPlatform) -> list[SocialLaunchContext]:
    stmt = (
        select(SocialLaunchContext)
        .where(SocialLaunchContext.platform == platform)
        .order_by(SocialLaunchContext.version.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_next_version(
    session: AsyncSession, *, platform: SocialLaunchPlatform, target_identity: str,
    current_identity: str | None, launch_state: LaunchState, planned_launch_at: datetime | None,
    launch_date_status: LaunchDateStatus, baseline_policy: LearningBaselinePolicy,
    historical_content_policy: HistoricalContentPolicy, raw_instruction: str,
    confirmed_structure: dict, created_by: int, learning_start_at: datetime | None = None,
    campaign_id=None, surface_id=None,
) -> SocialLaunchContext:
    """spec §40: never discards prior versions - always INSERTs, never UPDATEs an existing row.
    `learning_start_at` is left exactly as the caller passes it (usually carried forward unchanged
    from the previous version, since a rewritten launch instruction does not itself imply learning
    has started or reset - see services/social_launch_proposal_service.py::confirm_proposal() for
    the actual carry-forward logic)."""
    previous = await get_current_context(session, platform)
    next_version = (previous.version + 1) if previous is not None else 1
    context = SocialLaunchContext(
        platform=platform, version=next_version, target_identity=target_identity,
        current_identity=current_identity, launch_state=launch_state, planned_launch_at=planned_launch_at,
        launch_date_status=launch_date_status, learning_start_at=learning_start_at,
        baseline_policy=baseline_policy, historical_content_policy=historical_content_policy,
        campaign_id=campaign_id, surface_id=surface_id, raw_instruction=raw_instruction,
        confirmed_structure=confirmed_structure, created_by=created_by,
    )
    session.add(context)
    await session.commit()
    await session.refresh(context)
    return context


def compute_launch_context_fingerprint(context: SocialLaunchContext | None) -> str | None:
    """spec §16: any real change to launch_state/planned_launch_at/launch_date_status/
    baseline_policy/target_identity changes this value - a director's persisted run compares its
    own captured fingerprint against a freshly computed one to detect STALE_CONTEXT (mirrors
    services/director_run_service.py::compute_business_context_fingerprint()'s own targeted-hash
    idiom exactly). `None` when no context exists yet - a director run made with no launch context
    involved has nothing to fingerprint, never a fabricated hash of absence."""
    if context is None:
        return None
    parts = [
        f"version:{context.version}", f"launch_state:{context.launch_state.value}",
        f"planned_launch_at:{context.planned_launch_at.isoformat() if context.planned_launch_at else 'none'}",
        f"launch_date_status:{context.launch_date_status.value}",
        f"baseline_policy:{context.baseline_policy.value}",
        f"historical_content_policy:{context.historical_content_policy.value}",
        f"target_identity:{context.target_identity}",
    ]
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


def is_prelaunch_or_transition(context: SocialLaunchContext | None) -> bool:
    """spec §10: COLD_START applies whenever no context exists yet, or launch_state is PRE_LAUNCH/
    TRANSITION - a truthful, checkable predicate rather than re-deriving this comparison at every
    console/director call site."""
    if context is None:
        return True
    return context.launch_state in (LaunchState.PRE_LAUNCH, LaunchState.TRANSITION)


def describe_launch_context_for_creative(context: SocialLaunchContext | None) -> str:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §7: the ONE place that turns a SocialLaunchContext into the
    plain-text briefing line services/instagram_creative_director.py::CreativeDirectorInput.
    launch_context_note (and any future zero-to-one caller) actually uses - so every caller
    describes cold-start/transition identically instead of re-deriving this text ad hoc. Empty
    string (the field's own default) when there is no context or the platform is already LIVE with
    real history - an established account gets no injected launch framing at all."""
    if context is None or not is_prelaunch_or_transition(context):
        return ""
    if context.launch_state == LaunchState.TRANSITION:
        return (
            f"this account is transitioning from {context.current_identity or 'its prior identity'} to "
            f"{context.target_identity} - frame content as introducing/reinforcing the new identity, "
            "never assume audience familiarity with the target identity yet"
        )
    return (
        f"this is early content for a pre-launch account (target identity={context.target_identity}) - "
        "assume zero follower familiarity and no first-party format/audience/hook history exists yet"
    )


def mark_learning_started(context: SocialLaunchContext, *, now: datetime | None = None) -> None:
    """spec §5/§6: called ONLY by whatever real event actually satisfies the context's own
    baseline_policy (e.g. a real first post being recorded after LIVE transition) - never called
    speculatively. Mutates learning_start_at on the CURRENT row in place (this one field is
    intentionally exempt from the append-only-versioning discipline the rest of the model follows,
    since it records a REAL EVENT TIMESTAMP that happened once, not a founder-editable strategy
    field - mirrors VisualDesignerBriefVersion.activated_at's own identical "real event, not
    strategy, mutated in place" precedent)."""
    if context.learning_start_at is not None:
        return
    context.learning_start_at = now or datetime.now(timezone.utc)
