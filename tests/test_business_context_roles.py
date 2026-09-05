"""NINJA Social Intelligence Foundation §31/§105: role-aware permissions. Pure unit tests, no DB."""
from __future__ import annotations

from core.config import settings
from services.business_context_roles import (
    BusinessContextRole,
    commands_for_role,
    get_role_for_user,
    is_command_allowed,
)


def test_unmapped_user_has_no_role(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {})
    assert get_role_for_user(12345) is None


def test_unmapped_user_is_denied_every_command(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {})
    assert is_command_allowed(12345, "status") is False
    assert is_command_allowed(12345, "help") is False


def test_founder_has_all_commands(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {1: "founder"})
    assert get_role_for_user(1) == BusinessContextRole.FOUNDER
    for command in ("product", "campaign", "milestone", "directive", "claim", "context", "status", "help"):
        assert is_command_allowed(1, command), command


def test_directive_defaults_to_founder_only(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {1: "founder", 2: "product_owner", 3: "marketing"})
    assert is_command_allowed(1, "directive") is True
    assert is_command_allowed(2, "directive") is False
    assert is_command_allowed(3, "directive") is False


def test_viewer_and_editor_only_get_status_and_help(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {4: "viewer", 5: "editor"})
    for user_id in (4, 5):
        assert is_command_allowed(user_id, "status")
        assert is_command_allowed(user_id, "help")
        assert not is_command_allowed(user_id, "campaign")
        assert not is_command_allowed(user_id, "product")


def test_unknown_role_string_in_map_is_treated_as_no_role(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {6: "superadmin"})
    assert get_role_for_user(6) is None


def test_commands_for_role_matches_role_matrix() -> None:
    assert "directive" in commands_for_role(BusinessContextRole.FOUNDER)
    assert "directive" not in commands_for_role(BusinessContextRole.MARKETING)
    assert commands_for_role(BusinessContextRole.VIEWER) == frozenset({"status", "help"})
