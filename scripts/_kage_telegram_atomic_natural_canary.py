"""One-shot natural-candidate canary orchestration for the frozen KAGE release.

This helper selects with the production selector once, snapshots and claims that
same event, then passes only that ID into the unchanged content cycle. It is an
orchestration boundary, not a selector or product-behavior change.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID

import asyncpg
from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story_link import NewsEventStoryLink
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from scripts._canary_delivery_cap import HardDeliveryCap, wrap_bot_with_hard_cap
from scripts._kage_telegram_hard_cost_canary import _configure_frozen_canary_settings
from services.kage_delivery_truth import event_publication_state
from services.kage_telegram_canary_envelope import (
    CANARY_STAGE_INPUT_TOKEN_CAPS,
    CANARY_STAGE_OUTPUT_TOKEN_CAPS,
    TelegramCanaryEnvelope,
    maximum_canary_cost,
    telegram_canary_envelope,
    validate_request_envelope_contracts,
)
from services.news_editorial_relevance import evaluate_pre_generation_candidate
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from worker.content_cycle import _extract_scoring_result, _select_eligible_events, run_content_cycle

MAX_COST = Decimal("0.746389")
EXPECTED_ROUTE = RouteTarget(chat_id=-1004297182444, topic_id=2)
PROMPTS_ROOT = Path("/app/prompts")
POLL_SECONDS = 15
WAIT_SECONDS = 6 * 60 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configure_isolated_canary_redis() -> str:
    """Require an explicitly supplied disposable Redis endpoint for this process."""
    isolated_host = os.environ.get("KAGE_CANARY_REDIS_HOST", "").strip()
    if not isolated_host or isolated_host == settings.redis_host:
        raise RuntimeError("refusing canary: an isolated Redis host must be explicitly configured")
    settings.redis_host = isolated_host
    settings.redis_port = 6379
    settings.redis_db = 0
    return settings.redis_url


def _markup_buttons(markup: object | None) -> list[list[dict[str, str | None]]]:
    return [
        [{"text": button.text, "url": button.url} for button in row]
        for row in (getattr(markup, "inline_keyboard", None) or [])
    ]


def _photo_metadata(photo: object | None) -> dict[str, object]:
    result: dict[str, object] = {"input_type": type(photo).__name__ if photo is not None else None}
    filename = getattr(photo, "filename", None) or getattr(photo, "name", None)
    if filename:
        result["filename"] = str(filename)
    data = getattr(photo, "data", None)
    if isinstance(data, (bytes, bytearray)):
        result["sha256"] = hashlib.sha256(data).hexdigest()
        result["bytes"] = len(data)
    else:
        path = getattr(photo, "path", None)
        if path and Path(path).is_file():
            raw = Path(path).read_bytes()
            result["sha256"] = hashlib.sha256(raw).hexdigest()
            result["bytes"] = len(raw)
    return result


class AtomicNaturalCanary:
    def __init__(self) -> None:
        self.ro_engine = create_async_engine(
            settings.database_url,
            connect_args={"server_settings": {"default_transaction_read_only": "on"}},
        )
        self.claim_connection: asyncpg.Connection | None = None
        self.claim_key: int | None = None

    @asynccontextmanager
    async def _read_only_session(self) -> AsyncIterator[AsyncSession]:
        async with self.ro_engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                default_read_only = (await connection.execute(
                    text("SHOW default_transaction_read_only")
                )).scalar_one()
                transaction_read_only = (await connection.execute(
                    text("SHOW transaction_read_only")
                )).scalar_one()
                if str(default_read_only).lower() != "on" or str(transaction_read_only).lower() != "on":
                    raise RuntimeError("dual production read-only verification failed")
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    yield session
            finally:
                if transaction.is_active:
                    await transaction.rollback()

    async def _snapshot(self, session: AsyncSession, event_id: UUID) -> dict[str, object] | None:
        row = (await session.execute(
            select(
                NewsEvent.id, NewsEvent.title, NewsEvent.content, NewsEvent.published_at,
                NewsEvent.collected_at, NewsSource.name, NewsSource.reliability_score,
                EditorialTask.status, EditorialTask.updated_at, EditorialTask.workflow,
            )
            .join(NewsSource, NewsSource.id == NewsEvent.source_id)
            .join(EditorialTask, EditorialTask.event_id == NewsEvent.id)
            .where(
                NewsEvent.id == event_id,
                EditorialTask.workflow["workflow_name"].as_string() == "NEWS_ANALYSIS",
            )
            .order_by(EditorialTask.updated_at.desc())
            .limit(1)
        )).first()
        if row is None:
            return None
        (event_id, title, content, published_at, collected_at, source, reliability,
         task_status, task_updated_at, workflow) = row
        score = _extract_scoring_result(workflow if isinstance(workflow, dict) else {})
        decision = evaluate_pre_generation_candidate(
            title=title,
            content=content,
            standard_score=score,
            standard_threshold=settings.content_generation_min_score,
            source_reliability=reliability,
            published_at=published_at or collected_at,
            primary_evidence=any(token in source.lower() for token in ("github", "arxiv")),
            require_source_detail=(
                settings.copywriting_prompt_version == "11.10"
                and settings.article_acquisition_mode != "enforce"
            ),
            product_loop=settings.copywriting_prompt_version == "11.10",
        )
        content_tasks = int((await session.execute(
            select(func.count()).select_from(EditorialTask).where(
                EditorialTask.event_id == event_id,
                EditorialTask.workflow["workflow_name"].as_string() == "CONTENT_GENERATION",
            )
        )).scalar_one())
        # Durable event -> task -> draft -> receipt / publication_outcome path; the receipt's
        # source_event_id is never populated by record_delivery() and must not be used here.
        publication = await event_publication_state(session, event_id)
        deliveries = len(publication["delivered_task_ids"])
        story_id = (await session.execute(
            select(NewsEventStoryLink.story_id).where(
                NewsEventStoryLink.news_event_id == event_id,
            )
        )).scalar_one_or_none()
        now = _utc_now()
        anchor = published_at or collected_at
        task_status_value = getattr(task_status, "value", str(task_status))
        fresh = task_updated_at >= now - timedelta(
            hours=settings.content_generation_freshness_cutoff_hours
        )
        return {
            "event_id": str(event_id),
            "story_id": str(story_id) if story_id else None,
            "title": title,
            "source": source,
            "score": score,
            "event_age_hours": round((now - anchor.astimezone(timezone.utc)).total_seconds() / 3600, 3),
            "analysis_task_updated_at": task_updated_at.isoformat(),
            "analysis_task_status": task_status_value,
            "analysis_fresh": fresh,
            "content_generation_tasks": content_tasks,
            "delivery_records": deliveries,
            "delivery_receipt_ids": publication["sent_receipt_ids"],
            "publication_in_flight_tasks": publication["in_flight_task_ids"],
            "selector_result": {
                "eligible": decision.final_eligible,
                "selection_path": decision.selection_path,
                "rank_score": decision.rank_score,
                "reason": decision.reason,
            },
            "selector_selected_at": _utc_now().isoformat(),
            "valid": (
                task_status_value == "COMPLETED" and fresh and content_tasks == 0
                and deliveries == 0 and decision.final_eligible
            ),
        }

    async def select_top(self) -> dict[str, object] | None:
        async with self._read_only_session() as session:
            selected = await _select_eligible_events(session, max_results=1)
            return await self._snapshot(session, selected[0]) if selected else None

    async def recheck_same_event(self, event_id: UUID) -> dict[str, object] | None:
        async with self._read_only_session() as session:
            return await self._snapshot(session, event_id)

    async def claim(self, event_id: UUID) -> bool:
        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self.claim_connection = await asyncpg.connect(dsn=dsn)
        self.claim_key = event_id.int & ((1 << 63) - 1)
        if self.claim_key == 0:
            self.claim_key = 1
        return bool(await self.claim_connection.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)", self.claim_key
        ))

    async def release(self) -> None:
        if self.claim_connection is not None and not self.claim_connection.is_closed():
            if self.claim_key is not None:
                await self.claim_connection.fetchval(
                    "SELECT pg_advisory_unlock($1::bigint)", self.claim_key
                )
            await self.claim_connection.close()
        self.claim_connection = None

    async def close(self) -> None:
        await self.release()
        await self.ro_engine.dispose()


async def _run_claimed(event_id: UUID, selection: dict[str, object], ai, bot, prompts, pricing) -> dict[str, object]:
    delivery_cap = HardDeliveryCap(max_deliveries=1)
    sends: list[dict[str, object]] = []
    original_message = bot.send_message
    original_photo = bot.send_photo

    async def tap_message(*args, **kwargs):
        bound = inspect.signature(original_message).bind_partial(*args, **kwargs)
        try:
            response = await original_message(*args, **kwargs)
        except Exception as exc:
            sends.append({
                "method": "send_message",
                "chat_id": bound.arguments.get("chat_id"),
                "topic_id": bound.arguments.get("message_thread_id"),
                "status": "failed",
                "error_class": type(exc).__name__,
            })
            raise
        sends.append({
            "method": "send_message",
            "chat_id": bound.arguments.get("chat_id"),
            "topic_id": bound.arguments.get("message_thread_id"),
            "text": getattr(response, "text", None) or bound.arguments.get("text"),
            "buttons": _markup_buttons(bound.arguments.get("reply_markup")),
            "message_id": getattr(response, "message_id", None),
            "telegram_chat_id": getattr(getattr(response, "chat", None), "id", None),
            "status": "accepted",
        })
        return response

    async def tap_photo(*args, **kwargs):
        bound = inspect.signature(original_photo).bind_partial(*args, **kwargs)
        media = _photo_metadata(bound.arguments.get("photo"))
        try:
            response = await original_photo(*args, **kwargs)
        except Exception as exc:
            sends.append({
                "method": "send_photo",
                "chat_id": bound.arguments.get("chat_id"),
                "topic_id": bound.arguments.get("message_thread_id"),
                "sent_photo": media,
                "status": "failed",
                "error_class": type(exc).__name__,
            })
            raise
        sends.append({
            "method": "send_photo",
            "chat_id": bound.arguments.get("chat_id"),
            "topic_id": bound.arguments.get("message_thread_id"),
            "caption": getattr(response, "caption", None) or bound.arguments.get("caption"),
            "buttons": _markup_buttons(bound.arguments.get("reply_markup")),
            "message_id": getattr(response, "message_id", None),
            "telegram_chat_id": getattr(getattr(response, "chat", None), "id", None),
            "sent_photo": media,
            "status": "accepted",
        })
        return response

    bot.send_message = tap_message
    bot.send_photo = tap_photo
    wrap_bot_with_hard_cap(bot, delivery_cap)
    envelope = TelegramCanaryEnvelope(hard_cap_usd=MAX_COST)
    selected_at = datetime.fromisoformat(str(selection["selector_selected_at"]))
    first_dispatch: datetime | None = None
    authorize = envelope.authorize_dispatch

    def timed_authorize(request, model):
        nonlocal first_dispatch
        authorize(request, model)
        dispatched_at = _utc_now()
        envelope.dispatch_records[-1]["dispatch_at_utc"] = dispatched_at.isoformat()
        if first_dispatch is None:
            first_dispatch = dispatched_at
            envelope.dispatch_records[-1]["selection_to_dispatch_seconds"] = round(
                (dispatched_at - selected_at).total_seconds(), 3
            )

    envelope.authorize_dispatch = timed_authorize
    if envelope.max_cost_usd != MAX_COST or maximum_canary_cost() != MAX_COST:
        raise RuntimeError("hard envelope maximum changed")
    if envelope.workflow_step_attempts() != 1 or envelope.same_model_retries() != 0:
        raise RuntimeError("retry bound changed")
    if not CANARY_STAGE_INPUT_TOKEN_CAPS or not CANARY_STAGE_OUTPUT_TOKEN_CAPS:
        raise RuntimeError("application input/output bounds are not active")
    route = resolve_route(EditorialDestination.NEWS)
    if route != EXPECTED_ROUTE:
        raise RuntimeError("NEWS route changed before provider execution")
    try:
        with telegram_canary_envelope(envelope):
            result = await run_content_cycle(
                ai.capability_registry,
                bot,
                session_factory=async_session_factory,
                cost_tracker=ai.cost_tracker,
                pricing_catalog=pricing,
                gate_gateway=ai.gateway,
                gate_prompt_repository=prompts,
                event_ids_override=[event_id],
            )
        actual = sum(
            (Decimal(str(row["actual_cost_usd"])) for row in envelope.dispatch_records
             if row.get("actual_cost_usd") is not None),
            Decimal("0"),
        )
        return {
            "cycle": {
                "event_ids": [str(value) for value in result.event_ids],
                "generation_attempts": result.generation_attempts,
                "completed": result.completed,
                "failed": result.failed,
                "notified": result.notified,
                "factual_gate_pass": result.factual_gate_pass,
                "factual_gate_block": result.factual_gate_block,
                "local_guard_block": result.local_guard_block,
                "publication_records": result.publication_gate_records,
            },
            "selection": selection,
            "first_provider_dispatch_at_utc": first_dispatch.isoformat() if first_dispatch else None,
            "selection_to_first_dispatch_seconds": (
                round((first_dispatch - selected_at).total_seconds(), 3) if first_dispatch else None
            ),
            "provider_dispatches": envelope.dispatch_records,
            "provider_calls": len(envelope.dispatch_records),
            "actual_cost_usd": str(actual),
            "max_cost_usd": str(envelope.max_cost_usd),
            "hard_cap_usd": str(envelope.hard_cap_usd),
            "delivery_attempts": delivery_cap.attempted,
            "sends": sends,
        }
    finally:
        await bot.session.close()


_isolated_redis: Redis


async def main() -> None:
    setup_logging()
    _configure_frozen_canary_settings()
    if resolve_route(EditorialDestination.NEWS) != EXPECTED_ROUTE:
        raise RuntimeError("NEWS destination mismatch")
    if maximum_canary_cost() != MAX_COST:
        raise RuntimeError("precomputed worst-case cost changed")
    request_envelope_contracts = validate_request_envelope_contracts()
    prompts = FilePromptRepository(PROMPTS_ROOT)
    versions = {
        name: prompts.resolve(name, version).version
        for name, version in (
            ("research", "5"), ("intelligence", "4"), ("copywriting", "11.10"),
            ("quality", "9.2"), ("publication_factual_gate", "1"),
        )
    }
    print(json.dumps({
        "event": "KAGE_CANARY_PREARM_VALIDATION",
        "request_envelope_output_contracts": request_envelope_contracts,
        "max_canary_cost_usd": str(maximum_canary_cost()),
        "hard_cap_usd": str(MAX_COST),
        "provider_calls": 0,
    }), flush=True)
    global _isolated_redis
    isolated_redis_url = _configure_isolated_canary_redis()
    _isolated_redis = Redis.from_url(isolated_redis_url, decode_responses=True)
    if not await _isolated_redis.ping() or await _isolated_redis.dbsize() != 0:
        raise RuntimeError("isolated diagnostic Redis is unavailable or not empty")
    # Initialize the real provider/capability path before waiting; this makes the found-to-run
    # interval immediate and never touches production Redis because redis_client is injected.
    ai = assemble_ai_integration_layer(settings, prompts, redis_client=_isolated_redis)
    bot = create_bot()
    pricing = ModelRegistryPricingCatalog(build_model_registry())
    controller = AtomicNaturalCanary()
    deadline = time.monotonic() + WAIT_SECONDS
    last_wait_log = time.monotonic()
    outcome: dict[str, object] | None = None
    try:
        while time.monotonic() < deadline:
            selection = await controller.select_top()
            if selection is None:
                if time.monotonic() - last_wait_log >= 300:
                    print(json.dumps({
                        "event": "KAGE_CANARY_WAITING",
                        "at_utc": _utc_now().isoformat(),
                        "waited_seconds": int(WAIT_SECONDS - (deadline - time.monotonic())),
                        "provider_calls": 0,
                    }), flush=True)
                    last_wait_log = time.monotonic()
                await asyncio.sleep(POLL_SECONDS)
                continue
            if not selection.get("valid"):
                if (selection.get("content_generation_tasks", 0)
                        or selection.get("delivery_records", 0)
                        or not selection.get("analysis_fresh")):
                    await asyncio.sleep(POLL_SECONDS)
                    continue
                raise RuntimeError("selector/evaluator disagreement; refusing bypass")
            event_id = UUID(str(selection["event_id"]))
            if not await controller.claim(event_id):
                await controller.release()
                await asyncio.sleep(POLL_SECONDS)
                continue
            recheck = await controller.recheck_same_event(event_id)
            if not recheck or not recheck.get("valid"):
                await controller.release()
                if (recheck and (recheck.get("content_generation_tasks", 0)
                                 or recheck.get("delivery_records", 0)
                                 or not recheck.get("analysis_fresh"))):
                    await asyncio.sleep(POLL_SECONDS)
                    continue
                raise RuntimeError("same-event claim recheck failed; refusing bypass")
            # Keep the selection snapshot; recheck is a validation of the same ID, never a new pick.
            selection["claim_acquired_at_utc"] = _utc_now().isoformat()
            selection["claim"] = "PostgreSQL session advisory lock held through this attempt"
            selection["runtime_versions"] = versions
            selection["provider_calls_so_far"] = 0
            print(json.dumps({"event": "KAGE_CANARY_CANDIDATE_CLAIMED", "selection": selection},
                             ensure_ascii=False), flush=True)
            outcome = await _run_claimed(event_id, selection, ai, bot, prompts, pricing)
            print(json.dumps({"event": "KAGE_CANARY_FINISHED", **outcome},
                             ensure_ascii=False, default=str), flush=True)
            return
        print(json.dumps({
            "event": "NO_NATURAL_CANARY_CANDIDATE", "waited_hours": 6, "provider_calls": 0,
        }), flush=True)
    finally:
        await controller.close()
        await bot.session.close()
        await _isolated_redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
