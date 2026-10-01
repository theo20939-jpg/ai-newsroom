"""KAGE INSTAGRAM - FINAL CURRENT-STATE NATURAL ACCEPTANCE (one run, 2026-10-01).

= scripts/_instagram_viral_nominated_canary.py UNCHANGED (the worker's own per-slot path on a fresh READ-ONLY production pool, scratch DB, capped
isolated ledgers) + two additions that live only in this wrapper:
  1. the worker's own tried-skip (KAGE_TRIED_IDS: event ids already tried this cycle, exactly worker/content_cycle's mark_tried + continue);
  2. the Telegram review delivery is REAL for exactly one READY_FOR_EDITOR package, to the authorised Instagram topic only
     (chat -1004297182444, topic 40), through the product's own services.instagram_telegram_delivery.deliver_instagram_package
     (duplicate prevention, strict-topic fail-closed). A HOLD / BLOCK package is recorded locally and NOTHING is sent.
     Before the run a getMe preflight proves the credential. No Instagram publication path exists in this process.
The bot token is read from the main checkout's .env into this process only and is never printed or written.
Usage: python scripts/_instagram_final_acceptance_run.py <pool.jsonl> <members.jsonl> <out dir>
"""
import asyncio
import os
import runpy
import sys
from pathlib import Path

WT = Path(__file__).resolve().parent.parent
MAIN_ENV = WT.parent.parent / ".env"
AUTHORISED_CHAT_ID = -1004297182444
AUTHORISED_TOPIC_ID = 40

for line in MAIN_ENV.read_text(encoding="utf-8").splitlines():  # the Bot API credential only
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        os.environ["TELEGRAM_BOT_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
os.environ["NEWSROOM_TELEGRAM_CHAT_ID"] = str(AUTHORISED_CHAT_ID)
os.environ["INSTAGRAM_TOPIC_ID"] = str(AUTHORISED_TOPIC_ID)
sys.path.insert(0, str(WT))

import scripts._instagram_controlled_completion as cc_script  # noqa: E402
import scripts._instagram_e2e_week as harness  # noqa: E402
import services.instagram_automatic_trigger as trigger  # noqa: E402
import services.instagram_viral_nomination as nom  # noqa: E402
from core.config import settings  # noqa: E402

from aiohttp import ClientSession
from aiohttp.hdrs import USER_AGENT
from aiohttp.http import SERVER_SOFTWARE
from aiogram import __version__
from aiogram.client.session.aiohttp import AiohttpSession


class EnvProxySession(AiohttpSession):
    """aiogram session that honours HTTPS_PROXY (the machine reaches api.telegram.org only through its local proxy); same as AiohttpSession otherwise."""

    async def create_session(self) -> ClientSession:
        if self._session is None or self._session.closed:
            self._session = ClientSession(connector=self._connector_type(**self._connector_init), trust_env=True,
                                          headers={USER_AGENT: f"{SERVER_SOFTWARE} aiogram/{__version__}"})
            self._should_reset_connector = False
        return self._session


out = Path(sys.argv[3])
assert settings.newsroom_telegram_chat_id == AUTHORISED_CHAT_ID and settings.instagram_topic_id == AUTHORISED_TOPIC_ID, "unexpected Telegram routing"
SENT = {"count": 0}


async def _get_me() -> dict:
    from aiogram import Bot

    bot = Bot(token=settings.telegram_bot_token.get_secret_value(), session=EnvProxySession())
    try:
        me = await bot.get_me()
        return {"ok": True, "id": me.id, "username": me.username}
    finally:
        await bot.session.close()


GETME = asyncio.run(_get_me())
print("getMe preflight:", GETME)

real_install = harness._install_capture


def install_with_live_delivery():
    suit = real_install()
    recorded = trigger.deliver_instagram_package  # the harness's no-Telegram recorder (HOLD / BLOCK path)

    async def live(bot, session, *, presentation, gate_decision, package_identity, source_story_id, content_format, package_snapshot,
                   source_url=None, hold_or_block_reason=None):
        from aiogram import Bot

        from services.instagram_telegram_delivery import deliver_instagram_package

        target = out / "telegram_review_payload"
        target.mkdir(parents=True, exist_ok=True)
        files = []
        for i, media in enumerate(presentation.media, 1):
            path = target / f"media_{i:02d}.png"
            path.write_bytes(media)
            files.append(path.name)
        (target / "control_text.html").write_text(presentation.control_text, encoding="utf-8")
        if presentation.overflow_text:
            (target / "overflow_text.html").write_text(presentation.overflow_text, encoding="utf-8")
        payload = {"LABEL": "FOUNDER REVIEW PACKAGE - NO INSTAGRAM PUBLICATION", "kind": presentation.kind, "version_label": presentation.version_label,
                   "media_in_order": files, "gate_decision": gate_decision.value, "hold_or_block_reason": hold_or_block_reason,
                   "package_identity": package_identity, "getMe": GETME,
                   "destination": {"chat_id": settings.newsroom_telegram_chat_id, "topic_id": settings.instagram_topic_id}}
        if gate_decision.value != "ready_for_editor" or SENT["count"] >= 1:
            payload["send_outcome"] = {"sent": False, "reason": "not a READY package or already sent once - recorded locally, nothing sent"}
            harness._write(target / "payload.json", payload)
            return await recorded(bot, session, presentation=presentation, gate_decision=gate_decision, package_identity=package_identity,
                                  source_story_id=source_story_id, content_format=content_format, package_snapshot=package_snapshot,
                                  source_url=source_url, hold_or_block_reason=hold_or_block_reason)
        SENT["count"] += 1
        real_bot = Bot(token=settings.telegram_bot_token.get_secret_value(), session=EnvProxySession())
        try:
            outcome = await deliver_instagram_package(
                real_bot, session, presentation=presentation, gate_decision=gate_decision, package_identity=package_identity,
                source_story_id=source_story_id, content_format=content_format, package_snapshot=package_snapshot,
                source_url=source_url, hold_or_block_reason=hold_or_block_reason)
        finally:
            await real_bot.session.close()
        row = None
        try:
            from database.models.instagram_editorial_delivery import InstagramEditorialDelivery
            from sqlalchemy import select

            row = await session.scalar(select(InstagramEditorialDelivery).where(InstagramEditorialDelivery.package_identity == package_identity)
                                       .order_by(InstagramEditorialDelivery.version.desc()).limit(1))
        except Exception as exc:  # observation only
            payload["delivery_row_read_error"] = repr(exc)[:200]
        payload["send_outcome"] = {"sent": outcome.sent, "reason": outcome.reason, "delivery_id": outcome.delivery_id, "version": outcome.version,
                                   "state": str(getattr(row, "state", None)), "chat_id": getattr(row, "chat_id", None),
                                   "topic_id": getattr(row, "topic_id", None), "media_message_ids": getattr(row, "media_message_ids", None),
                                   "control_message_id": getattr(row, "control_message_id", None)}
        harness._write(target / "payload.json", payload)
        return outcome

    trigger.deliver_instagram_package = live
    return suit


harness._install_capture = install_with_live_delivery

TRIED = {t for t in os.environ.get("KAGE_TRIED_IDS", "").split(",") if t}
real_reads = nom.nominated_reads


def reads_after_tried(nomination, limit):
    return [(p, r) for p, r in real_reads(nomination, limit) if p.id not in TRIED]


nom.nominated_reads = reads_after_tried
_ = cc_script  # imported so the harness's capture hooks resolve in the same way as the unchanged canary
sys.argv = [str(WT / "scripts/_instagram_viral_nominated_canary.py"), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
