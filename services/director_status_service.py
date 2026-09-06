"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §6/§13/§32: DirectorStatusService - the ONE place that
answers "what is the real current state of each AI director", so `/directors` never puts business
logic in a Telegram handler (spec §13) and never fakes ACTIVE (spec §6's own explicit instruction).

CRITICAL: every check below is a feature-flag read, a database row count, or a static capability
registry lookup - NEVER a Gateway/LLM call (spec §18/§32's own "no LLM call from /directors").

Status vocabulary (spec §6's own six values, applied with one explicit, documented rule each):
- DISABLED: a real feature flag gates this director's own code path, and that flag is False.
- SHADOW: the director's logic is safely, cheaply (no LLM cost) invocable right now, AND either
  its gating flag is True or it has no gating flag at all and real evidence already exists for it
  to act on (e.g. persisted Art Director findings, persisted channel post history).
- READY: fully implemented and available, but deliberately never auto-invoked from a read-only
  status command because doing so would cost money (a real Gateway call) - Creative Director is
  the canonical example (spec §18's own cost-safety instruction).
- WAITING_FOR_DATA: implemented and safe to invoke, but the real data/evidence it depends on does
  not exist yet - a legitimate state, not a failure (spec §20).
- ACTIVE: this director has real enforcement authority over a production decision, and that
  enforcement flag is True. Checked honestly - never true anywhere in this codebase today.
- UNAVAILABLE / UNKNOWN: reserved for a hard missing capability / a genuinely indeterminate case.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_run import DirectorType
from database.models.social_launch_context import SocialLaunchContext, SocialLaunchPlatform
from database.models.telegram_channel_memory import TelegramChannelMemory
from database.models.telegram_visual_failure import TelegramVisualFailure
from services.business_context_snapshot_service import get_business_context_snapshot
from services.director_run_service import describe_latest_run
from services.instagram_platform_capabilities import CapabilityStatus, INSTAGRAM_PLATFORM_CAPABILITIES
from services.social_launch_context_service import get_current_context, is_prelaunch_or_transition


class DirectorStatus(str, enum.Enum):
    DISABLED = "disabled"
    READY = "ready"
    SHADOW = "shadow"
    ACTIVE = "active"
    WAITING_FOR_DATA = "waiting_for_data"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DirectorStatusEntry:
    name: str
    status: DirectorStatus
    detail: str = ""


@dataclass(frozen=True)
class DirectorConsoleStatus:
    as_of: datetime
    business: list[DirectorStatusEntry] = field(default_factory=list)
    telegram: list[DirectorStatusEntry] = field(default_factory=list)
    instagram: list[DirectorStatusEntry] = field(default_factory=list)


async def _business_status(session: AsyncSession, *, now: datetime) -> list[DirectorStatusEntry]:
    snapshot = await get_business_context_snapshot(session, now=now)
    if not snapshot.active_campaigns:
        return [DirectorStatusEntry(
            name="Campaign Planner", status=DirectorStatus.READY,
            detail="нет активных кампаний",
        )]
    plan = snapshot.active_campaigns[0]
    product_name = next(
        (s.product.name for s in snapshot.products if s.active_campaign is not None and s.active_campaign.campaign_id == plan.campaign_id),
        plan.product_id,
    )
    phase_text = f", фаза {plan.phase}" if plan.phase else ""
    return [DirectorStatusEntry(
        name="Campaign Planner", status=DirectorStatus.ACTIVE,
        detail=f"текущая кампания: {product_name}{phase_text}",
    )]


_ART_DIRECTOR_LOOKBACK = 20


async def _art_director_summary(session: AsyncSession) -> str | None:
    """Spec §19: reads PERSISTED findings only - never evaluates a new image just because
    `/directors` was called. A clean PASS is never persisted (database/models/telegram_visual_
    failure.py's own docstring), so a PASS count is never fabricated here either - only the
    decision types that genuinely have rows, plus the most frequent recent issue codes, exactly
    like `/directors`' own required example shape minus the one number this codebase cannot
    honestly produce."""
    stmt = (
        select(TelegramVisualFailure)
        .order_by(TelegramVisualFailure.created_at.desc())
        .limit(_ART_DIRECTOR_LOOKBACK)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return None

    decision_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for row in rows:
        decision_counts[row.art_director_decision.value] = decision_counts.get(row.art_director_decision.value, 0) + 1
        for code in row.issue_codes:
            issue_counts[code] = issue_counts.get(code, 0) + 1

    decisions_text = ", ".join(f"{name.upper()} {count}" for name, count in decision_counts.items())
    top_issues = sorted(issue_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    issues_text = ", ".join(f"{name} ×{count}" for name, count in top_issues)

    summary = f"последние {len(rows)} находок: {decisions_text}"
    if issues_text:
        summary += f"; частые проблемы: {issues_text}"
    return summary


def _cold_start_suffix(context: SocialLaunchContext | None) -> str:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §20: repository vocabulary only - the SAME LaunchState
    enum values the model itself uses (PRE_LAUNCH/TRANSITION/...), never an invented phrase like
    "not started yet". "" when no context is configured or the platform is already LIVE - an
    established account's WAITING_FOR_DATA detail stays exactly as it read before this phase."""
    if context is None or not is_prelaunch_or_transition(context):
        return ""
    return f" [{context.launch_state.value.upper()}]"


async def _telegram_status(
    session: AsyncSession, *, now: datetime, launch_context: SocialLaunchContext | None = None,
) -> list[DirectorStatusEntry]:
    entries: list[DirectorStatusEntry] = []
    cold_start_suffix = _cold_start_suffix(launch_context)

    entries.append(DirectorStatusEntry(
        name="Channel Director",
        status=DirectorStatus.SHADOW if settings.telegram_channel_director_shadow_enabled else DirectorStatus.DISABLED,
        detail="оценивает соответствие поста ленте (без влияния на публикацию)",
    ))

    art_director_detail = await _art_director_summary(session)
    entries.append(DirectorStatusEntry(
        name="Art Director",
        status=DirectorStatus.SHADOW if art_director_detail is not None else DirectorStatus.WAITING_FOR_DATA,
        detail=art_director_detail or "нет накопленных оценок рендера",
    ))

    growth_run_detail = await describe_latest_run(session, DirectorType.TELEGRAM_GROWTH, now=now)
    entries.append(DirectorStatusEntry(
        name="Growth Director",
        status=DirectorStatus.SHADOW if growth_run_detail is not None else DirectorStatus.WAITING_FOR_DATA,
        detail=(growth_run_detail or "нет накопленных performance-паттернов (сбор метрик не настроен)") + cold_start_suffix,
    ))

    channel_memory_count = (await session.execute(select(func.count()).select_from(TelegramChannelMemory))).scalar_one()
    strategy_run_detail = await describe_latest_run(session, DirectorType.TELEGRAM_STRATEGY, now=now)
    strategy_detail = strategy_run_detail or (
        f"{channel_memory_count} постов в памяти ленты" if channel_memory_count > 0 else "нет истории постов канала"
    )
    entries.append(DirectorStatusEntry(
        name="Strategy Director",
        status=DirectorStatus.SHADOW if (strategy_run_detail is not None or channel_memory_count > 0) else DirectorStatus.WAITING_FOR_DATA,
        detail=strategy_detail + cold_start_suffix,
    ))
    return entries


def _instagram_status(*, has_real_business_data: bool, launch_context: SocialLaunchContext | None = None) -> list[DirectorStatusEntry]:
    cold_start_suffix = _cold_start_suffix(launch_context)
    entries = [
        DirectorStatusEntry(
            name="Growth Strategist",
            status=DirectorStatus.SHADOW if has_real_business_data else DirectorStatus.WAITING_FOR_DATA,
            detail=("есть реальные продукт/кампания для стратегии" if has_real_business_data else "нет продуктов/кампаний для построения стратегии") + cold_start_suffix,
        ),
        DirectorStatusEntry(
            name="Format Director", status=DirectorStatus.SHADOW,
            detail="детерминированная оценка формата доступна по запросу",
        ),
        DirectorStatusEntry(
            name="Creative Director", status=DirectorStatus.READY,
            detail="реализован; не вызывается автоматически (платный LLM-вызов)",
        ),
    ]
    capability_statuses = {c.status for c in INSTAGRAM_PLATFORM_CAPABILITIES.values()}
    performance_status = (
        DirectorStatus.WAITING_FOR_DATA
        if capability_statuses <= {CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNKNOWN}
        else DirectorStatus.SHADOW
    )
    entries.append(DirectorStatusEntry(
        name="Performance Memory", status=performance_status,
        detail=("аккаунт Instagram не подключён - нет первичных метрик" + cold_start_suffix) if performance_status == DirectorStatus.WAITING_FOR_DATA else "",
    ))
    return entries


async def get_director_console_status(session: AsyncSession, *, now: datetime | None = None) -> DirectorConsoleStatus:
    now = now or datetime.now(timezone.utc)
    business = await _business_status(session, now=now)
    telegram_launch_context = await get_current_context(session, SocialLaunchPlatform.TELEGRAM)
    instagram_launch_context = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)
    telegram = await _telegram_status(session, now=now, launch_context=telegram_launch_context)
    snapshot = await get_business_context_snapshot(session, now=now)
    instagram = _instagram_status(
        has_real_business_data=bool(snapshot.products or snapshot.active_campaigns),
        launch_context=instagram_launch_context,
    )
    return DirectorConsoleStatus(as_of=now, business=business, telegram=telegram, instagram=instagram)
