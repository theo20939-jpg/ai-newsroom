"""TELEGRAPH LIVE PUBLISH: one-shot operator bootstrap command - creates a NEW Telegraph account
via the real `createAccount` API call and prints its `access_token` for the operator to copy into
`.env` as `TELEGRAPH_ACCESS_TOKEN`.

Run manually, exactly once (per Telegraph account this newsroom will publish under):

    python -m scripts.create_telegraph_account
    python -m scripts.create_telegraph_account --short-name "Ninja Pulse" --author-name "NINJA PULSE"

Never invoked by any worker, scheduler, or handler in this codebase -
services/telegraph_publisher.py::create_account() has exactly one caller: this script. Running it
TWICE creates a SECOND, independent Telegraph account/token; it does not "refresh" or "rotate" an
existing one. Do not run it again once `TELEGRAPH_ACCESS_TOKEN` is already set and working.

The printed `access_token` is NEVER written to any file by this script - not `.env`, not a log
file. The operator must copy it manually. Nothing in this codebase logs this value at any level
(services/telegraph_publisher.py never logs it; this script's own `print()` calls below are the
only place it is ever displayed, deliberately - `print()`, not `logger`, so it never lands in a
structured log sink)."""
from __future__ import annotations

import argparse
import asyncio

from services.telegraph_publisher import create_account


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--short-name", default="Ninja Pulse",
        help="Telegraph account short_name, 1-32 chars (default: 'Ninja Pulse').",
    )
    parser.add_argument(
        "--author-name", default="NINJA PULSE",
        help="Default author_name attached to pages created with this account (default: 'NINJA PULSE').",
    )
    parser.add_argument("--author-url", default=None, help="Optional default author_url.")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    account = await create_account(
        short_name=args.short_name, author_name=args.author_name, author_url=args.author_url,
    )
    print("Telegraph account created.")
    print(f"short_name:   {account.short_name}")
    print(f"author_name:  {account.author_name}")
    print(f"access_token: {account.access_token}")
    print()
    print("SAVE THIS NOW - add the following line to .env:")
    print(f"TELEGRAPH_ACCESS_TOKEN={account.access_token}")
    print()
    print("This access_token will not be shown again by this script. Never commit it to Git.")


if __name__ == "__main__":
    asyncio.run(main())
