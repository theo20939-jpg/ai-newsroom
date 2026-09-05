"""SOCIAL-INTELLIGENCE-OPS-1, spec §9/§10/§54/§55/§56: DirectorConsoleAccessPolicy - the ONE
centralized place that decides which console sections/fields a role may see. Read-only does NOT
mean non-sensitive (spec §9's own explicit framing) - a role that may CALL a console command is
not automatically entitled to every field that command's underlying service computed.

Every renderer in bot/director_console_formatting.py consults THIS policy - never a manually
duplicated `if role == VIEWER: skip` check scattered per handler/renderer (spec §54's own explicit
"do not implement privacy by manually deleting fields in each handler" instruction)."""
from __future__ import annotations

from dataclasses import dataclass

from services.business_context_roles import BusinessContextRole

REDACTED_LABEL = "[скрыто по роли]"

# Spec §9's own baseline matrix, applied consistently across every sensitive category below -
# FOUNDER always sees everything; PRODUCT_OWNER/MARKETING have "full product/campaign/director"
# and "full social/campaign" read access respectively (both cover the same sensitive categories in
# practice, since campaign strategy IS the shared concern); EDITOR gets only the OPERATIONAL
# categories it needs for editorial work (calendar, creative concepts, director status) but not
# founder-level strategic/legal detail; VIEWER gets none of the sensitive categories at all
# (spec §9's own explicit "at minimum" list).
_FULL_STRATEGIC_ACCESS = frozenset({
    BusinessContextRole.FOUNDER, BusinessContextRole.PRODUCT_OWNER, BusinessContextRole.MARKETING,
})
_OPERATIONAL_ACCESS = _FULL_STRATEGIC_ACCESS | {BusinessContextRole.EDITOR}


@dataclass(frozen=True)
class DirectorConsoleAccessPolicy:
    role: BusinessContextRole

    @property
    def is_founder(self) -> bool:
        return self.role == BusinessContextRole.FOUNDER

    def can_see_founder_directive_text(self) -> bool:
        """Spec §55: Founder Directive text - strategic, not operational. EDITOR does not need the
        founder's own wording to execute editorial work, only the console's own already-applied
        consequence (e.g. a format decision already reflects a directive's restriction)."""
        return self.role in _FULL_STRATEGIC_ACCESS

    def can_see_restricted_claims(self) -> bool:
        return self.role in _FULL_STRATEGIC_ACCESS

    def can_see_embargo_details(self) -> bool:
        return self.role in _FULL_STRATEGIC_ACCESS

    def can_see_tentative_launch_dates(self) -> bool:
        """Spec §55: an unannounced/TENTATIVE date is exactly the kind of internal-only fact that
        must never leak through a "read-only" status command."""
        return self.role in _FULL_STRATEGIC_ACCESS

    def can_see_internal_only_milestones(self) -> bool:
        return self.role in _FULL_STRATEGIC_ACCESS

    def can_see_unpublished_calendar(self) -> bool:
        """EDITOR needs to know what's coming to do editorial work (spec §9's own "content
        operational read access needed for editorial work") - VIEWER does not."""
        return self.role in _OPERATIONAL_ACCESS

    def can_see_unreleased_creative_concepts(self) -> bool:
        return self.role in _OPERATIONAL_ACCESS

    def can_see_internal_campaign_strategy_notes(self) -> bool:
        """Free-text advisory/avoidance notes (e.g. Growth Strategy's own avoidance_notes) can
        embed a Founder Directive's own wording or a restricted claim - treated as strategic, same
        gate as can_see_founder_directive_text()."""
        return self.role in _FULL_STRATEGIC_ACCESS
