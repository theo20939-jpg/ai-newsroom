"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 3: REEL production-script readiness -
CONCEPT_SCRIPT vs PRODUCTION_SCRIPT - computed by the CALLER building a REEL package (never by the
Creative Director itself), from the SAME 5-state Product fact model
`services/product_fact_state.py` already defines. Orthogonal to the existing QA/truthfulness gate
(`InstagramGateDecision` READY_FOR_EDITOR/HOLD/BLOCK, `services/instagram_editorial_gate.py`) -
this axis is about SCRIPT COMPLETENESS (are all required facts/assets known), never media/art
quality or truthfulness, and it never overrides that gate's own authority.

An UNKNOWN or UNDECIDED fact REQUIRED to truthfully state a PRODUCT-origin Reel's premise must
never be invented - the caller is expected to route that gap to the existing Director information-
need flow (`services.business_context_proposal_service.create_director_information_need()`)
INSTEAD of calling the Creative Director with fabricated evidence for it. This module only answers
"is anything still missing" - it never decides what to do about a gap, and it never talks to the
Creative Director or the Gateway itself (pure, DB-row-in/string-out)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.product_fact_state import FactState, resolve_feature_state, resolve_undecided_fact_state

if TYPE_CHECKING:
    from database.models.product import Product

CONCEPT_SCRIPT = "concept_script"
PRODUCTION_SCRIPT = "production_script"


def unresolved_required_facts(
    product: "Product", *, required_feature_names: list[str] | None = None,
    required_fact_keys: list[str] | None = None,
) -> list[str]:
    """The subset of `required_feature_names` that are still UNKNOWN (nobody has ever confirmed
    or planned them) plus the subset of `required_fact_keys` that are still UNDECIDED (explicitly
    flagged as "not decided yet") - i.e. every real, disclosed gap a truthful Reel about this
    Product currently has. A PLANNED or CONFIRMED feature is never "unresolved" here - a PLANNED
    feature can still be discussed truthfully (as upcoming, not live); that presentation nuance is
    the Creative Director's job, given accurate evidence, not this function's. DEPRECATED features
    are deliberately NOT surfaced as "unresolved" by this function - a deprecated feature is a
    reason to reject/skip the Reel premise entirely (never present a retired feature as live), a
    different, disclosed decision from "ask the Director a question", and out of this phase's
    scope (no live caller currently builds a Reel from a deprecated-feature premise)."""
    unresolved: list[str] = []
    for feature_name in required_feature_names or []:
        if resolve_feature_state(product, feature_name) == FactState.UNKNOWN:
            unresolved.append(feature_name)
    for fact_key in required_fact_keys or []:
        if resolve_undecided_fact_state(product, fact_key) == FactState.UNDECIDED:
            unresolved.append(fact_key)
    return unresolved


def compute_reel_script_readiness(
    *, unresolved_facts: list[str], asset_requirements_satisfiable: bool = True,
) -> str:
    """PRODUCTION_SCRIPT only when EVERY required fact is resolved AND every required production
    asset is known-satisfiable; CONCEPT_SCRIPT otherwise - the premise may still be valid (fact-
    grounded), just not yet executable (missing assets/execution details), matching the addendum's
    own "idea valid but required assets/facts may still be missing" framing. Never a third,
    invented readiness value - exactly these two, or nothing (the caller decides not to build a
    Reel at all when `unresolved_facts` is non-empty for a PRODUCT-origin premise, per this
    module's own docstring)."""
    if unresolved_facts:
        return CONCEPT_SCRIPT
    if not asset_requirements_satisfiable:
        return CONCEPT_SCRIPT
    return PRODUCTION_SCRIPT
