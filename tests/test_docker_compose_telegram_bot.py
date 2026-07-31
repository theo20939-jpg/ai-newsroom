"""Phase 16 callback-runtime fix (docs/phase16_ux_combined_preview_fix_report.md): the recurring
symptom was that no Docker service ever ran `python -m bot.main`, so Telegram callback buttons
stopped responding after every restart - the callback path only ever worked when someone started
`bot.main` manually. These tests parse docker-compose.yml directly (no Docker daemon required) and
guard the persistent `telegram_bot` service that fixes this, so a future edit can't silently drop
the service or point it at a different entry point.
"""
from pathlib import Path

import yaml

_COMPOSE_PATH = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _load_services() -> dict:
    with _COMPOSE_PATH.open(encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    return compose["services"]


def test_telegram_bot_service_exists() -> None:
    services = _load_services()
    assert "telegram_bot" in services


def test_telegram_bot_runs_the_existing_polling_entry_point() -> None:
    service = _load_services()["telegram_bot"]
    assert service["command"] == ["python", "-m", "bot.main"]


def test_telegram_bot_uses_the_existing_image_and_env_file() -> None:
    service = _load_services()["telegram_bot"]
    assert service["build"] == "."
    assert service["env_file"] == ".env"


def test_telegram_bot_depends_on_healthy_postgres_and_redis() -> None:
    service = _load_services()["telegram_bot"]
    depends_on = service["depends_on"]
    assert depends_on["postgres"]["condition"] == "service_healthy"
    assert depends_on["redis"]["condition"] == "service_healthy"


def test_telegram_bot_mounts_the_shared_image_storage_volume() -> None:
    service = _load_services()["telegram_bot"]
    volumes = service["volumes"]
    assert any(v.startswith("image_storage_data:/data/image_storage") for v in volumes)


def test_telegram_bot_restart_policy_matches_other_workers() -> None:
    services = _load_services()
    worker_restart_policies = {
        services[name]["restart"]
        for name in ("automation_worker", "news_analysis_worker", "content_worker")
    }
    assert worker_restart_policies == {"unless-stopped"}
    assert services["telegram_bot"]["restart"] == "unless-stopped"


def test_exactly_one_service_runs_bot_main() -> None:
    """The whole point of this fix: exactly one long-polling consumer, never zero, never two."""
    services = _load_services()
    runners = [
        name for name, cfg in services.items()
        if cfg.get("command") == ["python", "-m", "bot.main"]
    ]
    assert runners == ["telegram_bot"]


def test_no_service_configures_a_telegram_webhook() -> None:
    """Polling and webhook must never run simultaneously; the codebase has no webhook code at
    all (grepped separately), and no compose service should override that by env or command."""
    services = _load_services()
    for name, cfg in services.items():
        command = " ".join(cfg.get("command", []))
        assert "webhook" not in command.lower(), name
        env = cfg.get("environment") or {}
        env_blob = " ".join(f"{k}={v}" for k, v in env.items()).lower()
        assert "webhook" not in env_blob, name
