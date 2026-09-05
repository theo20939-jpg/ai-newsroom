"""NINJA Social Intelligence Foundation, Part II §32/§33: BusinessContextCommandParser. Turns one
free-text Telegram message into a structured, human-reviewable proposal - NEVER writes canonical
state itself (spec §102: "Never let an LLM self-confirm its own proposed mutation").

Architecture note: this repo's only existing path to the LLM Gateway is the full Capability +
CapabilityExecutor + WorkflowRunner + EditorialTask machinery (confirmed via forensic sweep - no
lighter-weight one-shot call exists anywhere). That machinery is workflow/Story-bound; a Telegram
command parse has no Story, no NewsEvent, no EditorialTask, and forcing one into existence merely
to satisfy the Capability contract would be a disproportionate, ill-fitting architecture graft.
Instead this module calls `capabilities/gateway_call.py::call_generate()` directly - the same
shared observability/error-classification/cost-accounting helper every real Capability already
uses internally - with a synthetic `RuntimeContext` (a fresh `task_id`/`event_id` that names no
real row; `call_generate()` only ever uses these two fields for observability metadata stamping,
never a DB lookup, confirmed by reading its own source). This reuses the codebase's real Gateway
plumbing without fabricating a task/workflow that does not exist."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.business_context_proposal import BusinessContextCommandType
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext

PARSER_PROMPT_NAME = "business_context_parser"
PARSER_PROMPT_VERSION = "1"


@dataclass(frozen=True)
class BusinessContextExtraction:
    """The parser's raw output - one field per prompt output_schema array, plus which command
    triggered it. Never applied to canonical tables directly; see `build_change_set()` below."""

    products_mentioned: list[dict[str, Any]] = field(default_factory=list)
    campaign_updates: list[dict[str, Any]] = field(default_factory=list)
    milestones: list[dict[str, Any]] = field(default_factory=list)
    directives: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    clarification_needed: list[str] = field(default_factory=list)


class BusinessContextParseError(Exception):
    """Wraps a `CapabilityError` from the underlying Gateway call - callers should show the user a
    plain "could not parse, try again" message, never a raw stack trace."""


async def parse_business_context_command(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, raw_text: str,
    context_summary_text: str, now: datetime,
) -> BusinessContextExtraction:
    prompt = prompt_repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    user_text = (
        f"CURRENT BUSINESS CONTEXT:\n{context_summary_text}\n\n"
        f"CURRENT DATE/TIME: {now.isoformat()}\n\n"
        f"MESSAGE TO PARSE:\n{raw_text}"
    )
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=user_text)]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )

    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name="business_context_parser",
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )
    outcome = await call_generate(gateway, request, runtime=runtime, sequence=1)
    if outcome.error is not None:
        raise BusinessContextParseError(str(outcome.error))
    assert outcome.response is not None
    output = outcome.response.structured_output or {}

    return BusinessContextExtraction(
        products_mentioned=output.get("products_mentioned", []),
        campaign_updates=output.get("campaign_updates", []),
        milestones=output.get("milestones", []),
        directives=output.get("directives", []),
        claims=output.get("claims", []),
        clarification_needed=output.get("clarification_needed", []),
    )


def build_change_set(extraction: BusinessContextExtraction) -> list[dict[str, Any]]:
    """Deterministic conversion from the LLM's extraction shape into
    services/business_context_proposal_service.py's own internal change-operation shape. Kept
    entirely separate from the extraction step itself so the DB-write contract never depends on
    exactly matching whatever JSON shape a future prompt version happens to emit."""
    change_set: list[dict[str, Any]] = []

    for product in extraction.products_mentioned:
        change_set.append({
            "entity_type": "product", "slug": product["slug"], "name": product["name"],
            "status": product.get("status"),
        })
        context_fields = {
            k: v for k, v in product.items() if k in ("current_stage", "description") and v is not None
        }
        if context_fields:
            change_set.append({
                "entity_type": "product_context_version", "product_slug": product["slug"],
                "raw_instruction": "", "structured_context": context_fields,
            })

    for update in extraction.campaign_updates:
        structured_context = {
            k: v for k, v in update.items()
            if k in (
                "status", "planned_launch_date", "date_confidence", "key_messages",
                "restricted_claims", "required_cta",
            ) and v is not None
        }
        change_set.append({
            "entity_type": "campaign", "product_slug": update["product_slug"],
            "name": update.get("campaign_name") or f"{update['product_slug']} campaign",
            "structured_context": structured_context,
        })

    for milestone in extraction.milestones:
        change_set.append({
            "entity_type": "campaign_milestone", "product_slug": milestone["product_slug"],
            "title": milestone["title"], "milestone_at": milestone.get("milestone_at"),
            "visibility": milestone.get("visibility", "internal_only"),
            "publicity_allowed": milestone.get("publicity_allowed", False),
            "asset_preparation_allowed": milestone.get("asset_preparation_allowed", False),
        })

    for directive in extraction.directives:
        change_set.append({
            "entity_type": "strategic_directive", "instruction": directive["instruction"],
            "valid_from": None, "valid_until": directive.get("valid_until"),
            "priority": directive.get("priority", 100), "scope": directive.get("scope"),
            "products": directive.get("products"),
        })

    for claim in extraction.claims:
        change_set.append({
            "entity_type": "claim_policy", "product_slug": claim["product_slug"],
            "claim_text": claim["claim_text"], "status": claim["status"],
            "embargoed_until": claim.get("embargoed_until"),
        })

    return change_set


def infer_command_type_from_change_set(change_set: list[dict[str, Any]]) -> BusinessContextCommandType:
    """Only used by /context (spec §25 - a universal command whose command_type is always CONTEXT
    regardless of what it produces); the 5 single-purpose commands set their own command_type
    directly at the call site instead of relying on inference."""
    return BusinessContextCommandType.CONTEXT
