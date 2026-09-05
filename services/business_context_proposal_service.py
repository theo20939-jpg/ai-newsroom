"""NINJA Social Intelligence Foundation, Part II §34/§35: BusinessContextProposal persistence +
the ONLY place canonical Business Context tables are ever mutated from a Telegram command. Mirrors
services/event_recap_review_service.py's own idempotent-immutable-once-final `set_decision()`
shape exactly, generalized to a multi-entity `proposed_change_set` (spec §25).

`confirm_proposal()` is the sole function that turns a proposal into real rows - it NEVER runs
from the parser directly (spec §32/§102: "Never let an LLM self-confirm its own proposed
mutation"), only from bot/handlers/business_context.py's own confirm callback, after an
already-authorized human has pressed Confirm."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

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
from services.campaign_service import create_campaign, create_milestone, update_campaign
from services.claim_policy_service import create_claim_policy
from services.product_context_service import (
    create_product,
    create_product_context_version,
    create_product_event,
    get_product_by_slug,
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
