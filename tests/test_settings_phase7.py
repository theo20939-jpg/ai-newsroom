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


def test_default_content_language_defaults_to_russian() -> None:
    """docs/content_generation_language_final_implementation_plan.md - Russian is the default
    target editorial output language."""
    settings = _settings()

    assert settings.default_content_language == "ru"


def test_default_content_language_is_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_CONTENT_LANGUAGE", "en")

    settings = _settings()

    assert settings.default_content_language == "en"


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


def test_news_collection_enabled_defaults_false() -> None:
    settings = _settings()

    assert settings.news_collection_enabled is False


def test_news_collection_enabled_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_COLLECTION_ENABLED", "true")

    settings = _settings()

    assert settings.news_collection_enabled is True


def test_news_collection_interval_seconds_defaults_1800() -> None:
    settings = _settings()

    assert settings.news_collection_interval_seconds == 1800


def test_news_collection_interval_seconds_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_COLLECTION_INTERVAL_SECONDS", "60")

    settings = _settings()

    assert settings.news_collection_interval_seconds == 60


def test_news_collection_interval_seconds_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(news_collection_interval_seconds=0)


def test_news_collection_interval_seconds_rejects_negative() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(news_collection_interval_seconds=-1)


# ---------------------------------------------------------------------------
# Phase 13 M4: automatic NEWS_ANALYSIS execution worker settings.
# ---------------------------------------------------------------------------


def test_news_analysis_enabled_defaults_false() -> None:
    settings = _settings()

    assert settings.news_analysis_enabled is False


def test_news_analysis_enabled_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_ANALYSIS_ENABLED", "true")

    settings = _settings()

    assert settings.news_analysis_enabled is True


def test_news_analysis_poll_interval_seconds_defaults_300() -> None:
    settings = _settings()

    assert settings.news_analysis_poll_interval_seconds == 300


def test_news_analysis_poll_interval_seconds_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_ANALYSIS_POLL_INTERVAL_SECONDS", "60")

    settings = _settings()

    assert settings.news_analysis_poll_interval_seconds == 60


def test_news_analysis_poll_interval_seconds_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(news_analysis_poll_interval_seconds=0)


def test_news_analysis_batch_size_defaults_5() -> None:
    settings = _settings()

    assert settings.news_analysis_batch_size == 5


def test_news_analysis_batch_size_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_ANALYSIS_BATCH_SIZE", "1")

    settings = _settings()

    assert settings.news_analysis_batch_size == 1


def test_news_analysis_batch_size_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(news_analysis_batch_size=0)


def test_news_analysis_freshness_cutoff_hours_defaults_48() -> None:
    settings = _settings()

    assert settings.news_analysis_freshness_cutoff_hours == 48.0


def test_news_analysis_freshness_cutoff_hours_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS", "24")

    settings = _settings()

    assert settings.news_analysis_freshness_cutoff_hours == 24.0


def test_news_analysis_freshness_cutoff_hours_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(news_analysis_freshness_cutoff_hours=0)


def test_no_phase13_specific_cost_cap_setting_was_added() -> None:
    """Binding, explicit non-decision (docs/phase13_automatic_news_analysis_decision_
    resolution.md Human Decision B): Phase 13 deliberately does not add a NEW,
    analysis-specific monetary cost-cap Settings field - cost containment for the analysis
    worker is entirely workload-based (freshness cutoff, batch cap, sequential execution, no
    automatic retry), never monetary. The pre-existing, general `max_daily_ai_cost` field
    (already present before Phase 13, tied to BudgetGuard, not analysis-specific) is untouched
    by this Plan and is not itself the subject of this decision - proven separately not to be
    newly wired to the analysis worker anywhere in worker/analysis_cycle.py or
    worker/analysis_main.py."""
    news_analysis_fields = [name for name in Settings.model_fields if name.startswith("news_analysis_")]
    assert news_analysis_fields == [
        "news_analysis_enabled",
        "news_analysis_poll_interval_seconds",
        "news_analysis_batch_size",
        "news_analysis_freshness_cutoff_hours",
    ]
    assert not any("cost" in name for name in news_analysis_fields)

    from pathlib import Path

    for module_path in ("worker/analysis_cycle.py", "worker/analysis_main.py"):
        source = Path(module_path).read_text(encoding="utf-8")
        assert "max_daily_ai_cost" not in source
        assert "CostTracker" not in source
        assert "BudgetGuard" not in source


# ---------------------------------------------------------------------------
# Phase 14: automatic CONTENT_GENERATION trigger + Telegram notification worker settings.
# ---------------------------------------------------------------------------


def test_content_generation_enabled_defaults_false() -> None:
    settings = _settings()

    assert settings.content_generation_enabled is False


def test_content_generation_enabled_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_GENERATION_ENABLED", "true")

    settings = _settings()

    assert settings.content_generation_enabled is True


def test_content_generation_poll_interval_seconds_defaults_300() -> None:
    settings = _settings()

    assert settings.content_generation_poll_interval_seconds == 300


def test_content_generation_poll_interval_seconds_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(content_generation_poll_interval_seconds=0)


def test_content_generation_batch_size_defaults_5() -> None:
    settings = _settings()

    assert settings.content_generation_batch_size == 5


def test_content_generation_batch_size_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(content_generation_batch_size=0)


def test_content_generation_scan_limit_defaults_50() -> None:
    settings = _settings()

    assert settings.content_generation_scan_limit == 50


def test_content_generation_scan_limit_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_GENERATION_SCAN_LIMIT", "100")

    settings = _settings()

    assert settings.content_generation_scan_limit == 100


def test_content_generation_scan_limit_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(content_generation_scan_limit=0)


def test_content_generation_scan_limit_default_is_at_least_batch_size_default() -> None:
    """docs/phase14_autonomous_newsroom_implementation_plan.md §3's own scan-limit guarantee:
    content_generation_scan_limit must be >= content_generation_batch_size. No cross-field
    pydantic validator exists for this (this Settings class has no such precedent to extend) -
    the relationship is proven here, directly, against the shipped defaults, instead."""
    settings = _settings()

    assert settings.content_generation_scan_limit >= settings.content_generation_batch_size


def test_content_generation_min_score_defaults_70() -> None:
    settings = _settings()

    assert settings.content_generation_min_score == 70


def test_content_generation_min_score_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_GENERATION_MIN_SCORE", "50")

    settings = _settings()

    assert settings.content_generation_min_score == 50


def test_content_generation_min_score_rejects_out_of_range() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(content_generation_min_score=101)
    with pytest.raises(Exception):  # noqa: B017
        _settings(content_generation_min_score=-1)


def test_content_generation_freshness_cutoff_hours_defaults_24() -> None:
    """Frozen as a technical safety boundary only (docs/phase14_autonomous_newsroom_
    implementation_plan.md §0 clarification 1) - NOT an editorial-freshness control. Default 24h,
    intentionally tighter than news_analysis_freshness_cutoff_hours's own 48h default, though the
    two settings are not required to move together."""
    settings = _settings()

    assert settings.content_generation_freshness_cutoff_hours == 24.0


def test_content_generation_freshness_cutoff_hours_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS", "12")

    settings = _settings()

    assert settings.content_generation_freshness_cutoff_hours == 12.0


def test_content_generation_freshness_cutoff_hours_rejects_zero() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, no need to import it here
        _settings(content_generation_freshness_cutoff_hours=0)


def test_content_generation_dry_run_defaults_true() -> None:
    """Safe default (docs/phase14_autonomous_newsroom_implementation_plan.md §0 clarification 3):
    dry-run only until a human deliberately flips this to False."""
    settings = _settings()

    assert settings.content_generation_dry_run is True


def test_content_generation_dry_run_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_GENERATION_DRY_RUN", "false")

    settings = _settings()

    assert settings.content_generation_dry_run is False


def test_editorial_chat_id_defaults_none() -> None:
    settings = _settings()

    assert settings.editorial_chat_id is None


def test_editorial_chat_id_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITORIAL_CHAT_ID", "123456789")

    settings = _settings()

    assert settings.editorial_chat_id == 123456789


def test_no_max_daily_ai_cost_style_field_added_for_content_generation() -> None:
    """Same binding non-decision Phase 13 already made (Decision Resolution Human Decision B),
    reused unmodified for Phase 14 (docs/phase14_autonomous_newsroom_implementation_plan.md §6):
    cost containment remains entirely workload-based (batch_size, scan_limit, freshness_cutoff_
    hours, min_score), never monetary."""
    content_generation_fields = [
        name for name in Settings.model_fields if name.startswith("content_generation_")
    ]
    assert content_generation_fields == [
        "content_generation_enabled",
        "content_generation_poll_interval_seconds",
        "content_generation_batch_size",
        "content_generation_scan_limit",
        "content_generation_min_score",
        "content_generation_freshness_cutoff_hours",
        "content_generation_dry_run",
    ]
    assert not any("cost" in name for name in content_generation_fields)


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
