"""Tests for core.auth_resolution.is_auth_configured."""
import pytest
from pydantic import SecretStr

from core.auth_resolution import is_auth_configured
from core.config import settings


def test_settings_value_recognized_even_when_absent_from_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of this module: pydantic-settings loads .env into
    core.config.settings without copying it into os.environ - a check must
    still recognize the value."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(settings, "github_token", SecretStr("configured-only-in-settings"))

    assert is_auth_configured("GITHUB_TOKEN") is True


def test_settings_value_missing_is_reported_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(settings, "github_token", None)

    assert is_auth_configured("GITHUB_TOKEN") is False


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("GITHUB_TOKEN", "github_token"),
        ("TELEGRAM_API_HASH", "telegram_api_hash"),
        ("TELEGRAM_SESSION_STRING", "telegram_session_string"),
    ],
)
def test_known_secret_string_fields_read_from_settings(monkeypatch: pytest.MonkeyPatch, name: str, field: str) -> None:
    monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, field, SecretStr("value"))
    assert is_auth_configured(name) is True

    monkeypatch.setattr(settings, field, None)
    assert is_auth_configured(name) is False


def test_telegram_api_id_read_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """telegram_api_id is a plain int field, not a SecretStr - covered separately."""
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.setattr(settings, "telegram_api_id", 12345)
    assert is_auth_configured("TELEGRAM_API_ID") is True

    monkeypatch.setattr(settings, "telegram_api_id", None)
    assert is_auth_configured("TELEGRAM_API_ID") is False


def test_unknown_name_falls_back_to_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """YOUTUBE_API_KEY etc. have no Settings field yet - must still be resolvable."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    assert is_auth_configured("YOUTUBE_API_KEY") is False

    monkeypatch.setenv("YOUTUBE_API_KEY", "value")
    assert is_auth_configured("YOUTUBE_API_KEY") is True
