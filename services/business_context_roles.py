"""NINJA Social Intelligence Foundation, Part II §31: role-aware command permissions. No general
role/permission system exists anywhere in this codebase to reuse (confirmed forensic sweep -
core/config.py's own `telegraph_approver_user_ids` precedent is a flat binary allowlist, never
graded roles) - this module is the first. Deliberately plain data + pure functions, no class, no
DB table: `settings.business_context_role_map` (core/config.py) is the single source of truth for
who has which role, fail-closed (a user_id absent from the map has NO role and therefore NO
commands - never a default role)."""
from __future__ import annotations

import enum

from core.config import settings


class BusinessContextRole(str, enum.Enum):
    FOUNDER = "founder"
    PRODUCT_OWNER = "product_owner"
    MARKETING = "marketing"
    EDITOR = "editor"
    VIEWER = "viewer"


# Spec §31's own suggested default matrix, preserved verbatim. `/directive` defaults to FOUNDER
# only, as the spec explicitly requires. Kept as a plain module-level dict (not a DB table) so it
# is configurable only by editing/deploying code, never by an in-chat command - permissions
# themselves are not something any Telegram command can ever propose or confirm a change to.
DEFAULT_ROLE_COMMANDS: dict[BusinessContextRole, frozenset[str]] = {
    BusinessContextRole.FOUNDER: frozenset(
        {"product", "campaign", "milestone", "directive", "claim", "context", "status", "help"}
    ),
    BusinessContextRole.PRODUCT_OWNER: frozenset(
        {"product", "campaign", "milestone", "claim", "context", "status", "help"}
    ),
    BusinessContextRole.MARKETING: frozenset({"campaign", "milestone", "context", "status", "help"}),
    BusinessContextRole.EDITOR: frozenset({"status", "help"}),
    BusinessContextRole.VIEWER: frozenset({"status", "help"}),
}


def get_role_for_user(user_id: int) -> BusinessContextRole | None:
    """`None` means "no role at all" - the fail-closed default for any user_id not explicitly
    present in `settings.business_context_role_map`. Never guesses/defaults to VIEWER."""
    raw = settings.business_context_role_map.get(user_id)
    if raw is None:
        return None
    try:
        return BusinessContextRole(raw)
    except ValueError:
        return None


def commands_for_role(role: BusinessContextRole) -> frozenset[str]:
    return DEFAULT_ROLE_COMMANDS.get(role, frozenset())


def is_command_allowed(user_id: int, command: str) -> bool:
    role = get_role_for_user(user_id)
    if role is None:
        return False
    return command in commands_for_role(role)
