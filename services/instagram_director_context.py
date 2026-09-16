"""Persistent brand/account context for the existing Instagram Director.

Static brand strategy is versioned in ``docs/instagram/director_context_v1.md``. Volatile product
and launch truth is rendered from the existing Business Context and Social Launch Context models
at decision time, so the markdown file never becomes a stale copy of availability or claims.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from database.models.social_launch_context import SocialLaunchContext
from services.business_context_snapshot_service import BusinessContextSnapshot

_CONTEXT_PATH = Path(__file__).resolve().parent.parent / "docs" / "instagram" / "director_context_v1.md"


@lru_cache(maxsize=1)
def load_instagram_director_context() -> str:
    return _CONTEXT_PATH.read_text(encoding="utf-8")


def render_product_truth(snapshot: BusinessContextSnapshot) -> str:
    lines = [f"BUSINESS CONTEXT AS OF: {snapshot.as_of.isoformat()}"]
    if not snapshot.products:
        lines.append("No canonical NINJA product records are currently available.")
        return "\n".join(lines)

    approved_by_product: dict[str, list[str]] = {}
    restricted_by_product: dict[str, list[str]] = {}
    for claim in snapshot.approved_claims:
        approved_by_product.setdefault(str(claim.product_id), []).append(claim.claim_text)
    for claim in snapshot.restricted_claims:
        restricted_by_product.setdefault(str(claim.product_id), []).append(claim.claim_text)

    for summary in snapshot.products:
        product = summary.product
        product_id = str(product.id)
        lines.append(f"PRODUCT: {product.name} (slug={product.slug}, status={product.status.value})")
        if product.current_stage:
            lines.append(f"- current stage: {product.current_stage}")
        if product.description:
            lines.append(f"- description: {product.description}")
        for feature in product.current_features or []:
            lines.append(f"- confirmed current feature: {feature}")
        for feature in product.planned_features or []:
            lines.append(f"- planned, not yet live feature: {feature}")
        for fact in product.undecided_facts or []:
            lines.append(f"- explicitly undecided fact key: {fact}")
        if product.pricing_status:
            lines.append(f"- pricing status: {product.pricing_status}")
        if product.product_url:
            lines.append(f"- current product URL: {product.product_url}")
        if product.waitlist_url:
            lines.append(f"- current waitlist URL: {product.waitlist_url}")
        for claim in approved_by_product.get(product_id, []):
            lines.append(f"- approved claim: {claim}")
        for claim in restricted_by_product.get(product_id, []):
            lines.append(f"- restricted claim, never use: {claim}")
        if summary.active_campaign is not None:
            lines.append(
                f"- active campaign: status={summary.active_campaign.status}, "
                f"phase={summary.active_campaign.phase}"
            )

    if snapshot.active_directives:
        lines.append("ACTIVE FOUNDER DIRECTIVES:")
        lines.extend(f"- {directive.instruction}" for directive in snapshot.active_directives)
    else:
        lines.append("ACTIVE FOUNDER DIRECTIVES: none")
    return "\n".join(lines)


def render_account_context(launch_context: SocialLaunchContext | None) -> str:
    if launch_context is None:
        return "No confirmed Instagram SocialLaunchContext is available. Do not invent account history."
    return "\n".join(
        [
            f"target_identity={launch_context.target_identity}",
            f"current_identity={launch_context.current_identity or '(none)'}",
            f"launch_state={launch_context.launch_state.value}",
            f"launch_date_status={launch_context.launch_date_status.value}",
            f"baseline_policy={launch_context.baseline_policy.value}",
            f"historical_content_policy={launch_context.historical_content_policy.value}",
            f"confirmed instruction={launch_context.raw_instruction}",
        ]
    )
