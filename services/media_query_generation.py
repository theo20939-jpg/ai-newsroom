"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 4: bounded, deterministic query-variant
generation from a `MediaIntent`. Never spams a search backend with dozens of queries (section 4's
own explicit instruction) - `MAX_QUERY_VARIANTS = 5` is a hard cap, not a soft default."""
from __future__ import annotations

from schemas.media_intent import MediaIntent

MAX_QUERY_VARIANTS = 5
MIN_QUERY_VARIANTS = 3


def generate_search_queries(intent: MediaIntent, *, max_variants: int = MAX_QUERY_VARIANTS) -> list[str]:
    """Deterministic - the same `MediaIntent` always yields the same queries, in the same order,
    exact-identifier variants first (section 4: "prioritize exact identifiers"). Never produces
    more than `max_variants` (clamped to `MAX_QUERY_VARIANTS`); may produce fewer if the intent
    itself is thin (never pads with junk queries to hit a target count)."""
    max_variants = max(1, min(max_variants, MAX_QUERY_VARIANTS))
    queries: list[str] = []

    def _add(q: str) -> None:
        q = " ".join(q.split())  # collapse whitespace, never emit a doubled-space query
        if q and q not in queries:
            queries.append(q)

    company = intent.company
    product = intent.product_name
    model = intent.model_name
    person = intent.person
    event = intent.event

    # 1. The single most exact identifier combination available.
    if model and company:
        _add(f"{company} {model}")
    elif product and company:
        _add(f"{company} {product}")
    elif person and event:
        _add(f"{person} {event}")
    elif model:
        _add(model)
    elif product:
        _add(product)
    elif person:
        _add(person)

    # 2. + official/launch terminology, when there's a real identifier to attach it to.
    primary = model or product or person or intent.primary_entity
    if primary:
        _add(f"{primary} official photo")
        _add(f"{primary} press image")

    # 3. + event/time context, when present - narrows a generic product name to the right cycle.
    if primary and intent.event:
        _add(f"{primary} {intent.event}")
    if primary and intent.time_context:
        _add(f"{primary} {intent.time_context}")

    # 4. Always-available fallback: the primary_entity alone, so a thin intent still yields
    # at least MIN_QUERY_VARIANTS-worth of real search surface where possible.
    _add(intent.primary_entity)

    return queries[:max_variants]
