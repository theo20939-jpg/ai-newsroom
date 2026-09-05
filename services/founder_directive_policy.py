"""SOCIAL-INTELLIGENCE-OPS-1, spec §17/§19: shared Founder Directive precedence check - hoisted out
of services/instagram_growth_strategist.py (the only prior caller, which now imports this same
function rather than defining its own copy) so every platform-agnostic and platform-specific
consumer shares ONE function, never independently-drifting copies of the same safety-critical
logic. This is genuinely business-generic: it only reads StrategicDirective's own structured scope
fields (products/platforms), never anything platform-specific.

CRITICAL (spec §17): Founder Directives outrank engagement/relevance optimization - a directive
whose structured scope covers a product/platform always wins over whatever campaign state alone
would have permitted (spec's own "Store пока не продвигаем" example: high organic/campaign
relevance never overrides an active, matching directive)."""
from __future__ import annotations

from database.models.strategic_directive import DirectiveStatus, StrategicDirective


def directive_blocks_product(
    directives: list[StrategicDirective], *, product_slug: str, platform: str = "instagram",
) -> list[StrategicDirective]:
    """A directive with an empty `products`/`platforms` scope is read as "applies to everything" -
    exactly as broad as a founder saying "all products, all platforms" (spec's own "as narrow or as
    broad as the founder actually said" instruction)."""
    matches = []
    for directive in directives:
        if directive.status != DirectiveStatus.ACTIVE:
            continue
        scoped_products = directive.products or []
        scoped_platforms = directive.platforms or []
        product_matches = not scoped_products or product_slug in scoped_products
        platform_matches = not scoped_platforms or platform in scoped_platforms
        if product_matches and platform_matches:
            matches.append(directive)
    return matches
