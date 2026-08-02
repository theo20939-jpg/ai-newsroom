"""Phase 17 M6.1 Stage 1 - safe security preflight tests (docs/
phase17_m6_1_production_cutover_runbook.md).

Pure, deterministic tests only - never a live network call (OpenAI/Telegram/Postgres/Redis auth
checks are exercised manually, once, outside the automated suite, per this milestone's own
explicit instruction). Covers: presence-check never returns a value, override-file validation
rejects any secret-like key name, and a static source-scan confirming this module never logs a
`get_secret_value()` result.
"""
from __future__ import annotations

import inspect
import re
import textwrap

import pytest

from scripts.security_preflight_safe import check_presence, validate_override_file


def test_check_presence_returns_only_set_or_missing() -> None:
    result = check_presence()
    assert set(result) == {
        "OPENAI_API_KEY", "GITHUB_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING", "POSTGRES_PASSWORD", "EDITORIAL_CHAT_ID",
    }
    for value in result.values():
        assert value in ("SET", "MISSING")


def test_override_validation_skipped_when_file_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    status, keys = validate_override_file("docker-compose.override.yml")
    assert status == "SKIPPED"
    assert keys == []


def test_override_validation_passes_clean_mode_only_file(tmp_path) -> None:
    override = tmp_path / "docker-compose.override.yml"
    override.write_text(
        textwrap.dedent(
            """
            services:
              content_worker:
                environment:
                  EDITORIAL_BRIEF_MODE: shadow
                  CHANNEL_RELEVANCE_MODE: off
            """
        ),
        encoding="utf-8",
    )
    status, keys = validate_override_file(str(override))
    assert status == "PASS"
    assert keys == ["CHANNEL_RELEVANCE_MODE", "EDITORIAL_BRIEF_MODE"]


def test_override_validation_rejects_secret_like_key(tmp_path) -> None:
    override = tmp_path / "docker-compose.override.yml"
    override.write_text(
        textwrap.dedent(
            """
            services:
              content_worker:
                environment:
                  TELEGRAM_BOT_TOKEN: shadow
            """
        ),
        encoding="utf-8",
    )
    status, _keys = validate_override_file(str(override))
    assert status == "FAIL"


def test_override_validation_rejects_non_mode_value(tmp_path) -> None:
    override = tmp_path / "docker-compose.override.yml"
    override.write_text(
        textwrap.dedent(
            """
            services:
              content_worker:
                environment:
                  EDITORIAL_BRIEF_MODE: enforce
            """
        ),
        encoding="utf-8",
    )
    status, _keys = validate_override_file(str(override))
    assert status == "FAIL"


@pytest.mark.parametrize("forbidden", ["TOKEN", "KEY", "HASH", "PASSWORD", "SECRET", "SESSION", "DSN", "URL", "CHAT_ID"])
def test_override_validation_rejects_every_forbidden_substring(tmp_path, forbidden: str) -> None:
    override = tmp_path / "docker-compose.override.yml"
    override.write_text(
        textwrap.dedent(
            f"""
            services:
              content_worker:
                environment:
                  SOME_{forbidden}_FIELD: shadow
            """
        ),
        encoding="utf-8",
    )
    status, _keys = validate_override_file(str(override))
    assert status == "FAIL"


def test_module_never_logs_get_secret_value_result() -> None:
    """Static source scan: `get_secret_value()` may only ever appear as an argument passed
    directly into a client constructor/request call - never assigned to a variable that could
    later be printed, and never passed to `print()`/`logger.*` directly."""
    import scripts.security_preflight_safe as module

    source = inspect.getsource(module)
    for line in source.splitlines():
        if "get_secret_value()" not in line:
            continue
        assert "print(" not in line
        assert not re.search(r"log(ger)?\.\w+\(.*get_secret_value", line)


def test_module_has_no_print_of_settings_repr() -> None:
    import scripts.security_preflight_safe as module

    source = inspect.getsource(module)
    assert "print(settings" not in source
    assert "repr(settings" not in source
    assert "vars(settings" not in source


def test_no_dotenv_or_full_environ_dump() -> None:
    """This module must never read `.env` directly or dump `os.environ`."""
    import scripts.security_preflight_safe as module

    source = inspect.getsource(module)
    assert "os.environ" not in source
    assert ".env" not in source
    assert "printenv" not in source
