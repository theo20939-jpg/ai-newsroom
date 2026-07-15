"""Resolves whether a named credential is configured - never exposes its value.

.env values load into core.config.settings via pydantic-settings; they are
not copied into os.environ. A check against raw os.environ therefore misses
anything set only through .env, even though core.config.settings can see it
fine. Known project secrets are checked against Settings here; a name with
no Settings field yet (e.g. an auth requirement for an adapter that hasn't
been built) falls back to os.environ so it isn't treated as permanently
unconfigured.

This is the one place this check lives - services.source_pack_importer (and
any future caller needing the same check) calls is_auth_configured() instead
of re-implementing its own os.environ / settings lookup.
"""
import os

from core.config import settings

# Extend this dict as new adapters gain their own Settings field - never
# re-implement this lookup elsewhere.
_SETTINGS_AUTH_FIELDS: dict[str, str] = {
    "GITHUB_TOKEN": "github_token",
    "TELEGRAM_API_ID": "telegram_api_id",
    "TELEGRAM_API_HASH": "telegram_api_hash",
    "TELEGRAM_SESSION_STRING": "telegram_session_string",
    # Not yet Settings fields - fall back to os.environ until an adapter
    # needing them is built: YOUTUBE_API_KEY, X_BEARER_TOKEN,
    # PRODUCT_HUNT_TOKEN, SEMANTIC_SCHOLAR_API_KEY.
}


def is_auth_configured(name: str) -> bool:
    """Return whether the named credential is configured. Never logs or returns its value."""
    field_name = _SETTINGS_AUTH_FIELDS.get(name)
    if field_name is not None:
        return getattr(settings, field_name) is not None

    return bool(os.environ.get(name))
