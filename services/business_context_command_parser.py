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
from services.product_fact_state import normalize_fact_key

PARSER_PROMPT_NAME = "business_context_parser"
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: v2 adds `products_mentioned[].feature_updates` (fact_key/
# feature_name/fact_state - the 5-state Product fact model's extraction surface, see
# services/product_fact_state.py) - v1.yaml is left byte-identical/unused going forward, mirroring
# this codebase's own established versioned-prompt convention (e.g. prompts/copywriting/v*.yaml)
# rather than editing a shipped prompt version in place.
#
# HOTFIX (live production diagnosis): v3 fixes a structured-output contract bug present since v1 -
# OpenAI's strict `response_format="json_schema"` mode requires every key in an object's
# `properties` to also appear in that object's `required` array (an "optional" field is expressed
# by unioning its type with null, never by omitting it from `required`). v1/v2 never satisfied
# this for any nested object with an optional field, so every real provider request was rejected
# with a 400 `invalid_json_schema` error before any output was ever generated - confirmed live via
# the exact 400 response body, not guessed. v3 is schema-shape-only; every field's real-world
# meaning is unchanged. See prompts/business_context_parser/v3.yaml's own header for detail.
PARSER_PROMPT_VERSION = "3"


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


def _feature_update_fields(feature_updates: list[dict[str, Any]]) -> dict[str, Any]:
    """Converts the parser's `feature_updates` extraction (fact_key/feature_name/fact_state) into
    services/product_context_service.py's own additive `*_add`/`*_remove` pseudo-fields - see
    that module's `_PRODUCT_LIST_MERGE_FIELDS` for why these are deltas, never a wholesale-replace
    list. "confirmed"/"planned" name the FEATURE (current_features/planned_features, by human-
    readable name); "undecided" names the FACT (undecided_facts, by canonical fact_key) - two
    different identity spaces, matching services/product_fact_state.py's own distinction."""
    current_add: list[str] = []
    planned_add: list[str] = []
    undecided_add: list[str] = []
    for update in feature_updates:
        state = update.get("fact_state")
        if state == "confirmed":
            current_add.append(update["feature_name"])
        elif state == "planned":
            planned_add.append(update["feature_name"])
        elif state == "undecided":
            undecided_add.append(normalize_fact_key(update["fact_key"]))

    fields: dict[str, Any] = {}
    if current_add:
        fields["current_features_add"] = current_add
    if planned_add:
        fields["planned_features_add"] = planned_add
    if undecided_add:
        fields["undecided_facts_add"] = undecided_add
    return fields


def build_change_set(extraction: BusinessContextExtraction, *, raw_text: str = "") -> list[dict[str, Any]]:
    """Deterministic conversion from the LLM's extraction shape into
    services/business_context_proposal_service.py's own internal change-operation shape. Kept
    entirely separate from the extraction step itself so the DB-write contract never depends on
    exactly matching whatever JSON shape a future prompt version happens to emit.

    `raw_text` (the original human message) is threaded through onto every `product_context_
    version` operation's own `raw_instruction` field - previously hardcoded to "", losing
    provenance despite `ProductContextVersion.raw_instruction` existing specifically to answer
    "what did the human actually say" (fixed as part of Phase 1, since the Director conversational
    extension's own audit trail requirement depends on this being real)."""
    change_set: list[dict[str, Any]] = []

    for product in extraction.products_mentioned:
        change_set.append({
            "entity_type": "product", "slug": product["slug"], "name": product["name"],
            "status": product.get("status"),
        })
        context_fields = {
            k: v for k, v in product.items() if k in ("current_stage", "description") and v is not None
        }
        context_fields.update(_feature_update_fields(product.get("feature_updates") or []))
        if context_fields:
            change_set.append({
                "entity_type": "product_context_version", "product_slug": product["slug"],
                "raw_instruction": raw_text, "structured_context": context_fields,
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
        visibility = milestone.get("visibility")
        publicity_allowed = milestone.get("publicity_allowed")
        asset_preparation_allowed = milestone.get("asset_preparation_allowed")
        change_set.append({
            "entity_type": "campaign_milestone", "product_slug": milestone["product_slug"],
            "title": milestone["title"], "milestone_at": milestone.get("milestone_at"),
            "visibility": visibility if visibility is not None else "internal_only",
            "publicity_allowed": publicity_allowed if publicity_allowed is not None else False,
            "asset_preparation_allowed": (
                asset_preparation_allowed if asset_preparation_allowed is not None else False
            ),
        })

    for directive in extraction.directives:
        priority = directive.get("priority")
        change_set.append({
            "entity_type": "strategic_directive", "instruction": directive["instruction"],
            "valid_from": None, "valid_until": directive.get("valid_until"),
            "priority": priority if priority is not None else 100, "scope": directive.get("scope"),
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
