"""Phase 23.1L Part F/G - a true, per-message hard delivery cap for bounded live canaries (docs/
phase23_1l_runtime_isolation_final_canary_report.md).

Root cause of the Phase 23.1K incident (6 sends against max_deliveries=5): the canary script's own
stop condition (`if total_notified >= target: break`) was checked once BETWEEN rounds, not before
each individual Telegram send. `worker/content_cycle.py::run_content_cycle()` can itself deliver
more than one message per call (bounded by `content_generation_scan_limit`/batch processing, not by
any per-message budget), so a round that started below the target could still push the total past
it in one call.

Deliberately NOT a change to `worker/content_cycle.py` or any other production editorial service -
per the phase brief's own explicit "do not inject test-specific counters throughout production
editorial services; keep the bound at the orchestration boundary responsible for the bounded live
canary" instruction. This module wraps the `aiogram.Bot` instance a canary script itself
constructs and passes into `run_content_cycle()` - the real Telegram-facing call site - so the
budget is enforced at the last possible moment before any network call, regardless of how many
candidates a single round/batch happens to contain.

`HardDeliveryCap.try_consume()` is a synchronous, in-process counter check - no I/O - called
immediately before delegating to the real `bot.send_message`/`bot.send_photo`. Once exhausted, it
raises `DeliveryCapExhaustedError` (a real `TelegramAPIError` subclass) instead of letting the
call reach aiogram at all - `services/telegram_routing.py`'s existing `except TelegramAPIError:`
handling already treats this exactly like any other failed send (records `notification_failed`,
returns `RoutingOutcome(sent=False, ...)`, never crashes the cycle) - no new error-handling path
needed anywhere in production code.

Budget semantics (documented per Part G Case 6): the budget is consumed on every SEND ATTEMPT
(`try_consume()` runs before the real call, success or failure), not only on confirmed successful
deliveries. The invariant this cap protects is "at most N real calls ever reach the Telegram API"
- if only successful sends counted, an unbounded number of failing attempts could still exhaust
real API quota/cost while never being counted against the cap, defeating its purpose as a hard
runtime safety control.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError


class DeliveryCapExhaustedError(TelegramAPIError):
    """Raised instead of letting a Telegram send reach aiogram once the hard per-message delivery
    cap has been reached. A real TelegramAPIError subclass (not aiogram's own __init__, which
    requires a constructed TelegramMethod this cap never has) so every existing `except
    TelegramAPIError:` call site already handles it safely, with zero new code."""

    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)
        self.message = message


@dataclass
class HardDeliveryCap:
    """Immediately BEFORE every Telegram send: if attempted >= max_deliveries: refuse. Enforced
    per individual message, never per batch/round/after-send - `try_consume()` is the only mutator
    and the only gate, called from the wrapped bot methods below, nowhere else."""

    max_deliveries: int
    attempted: int = 0
    attempts_log: list[str] = field(default_factory=list)

    def try_consume(self, *, label: str = "") -> None:
        if self.attempted >= self.max_deliveries:
            raise DeliveryCapExhaustedError(
                f"Hard delivery cap reached ({self.attempted}/{self.max_deliveries}) - refusing to send{f' ({label})' if label else ''}."
            )
        self.attempted += 1
        self.attempts_log.append(label)

    @property
    def remaining(self) -> int:
        return max(0, self.max_deliveries - self.attempted)


def wrap_bot_with_hard_cap(bot: Bot, cap: HardDeliveryCap) -> None:
    """Patches `bot.send_message`/`bot.send_photo` in place so every call - regardless of which
    production code path (worker/content_cycle.py or anything else) invokes it through this same
    `bot` instance - is gated by `cap.try_consume()` first. Idempotent to call once per canary
    script run; not intended to be reusable across multiple bot instances."""
    original_send_message = bot.send_message
    original_send_photo = bot.send_photo

    async def _capped_send_message(chat_id: Any, text: Any = None, *args: Any, **kwargs: Any) -> Any:
        cap.try_consume(label=f"send_message chat_id={chat_id}")
        return await original_send_message(chat_id, text, *args, **kwargs)

    async def _capped_send_photo(chat_id: Any, *args: Any, **kwargs: Any) -> Any:
        cap.try_consume(label=f"send_photo chat_id={chat_id}")
        return await original_send_photo(chat_id, *args, **kwargs)

    bot.send_message = _capped_send_message  # type: ignore[method-assign]
    bot.send_photo = _capped_send_photo  # type: ignore[method-assign,assignment]
