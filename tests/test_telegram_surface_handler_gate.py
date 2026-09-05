"""SOCIAL-INTELLIGENCE-OPS-1, spec §58: /surface gate tests - CommandRegistry usage, mutation
requires FOUNDER tier, wrong chat/topic rejected, no publish/Gateway symbol beyond the sanctioned
one-shot parser call."""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.handlers.telegram_surface import _is_authorized_chat_and_topic
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


def test_surface_command_uses_command_registry() -> None:
    from services.business_context_command_registry import get_command

    assert get_command("surface") is not None


def test_only_founder_tier_can_mutate(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {1: "founder", 2: "product_owner", 3: "marketing", 4: "editor", 5: "viewer"})
    # The exact proxy check bot/handlers/telegram_surface.py::handle_surface uses for "may mutate".
    assert is_command_allowed(1, "directive") is True
    for non_founder in (2, 3, 4, 5):
        assert is_command_allowed(non_founder, "directive") is False


def test_every_role_can_read_surface_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {1: "founder", 2: "product_owner", 3: "marketing", 4: "editor", 5: "viewer"})
    for user_id in (1, 2, 3, 4, 5):
        assert is_command_allowed(user_id, "surface") is True


def test_unauthorized_user_cannot_read_surface(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_context_role_map", {})
    assert is_command_allowed(999, "surface") is False


def test_handler_module_has_no_publish_symbol() -> None:
    import inspect

    import bot.handlers.telegram_surface as module

    source = inspect.getsource(module).lower()
    for forbidden in ("graph.facebook", "send_media_group", "publish_to_instagram"):
        assert forbidden not in source, f"unexpected symbol in telegram_surface handler: {forbidden!r}"
