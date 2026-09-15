"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: services/product_fact_state.py - the 5-state Product
fact model (UNKNOWN/UNDECIDED/PLANNED/CONFIRMED/DEPRECATED). Pure functions, no DB - a plain
SimpleNamespace stands in for `Product`/`ProductContextVersion` (only the attributes the module
actually reads are needed)."""
from __future__ import annotations

from types import SimpleNamespace

from database.models.product import ProductStatus
from services.product_fact_state import (
    FactState,
    canonical_fact_key,
    normalize_fact_key,
    resolve_feature_state,
    resolve_undecided_fact_state,
)


def _product(**overrides) -> SimpleNamespace:
    base = dict(
        current_features=[], planned_features=[], undecided_facts=[], status=ProductStatus.DEVELOPMENT,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _version(structured_context: dict, created_at="2026-09-01") -> SimpleNamespace:
    return SimpleNamespace(structured_context=structured_context, created_at=created_at)


def test_unknown_is_pure_absence_not_undecided() -> None:
    """The addendum's own core distinction: a feature absent from every list is UNKNOWN, never
    UNDECIDED."""
    product = _product()
    assert resolve_feature_state(product, "Production Mode") == FactState.UNKNOWN
    assert resolve_undecided_fact_state(product, "production_mode.billing") == FactState.UNKNOWN


def test_confirmed_feature() -> None:
    product = _product(current_features=["Production Mode"])
    assert resolve_feature_state(product, "Production Mode") == FactState.CONFIRMED


def test_planned_feature() -> None:
    product = _product(planned_features=["Production Mode"])
    assert resolve_feature_state(product, "Production Mode") == FactState.PLANNED


def test_undecided_fact_is_explicit_not_inferred() -> None:
    product = _product(undecided_facts=["production_mode.billing"])
    assert resolve_undecided_fact_state(product, "production_mode.billing") == FactState.UNDECIDED
    # A DIFFERENT aspect of the same feature, never mentioned, stays UNKNOWN.
    assert resolve_undecided_fact_state(product, "production_mode.launch_date") == FactState.UNKNOWN


def test_undecided_state_independent_of_planned_state() -> None:
    """A feature can be PLANNED while one of its aspects is still UNDECIDED at the same time -
    two different identity spaces (feature name vs canonical fact key)."""
    product = _product(planned_features=["Production Mode"], undecided_facts=["production_mode.billing"])
    assert resolve_feature_state(product, "Production Mode") == FactState.PLANNED
    assert resolve_undecided_fact_state(product, "production_mode.billing") == FactState.UNDECIDED


def test_deprecated_via_product_status_paused() -> None:
    product = _product(current_features=["Old Feature"], status=ProductStatus.PAUSED)
    assert resolve_feature_state(product, "Old Feature") == FactState.DEPRECATED


def test_deprecated_via_product_status_sunset() -> None:
    product = _product(planned_features=["Old Feature"], status=ProductStatus.SUNSET)
    assert resolve_feature_state(product, "Old Feature") == FactState.DEPRECATED


def test_deprecated_via_removal_in_version_history() -> None:
    product = _product()
    history = [_version({"current_features_remove": ["Retired Feature"]})]
    assert resolve_feature_state(product, "Retired Feature", version_history=history) == FactState.DEPRECATED


def test_removal_from_planned_also_deprecates() -> None:
    product = _product()
    history = [_version({"planned_features_remove": ["Cancelled Feature"]})]
    assert resolve_feature_state(product, "Cancelled Feature", version_history=history) == FactState.DEPRECATED


def test_no_removal_in_history_stays_unknown() -> None:
    product = _product()
    history = [_version({"description": "unrelated change"})]
    assert resolve_feature_state(product, "Never Mentioned", version_history=history) == FactState.UNKNOWN


def test_canonical_fact_key_shape() -> None:
    assert canonical_fact_key("Production Mode", "Billing") == "production_mode.billing"
    assert canonical_fact_key("Web Search", "Public Availability") == "web_search.public_availability"


def test_normalize_fact_key_is_idempotent_and_defensive() -> None:
    assert normalize_fact_key("production_mode.billing") == "production_mode.billing"
    assert normalize_fact_key("Production Mode.Billing") == "production_mode.billing"
    assert normalize_fact_key("  Web-Search . Public Availability ") == "web_search.public_availability"
