"""NINJA Social Intelligence Foundation, Part II §34/§35: BusinessContextProposal persistence +
the ONLY place canonical Business Context tables are ever mutated from a Telegram command. Mirrors
services/event_recap_review_service.py's own idempotent-immutable-once-final `set_decision()`
shape exactly, generalized to a multi-entity `proposed_change_set` (spec §25).

`confirm_proposal()` is the sole function that turns a proposal into real rows - it NEVER runs
from the parser directly (spec §32/§102: "Never let an LLM self-confirm its own proposed
mutation"), only from bot/handlers/business_context.py's own confirm callback, after an
already-authorized human has pressed Confirm."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.business_context_proposal import (
    BusinessContextCommandType,
    BusinessContextProposal,
    BusinessContextProposalStatus,
)
from database.models.business_context_shared import Visibility
from database.models.campaign_milestone import CampaignMilestone
from database.models.claim_policy import ClaimStatus
from database.models.product import ProductStatus
from database.models.product_event import ProductEventType
from services.campaign_service import create_campaign, create_milestone, list_upcoming_milestones, update_campaign
from services.claim_policy_service import create_claim_policy
from services.product_context_service import (
    create_product,
    create_product_context_version,
    create_product_event,
    get_product,
    get_product_by_slug,
    list_product_context_versions,
    list_products,
)
from services.strategic_directive_service import create_directive


class UnresolvedProductError(ValueError):
    """A change operation referenced a `product_slug` with no matching Product row and no
    accompanying `create_product` operation earlier in the same change set. Raised only inside
    `confirm_proposal()` - never silently ignored, since applying a partial change set would leave
    canonical state inconsistent with what the human actually confirmed."""


async def create_proposal(
    session: AsyncSession, *, command_type: BusinessContextCommandType, raw_instruction: str,
    proposed_change_set: list[dict[str, Any]], created_by: int, parsed_structure: dict[str, Any] | None = None,
    telegram_chat_id: int | None = None, telegram_topic_id: int | None = None,
    telegram_message_id: int | None = None, expires_at: datetime | None = None,
) -> BusinessContextProposal:
    proposal = BusinessContextProposal(
        command_type=command_type, raw_instruction=raw_instruction, proposed_change_set=proposed_change_set,
        parsed_structure=parsed_structure, created_by=created_by, telegram_chat_id=telegram_chat_id,
        telegram_topic_id=telegram_topic_id, telegram_message_id=telegram_message_id, expires_at=expires_at,
    )
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def get_proposal(session: AsyncSession, proposal_id: UUID) -> BusinessContextProposal | None:
    return await session.get(BusinessContextProposal, proposal_id)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


async def _resolve_product_id(
    session: AsyncSession, op: dict[str, Any], slug_to_id: dict[str, UUID],
) -> UUID:
    slug = op.get("product_slug")
    if slug is None:
        raise UnresolvedProductError(f"change operation missing product_slug: {op}")
    if slug in slug_to_id:
        return slug_to_id[slug]
    product = await get_product_by_slug(session, slug)
    if product is None:
        raise UnresolvedProductError(f"no Product found for slug {slug!r} and no prior create_product op")
    slug_to_id[slug] = product.id
    return product.id


async def _apply_change_operation(
    session: AsyncSession, op: dict[str, Any], *, decided_by: int, slug_to_id: dict[str, UUID],
) -> str:
    """Applies exactly one change-set entry, returns a string identifier of the row it produced
    (added to `BusinessContextProposal.resulting_version_ids` for auditability)."""
    entity_type = op["entity_type"]

    if entity_type == "product":
        status = ProductStatus(op["status"]) if op.get("status") else ProductStatus.IDEA
        product = await create_product(session, slug=op["slug"], name=op["name"], status=status)
        slug_to_id[op["slug"]] = product.id
        return f"product:{product.id}"

    if entity_type == "product_context_version":
        product_id = await _resolve_product_id(session, op, slug_to_id)
        version = await create_product_context_version(
            session, product_id=product_id, raw_instruction=op.get("raw_instruction", ""),
            structured_context=op.get("structured_context", {}), confirmed_by=decided_by,
        )
        return f"product_context_version:{version.id}"

    if entity_type == "product_event":
        product_id = await _resolve_product_id(session, op, slug_to_id)
        event_at = _parse_dt(op["event_at"])
        assert event_at is not None, "product_event operation must carry a real event_at"
        event = await create_product_event(
            session, product_id=product_id, event_type=ProductEventType(op["event_type"]),
            title=op["title"], event_at=event_at, description=op.get("description"),
            importance=op.get("importance", 100),
            visibility=Visibility(op.get("visibility", Visibility.INTERNAL_ONLY.value)),
            raw_instruction=op.get("raw_instruction"), structured_payload=op.get("structured_payload"),
        )
        return f"product_event:{event.id}"

    if entity_type == "campaign" and op.get("action") == "update":
        campaign = await update_campaign(
            session, UUID(op["campaign_id"]), structured_context=op.get("structured_context", {}),
        )
        if campaign is None:
            raise UnresolvedProductError(f"no LaunchCampaign found for id {op['campaign_id']!r}")
        return f"campaign:{campaign.id}"

    if entity_type == "campaign":
        product_id = await _resolve_product_id(session, op, slug_to_id)
        campaign = await create_campaign(
            session, product_id=product_id, name=op["name"], structured_context=op.get("structured_context"),
        )
        return f"campaign:{campaign.id}"

    if entity_type == "campaign_milestone":
        product_id = await _resolve_product_id(session, op, slug_to_id)
        milestone_at = _parse_dt(op["milestone_at"])
        assert milestone_at is not None, "campaign_milestone operation must carry a real milestone_at"
        milestone: CampaignMilestone = await create_milestone(
            session, product_id=product_id,
            campaign_id=UUID(op["campaign_id"]) if op.get("campaign_id") else None,
            title=op["title"], milestone_at=milestone_at, type=op.get("type"),
            description=op.get("description"), importance=op.get("importance", 100),
            visibility=Visibility(op.get("visibility", Visibility.INTERNAL_ONLY.value)),
            publicity_allowed=bool(op.get("publicity_allowed", False)),
            asset_preparation_allowed=bool(op.get("asset_preparation_allowed", False)),
        )
        return f"campaign_milestone:{milestone.id}"

    if entity_type == "strategic_directive":
        directive = await create_directive(
            session, instruction=op["instruction"], valid_from=_parse_dt(op["valid_from"]) or datetime.now(timezone.utc),
            created_by=decided_by, valid_until=_parse_dt(op.get("valid_until")), priority=op.get("priority", 100),
            scope=op.get("scope"), products=op.get("products"), platforms=op.get("platforms"),
        )
        return f"strategic_directive:{directive.id}"

    if entity_type == "claim_policy":
        product_id = await _resolve_product_id(session, op, slug_to_id)
        claim = await create_claim_policy(
            session, product_id=product_id, claim_text=op["claim_text"], status=ClaimStatus(op["status"]),
            campaign_id=UUID(op["campaign_id"]) if op.get("campaign_id") else None,
            embargoed_until=_parse_dt(op.get("embargoed_until")), notes=op.get("notes"),
        )
        return f"claim_policy:{claim.id}"

    raise UnresolvedProductError(f"unknown entity_type in change operation: {entity_type!r}")


async def confirm_proposal(
    session: AsyncSession, proposal_id: UUID, *, decided_by: int,
) -> BusinessContextProposal | None:
    """Idempotent and immutable-once-final, byte-for-byte the same policy services/event_recap_
    review_service.py::set_decision() already established: a second CONFIRM on an already-final
    proposal is a no-op returning the unchanged row, never a duplicate application of the change
    set. Applies every operation in `proposed_change_set`, in order, within this one call - if any
    operation fails, the exception propagates and the whole transaction is expected to be rolled
    back by the caller (no partial canonical state)."""
    proposal = await session.get(BusinessContextProposal, proposal_id)
    if proposal is None:
        return None
    if proposal.status != BusinessContextProposalStatus.PENDING:
        return proposal

    slug_to_id: dict[str, UUID] = {}
    resulting_ids: list[str] = []
    for op in proposal.proposed_change_set:
        resulting_ids.append(await _apply_change_operation(session, op, decided_by=decided_by, slug_to_id=slug_to_id))

    proposal.status = BusinessContextProposalStatus.CONFIRMED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by = decided_by
    proposal.resulting_version_ids = resulting_ids
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def cancel_proposal(session: AsyncSession, proposal_id: UUID, *, decided_by: int) -> BusinessContextProposal | None:
    """Idempotent: a second CANCEL (or a CANCEL on an already-CONFIRMED proposal) is a no-op
    returning the unchanged row - mirrors confirm_proposal()'s own immutable-once-final policy.
    Never mutates any canonical Business Context table."""
    proposal = await session.get(BusinessContextProposal, proposal_id)
    if proposal is None:
        return None
    if proposal.status != BusinessContextProposalStatus.PENDING:
        return proposal
    proposal.status = BusinessContextProposalStatus.CANCELLED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by = decided_by
    await session.commit()
    await session.refresh(proposal)
    return proposal


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: Director-initiated information needs + the shared
# reply-to/exactly-one-pending resolution rule ("Founder Plan Review" constraint #3 - natural-
# language confirmation safety must never guess which proposal a bare "да"/reply answers).
# ---------------------------------------------------------------------------

DIRECTOR_INITIATED_ORIGIN = "director_initiated"

# A director-initiated proposal's own `proposed_change_set` is empty (see module docstring) - a
# system-authored row has no real Telegram user id, so `created_by` (NOT NULL) uses this
# documented sentinel rather than a fabricated/borrowed human id.
_SYSTEM_CREATED_BY = 0


async def list_pending_proposals(
    session: AsyncSession, *, telegram_chat_id: int | None, telegram_topic_id: int | None,
) -> list[BusinessContextProposal]:
    """Every PENDING proposal (any origin) in one chat+topic, oldest first - the exact
    universe `resolve_target_proposal()` disambiguates over. A plain `COUNT`/`SELECT`, no new
    storage."""
    stmt = (
        select(BusinessContextProposal)
        .where(
            BusinessContextProposal.status == BusinessContextProposalStatus.PENDING,
            BusinessContextProposal.telegram_chat_id == telegram_chat_id,
            BusinessContextProposal.telegram_topic_id == telegram_topic_id,
        )
        .order_by(BusinessContextProposal.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def resolve_target_proposal(
    session: AsyncSession, *, telegram_chat_id: int | None, telegram_topic_id: int | None,
    reply_to_message_id: int | None,
) -> tuple[BusinessContextProposal | None, list[BusinessContextProposal]]:
    """The ONE shared resolution rule behind every natural-language reply this phase handles -
    confirming a mutation proposal with a bare "да", or answering a Director-initiated question.
    Returns `(resolved, pending)`: `resolved` is set ONLY when unambiguous - either
    `reply_to_message_id` matches exactly one PENDING proposal's own `telegram_message_id`, or
    (when it doesn't match any, or no reply was made) exactly one PENDING proposal exists in this
    chat+topic at all. Otherwise `resolved` is None and the caller must ask for clarification -
    this function NEVER guesses which proposal a message concerns."""
    pending = await list_pending_proposals(
        session, telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id,
    )
    if reply_to_message_id is not None:
        matches = [p for p in pending if p.telegram_message_id == reply_to_message_id]
        if len(matches) == 1:
            return matches[0], pending
    if len(pending) == 1:
        return pending[0], pending
    return None, pending


async def find_open_director_question(
    session: AsyncSession, *, product_slug: str, missing_fact: str,
) -> BusinessContextProposal | None:
    """Dedup lookup: an already-open (PENDING) director-initiated question for the exact same
    `(product_slug, missing_fact)` pair - `create_director_information_need()`'s own
    rate-limiting gate ("Deduplicate equivalent open questions")."""
    stmt = select(BusinessContextProposal).where(
        BusinessContextProposal.status == BusinessContextProposalStatus.PENDING,
        BusinessContextProposal.origin == DIRECTOR_INITIATED_ORIGIN,
    )
    for candidate in (await session.execute(stmt)).scalars().all():
        ctx = candidate.origin_context or {}
        if ctx.get("product_slug") == product_slug and ctx.get("missing_fact") == missing_fact:
            return candidate
    return None


async def create_director_information_need(
    session: AsyncSession, *, product_slug: str, missing_fact: str, opportunity_id: str,
    opportunity_source_type: str, question_text: str, telegram_chat_id: int | None = None,
    telegram_topic_id: int | None = None,
) -> BusinessContextProposal:
    """Creates (or, deduplicated, returns the existing) Director-initiated information-need
    proposal - the mechanism behind "a real PRODUCT opportunity is blocked by missing/stale truth,
    ask the Founder instead of inventing it". `origin_context` retains exactly what's needed to
    correlate a later Founder answer back to the opportunity that asked (spec: product_slug,
    missing_fact, opportunity_id, opportunity_source_type) - a plain JSON blob, not a new model,
    since there is no persisted opportunity row to FK to (ContentOpportunity is rebuilt fresh every
    cycle)."""
    existing = await find_open_director_question(session, product_slug=product_slug, missing_fact=missing_fact)
    if existing is not None:
        return existing

    proposal = BusinessContextProposal(
        command_type=BusinessContextCommandType.CONTEXT,
        status=BusinessContextProposalStatus.PENDING,
        raw_instruction=f"[director_initiated] {question_text}",
        proposed_change_set=[],
        origin=DIRECTOR_INITIATED_ORIGIN,
        question_text=question_text,
        origin_context={
            "product_slug": product_slug, "missing_fact": missing_fact,
            "opportunity_id": opportunity_id, "opportunity_source_type": opportunity_source_type,
        },
        created_by=_SYSTEM_CREATED_BY, telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id,
    )
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def close_answered_question(session: AsyncSession, proposal_id: UUID, *, answered_by: int) -> BusinessContextProposal | None:
    """Marks a Director-initiated question no longer open once the Founder's natural-language
    answer has produced its own new (separate, still-PENDING-for-confirmation) proposal - reuses
    the existing CANCELLED status verbatim (idempotent, via `cancel_proposal()`) rather than adding
    a new status value to the enum (which would need its own migration) - "cancelled" here means
    "no longer awaiting an answer", not "the Founder rejected it"."""
    return await cancel_proposal(session, proposal_id, decided_by=answered_by)


_DEFAULT_UNDECIDED_REASK_COOLDOWN = timedelta(days=14)
_DEFAULT_MILESTONE_LOOKAHEAD = timedelta(days=14)


async def scan_for_director_information_needs(
    session: AsyncSession, *, now: datetime, telegram_chat_id: int | None = None,
    telegram_topic_id: int | None = None, undecided_reask_cooldown: timedelta = _DEFAULT_UNDECIDED_REASK_COOLDOWN,
    milestone_lookahead: timedelta = _DEFAULT_MILESTONE_LOOKAHEAD,
) -> list[BusinessContextProposal]:
    """Conservative, deterministic, zero-LLM proactive scan over CURRENT Business Context state
    (no Trend Radar dependency - Phase 1 explicitly does not require it). Produces at most a small
    number of NEW Director-initiated information-need proposals, each deduplicated via
    `create_director_information_need()`'s own open-question check, so calling this repeatedly
    (e.g. once per content_worker cycle, once Phase 2 wires it in) never floods the Founder with
    repeated identical questions.

    Two concrete, testable rules implemented in Phase 1 (a deliberately narrow, disclosed subset -
    "meaningful editorial gaps"/"obvious product/content opportunities from current context" are
    Phase 2 territory, since they need the opportunity-construction logic that phase introduces):

    1. A still-UNDECIDED fact is only re-asked after `undecided_reask_cooldown` has passed since
       it was first recorded (via the most recent ProductContextVersion that added it) - never on
       every scan (spec: "Deduplicate equivalent open questions" / "just-in-time, not noisy").
    2. An upcoming CampaignMilestone (within `milestone_lookahead`) with asset preparation allowed
       but no product context update since the milestone was created - flags a real, concrete gap
       ("we're about to need content for this and don't know enough yet") rather than inventing
       one."""
    created: list[BusinessContextProposal] = []

    for product in await list_products(session):
        for fact_key in product.undecided_facts or []:
            versions = await list_product_context_versions(session, product.id)
            recorded_at = None
            for version in versions:
                if fact_key in (version.structured_context or {}).get("undecided_facts_add", []):
                    recorded_at = version.created_at
                    break  # versions are newest-first; the first match is the most recent record
            if recorded_at is not None and (now - recorded_at) < undecided_reask_cooldown:
                continue
            question = (
                f"Прошло время с тех пор, как «{fact_key}» для {product.name} было отмечено как "
                "нерешённое - актуально ли это ещё, или уже есть ответ?"
            )
            proposal = await create_director_information_need(
                session, product_slug=product.slug, missing_fact=fact_key,
                opportunity_id=f"stale_undecided:{product.slug}:{fact_key}",
                opportunity_source_type="PRODUCT", question_text=question,
                telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id,
            )
            created.append(proposal)

    for milestone in await list_upcoming_milestones(session, now=now, days=milestone_lookahead.days):
        if not milestone.asset_preparation_allowed:
            continue
        milestone_product = await get_product(session, milestone.product_id)
        if milestone_product is None:
            continue
        versions = await list_product_context_versions(session, milestone_product.id)
        has_fresh_context = any(v.created_at >= milestone.created_at for v in versions)
        if has_fresh_context:
            continue
        missing_fact = f"milestone.{milestone.id}.asset_readiness"
        question = (
            f"Приближается milestone «{milestone.title}» для {milestone_product.name} "
            f"({milestone.milestone_at.date().isoformat()}), для которого разрешена подготовка "
            "материалов - что нужно знать, чтобы начать готовить контент?"
        )
        proposal = await create_director_information_need(
            session, product_slug=milestone_product.slug, missing_fact=missing_fact,
            opportunity_id=f"approaching_milestone:{milestone.id}", opportunity_source_type="PRODUCT",
            question_text=question, telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id,
        )
        created.append(proposal)

    return created
