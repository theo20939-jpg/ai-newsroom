"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §43: /launch gate tests - CommandRegistry usage, mutation
requires FOUNDER tier, wrong chat/topic rejected, read pure, non-Founder rejected."""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.handlers.launch import _is_authorized_chat_and_topic
from core.config import settings
from services.business_context_roles import is_command_allowed


def _message(chat_id: int, thread_id: int | None) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.message_thread_id = thread_id
    return message


def test_wrong_chat_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-999, thread_id=None)) is False


def test_general_topic_is_authorized(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=None)) is True


def test_launch_command_uses_command_registry() -> None:
    from services.business_context_command_registry import get_command

    assert get_command("launch") is not None


def test_only_founder_tier_can_mutate(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {1: "founder", 2: "product_owner", 3: "marketing", 4: "editor", 5: "viewer"})
    # The exact proxy check bot/handlers/launch.py::handle_launch uses for "may submit an instruction".
    assert is_command_allowed(1, "directive") is True
    for non_founder in (2, 3, 4, 5):
        assert is_command_allowed(non_founder, "directive") is False


def test_every_role_can_read_launch_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {1: "founder", 2: "product_owner", 3: "marketing", 4: "editor", 5: "viewer"})
    for user_id in (1, 2, 3, 4, 5):
        assert is_command_allowed(user_id, "launch") is True


def test_unauthorized_user_cannot_read_launch_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {})
    assert is_command_allowed(999, "launch") is False


def test_handler_module_has_no_publish_or_platform_api_symbol() -> None:
    import inspect

    import bot.handlers.launch as module

    source = inspect.getsource(module).lower()
    for forbidden in ("graph.facebook", "send_media_group", "publish_to_instagram", "telegram_surface_registry"):
        assert forbidden not in source, f"unexpected symbol in launch handler: {forbidden!r}"


def test_launch_context_disabled_by_default() -> None:
    """spec §47: social_launch_context_enabled defaults False."""
    from core.config import Settings

    assert Settings.model_fields["social_launch_context_enabled"].default is False
