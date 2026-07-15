"""One-time interactive utility to generate a Telethon StringSession.

Launch with:
    python -m scripts.create_telegram_session

Reads TELEGRAM_API_ID / TELEGRAM_API_HASH from .env (core.config.settings).
Prompts interactively for the phone number, login code and - if two-step
verification is enabled - the 2FA password, using Telethon's standard
login flow. Prints the resulting TELEGRAM_SESSION_STRING for you to copy
into .env by hand.

Does not create a .session file (only an in-memory StringSession is used)
and never writes to .env itself.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import ENV_FILE, settings


def _check_configuration() -> None:
    """Give a precise, actionable diagnostic for each missing piece of config.

    Debugging aid only: pinpoints whether .env was found at all versus which
    specific variable inside it is missing, instead of one generic error.
    """
    if not ENV_FILE.exists():
        raise RuntimeError(f".env not found at {ENV_FILE}")

    missing = [
        name
        for name, value in (
            ("TELEGRAM_API_ID", settings.telegram_api_id),
            ("TELEGRAM_API_HASH", settings.telegram_api_hash),
        )
        if value is None
    ]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} missing from {ENV_FILE}")

    print(f".env loaded successfully from {ENV_FILE}")


async def main() -> None:
    """Run the interactive Telethon login flow and print the session string."""
    _check_configuration()

    client = TelegramClient(
        StringSession(),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )

    async with client:
        # Entering the client with an unauthorized StringSession triggers
        # Telethon's interactive login: phone number, then login code, then
        # the 2FA password if two-step verification is enabled.
        session_string = client.session.save()

    print("\nTELEGRAM_SESSION_STRING generated - copy the value below into your .env:\n")
    print(session_string)


if __name__ == "__main__":
    asyncio.run(main())
