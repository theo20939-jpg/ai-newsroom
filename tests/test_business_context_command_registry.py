"""NINJA Social Intelligence Foundation §29/§105: CommandRegistry / /help consistency invariant.
Pure unit tests, no DB."""
from __future__ import annotations

from bot.business_context_formatting import render_help, render_help_detail
from services.business_context_command_registry import COMMAND_REGISTRY, get_command
from services.business_context_roles import BusinessContextRole, DEFAULT_ROLE_COMMANDS
from services.business_context_roles import commands_for_role as role_commands_for_role

_ALL_COMMAND_NAMES = frozenset({
    "product", "campaign", "milestone", "directive", "claim", "context", "status", "help",
    # SOCIAL-INTELLIGENCE-INTEGRATION-1 §6-12: Director Console, added through this SAME registry.
    "directors", "plan", "opportunities", "calendar", "performance",
    # SOCIAL-INTELLIGENCE-OPS-1 §3: /surface, added through this SAME registry.
    "surface",
})


def test_registry_covers_every_spec_command() -> None:
    assert set(COMMAND_REGISTRY.keys()) == _ALL_COMMAND_NAMES


def test_role_matrix_never_references_an_unregistered_command() -> None:
    """§29's own "HELP CANNOT DRIFT FROM REAL COMMANDS" invariant, checked the other direction: a
    role must never be granted a command that isn't in the registry at all."""
    for role, commands in DEFAULT_ROLE_COMMANDS.items():
        for command in commands:
            assert get_command(command) is not None, f"{role} references unregistered command {command!r}"


def test_help_text_only_lists_commands_actually_in_the_registry() -> None:
    text = render_help(BusinessContextRole.FOUNDER, role_commands_for_role(BusinessContextRole.FOUNDER))
    for name in _ALL_COMMAND_NAMES:
        assert f"/{name}" in text


def test_help_text_is_filtered_by_role() -> None:
    viewer_text = render_help(BusinessContextRole.VIEWER, role_commands_for_role(BusinessContextRole.VIEWER))
    assert "/directive" not in viewer_text
    assert "/status" in viewer_text


def test_help_detail_renders_without_error_for_every_command() -> None:
    for name in _ALL_COMMAND_NAMES:
        command = get_command(name)
        assert command is not None
        detail = render_help_detail(command)
        assert f"/{name}" in detail
