"""NINJA Social Intelligence Foundation §30/§105: General-topic two-factor gate. Pure unit tests
against `_is_authorized_chat_and_topic()` directly, using a plain MagicMock stand-in for
aiogram's `Message` (no real Bot/Dispatcher needed - the function only reads `.chat.id`/
`.message_thread_id`)."""
from __future__ import annotations

from unittest.mock import MagicMock

from core.config import settings
from bot.handlers.business_context import _is_authorized_chat_and_topic


def _message(chat_id: int, thread_id: int | None) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.message_thread_id = thread_id
    return message


def test_wrong_chat_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-999, thread_id=None)) is False


def test_no_configured_chat_id_rejects_everything(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=None)) is False


def test_general_topic_with_no_thread_id_is_authorized(monkeypatch) -> None:
    """General's own real Telegram semantics: no message_thread_id at all - business_context_
    topic_id stays None by default, so this must match."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=None)) is True


def test_named_subtopic_is_rejected_when_general_is_expected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", None)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=42)) is False


def test_explicit_topic_override_is_honored(monkeypatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100)
    monkeypatch.setattr(settings, "business_context_topic_id", 42)
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=42)) is True
    assert _is_authorized_chat_and_topic(_message(chat_id=-100, thread_id=None)) is False
