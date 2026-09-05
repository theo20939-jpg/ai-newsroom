"""VISUAL-DESIGN-AUTONOMY-1A, spec §5-10: VisualBriefRevisionGenerator - the ONE LLM call that
drafts a persistent Designer Brief CANDIDATE from repeated-pattern evidence. Distinct from
services/visual_design_director.py's own generate_creative_direction() (a PER-POST prompt,
expected to change every call) - this module only ever runs after services/
visual_brief_adaptation_service.py has already confirmed REPEATED_PATTERN evidence exists for a
scope, and is expected to run rarely.

Architecture note (mirrors services/visual_design_director.py's own, and ultimately
services/instagram_creative_director.py's original precedent, exactly): a one-shot
capabilities/gateway_call.py::call_generate() call with a synthetic RuntimeContext - no
EditorialTask/Story to bind to. A Gateway failure has no sensible deterministic fallback (there is
no simpler algorithm that "rewrites a creative brief") - it raises a typed error, never fabricates
a candidate.

CRITICAL (spec §10): every generated candidate is checked against
services/visual_brand_core.py::check_brief_text_against_brand_core() AFTER generation, never
trusted to prompt discipline alone - a violation raises, the caller must not persist that
candidate."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.visual_brand_core import BRAND_CORE_RULES, check_brief_text_against_brand_core

PROMPT_NAME = "telegram_visual_brief_revision"
_PROMPT_VERSION = "1"


class BriefRevisionUnavailableError(Exception):
    """Raised when the Gateway call itself fails, or returns no usable structured output - no
    deterministic fallback exists for brief revision; callers must handle this explicitly, never
    fabricate a candidate in its place."""


class BriefRevisionBrandCoreViolationError(Exception):
    """Raised when a generated candidate violates VisualBrandCore - the candidate is REJECTED,
    never persisted, never silently sanitized."""


@dataclass(frozen=True)
class BriefRevisionContext:
    """Spec §5: bounded, compact, deterministic-summary-only - never the entire Newsroom history."""

    as_of: datetime
    scope: str
    brand_core_rules: list[str]
    active_brief_text: str
    active_brief_version: int
    adaptation_reason: str
    issue_code_distribution: dict[str, int]
    successful_history_summary: list[str]
    feed_context_summary: list[str]
    recent_art_director_feedback: list[str]
    budget_state_summary: str


@dataclass(frozen=True)
class CandidateBriefProposal:
    scope: str
    parent_brief_version_id: str
    candidate_brief_text: str
    change_summary: str
    reasoning: list[str] = field(default_factory=list)
    target_failure_patterns: list[str] = field(default_factory=list)
    expected_effects: list[str] = field(default_factory=list)
    known_risks: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    brand_core_rules_acknowledged: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    cost_usd: float | None = None


def build_brief_revision_context(
    *, scope: str, active_brief_text: str, active_brief_version: int, adaptation_reason: str,
    issue_code_distribution: dict[str, int], successful_history_summary: list[str],
    feed_context_summary: list[str], recent_art_director_feedback: list[str], budget_state_summary: str,
    now: datetime | None = None,
) -> BriefRevisionContext:
    return BriefRevisionContext(
        as_of=now or datetime.now(timezone.utc), scope=scope, brand_core_rules=list(BRAND_CORE_RULES),
        active_brief_text=active_brief_text, active_brief_version=active_brief_version,
        adaptation_reason=adaptation_reason, issue_code_distribution=issue_code_distribution,
        successful_history_summary=successful_history_summary, feed_context_summary=feed_context_summary,
        recent_art_director_feedback=recent_art_director_feedback, budget_state_summary=budget_state_summary,
    )


def _build_user_text(context: BriefRevisionContext) -> str:
    return "\n\n".join([
        f"SCOPE: {context.scope}",
        f"CURRENT BRIEF (v{context.active_brief_version}):\n{context.active_brief_text}",
        f"REASON FOR REVISION (REPEATED_PATTERN evidence - never a single incident): {context.adaptation_reason}",
        f"ISSUE CODE DISTRIBUTION (recent attempts): {context.issue_code_distribution}",
        "WHAT IS ALREADY WORKING (preserve where possible):\n" + "\n".join(f"- {line}" for line in context.successful_history_summary),
        "RECENT FEED CONTEXT (advisory only):\n" + "\n".join(f"- {line}" for line in context.feed_context_summary),
        "RECENT ART DIRECTOR FEEDBACK (advisory only):\n" + "\n".join(f"- {line}" for line in context.recent_art_director_feedback),
        f"BUDGET STATE: {context.budget_state_summary}",
    ])


async def generate_candidate_brief_proposal(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, context: BriefRevisionContext,
    parent_brief_version_id: str,
) -> CandidateBriefProposal:
    from capabilities.gateway_call import call_generate  # local import: avoids a capabilities<->services import cycle at module load time

    try:
        prompt = prompt_repository.resolve(PROMPT_NAME, _PROMPT_VERSION)
    except Exception as exc:
        raise BriefRevisionUnavailableError(f"prompt unavailable: {exc}") from exc

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    system_text += "\n\nIMMUTABLE BRAND CORE (never violate, never weaken):\n" + "\n".join(f"- {rule}" for rule in context.brand_core_rules)

    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=_build_user_text(context))]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=PROMPT_NAME, priority=TaskPriority.S,
        attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise BriefRevisionUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise BriefRevisionUnavailableError(str(outcome.error))

    response = outcome.response
    if response is None or response.structured_output is None:
        raise BriefRevisionUnavailableError("no structured output returned")
    output = response.structured_output

    candidate_text = output.get("candidate_brief_text", "")
    if not candidate_text.strip():
        raise BriefRevisionUnavailableError("model returned an empty candidate_brief_text")

    proposal = CandidateBriefProposal(
        scope=context.scope, parent_brief_version_id=parent_brief_version_id, candidate_brief_text=candidate_text,
        change_summary=output.get("change_summary", ""), reasoning=list(output.get("reasoning", [])),
        target_failure_patterns=list(output.get("target_failure_patterns", [])),
        expected_effects=list(output.get("expected_effects", [])), known_risks=list(output.get("known_risks", [])),
        evidence_refs=[f"issue_code_distribution:{context.issue_code_distribution}", f"reason:{context.adaptation_reason}"],
        confidence=float(output.get("confidence", 0.0)), brand_core_rules_acknowledged=list(context.brand_core_rules),
        model_provider=outcome.call.provider if outcome.call is not None else None,
        model_name=outcome.call.model_used if outcome.call is not None else None,
        cost_usd=None,  # no PricingCatalog integration in this phase's scope - never a fabricated known cost
    )

    brand_check = check_brief_text_against_brand_core(proposal.candidate_brief_text)
    if not brand_check.compliant:
        raise BriefRevisionBrandCoreViolationError(
            "generated candidate brief violates Brand Core: " + "; ".join(v.detail for v in brand_check.violations)
        )

    return proposal
