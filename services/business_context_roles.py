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

# SOCIAL-INTELLIGENCE-INTEGRATION-1 §5's own suggested matrix, preserved verbatim: Director
# Console commands are all read-only (spec §5's own "All console actions are READ ONLY in this
# phase" instruction), so VIEWER gets them too - the same reasoning that already gives VIEWER
# /status (also read-only) extends naturally to /directors/opportunities/performance (read-only
# director state); /plan and /calendar are withheld from EDITOR specifically because spec §5 only
# lists "directors/opportunities/performance where appropriate" for that role, not the full set.
_DIRECTOR_CONSOLE_COMMANDS = frozenset({"directors", "plan", "opportunities", "calendar", "performance"})

# SOCIAL-INTELLIGENCE-OPS-1 §5: every role may READ /surface status; only FOUNDER may submit a
# configuration change (enforced separately, inside bot/handlers/telegram_surface.py, via the same
# "directive"-allowed FOUNDER-tier proxy the Business Context callback handler already uses - the
# registry/role system only gates "may use /surface at all", never the read/write distinction).
_SURFACE_COMMAND = frozenset({"surface"})

# VISUAL-DESIGN-AUTONOMY-1 §54: /design read is available to every role that already has director
# console read access (mirrors _DIRECTOR_CONSOLE_COMMANDS's own reasoning exactly - Visual System
# status is read-only director state, same category as /directors/performance); mutation
# (freeze/unfreeze/rollback) is additionally FOUNDER-only, enforced the same "directive"-allowed
# proxy check bot/handlers/telegram_surface.py already established for /surface, never a second
# permission system.
_DESIGN_COMMAND = frozenset({"design"})

DEFAULT_ROLE_COMMANDS: dict[BusinessContextRole, frozenset[str]] = {
    BusinessContextRole.FOUNDER: frozenset(
        {"product", "campaign", "milestone", "directive", "claim", "context", "status", "help"}
        | _DIRECTOR_CONSOLE_COMMANDS | _SURFACE_COMMAND | _DESIGN_COMMAND
    ),
    BusinessContextRole.PRODUCT_OWNER: frozenset(
        {"product", "campaign", "milestone", "claim", "context", "status", "help"}
        | _DIRECTOR_CONSOLE_COMMANDS | _SURFACE_COMMAND | _DESIGN_COMMAND
    ),
    BusinessContextRole.MARKETING: frozenset(
        {"campaign", "milestone", "context", "status", "help"} | _DIRECTOR_CONSOLE_COMMANDS | _SURFACE_COMMAND | _DESIGN_COMMAND
    ),
    BusinessContextRole.EDITOR: frozenset(
        {"status", "help", "directors", "opportunities", "performance"} | _SURFACE_COMMAND | _DESIGN_COMMAND
    ),
    BusinessContextRole.VIEWER: frozenset({"status", "help"} | _DIRECTOR_CONSOLE_COMMANDS | _SURFACE_COMMAND | _DESIGN_COMMAND),
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
