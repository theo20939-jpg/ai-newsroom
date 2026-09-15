"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1: the 5-state Product fact model
(UNKNOWN/UNDECIDED/PLANNED/CONFIRMED/DEPRECATED) and canonical fact-key normalization. Pure,
DB-free functions - no new model, no new table; every state is derived from the EXISTING
`Product.current_features`/`.planned_features`/`.undecided_facts` JSON-string-list columns (plus,
for DEPRECATED, an already-fetched `ProductContextVersion` history list the caller supplies), and
from `Product.status` for whole-product retirement.

`current_features`/`planned_features` hold human-readable feature NAMES (unchanged, pre-existing
convention). `undecided_facts` holds stable, ASCII, machine-readable canonical KEYS
("<feature_slug>.<aspect_slug>", e.g. "production_mode.billing") - a different identity space,
because "is this feature confirmed to exist" and "has a specific aspect of it been decided" are
different questions (a feature can be PLANNED while one of its aspects is still UNDECIDED at the
same time). Natural-language prose is never stored here - it lives in
ProductContextVersion.raw_instruction/structured_context (see services/product_context_service.py)."""
from __future__ import annotations

import enum
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database.models.product import Product
    from database.models.product_context_version import ProductContextVersion


class FactState(str, enum.Enum):
    """UNKNOWN != UNDECIDED (the one distinction this whole model exists to make): UNKNOWN is
    pure derived absence (nobody has ever said anything about this) - the state that should
    trigger a Director proactive question. UNDECIDED is itself a real, confirmed fact ("we
    discussed this and explicitly have not decided yet") and must never be re-derived from
    silence."""

    UNKNOWN = "unknown"
    UNDECIDED = "undecided"
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    DEPRECATED = "deprecated"


_FACT_KEY_SEGMENT_RE = re.compile(r"[^a-z0-9]+")


def _normalize_segment(raw: str) -> str:
    lowered = raw.strip().lower()
    normalized = _FACT_KEY_SEGMENT_RE.sub("_", lowered).strip("_")
    return normalized or "fact"


def normalize_fact_key(raw: str) -> str:
    """Normalizes an already-English/Latin canonical fact key (e.g. from the parser's own
    `feature_updates[].fact_key` extraction) into the stable `<feature_slug>.<aspect_slug>` shape
    - lowercase, non-alphanumeric runs collapsed to a single underscore, per dot-separated
    segment. Defensive normalization only (fixes "Production Mode.Billing" -> "production_mode.
    billing") - it does NOT translate/transliterate Cyrillic text into a meaningful key; the
    parser prompt is responsible for emitting an English/Latin key in the first place (spec:
    "Founder Plan Review" constraint #4)."""
    segments = raw.split(".")
    return ".".join(_normalize_segment(segment) for segment in segments)


def canonical_fact_key(feature_slug: str, aspect: str) -> str:
    return f"{_normalize_segment(feature_slug)}.{_normalize_segment(aspect)}"


def resolve_feature_state(
    product: "Product", feature_name: str, *, version_history: list["ProductContextVersion"] | None = None,
) -> FactState:
    """Resolves the state of a FEATURE (identified by its human-readable name, matching
    `current_features`/`planned_features` membership) - CONFIRMED/PLANNED/DEPRECATED/UNKNOWN.
    Never returns UNDECIDED (that state only applies to a specific fact key, see
    `resolve_undecided_fact_state` below - a feature's mere existence is not itself an "undecided
    fact" in this model)."""
    from database.models.product import ProductStatus

    is_current = feature_name in (product.current_features or [])
    is_planned = feature_name in (product.planned_features or [])
    whole_product_retired = product.status in (ProductStatus.PAUSED, ProductStatus.SUNSET)

    if is_current or is_planned:
        # A whole-product retirement deprecates every one of ITS ACTUAL features (even one never
        # otherwise explicitly removed) - but never a feature name that was never present in the
        # first place (that stays UNKNOWN below, even on a paused product - "the product is
        # retired" does not retroactively make up a feature history that never existed).
        if whole_product_retired:
            return FactState.DEPRECATED
        return FactState.CONFIRMED if is_current else FactState.PLANNED

    if version_history:
        for version in version_history:
            ctx = version.structured_context or {}
            removed = set(ctx.get("current_features_remove") or []) | set(ctx.get("planned_features_remove") or [])
            if feature_name in removed:
                return FactState.DEPRECATED
    return FactState.UNKNOWN


def resolve_undecided_fact_state(product: "Product", fact_key: str) -> FactState:
    """Resolves the state of a specific FACT (identified by its canonical key) -
    UNDECIDED if present in `Product.undecided_facts`, else UNKNOWN (pure absence - the state
    that should trigger a Director proactive question, never silently inferred as "decided
    against")."""
    key = normalize_fact_key(fact_key)
    if key in (product.undecided_facts or []):
        return FactState.UNDECIDED
    return FactState.UNKNOWN
