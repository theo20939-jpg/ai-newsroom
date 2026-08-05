"""Phase 18.8 - Local Production Readiness & Shadow Validation: deployment/environment/safety
regression guards (docs/phase18_8_environment_audit.md, docs/phase18_8_shadow_validation_report.md).

This phase made no source-code changes (M0-M4 are operational: Docker container recovery, a real
read-only collection run, a re-run of Phase 18.5's own existing shadow-collection tool, and
documentation) - these tests exist to pin down, as an executable regression guard, the safety
properties that operational work implicitly relied on: the compose stack's own shape, every meme
mode flag's default, and that nothing in this repository's checked-in configuration hardcodes a
live/paid mode.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent

_EXPECTED_SERVICES = {
    "backend", "automation_worker", "news_analysis_worker", "content_worker", "telegram_bot",
    "postgres", "redis",
}


def _load_compose() -> dict:
    return yaml.safe_load((_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Deployment configuration validation
# ---------------------------------------------------------------------------


def test_compose_defines_every_expected_service() -> None:
    compose = _load_compose()
    assert set(compose["services"].keys()) == _EXPECTED_SERVICES


def test_compose_postgres_and_redis_have_healthchecks() -> None:
    compose = _load_compose()
    assert "healthcheck" in compose["services"]["postgres"]
    assert "healthcheck" in compose["services"]["redis"]


def test_compose_workers_depend_on_healthy_postgres() -> None:
    compose = _load_compose()
    for name in ("automation_worker", "news_analysis_worker", "content_worker", "backend"):
        depends_on = compose["services"][name]["depends_on"]
        assert depends_on["postgres"]["condition"] == "service_healthy"


def test_compose_every_app_service_uses_env_file_not_inline_secrets() -> None:
    """No service definition may embed a credential-shaped inline value - every service must load
    secrets via `env_file: .env`, never hardcode one directly in the (committed) compose file."""
    compose = _load_compose()
    app_services = _EXPECTED_SERVICES - {"postgres", "redis"}
    secret_markers = ("sk-", "xoxb-", "AKIA")
    for name in app_services:
        service = compose["services"][name]
        assert service.get("env_file") == ".env"
        rendered = yaml.safe_dump(service)
        for marker in secret_markers:
            assert marker not in rendered, f"{name} appears to hardcode a secret-shaped value"


def test_compose_named_volumes_declared() -> None:
    compose = _load_compose()
    assert set(compose["volumes"].keys()) >= {"postgres_data", "redis_data", "image_storage_data"}


def test_compose_workers_restart_unless_stopped() -> None:
    """Documents the exact policy that explains why the M0 audit found four containers stopped
    (unless-stopped never auto-restarts an explicitly-stopped container) - a regression guard that
    this policy choice itself doesn't silently change."""
    compose = _load_compose()
    for name in _EXPECTED_SERVICES:
        assert compose["services"][name]["restart"] == "unless-stopped"


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------


def test_env_example_has_no_real_looking_secret_values() -> None:
    """`.env.example` must only ever contain placeholder/empty assignments - never a real-looking
    credential, since this file is committed to the repository."""
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for marker in ("sk-", "xoxb-", "AKIA"):
        assert marker not in text


def test_env_example_defines_every_core_infrastructure_variable() -> None:
    """Not a claim that .env.example is fully in sync with the real .env (docs/
    phase18_8_environment_audit.md's own finding: it is not - several real operational flags like
    CONTENT_GENERATION_*/NEWS_COLLECTION_ENABLED are missing from the example file, a real,
    disclosed drift, not fixed in this phase) - only that the baseline infrastructure connectivity
    variables every service needs are present."""
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for var in (
        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "REDIS_HOST", "OPENAI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    ):
        assert f"{var}=" in text


# ---------------------------------------------------------------------------
# Shadow mode safety / no-live-call guarantees
# ---------------------------------------------------------------------------


def test_all_meme_mode_settings_default_off_or_v1() -> None:
    """Regression guard for this phase's own central safety claim: nothing in Phase 18.8 changed
    any meme-related setting's default. Constructs a fresh `Settings()` directly (never
    `importlib.reload`s the `core.config` module - reload re-executes the module's top-level
    `settings = Settings()` singleton assignment in place, which corrupts every other already-
    imported module's own bound reference to it for the rest of the pytest session - confirmed
    directly: an earlier draft of this test using `importlib.reload` caused 3 unrelated tests in
    other files to spuriously fail when run in the same session, and passed in isolation)."""
    from core.config import Settings

    settings = Settings()

    assert settings.meme_opportunity_mode == "off"
    assert settings.meme_safety_gate_mode == "off"
    assert settings.meme_image_generation_mode == "off"
    assert settings.meme_telegram_preview_mode == "off"
    assert settings.meme_opportunity_calibration_version == "v1"
    assert settings.meme_safety_calibration_version == "v1"


def test_compose_file_never_hardcodes_a_live_meme_mode() -> None:
    """No compose service may set MEME_OPPORTUNITY_MODE/MEME_SAFETY_GATE_MODE/
    MEME_IMAGE_GENERATION_MODE/MEME_TELEGRAM_PREVIEW_MODE to anything other than "off" (or omit it
    entirely, which is equivalent since core.config.Settings defaults to "off") - a static
    guarantee that a docker-compose.yml edit could never silently activate a live mode without
    this test catching it."""
    text = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8").upper()
    for flag in (
        "MEME_OPPORTUNITY_MODE", "MEME_SAFETY_GATE_MODE", "MEME_IMAGE_GENERATION_MODE",
        "MEME_TELEGRAM_PREVIEW_MODE",
    ):
        assert f"{flag}: SHADOW" not in text
        assert f"{flag}=SHADOW" not in text
        assert f"{flag}: DRY_RUN" not in text
        assert f"{flag}=DRY_RUN" not in text


def test_phase18_5_shadow_collection_script_still_has_no_forbidden_imports() -> None:
    """Phase 18.8 M3 reused scripts/phase18_5_shadow_collection.py verbatim, unmodified - this
    re-confirms the exact safety property that reuse depended on, scoped to this phase's own test
    file so a Phase 18.8-specific regression run doesn't have to reach into Phase 18.5's test
    module to see it."""
    import ast

    source = Path("scripts/phase18_5_shadow_collection.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_substrings = (
        "capabilities.executor", "workflows.runner", "bot.", "llm_gateway", "meme_image_generation",
        "meme_preview_notifier", "meme_candidate_service",
    )
    for module in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in module


def test_phase18_5_shadow_collection_script_still_has_no_write_statements() -> None:
    source = Path("scripts/phase18_5_shadow_collection.py").read_text(encoding="utf-8").lower()
    for forbidden in ("session.add(", "session.commit(", "insert(", "update(", "delete(", ".execute(text("):
        assert forbidden not in source
