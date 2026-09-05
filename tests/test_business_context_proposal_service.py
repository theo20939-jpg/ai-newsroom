"""NINJA Social Intelligence Foundation §34/§35/§105: BusinessContextProposal create -> confirm/
cancel. Mirrors tests/test_event_recap_review_service.py's own conventions - real db_session,
@pytest.mark.asyncio on every test, a small local helper building any real FK rows needed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.business_context_proposal import BusinessContextCommandType, BusinessContextProposalStatus
from database.models.campaign import LaunchCampaign
from database.models.claim_policy import ClaimPolicy
from database.models.product import Product
from database.models.product_context_version import ProductContextVersion
from services.business_context_proposal_service import cancel_proposal, confirm_proposal, create_proposal, get_proposal
from services.product_context_service import create_product


@pytest.mark.asyncio
async def test_create_proposal_is_pending_and_does_not_mutate_canonical_state(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="test raw text",
        proposed_change_set=[{"entity_type": "product", "slug": "testprod1", "name": "Test Product", "status": None}],
        created_by=1,
    )
    assert proposal.status == BusinessContextProposalStatus.PENDING

    count = (await db_session.execute(select(func.count()).select_from(Product).where(Product.slug == "testprod1"))).scalar_one()
    assert count == 0, "canonical Product must not exist before confirmation"


@pytest.mark.asyncio
async def test_confirm_applies_change_set_and_persists_raw_instruction(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="NINJA Store в разработке",
        proposed_change_set=[{"entity_type": "product", "slug": "testprod2", "name": "Test Product 2", "status": "development"}],
        created_by=42,
    )
    confirmed = await confirm_proposal(db_session, proposal.id, decided_by=42)
    assert confirmed is not None
    assert confirmed.status == BusinessContextProposalStatus.CONFIRMED
    assert confirmed.decided_by == 42
    assert confirmed.resulting_version_ids and confirmed.resulting_version_ids[0].startswith("product:")

    product = (await db_session.execute(select(Product).where(Product.slug == "testprod2"))).scalar_one()
    assert product.name == "Test Product 2"
    assert product.status.value == "development"
    # Raw instruction retained on the proposal itself (spec §35's own audit-trail requirement).
    assert confirmed.raw_instruction == "NINJA Store в разработке"


@pytest.mark.asyncio
async def test_confirm_is_idempotent_no_duplicate_rows_on_repeated_confirm(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="x",
        proposed_change_set=[{"entity_type": "product", "slug": "testprod3", "name": "Test Product 3", "status": None}],
        created_by=1,
    )
    first = await confirm_proposal(db_session, proposal.id, decided_by=1)
    second = await confirm_proposal(db_session, proposal.id, decided_by=999)  # even a different decider
    assert first is not None and second is not None
    assert first.decided_by == second.decided_by == 1, "second confirm must not overwrite the original decider"

    count = (await db_session.execute(select(func.count()).select_from(Product).where(Product.slug == "testprod3"))).scalar_one()
    assert count == 1, "repeated confirm must never create a duplicate Product row"


@pytest.mark.asyncio
async def test_cancel_persists_nothing_to_canonical_tables(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="x",
        proposed_change_set=[{"entity_type": "product", "slug": "testprod4", "name": "Test Product 4", "status": None}],
        created_by=1,
    )
    cancelled = await cancel_proposal(db_session, proposal.id, decided_by=1)
    assert cancelled is not None
    assert cancelled.status == BusinessContextProposalStatus.CANCELLED

    count = (await db_session.execute(select(func.count()).select_from(Product).where(Product.slug == "testprod4"))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_cancel_is_idempotent(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="x",
        proposed_change_set=[{"entity_type": "product", "slug": "testprod5", "name": "x", "status": None}],
        created_by=7,
    )
    first = await cancel_proposal(db_session, proposal.id, decided_by=7)
    second = await cancel_proposal(db_session, proposal.id, decided_by=999)
    assert first is not None and second is not None
    assert first.decided_by == second.decided_by == 7


@pytest.mark.asyncio
async def test_cancel_after_confirm_is_a_noop(db_session: AsyncSession) -> None:
    """A proposal is immutable once final in EITHER direction - confirm-then-cancel must never
    flip a CONFIRMED proposal back to CANCELLED."""
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="x",
        proposed_change_set=[{"entity_type": "product", "slug": "testprod6", "name": "x", "status": None}],
        created_by=1,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=1)
    result = await cancel_proposal(db_session, proposal.id, decided_by=1)
    assert result is not None
    assert result.status == BusinessContextProposalStatus.CONFIRMED


@pytest.mark.asyncio
async def test_confirm_on_nonexistent_proposal_returns_none_never_raises(db_session: AsyncSession) -> None:
    from uuid import uuid4
    result = await confirm_proposal(db_session, uuid4(), decided_by=1)
    assert result is None


@pytest.mark.asyncio
async def test_multi_entity_change_set_creates_product_and_campaign_together(db_session: AsyncSession) -> None:
    """Spec §25: a single /context proposal may span multiple entity types - all applied in one
    confirm() call."""
    proposal = await create_proposal(
        db_session, command_type=BusinessContextCommandType.CONTEXT, raw_instruction="multi-entity test",
        proposed_change_set=[
            {"entity_type": "product", "slug": "multitest", "name": "Multi Test Product", "status": "pre_launch"},
            {
                "entity_type": "campaign", "product_slug": "multitest", "name": "Multi Test Launch",
                "structured_context": {"status": "tentative", "date_confidence": "estimated"},
            },
            {
                "entity_type": "claim_policy", "product_slug": "multitest", "claim_text": "price not disclosed",
                "status": "embargoed",
            },
        ],
        created_by=1,
    )
    confirmed = await confirm_proposal(db_session, proposal.id, decided_by=1)
    assert confirmed is not None
    assert confirmed.resulting_version_ids is not None
    assert len(confirmed.resulting_version_ids) == 3

    product = (await db_session.execute(select(Product).where(Product.slug == "multitest"))).scalar_one()
    campaign = (await db_session.execute(select(LaunchCampaign).where(LaunchCampaign.product_id == product.id))).scalar_one()
    assert campaign.status.value == "tentative"
    assert campaign.date_confidence.value == "estimated"

    claim = (await db_session.execute(select(ClaimPolicy).where(ClaimPolicy.product_id == product.id))).scalar_one()
    assert claim.status.value == "embargoed"


@pytest.mark.asyncio
async def test_product_context_version_records_raw_instruction_and_supersedes_chain(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="versiontest", name="Version Test")

    p1 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="first update",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": "versiontest",
            "raw_instruction": "first update", "structured_context": {"description": "v1 description"},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, p1.id, decided_by=1)

    p2 = await create_proposal(
        db_session, command_type=BusinessContextCommandType.PRODUCT, raw_instruction="second update",
        proposed_change_set=[{
            "entity_type": "product_context_version", "product_slug": "versiontest",
            "raw_instruction": "second update", "structured_context": {"description": "v2 description"},
        }],
        created_by=1,
    )
    await confirm_proposal(db_session, p2.id, decided_by=1)

    versions = list((await db_session.execute(
        select(ProductContextVersion).where(ProductContextVersion.product_id == product.id).order_by(ProductContextVersion.version)
    )).scalars().all())
    assert len(versions) == 2
    assert versions[0].version == 1
    assert versions[1].version == 2
    assert versions[1].supersedes_id == versions[0].id
    assert versions[0].raw_instruction == "first update"

    await db_session.refresh(product)
    assert product.description == "v2 description"
