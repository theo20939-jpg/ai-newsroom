"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: services/product_context_service.py's new list-merge
convention (`current_features_add/remove`, `planned_features_add/remove`,
`undecided_facts_add/remove`) - a single natural-language message states only the DELTA, never
the full list, so `create_product_context_version()` must merge, never wholesale-replace, these
three fields (unlike every other scalar field, which still replaces)."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.product_context_service import create_product, create_product_context_version, get_product


@pytest.mark.asyncio
async def test_current_features_add_is_additive_not_a_replace(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="mergetest1", name="Merge Test 1")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="added feature A",
        structured_context={"current_features_add": ["Feature A"]}, confirmed_by=1,
    )
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="added feature B",
        structured_context={"current_features_add": ["Feature B"]}, confirmed_by=1,
    )
    reloaded = await get_product(db_session, product.id)
    assert reloaded is not None
    assert reloaded.current_features == ["Feature A", "Feature B"]


@pytest.mark.asyncio
async def test_adding_the_same_feature_twice_does_not_duplicate(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="mergetest2", name="Merge Test 2")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="x",
        structured_context={"planned_features_add": ["Production Mode"]}, confirmed_by=1,
    )
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="y",
        structured_context={"planned_features_add": ["Production Mode"]}, confirmed_by=1,
    )
    reloaded = await get_product(db_session, product.id)
    assert reloaded is not None
    assert reloaded.planned_features == ["Production Mode"]


@pytest.mark.asyncio
async def test_planned_feature_can_later_be_promoted_to_current(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="mergetest3", name="Merge Test 3")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="planned",
        structured_context={"planned_features_add": ["Production Mode"]}, confirmed_by=1,
    )
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="promote",
        structured_context={
            "planned_features_remove": ["Production Mode"], "current_features_add": ["Production Mode"],
        },
        confirmed_by=1,
    )
    reloaded = await get_product(db_session, product.id)
    assert reloaded is not None
    assert reloaded.planned_features == []
    assert reloaded.current_features == ["Production Mode"]


@pytest.mark.asyncio
async def test_undecided_facts_add_and_remove_use_canonical_keys(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="mergetest4", name="Merge Test 4")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="undecided",
        structured_context={"undecided_facts_add": ["Production Mode.Billing"]}, confirmed_by=1,
    )
    reloaded = await get_product(db_session, product.id)
    assert reloaded is not None
    # Stored normalized (lowercase, underscore-joined), not verbatim as extracted.
    assert reloaded.undecided_facts == ["production_mode.billing"]

    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="resolved",
        structured_context={"undecided_facts_remove": ["production_mode.billing"]}, confirmed_by=1,
    )
    reloaded = await get_product(db_session, product.id)
    assert reloaded is not None
    assert reloaded.undecided_facts == []


@pytest.mark.asyncio
async def test_scalar_fields_still_replace_not_merge(db_session: AsyncSession) -> None:
    """Regression guard: only the three list fields above changed behavior - `description` etc.
    must still be a plain wholesale replace, exactly as before this phase."""
    product = await create_product(db_session, slug="mergetest5", name="Merge Test 5")
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="v1",
        structured_context={"description": "first"}, confirmed_by=1,
    )
    await create_product_context_version(
        db_session, product_id=product.id, raw_instruction="v2",
        structured_context={"description": "second"}, confirmed_by=1,
    )
    reloaded = await get_product(db_session, product.id)
    assert reloaded is not None
    assert reloaded.description == "second"
