"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §31: Director Console gate tests - mirrors
tests/test_business_context_handler_gate.py's own convention exactly (pure unit tests against the
gate function, a plain MagicMock stand-in for aiogram's Message)."""
from __future__ import annotations

from unittest.mock import MagicMock

from bot.handlers.director_console import _is_authorized_chat_and_topic, _parse_platform_filter
from core.config import settings


def _message(chat_id: int, thread_id: int | None) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.message_thread_id = thread_id
    return message


def _command(args: str | None) -> MagicMock:
    command = MagicMock()
    command.args = args
    return command


def test_wrong_chat_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-999, thread_id=None)) is False


def test_general_topic_is_authorized(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=None)) is True


def test_named_subtopic_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=42)) is False


def test_platform_filter_accepts_known_values() -> None:
    assert _parse_platform_filter(_command("telegram")) == ("telegram", None)
    assert _parse_platform_filter(_command("Instagram")) == ("instagram", None)
    assert _parse_platform_filter(_command(None)) == (None, None)


def test_platform_filter_rejects_unknown_value_with_error_not_a_crash() -> None:
    platform, error = _parse_platform_filter(_command("tiktok"))
    assert platform is None
    assert error is not None


def test_handler_module_has_no_publish_or_gateway_symbol() -> None:
    """Spec §29: /directors /plan /opportunities /calendar /performance must never send a public
    post, call the AI Gateway, or touch a platform API - swept at the source level, mirroring the
    Instagram phase's own equivalent safety sweep."""
    import inspect

    import bot.handlers.director_console as module

    source = inspect.getsource(module).lower()
    for forbidden in ("call_generate", "llmgateway", "graph.facebook", "send_media_group", "publish"):
        assert forbidden not in source, f"unexpected symbol in director_console handler: {forbidden!r}"
