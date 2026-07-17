"""Tests for the Phase 7 additions to core.config.Settings and
integrations.llm_gateway.providers.base.build_openai_credential.

Every Settings() construction here goes through `_settings()`, which passes
`_env_file=None` to avoid reading the real, developer-local .env file - tests
are isolated to explicit constructor kwargs / monkeypatched environment
variables only, never ambient secrets.
"""
from typing import Any

import pytest
from pydantic import SecretStr

from core.config import Settings
from integrations.llm_gateway.providers.base import build_openai_credential


def _settings(**overrides: Any) -> Settings:
    # mypy has no visibility into BaseSettings' dynamically-accepted `_env_file`
    # kwarg without the pydantic mypy plugin (not configured in this repo) -
    # isolated to this one helper rather than repeated per call site.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_enabled_providers_defaults_to_empty_list() -> None:
    settings = _settings()

    assert settings.enabled_providers == []


def test_verify_capabilities_at_boot_defaults_false() -> None:
    settings = _settings()

    assert settings.verify_capabilities_at_boot is False


def test_redis_unavailable_policy_defaults_none() -> None:
    settings = _settings()

    assert settings.redis_unavailable_policy is None


def test_enabled_providers_parses_json_array_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLED_PROVIDERS", '["openai", "anthropic"]')

    settings = _settings()

    assert settings.enabled_providers == ["openai", "anthropic"]


def test_redis_unavailable_policy_accepts_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_UNAVAILABLE_POLICY", "fail_open")

    settings = _settings()

    assert settings.redis_unavailable_policy == "fail_open"


def test_redis_unavailable_policy_accepts_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_UNAVAILABLE_POLICY", "fail_closed")

    settings = _settings()

    assert settings.redis_unavailable_policy == "fail_closed"


def test_redis_unavailable_policy_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_UNAVAILABLE_POLICY", "not_a_real_policy")

    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings()


def test_build_openai_credential_assembles_api_key_from_settings() -> None:
    settings = _settings(openai_api_key=SecretStr("sk-test-value"))

    credential = build_openai_credential(settings)

    assert credential.api_key is not None
    assert credential.api_key.get_secret_value() == "sk-test-value"
    assert credential.service_account_json is None
    assert credential.access_key_id is None


def test_build_openai_credential_with_no_key_configured() -> None:
    settings = _settings()

    credential = build_openai_credential(settings)

    assert credential.api_key is None
