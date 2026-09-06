"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §17-23: build_prelaunch_advisory() - the cross-platform
pre-launch advisory capability. Unlike services/telegram_strategy_director.py /
services/telegram_growth_director.py / services/instagram_growth_strategist.py (all deterministic,
zero-Gateway-call derivations over structured input), this genuinely needs real language reasoning
- "prepare a rebrand sequence", "propose first content pillars for an empty account" are not
mechanically derivable from counters the way "posts_24h > threshold" is. Mirrors services/
visual_design_director.py's own one-shot call_generate() shape (a real Gateway call, real cost,
bounded by services/social_advisory_budget_service.py - never called from a read command).

CRITICAL (spec §2/§11): this function's OWN prompt (prompts/social_prelaunch_advisory/v1.yaml)
enforces the STRATEGIC_KNOWLEDGE vs FIRST_PARTY_PERFORMANCE_KNOWLEDGE boundary this whole phase
exists to protect - it is instructed to reason from founder directives/campaign context/newsroom
opportunities/cold-start evidence limitations, and explicitly never claim NINJA PULSE performance
that does not exist yet."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from database.models.social_launch_context import SocialLaunchContext
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext

ADVISORY_PROMPT_NAME = "social_prelaunch_advisory"
ADVISORY_PROMPT_VERSION = "1"


class PrelaunchAdvisoryError(Exception):
    """Wraps a Gateway failure - callers must show a plain failure message, never a raw traceback,
    and must never persist a fabricated DirectorRun over a failed call."""


@dataclass(frozen=True)
class PrelaunchAdvisory:
    current_state: str
    target_state: str
    launch_objectives: list[str] = field(default_factory=list)
    transition_tasks: list[str] = field(default_factory=list)
    content_pillars: list[str] = field(default_factory=list)
    initial_content_sequence: list[str] = field(default_factory=list)
    cadence_hypothesis: str = ""
    format_hypotheses: list[str] = field(default_factory=list)
    visual_direction: str = ""
    profile_setup: list[str] = field(default_factory=list)
    pinned_intro_content: list[str] = field(default_factory=list)
    first_learning_questions: list[str] = field(default_factory=list)
    measurement_plan: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    cost_usd: float | None = None  # no PricingCatalog integration in this phase's scope


def _context_summary(context: SocialLaunchContext | None) -> str:
    if context is None:
        return "No SocialLaunchContext configured yet for this platform - genuinely COLD_START, no founder instruction recorded."
    return (
        f"target_identity={context.target_identity}, current_identity={context.current_identity or 'n/a'}, "
        f"launch_state={context.launch_state.value}, planned_launch_at={context.planned_launch_at or 'unscheduled'}, "
        f"launch_date_status={context.launch_date_status.value}, baseline_policy={context.baseline_policy.value}, "
        f"historical_content_policy={context.historical_content_policy.value}, "
        f"learning_start_at={context.learning_start_at or 'not started - no first-party evidence exists yet'}, "
        f"raw_instruction={context.raw_instruction!r}"
    )


async def build_prelaunch_advisory(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, platform: str,
    launch_context: SocialLaunchContext | None, business_context_summary: str,
    newsroom_opportunities_summary: str,
) -> PrelaunchAdvisory:
    prompt = prompt_repository.resolve(ADVISORY_PROMPT_NAME, ADVISORY_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    user_text = (
        f"PLATFORM: {platform}\n\nLAUNCH CONTEXT:\n{_context_summary(launch_context)}\n\n"
        f"BUSINESS CONTEXT:\n{business_context_summary}\n\n"
        f"NEWSROOM OPPORTUNITIES:\n{newsroom_opportunities_summary}"
    )
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=user_text)]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=ADVISORY_PROMPT_NAME, priority=TaskPriority.C,
        attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise PrelaunchAdvisoryError(str(exc)) from exc
    if outcome.error is not None:
        raise PrelaunchAdvisoryError(str(outcome.error))
    assert outcome.response is not None
    output = outcome.response.structured_output or {}

    return PrelaunchAdvisory(
        current_state=output.get("current_state", ""), target_state=output.get("target_state", ""),
        launch_objectives=list(output.get("launch_objectives") or []),
        transition_tasks=list(output.get("transition_tasks") or []),
        content_pillars=list(output.get("content_pillars") or []),
        initial_content_sequence=list(output.get("initial_content_sequence") or []),
        cadence_hypothesis=output.get("cadence_hypothesis", ""),
        format_hypotheses=list(output.get("format_hypotheses") or []),
        visual_direction=output.get("visual_direction", ""),
        profile_setup=list(output.get("profile_setup") or []),
        pinned_intro_content=list(output.get("pinned_intro_content") or []),
        first_learning_questions=list(output.get("first_learning_questions") or []),
        measurement_plan=list(output.get("measurement_plan") or []),
        risks=list(output.get("risks") or []),
        model_provider=outcome.call.provider, model_name=outcome.call.model_used,
    )
