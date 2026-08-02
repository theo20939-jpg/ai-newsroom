"""Phase 17 M6.1 Stage 1 - safe security preflight (docs/
phase17_m6_1_production_cutover_runbook.md).

The one hard rule this module exists to enforce: **never print a secret value, a prefix, a
suffix, a length, a masked form, a hash, or a fingerprint of any secret** - only `SET`/`MISSING`
for presence and `PASS`/`FAIL`/`SKIPPED`/`NOT REQUIRED` for a live check. Every exception is
caught broadly and reduced to a bare status - `str(exc)` is never logged or returned, since some
SDK error messages can echo back part of a request (including a credential) in their body.

No generation call (OpenAI: `models.list()` only, a free metadata endpoint - never `chat.
completions`/`responses.create`), no Telegram message sent, no channel read (Telethon: `connect()`
+ `is_user_authorized()` + `disconnect()` only - never `iter_messages()`), no collector run.
"""
from __future__ import annotations

import asyncio
from typing import NamedTuple

from core.config import settings

_SECRET_LIKE_SUBSTRINGS = (
    "TOKEN", "KEY", "HASH", "PASSWORD", "SECRET", "SESSION", "DSN", "URL", "CHAT_ID",
)


def check_presence() -> dict[str, str]:
    """SET/MISSING only - never the value itself, never its length."""
    values = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "GITHUB_TOKEN": settings.github_token,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_API_ID": settings.telegram_api_id,
        "TELEGRAM_API_HASH": settings.telegram_api_hash,
        "TELEGRAM_SESSION_STRING": settings.telegram_session_string,
        "POSTGRES_PASSWORD": settings.postgres_password,
        "EDITORIAL_CHAT_ID": settings.editorial_chat_id,
    }
    return {name: ("SET" if value is not None else "MISSING") for name, value in values.items()}


async def check_openai_auth() -> str:
    """`models.list()` is a free metadata endpoint - never a generation call, never billed."""
    if settings.openai_api_key is None:
        return "SKIPPED"
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        await client.models.list()
        return "PASS"
    except Exception:  # noqa: BLE001 - never leak exception detail, which may echo the credential
        return "FAIL"


async def check_github_token() -> str:
    """GitHub is not required for Stage 1 runtime - presence-only, no network call."""
    return "SET" if settings.github_token is not None else "NOT REQUIRED"


async def check_telegram_bot_auth() -> str:
    """`getMe` only - identity check, never `sendMessage`. Zero messages sent."""
    if settings.telegram_bot_token is None:
        return "FAIL"
    try:
        import httpx

        token = settings.telegram_bot_token.get_secret_value()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        payload = response.json()
        return "PASS" if response.status_code == 200 and payload.get("ok") is True else "FAIL"
    except Exception:  # noqa: BLE001
        return "FAIL"


async def check_telegram_user_session_auth() -> str:
    """`connect()` + `is_user_authorized()` + `disconnect()` only - never `iter_messages()`,
    never reads a single channel, never runs the collector path."""
    if settings.telegram_api_id is None or settings.telegram_api_hash is None or settings.telegram_session_string is None:
        return "FAIL"
    try:
        from telethon import TelegramClient  # type: ignore[import-untyped]
        from telethon.sessions import StringSession  # type: ignore[import-untyped]

        client = TelegramClient(
            StringSession(settings.telegram_session_string.get_secret_value()),
            settings.telegram_api_id, settings.telegram_api_hash.get_secret_value(),
        )
        await client.connect()
        try:
            authorized = await client.is_user_authorized()
            return "PASS" if authorized else "FAIL"
        finally:
            await client.disconnect()
    except Exception:  # noqa: BLE001
        return "FAIL"


async def check_postgres() -> str:
    try:
        from sqlalchemy import text

        from database.session import async_session_factory

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return "PASS"
    except Exception:  # noqa: BLE001
        return "FAIL"


async def check_redis() -> str:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        try:
            pong = await client.ping()
            return "PASS" if pong else "FAIL"
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001
        return "FAIL"


def validate_override_file(path: str = "docker-compose.override.yml") -> tuple[str, list[str]]:
    """Reads ONLY the override file (never a merged/effective config), checks every mode value
    is in the allowed set, and confirms no key name contains any secret-like substring - never
    prints the file's own content."""
    from pathlib import Path

    import yaml  # type: ignore[import-untyped]

    file_path = Path(path)
    if not file_path.exists():
        return "SKIPPED", []

    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    allowed_values = {"off", "shadow"}
    mode_keys_found: list[str] = []
    services = data.get("services", {})
    if not isinstance(services, dict):
        return "FAIL", []

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            return "FAIL", []
        env = service_config.get("environment", {})
        if not isinstance(env, dict):
            return "FAIL", []
        for key, value in env.items():
            for forbidden in _SECRET_LIKE_SUBSTRINGS:
                if forbidden in key.upper():
                    return "FAIL", []
            # YAML 1.1 coerces the bare word "off" to the boolean False (and "on"/"yes"/"no"
            # similarly) - normalize that back before comparing, rather than requiring every
            # override file author to remember to quote "off" as a string.
            normalized = "off" if value is False else str(value).lower()
            if normalized not in allowed_values:
                return "FAIL", []
            mode_keys_found.append(key)

    return "PASS", sorted(set(mode_keys_found))


class PreflightResult(NamedTuple):
    presence: dict[str, str]
    auth: dict[str, str]
    override_status: str
    override_keys: list[str]


async def run_all() -> PreflightResult:
    presence = check_presence()
    auth = {
        "OPENAI_AUTH": await check_openai_auth(),
        "GITHUB_TOKEN_CHECK": await check_github_token(),
        "TELEGRAM_BOT_AUTH": await check_telegram_bot_auth(),
        "TELEGRAM_USER_SESSION": await check_telegram_user_session_auth(),
        "POSTGRES": await check_postgres(),
        "REDIS": await check_redis(),
    }
    override_status, override_keys = validate_override_file()
    return PreflightResult(presence=presence, auth=auth, override_status=override_status, override_keys=override_keys)


def main() -> int:
    result = asyncio.run(run_all())
    print("Phase 17 Stage 1 - safe security preflight (no secret values ever printed)")
    print("=" * 72)
    print("CREDENTIAL PRESENCE:")
    for name, status in result.presence.items():
        print(f"  {name}: {status}")
    print("AUTHENTICATION:")
    for name, status in result.auth.items():
        print(f"  {name}: {status}")
    print(f"OVERRIDE FILE VALIDATION: {result.override_status}")
    print(f"OVERRIDE MODE KEYS: {result.override_keys}")
    print("=" * 72)
    hard_failures = [v for v in result.auth.values() if v == "FAIL"]
    overall_pass = not hard_failures and result.override_status in ("PASS", "SKIPPED")
    print("OVERALL: PASS" if overall_pass else "OVERALL: FAIL")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
