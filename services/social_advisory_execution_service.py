"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §25-28: SocialAdvisoryExecutionService - the ONLY place a
pre-launch advisory is computed AND persisted. Mirrors services/director_execution_service.py's
own console-read-purity invariant exactly: `bot/handlers/director_console.py`'s existing pure
reads never import or call anything in this module; only the new, explicit, FOUNDER-only
`/directors refresh <platform>` mutation command does (spec §25's own "NOT a read operation"
instruction).

Budget-checked BEFORE every Gateway call (services/social_advisory_budget_service.py) - never
after. `settings.social_advisory_execution_enabled` (default False) is the outer gate this
function's only real caller (bot/handlers/director_console.py's refresh handler) checks first;
this function itself has no opinion about that flag, it only computes and persists."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRun, DirectorRunStatus, DirectorType
from database.models.news_event import NewsEvent
from database.models.social_launch_context import SocialLaunchPlatform
from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from services.business_context_snapshot_service import get_business_context_snapshot
from services.director_run_service import compute_business_context_fingerprint, create_director_run
from services.social_advisory_budget_service import SocialAdvisoryBudgetDecision, check_social_advisory_budget
from services.social_launch_context_service import compute_launch_context_fingerprint, get_current_context
from services.social_prelaunch_advisory import PrelaunchAdvisory, PrelaunchAdvisoryError, build_prelaunch_advisory

_PLATFORM_DIRECTOR_TYPE = {
    SocialLaunchPlatform.TELEGRAM: DirectorType.TELEGRAM_PRELAUNCH,
    SocialLaunchPlatform.INSTAGRAM: DirectorType.INSTAGRAM_PRELAUNCH,
}


@dataclass(frozen=True)
class PrelaunchAdvisoryExecutionResult:
    platform: SocialLaunchPlatform
    advisory: PrelaunchAdvisory | None
    run: DirectorRun | None
    budget_decision: SocialAdvisoryBudgetDecision
    error: str | None = None


def _advisory_payload(advisory: PrelaunchAdvisory) -> dict:
    """Explicit field selection, never dataclasses.asdict() with model_provider/model_name/cost_usd
    included - mirrors services/director_execution_service.py's own established convention."""
    return {
        "current_state": advisory.current_state, "target_state": advisory.target_state,
        "launch_objectives": advisory.launch_objectives, "transition_tasks": advisory.transition_tasks,
        "content_pillars": advisory.content_pillars, "initial_content_sequence": advisory.initial_content_sequence,
        "cadence_hypothesis": advisory.cadence_hypothesis, "format_hypotheses": advisory.format_hypotheses,
        "visual_direction": advisory.visual_direction, "profile_setup": advisory.profile_setup,
        "pinned_intro_content": advisory.pinned_intro_content, "first_learning_questions": advisory.first_learning_questions,
        "measurement_plan": advisory.measurement_plan, "risks": advisory.risks,
    }


async def _recent_newsroom_opportunities_summary(session: AsyncSession, *, limit: int = 10) -> str:
    """A real, minimal query over already-collected NewsEvent rows - never fabricated. Full
    editorial-fit scoring (GOOD_FOR_LAUNCH / SAVE_FOR_AFTER_LAUNCH per spec §34) is left to a
    future phase; this is deliberately just "what real stories exist right now" context for the
    advisory prompt to reason over itself."""
    stmt = select(NewsEvent.title).order_by(NewsEvent.published_at.desc().nullslast()).limit(limit)
    titles = list((await session.execute(stmt)).scalars().all())
    if not titles:
        return "No recent Newsroom stories available."
    return "\n".join(f"- {title}" for title in titles)


async def run_prelaunch_advisory(
    session: AsyncSession, gateway: LLMGateway, prompt_repository: PromptRepository, *,
    platform: SocialLaunchPlatform, now: datetime | None = None,
) -> PrelaunchAdvisoryExecutionResult:
    now = now or datetime.now(timezone.utc)
    budget = await check_social_advisory_budget(session, now=now)
    if not budget.allowed:
        return PrelaunchAdvisoryExecutionResult(platform=platform, advisory=None, run=None, budget_decision=budget.decision)

    launch_context = await get_current_context(session, platform)
    snapshot = await get_business_context_snapshot(session, now=now)
    business_context_summary = (
        f"{len(snapshot.active_campaigns)} active campaign(s), {len(snapshot.active_directives)} active directive(s), "
        f"{len(snapshot.approved_claims)} approved claim(s), {len(snapshot.restricted_claims)} restricted claim(s)."
    )
    opportunities_summary = await _recent_newsroom_opportunities_summary(session)

    try:
        advisory = await build_prelaunch_advisory(
            gateway, prompt_repository, platform=platform.value, launch_context=launch_context,
            business_context_summary=business_context_summary, newsroom_opportunities_summary=opportunities_summary,
        )
    except PrelaunchAdvisoryError as exc:
        return PrelaunchAdvisoryExecutionResult(
            platform=platform, advisory=None, run=None, budget_decision=budget.decision, error=str(exc),
        )

    launch_fingerprint = compute_launch_context_fingerprint(launch_context)
    run = await create_director_run(
        session, director_type=_PLATFORM_DIRECTOR_TYPE[platform], platform=platform.value, generated_at=now,
        input_fingerprint=launch_fingerprint or "no_launch_context",
        result_payload=_advisory_payload(advisory),
        status=DirectorRunStatus.OK if launch_context is not None else DirectorRunStatus.WAITING_FOR_DATA,
        decision=(advisory.launch_objectives[0][:100] if advisory.launch_objectives else "no launch objective identified"),
        business_context_fingerprint=compute_business_context_fingerprint(snapshot),
        launch_context_fingerprint=launch_fingerprint,
        model_provider=advisory.model_provider, model_name=advisory.model_name, cost_usd=advisory.cost_usd,
    )

    return PrelaunchAdvisoryExecutionResult(platform=platform, advisory=advisory, run=run, budget_decision=budget.decision)
